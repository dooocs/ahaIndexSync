import { communityGateways, type Gateways } from './gateway-config.ts';

export const MAGICK_WASM_BYTES = 15447097;
export const MAGICK_WASM_SHA256 = 'b7d6710436b150dc5bd1ca04d80b6b7614c54854d7470f888f7e69a2a41b00e4';

export class EncoderRuntimeError extends Error {
  constructor() { super('Image encoder temporarily unavailable'); this.name='EncoderRuntimeError'; }
}

export async function runtimeWasm(gateways: Gateways, serviceKey: string, fetcher: typeof fetch = fetch) {
  const checked = communityGateways(gateways.publicUrl,gateways.serviceUrl);
  if (!serviceKey) throw new Error('Missing runtime asset configuration');
  const response = await fetcher(`${checked.serviceUrl}/storage/v1/object/authenticated/community-runtime/magick-0.0.44.wasm`,{
    headers:{apikey:serviceKey,Authorization:`Bearer ${serviceKey}`},
    redirect:'error',signal:AbortSignal.timeout(30000),
  });
  if (!response.ok || !response.body) throw new Error('Runtime asset unavailable');
  const reader=response.body.getReader();
  const bytes=new Uint8Array(MAGICK_WASM_BYTES); let size=0;
  while (true) {
    const {value,done}=await reader.read(); if(done) break;
    size+=value.length;
    if (size>MAGICK_WASM_BYTES) { await reader.cancel(); throw new Error('Invalid runtime asset'); }
    bytes.set(value,size-value.length);
  }
  if (size!==MAGICK_WASM_BYTES) throw new Error('Invalid runtime asset');
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
  if (hash!==MAGICK_WASM_SHA256) throw new Error('Invalid runtime asset');
  return bytes;
}
