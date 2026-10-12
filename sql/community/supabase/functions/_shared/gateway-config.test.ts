import { communityGateways, publicPhotoUrl } from './gateway-config.ts';
import { createClient } from 'npm:@supabase/supabase-js@2.103.0';

const publicUrl = 'https://spb-x6r06737x2zdpg3x.supabase.opentrust.net';
const internalUrl = 'http://kong:8000';
const assert = (value: unknown, message: string) => { if (!value) throw new Error(message); };

Deno.test('internal requests use the local gateway while photos retain their public signature', () => {
  const gateways = communityGateways(publicUrl, internalUrl);
  assert(gateways.serviceUrl === internalUrl, 'Service requests must use the internal gateway');
  const path = '/storage/v1/object/sign/meet-photos/owner/photo/photo.jpg?token=test%2Btoken&download=';
  assert(publicPhotoUrl(internalUrl + path, gateways) === publicUrl + path, 'Signed path and query must survive origin conversion');
  assert(publicPhotoUrl(publicUrl + path, gateways) === publicUrl + path, 'Already public links must remain valid');
});

Deno.test('official cloud works without an internal gateway override', () => {
  const url = 'https://abcdefghijklmnopqrst.supabase.co';
  const gateways = communityGateways(url);
  assert(gateways.serviceUrl === url, 'Official cloud service URL changed');
  const photo = url + '/storage/v1/object/sign/meet-photos/owner/photo/thumb.jpg?token=test';
  assert(publicPhotoUrl(photo, gateways) === photo, 'Official cloud photo URL changed');
});

Deno.test('gateway configuration and signed links reject unexpected origins and credential exposure', () => {
  const gateways = communityGateways(publicUrl, internalUrl);
  const path = '/storage/v1/object/sign/meet-photos/owner/photo/photo.jpg?token=private-test-token';
  for (const value of [
    'private-test-token',
    'https://unexpected.example.test' + path,
    publicUrl + '/storage/v1/object/public/meet-photos/photo.jpg?token=private-test-token',
    publicUrl + '/storage/v1/object/sign/another-bucket/photo.jpg?token=private-test-token',
    publicUrl + '/storage/v1/object/sign/meet-photos/photo.jpg',
    publicUrl + path + '#private-test-token',
    'https://user:private-test-token@spb-x6r06737x2zdpg3x.supabase.opentrust.net' + path,
  ]) {
    let rejected = false;
    try { publicPhotoUrl(value, gateways); } catch (error) {
      rejected = true;
      assert(!String(error).includes('private-test-token'), 'Rejected URLs must not leak their tokens');
    }
    assert(rejected, 'Invalid signed URL accepted');
  }
  for (const value of ['http://public.example.test', publicUrl + '/api', publicUrl + '?secret=test',
    'https://user:password@spb-x6r06737x2zdpg3x.supabase.opentrust.net']) {
    let rejected = false;
    try { communityGateways(value); } catch { rejected = true; }
    assert(rejected, 'Invalid public gateway accepted');
  }
});

Deno.test('the actual SDK signs through the internal gateway and exposes only a public photo token', async () => {
  const gateways = communityGateways(publicUrl, internalUrl);
  const path = 'owner/photo/photo.jpg';
  let called = false;
  const client = createClient(gateways.serviceUrl, 'server-only-test-key', {
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
    global: { fetch: async (input, init) => {
      assert(String(input) === internalUrl + '/storage/v1/object/sign/meet-photos', 'Signing used an external gateway');
      assert(init?.method === 'POST', 'Signing did not use the expected method');
      assert(new Headers(init?.headers).get('authorization') === 'Bearer server-only-test-key', 'Signing lost server authorization');
      const request = JSON.parse(String(init?.body));
      assert(request.expiresIn === 120 && request.paths[0] === path, 'Signing lifetime or photo path changed');
      called = true;
      return Response.json([{ path, error: null, signedURL: '/object/sign/meet-photos/' + path + '?token=short-photo-token' }]);
    } },
  });
  const signed = await client.storage.from('meet-photos').createSignedUrls([path], 120);
  assert(called && !signed.error && signed.data?.length === 1, 'SDK signing failed');
  const result = publicPhotoUrl(signed.data![0].signedUrl, gateways);
  assert(result === publicUrl + '/storage/v1/object/sign/meet-photos/' + path + '?token=short-photo-token', 'Browser URL is not the public signed object URL');
  assert(!result.includes('server-only-test-key') && !result.includes('kong:8000'), 'A server credential or internal host reached the browser URL');
});
