import { createClient } from 'npm:@supabase/supabase-js@2.103.0';
import { communityGateways, publicPhotoUrl } from './gateway-config.ts';

export const bucket = 'meet-photos';
const gateways = communityGateways(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_LOCAL_URL'));
export const url = gateways.serviceUrl;
export const browserPhotoUrl = (value: string) => publicPhotoUrl(value, gateways);
export const admin = createClient(url, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!, {
  auth: { persistSession: false, autoRefreshToken: false },
  global: { fetch: (url, options) => fetch(url, { ...options, signal: AbortSignal.timeout(30000) }) },
});
export const paths = (owner: string, id: string) => [`${owner}/${id}/photo.jpg`, `${owner}/${id}/thumb.jpg`];
export async function drainDeletions(owner?: string) {
  let query = admin.from('meet_photo_deletions').select('id,owner_id').order('created_at').limit(100);
  if (owner) query = query.eq('owner_id', owner);
  const { data, error } = await query;
  if (error) throw error;
  if (!data.length) return 0;
  const removed = await admin.storage.from(bucket).remove(data.flatMap(row => paths(row.owner_id, row.id)));
  if (removed.error) throw removed.error;
  const cleared = await admin.from('meet_photo_deletions').delete().in('id', data.map(row => row.id));
  if (cleared.error) throw cleared.error;
  return data.length;
}
