import { ImageMagick } from 'npm:@imagemagick/magick-wasm@0.0.44';
import { runtimeWasm, MAGICK_WASM_BYTES } from './runtime-wasm.ts';

const gateways={publicUrl:'https://spb-example.supabase.opentrust.net',serviceUrl:'http://kong:8000'};
Deno.test('pinned encoder asset loads through the private internal storage gateway',async()=>{
  if (!ImageMagick) throw new Error('Encoder dependency missing');
  const source=await Deno.readFile(new URL('x86/magick.wasm',import.meta.resolve('npm:@imagemagick/magick-wasm@0.0.44')));
  const bytes=await runtimeWasm(gateways,'test-server-only-key',async(input,init)=>{
    if (input!==`${gateways.serviceUrl}/storage/v1/object/authenticated/community-runtime/magick-0.0.44.wasm`) throw new Error('Wrong asset gateway');
    if (new Headers(init?.headers).get('Authorization')!=='Bearer test-server-only-key' || init?.redirect!=='error') throw new Error('Unsafe asset authorization');
    return new Response(Uint8Array.from(source));
  });
  if (bytes.length!==MAGICK_WASM_BYTES) throw new Error('Wrong encoder asset');
});
Deno.test('missing, corrupt and oversized runtime assets are rejected',async()=>{
  for (const response of [new Response('missing',{status:404}),new Response(new Uint8Array(4)),new Response(new Uint8Array(MAGICK_WASM_BYTES+1)),new Response(new Uint8Array(MAGICK_WASM_BYTES))]) {
    let rejected=false;
    try { await runtimeWasm(gateways,'test-key',async()=>response); } catch { rejected=true; }
    if(!rejected) throw new Error('Invalid runtime asset accepted');
  }
});
