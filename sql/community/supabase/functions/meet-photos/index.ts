import { createClient } from 'npm:@supabase/supabase-js@2.103.0';
import { admin, bucket, browserPhotoUrl, drainDeletions, paths, url } from '../_shared/photo-storage.ts';
import { encodePhoto } from './encode.ts';
import { EncoderRuntimeError } from '../_shared/runtime-wasm.ts';
import { requestAuthorization } from '../_shared/request-authorization.ts';

const headers = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'authorization, apikey, content-type, x-client-info, x-community-authorization', 'Access-Control-Allow-Methods': 'POST, OPTIONS', 'Cache-Control': 'private, no-store' };
const reply = (data: unknown, status = 200) => Response.json(data, { status, headers });
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

Deno.serve(async req => {
  if (req.method === 'OPTIONS') return new Response(null, { headers });
  if (req.method !== 'POST') return reply({ error: 'method_not_allowed' }, 405);
  // Custom auth is mandatory even when gateway JWT verification is disabled for signing-key compatibility.
  const authorization = requestAuthorization(req.headers);
  if (!authorization?.startsWith('Bearer ')) return reply({ error: 'login_required' }, 401);
  const client = createClient(url, Deno.env.get('SUPABASE_ANON_KEY')!, {
    auth: { persistSession: false, autoRefreshToken: false },
    global: { headers: { Authorization: authorization }, fetch: (url, init) => fetch(url, { ...init, signal: AbortSignal.timeout(15000) }) },
  });
  const { data: { user }, error: authError } = await client.auth.getUser(authorization.slice(7));
  if (authError || !user?.email_confirmed_at || user.is_anonymous) return reply({ error: 'login_required' }, 401);
  try {
    // Bound the actual body, including chunked requests, before multipart parsing.
    const reader = req.body?.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    if (!reader) return reply({ error: 'invalid_request' }, 400);
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > 1100000) { await reader.cancel(); return reply({ error: 'image_too_large' }, 413); }
      chunks.push(value);
    }
    const body = new Blob(chunks.map(chunk => Uint8Array.from(chunk)));
    if (req.headers.get('content-type')?.startsWith('multipart/form-data')) {
      const form = await new Response(body, { headers: { 'Content-Type': req.headers.get('content-type')! } }).formData();
      const file = form.get('file');
      if (!(file instanceof Blob) || file.type !== 'image/jpeg') return reply({ error: 'invalid_image' }, 400);
      const id = crypto.randomUUID();
      const reservation = await admin.rpc('reserve_meet_photo', { p_owner: user.id, p_id: id });
      if (reservation.error) throw reservation.error;
      try {
        let encoded;
        try { encoded = await encodePhoto(new Uint8Array(await file.arrayBuffer())); }
        catch (error) {
          return error instanceof EncoderRuntimeError
            ? await failUpload(user.id,id,'photo_service_unavailable',503)
            : await failUpload(user.id,id,'invalid_image',400);
        }
        const keys = paths(user.id, id);
        for (const [index, bytes] of [encoded.photo, encoded.thumb].entries()) {
          const uploaded = await admin.storage.from(bucket).upload(keys[index], bytes, { contentType: 'image/jpeg', cacheControl: '120', upsert: false });
          if (uploaded.error) throw uploaded.error;
        }
        const ready = await admin.from('meet_photos').update({ state: 'ready', width: encoded.width, height: encoded.height, bytes: encoded.photo.length }).eq('id', id).eq('owner_id', user.id).select('id,width,height,post_id,sort_order').single();
        if (ready.error) throw ready.error;
        return reply({ photo: ready.data });
      } catch (error) {
        await admin.from('meet_photos').delete().eq('id', id).eq('owner_id', user.id);
        // Account deletion can remove the row while Storage writes are still in flight.
        await admin.from('meet_photo_deletions').upsert({ id, owner_id: user.id });
        await drainDeletions(user.id).catch(() => {});
        throw error;
      }
    }
    if (size > 10000) return reply({ error: 'invalid_request' }, 400);
    const input = JSON.parse(await body.text());
    if (input.action === 'discard') {
      if (!uuid.test(input.id)) return reply({ error: 'invalid_request' }, 400);
      const removed = await admin.from('meet_photos').delete().eq('id', input.id).eq('owner_id', user.id).is('post_id', null);
      if (removed.error) throw removed.error;
      await drainDeletions(user.id);
      return reply({ ok: true });
    }
    if (input.action !== 'list' || !Array.isArray(input.posts) || input.posts.length > 20 || input.posts.some((id: unknown) => !Number.isSafeInteger(id) || Number(id) <= 0)) return reply({ error: 'invalid_request' }, 400);
    const params = { p_posts: input.posts, p_own: input.own === true };
    const result = Deno.env.get('COMMUNITY_RPC_MODE') === 'edge'
      ? await admin.rpc('meet_api', { p_action: 'list_meet_photos', p_actor: user.id, p_params: params })
      : await client.rpc('list_meet_photos', params);
    if (result.error) throw result.error;
    const rows = result.data;
    if (!rows.length) return reply({ photos: [] });
    const keys = rows.map((row: { owner_id: string; id: string }) => paths(row.owner_id, row.id)[input.full === true ? 0 : 1]);
    const signed = await admin.storage.from(bucket).createSignedUrls(keys, 120);
    if (signed.error || signed.data?.some(row => row.error || !row.signedUrl)) throw signed.error || new Error('sign_failed');
    return reply({ photos: rows.map((row: { id: string; post_id: number; sort_order: number; width: number; height: number }, i: number) => ({ id: row.id, post_id: row.post_id, sort_order: row.sort_order, width: row.width, height: row.height, url: browserPhotoUrl(signed.data![i].signedUrl) })) });
  } catch (error) {
    const code = (error as { code?: string }).code;
    if (code === 'P0001') return reply({ error: 'upload_rate_limit' }, 429);
    if (code === '22023') return reply({ error: 'photo_limit' }, 400);
    if (code === '42501') return reply({ error: 'login_required' }, 401);
    console.error('meet-photos request failed', code || 'internal');
    return reply({ error: 'photo_service_unavailable' }, 503);
  }
});

async function failUpload(owner: string, id: string, error: string, status: number) {
  await admin.from('meet_photos').delete().eq('id', id).eq('owner_id', owner);
  await drainDeletions(owner).catch(() => {});
  return reply({ error }, status);
}
