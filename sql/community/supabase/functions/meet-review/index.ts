import { admin, bucket, browserPhotoUrl, paths } from '../_shared/photo-storage.ts';
import { acceptsKey, issueSession, validSession } from './auth.ts';
import { requestAuthorization } from '../_shared/request-authorization.ts';

const allowed = new Set(['http://127.0.0.1:4328', 'http://localhost:4328', 'https://www.amazingindex.com']);
const statuses = ['pending', 'published', 'rejected', 'withdrawn'];

Deno.serve(async req => {
  const origin = req.headers.get('origin') || '';
  const headers = { 'Access-Control-Allow-Origin': allowed.has(origin) ? origin : 'null', 'Vary': 'Origin', 'Access-Control-Allow-Headers': 'authorization, apikey, content-type, x-community-authorization', 'Access-Control-Allow-Methods': 'POST, OPTIONS', 'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer' };
  const reply = (data: unknown, status = 200) => Response.json(data, { status, headers });
  if (!allowed.has(origin)) return reply({ error: 'forbidden_origin' }, 403);
  if (req.method === 'OPTIONS') return new Response(null, { headers });
  if (req.method !== 'POST') return reply({ error: 'method_not_allowed' }, 405);
  const keyHash = Deno.env.get('COMMUNITY_REVIEW_KEY_HASH') || '';
  if (!/^[0-9a-f]{64}$/.test(keyHash)) return reply({ error: 'review_unavailable' }, 503);
  try {
    // Bound the body before parsing; never log tokens, request bodies or URLs.
    const reader = req.body?.getReader();
    if (!reader) return reply({ error: 'invalid_request' }, 400);
    let size = 0;
    const chunks: Uint8Array[] = [];
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > 8192) { await reader.cancel(); return reply({ error: 'invalid_request' }, 413); }
      chunks.push(value);
    }
    let input;
    try { input = JSON.parse(await new Blob(chunks.map(value => Uint8Array.from(value))).text()); }
    catch { return reply({ error: 'invalid_request' }, 400); }
    if (!input || typeof input !== 'object' || Array.isArray(input)) return reply({ error: 'invalid_request' }, 400);
    if (input.action === 'exchange') {
      if (!await acceptsKey(input.key, keyHash)) return reply({ error: 'review_unauthorized' }, 401);
      return reply(await issueSession(keyHash));
    }
    const auth = requestAuthorization(req.headers) || '';
    if (!auth.startsWith('Bearer ') || !await validSession(auth.slice(7), keyHash)) return reply({ error: 'review_unauthorized' }, 401);
    if (input.action === 'list') {
      if (!statuses.includes(input.status) || (input.before != null && (!Number.isSafeInteger(input.before) || input.before <= 0))) return reply({ error: 'invalid_request' }, 400);
      let query = admin.from('meet_posts').select('id,nickname,age,gender,city,title,status,updated_at').eq('status', input.status).order('id', { ascending: false }).limit(21);
      if (input.before) query = query.lt('id', input.before);
      const { data, error } = await query;
      if (error) throw error;
      return reply({ posts: data.slice(0, 20), more: data.length > 20 });
    }
    if (!Number.isSafeInteger(input.id) || input.id <= 0) return reply({ error: 'invalid_request' }, 400);
    if (input.action === 'detail') {
      const { data, error } = await admin.rpc('get_meet_review_post', { p_id: input.id });
      if (error) throw error;
      if (!data) return reply({ error: 'post_missing' }, 404);
      const snapshot = data.snapshot;
      const rows = snapshot.photos;
      if (rows.some((row: { state: string }) => row.state !== 'ready') || rows.length > 6) return reply({ error: 'photos_not_ready' }, 409);
      const keys = rows.flatMap((row: { owner_id: string; id: string }) => paths(row.owner_id, row.id));
      const signed = keys.length ? await admin.storage.from(bucket).createSignedUrls(keys, 120) : { data: [], error: null };
      if (signed.error || signed.data?.some(row => row.error || !row.signedUrl)) throw signed.error || new Error('sign_failed');
      const { owner_id: _owner, ...post } = snapshot.post;
      return reply({ post, contact: snapshot.contact, version: data.version, photos: rows.map((row: { id: string; width: number; height: number }, i: number) => ({ id: row.id, width: row.width, height: row.height, url: browserPhotoUrl(signed.data![i * 2].signedUrl), thumb: browserPhotoUrl(signed.data![i * 2 + 1].signedUrl) })) });
    }
    if (input.action !== 'review' || !statuses.includes(input.status) || typeof input.version !== 'string' || typeof input.reason !== 'string') return reply({ error: 'invalid_request' }, 400);
    const { error } = await admin.rpc('review_meet_post', { p_id: input.id, p_version: input.version, p_status: input.status, p_reason: input.reason, p_reviewer: `link:${keyHash.slice(0, 16)}` });
    if (error) throw error;
    return reply({ ok: true });
  } catch (error) {
    const code = (error as { code?: string }).code;
    if (code === 'PT409') return reply({ error: 'post_changed' }, 409);
    if (code === 'P0002') return reply({ error: 'post_missing' }, 404);
    if (code === '22023') return reply({ error: 'invalid_review' }, 400);
    console.error('meet-review failed', code || 'internal');
    return reply({ error: 'review_unavailable' }, 503);
  }
});
