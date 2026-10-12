const encoder = new TextEncoder();
export const SESSION_SECONDS = 3600;
const hex = (bytes: ArrayBuffer) => [...new Uint8Array(bytes)].map(b => b.toString(16).padStart(2, '0')).join('');
export const hashKey = async (key: string) => hex(await crypto.subtle.digest('SHA-256', encoder.encode(key)));

export async function acceptsKey(value: unknown, expected: string): Promise<boolean> {
  if (typeof value !== 'string' || !/^[0-9a-f]{64}$/.test(value) || !/^[0-9a-f]{64}$/.test(expected)) return false;
  const actual = await hashKey(value);
  let difference = 0;
  for (let i = 0; i < 64; i++) difference |= actual.charCodeAt(i) ^ expected.charCodeAt(i);
  return difference === 0;
}

const signingKey = (secret: string) => crypto.subtle.importKey('raw', encoder.encode(`meet-review-session:${secret}`), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign', 'verify']);

export async function issueSession(secret: string, now = Date.now()) {
  const expires = Math.floor(now / 1000) + SESSION_SECONDS;
  const payload = `review-v1.${expires}.${crypto.randomUUID()}`;
  const signature = hex(await crypto.subtle.sign('HMAC', await signingKey(secret), encoder.encode(payload)));
  return { session: `${payload}.${signature}`, expiresAt: expires * 1000 };
}

export async function validSession(value: string, secret: string, now = Date.now()): Promise<boolean> {
  if (!/^[0-9a-f]{64}$/.test(secret) || value.length > 200) return false;
  const match = value.match(/^(review-v1\.(\d{10,11})\.[0-9a-f-]{36})\.([0-9a-f]{64})$/);
  if (!match) return false;
  const remaining = Number(match[2]) - Math.floor(now / 1000);
  if (remaining <= 0 || remaining > SESSION_SECONDS) return false;
  const signature = Uint8Array.from(match[3].match(/../g)!, byte => parseInt(byte, 16));
  return crypto.subtle.verify('HMAC', await signingKey(secret), signature, encoder.encode(match[1]));
}
