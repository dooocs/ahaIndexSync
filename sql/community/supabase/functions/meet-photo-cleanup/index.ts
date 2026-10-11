import { admin, drainDeletions } from '../_shared/photo-storage.ts';
import { requestAuthorization } from '../_shared/request-authorization.ts';

Deno.serve(async req => {
  const secret = Deno.env.get('COMMUNITY_CLEANUP_SECRET');
  if (!secret || req.method !== 'POST' || requestAuthorization(req.headers) !== `Bearer ${secret}`) return new Response('Unauthorized', { status: 401 });
  const swept = await admin.rpc('sweep_meet_photos');
  if (swept.error) return new Response('Cleanup failed', { status: 500 });
  try { return Response.json({ deleted: await drainDeletions() }); }
  catch { return new Response('Cleanup failed', { status: 500 }); }
});
