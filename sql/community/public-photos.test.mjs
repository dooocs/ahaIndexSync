import assert from 'node:assert/strict';
import test from 'node:test';
import { handlePublicPhotos } from './supabase/functions/meet-public-photos/index.ts';

const config = { publicUrl: 'https://community.example', serviceUrl: 'http://gateway.internal:8000', serviceKey: 'server-test-key' };
const request = body => new Request('https://function.example', { method: 'POST', body: JSON.stringify(body) });

test('public signing selects only ready photos from approved, unexpired and consented posts', async () => {
  const key = 'owner/photo/thumb.jpg'; let calls = 0;
  const response = await handlePublicPhotos(request({ action: 'list', posts: [4] }), config, async (input, options) => {
    calls++; const url = new URL(input);
    assert.equal(url.origin, config.serviceUrl);
    assert.equal(options.headers.Authorization, 'Bearer server-test-key');
    if (calls === 1) {
      assert.equal(url.searchParams.get('state'), 'eq.ready');
      assert.equal(url.searchParams.get('post_id'), 'in.(4)');
      assert.equal(url.searchParams.get('meet_posts.status'), 'eq.published');
      assert.equal(url.searchParams.get('meet_posts.consent_version'), 'eq.2026-10-11-public-photos');
      assert.ok(url.searchParams.get('meet_posts.expires_at').startsWith('gt.'));
      assert.ok(url.searchParams.get('select').includes('meet_posts!inner'));
      return Response.json([{ id: 'photo', owner_id: 'owner', post_id: 4, sort_order: 0, width: 1600, height: 1200 }]);
    }
    assert.deepEqual(JSON.parse(options.body), { paths: [key], expiresIn: 120 });
    return Response.json([{ path: key, signedURL: `/object/sign/meet-photos/${key}?token=fixture` }]);
  });
  assert.equal(response.status, 200);
  const data = await response.json();
  assert.equal(data.photos[0].url, `https://community.example/storage/v1/object/sign/meet-photos/${key}?token=fixture`);
  assert.equal(Object.hasOwn(data.photos[0], 'owner_id'), false);
  assert.equal(Object.hasOwn(data.photos[0], 'contact'), false);
  assert.equal(calls, 2);
});

test('private previews and arbitrary object paths cannot be requested anonymously', async () => {
  for (const body of [{ action: 'list', posts: [4], own: true }, { action: 'discard', posts: [4] },
    { action: 'list', posts: [-1] }, { action: 'list', posts: ['4)'] }, { action: 'list', posts: Array(21).fill(4) }]) {
    const response = await handlePublicPhotos(request(body), config, async () => assert.fail('No privileged request expected'));
    assert.equal(response.status, 400);
  }
});

test('a filtered-out post produces no signing request', async () => {
  let calls = 0;
  const response = await handlePublicPhotos(request({ action: 'list', posts: [4] }), config, async () => {
    calls++; return Response.json([]);
  });
  assert.deepEqual(await response.json(), { photos: [] });
  assert.equal(calls, 1);
});
