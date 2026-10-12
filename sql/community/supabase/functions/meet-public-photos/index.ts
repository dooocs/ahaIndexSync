type Config = { publicUrl: string; serviceUrl: string; serviceKey: string };
type Photo = { id: string; owner_id: string; post_id: number; sort_order: number; width: number; height: number };
declare const Deno: { env: { get(name: string): string | undefined }; serve(handler: (req: Request) => Promise<Response>): void };

const headers = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'authorization, apikey, content-type, x-community-authorization', 'Access-Control-Allow-Methods': 'POST, OPTIONS', 'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff' };
const reply = (data: unknown, status = 200) => Response.json(data, { status, headers });
const consentVersion = '2026-10-11-public-photos';

export async function handlePublicPhotos(req: Request, config: Config, fetcher: typeof fetch = fetch): Promise<Response> {
  if (req.method === 'OPTIONS') return new Response(null, { headers });
  if (req.method !== 'POST') return reply({ error: 'method_not_allowed' }, 405);
  let input;
  try {
    const reader = req.body?.getReader();
    if (!reader) return reply({ error: 'invalid_request' }, 400);
    const chunks: Uint8Array[] = []; let size = 0;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > 10000) { await reader.cancel(); return reply({ error: 'invalid_request' }, 413); }
      chunks.push(value);
    }
    input = JSON.parse(await new Blob(chunks.map(chunk => Uint8Array.from(chunk))).text());
  } catch { return reply({ error: 'invalid_request' }, 400); }
  if (!input || input.action !== 'list' || input.own === true || !Array.isArray(input.posts) || input.posts.length > 20 ||
      input.posts.some((id: unknown) => !Number.isSafeInteger(id) || Number(id) <= 0)) return reply({ error: 'invalid_request' }, 400);
  try {
    const service = new URL(config.serviceUrl), publicUrl = new URL(config.publicUrl);
    if (!['http:', 'https:'].includes(service.protocol) || publicUrl.protocol !== 'https:' ||
        service.username || service.password || publicUrl.username || publicUrl.password ||
        service.pathname !== '/' || publicUrl.pathname !== '/' || service.search || publicUrl.search || service.hash || publicUrl.hash || !config.serviceKey) throw new Error('invalid_gateway');
    if (!input.posts.length) return reply({ photos: [] });
    const authorization = { apikey: config.serviceKey, Authorization: `Bearer ${config.serviceKey}` };
    const query = new URL('/rest/v1/meet_photos', service);
    query.search = new URLSearchParams({
      select: 'id,owner_id,post_id,sort_order,width,height,meet_posts!inner(id)',
      state: 'eq.ready', post_id: `in.(${input.posts.join(',')})`,
      'meet_posts.status': 'eq.published', 'meet_posts.expires_at': `gt.${new Date().toISOString()}`,
      'meet_posts.consent_version': `eq.${consentVersion}`, order: 'post_id.asc,sort_order.asc', limit: '120',
    }).toString();
    const rowsResponse = await fetcher(query, { headers: authorization, signal: AbortSignal.timeout(15000) });
    if (!rowsResponse.ok) throw new Error('query_failed');
    const rows: Photo[] = await rowsResponse.json();
    if (!Array.isArray(rows)) throw new Error('invalid_rows');
    if (!rows.length) return reply({ photos: [] });
    const keys = rows.map(row => `${row.owner_id}/${row.id}/${input.full === true ? 'photo' : 'thumb'}.jpg`);
    const signedResponse = await fetcher(new URL('/storage/v1/object/sign/meet-photos', service), {
      method: 'POST', headers: { ...authorization, 'Content-Type': 'application/json' },
      body: JSON.stringify({ paths: keys, expiresIn: 120 }), signal: AbortSignal.timeout(15000),
    });
    if (!signedResponse.ok) throw new Error('sign_failed');
    const signed = await signedResponse.json();
    if (!Array.isArray(signed) || signed.length !== rows.length) throw new Error('invalid_signatures');
    return reply({ photos: rows.map((row, index) => {
      const item = signed[index];
      if (item.error || typeof item.signedURL !== 'string' || !item.signedURL.startsWith('/object/sign/meet-photos/')) throw new Error('invalid_signature');
      const url = new URL(`/storage/v1${item.signedURL}`, publicUrl);
      if (url.origin !== publicUrl.origin || decodeURIComponent(url.pathname) !== `/storage/v1/object/sign/meet-photos/${keys[index]}` || !url.searchParams.get('token') || url.hash) throw new Error('invalid_signature');
      return { id: row.id, post_id: row.post_id, sort_order: row.sort_order, width: row.width, height: row.height, url: url.href };
    }) });
  } catch {
    console.error('meet-public-photos request failed');
    return reply({ error: 'photo_service_unavailable' }, 503);
  }
}

if (typeof Deno !== 'undefined') Deno.serve(req => handlePublicPhotos(req, {
  publicUrl: Deno.env.get('SUPABASE_URL') || '',
  serviceUrl: Deno.env.get('SUPABASE_LOCAL_URL') || Deno.env.get('SUPABASE_URL') || '',
  serviceKey: Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') || '',
}));
