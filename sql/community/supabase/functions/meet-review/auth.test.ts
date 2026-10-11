import { acceptsKey, hashKey, issueSession, validSession } from './auth.ts';
const ok = (value: boolean, label: string) => { if (!value) throw new Error(label); };
Deno.test('permanent keys exchange for renewable, bounded and revocable review sessions', async () => {
  const key = 'a'.repeat(64), hash = await hashKey(key), now = 1790000000000;
  ok(await acceptsKey(key, hash), 'correct key');
  ok(!await acceptsKey('b'.repeat(64), hash), 'wrong key');
  ok(!await acceptsKey(hash, hash), 'hash is not a usable entry key');
  ok(!await acceptsKey('', ''), 'missing configuration fails closed');
  const first = await issueSession(hash, now);
  ok(await validSession(first.session, hash, now), 'valid session');
  ok(!await validSession(first.session + 'x', hash, now), 'tampered signature');
  ok(!await validSession(first.session, await hashKey('b'.repeat(64)), now), 'key rotation revokes sessions');
  ok(!await validSession(first.session, hash, now + 3600000), 'session expires');
  ok(!await validSession(first.session.replace(String(first.expiresAt / 1000), String(first.expiresAt / 1000 + 1)), hash, now), 'tampered expiry');
  const later = await issueSession(hash, now + 365 * 86400000);
  ok(await validSession(later.session, hash, now + 365 * 86400000), 'same permanent key works a year later');
  ok(!await validSession(key, hash, now), 'permanent key cannot directly call protected actions');
});
