import { requestAuthorization } from './request-authorization.ts';

Deno.test('the original credential survives a gateway-replaced Authorization header', () => {
  const headers = new Headers({ Authorization: 'Bearer gateway-token', 'X-Community-Authorization': 'Bearer user-token' });
  if (requestAuthorization(headers) !== 'Bearer user-token') throw new Error('Gateway credential replaced the user credential');
});
Deno.test('standard headers remain supported and credential selection does not authenticate', () => {
  if (requestAuthorization(new Headers({ Authorization: 'Bearer old-client-token' })) !== 'Bearer old-client-token') throw new Error('Standard transport changed');
  if (requestAuthorization(new Headers()) !== null) throw new Error('A credential was invented');
  if (requestAuthorization(new Headers({ Authorization: 'Bearer fallback', 'X-Community-Authorization': '' })) !== '') throw new Error('Empty custom credentials accepted a fallback');
});
