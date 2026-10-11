import { ImageMagick, MagickFormat, MagickColors, initializeImageMagick } from 'npm:@imagemagick/magick-wasm@0.0.44';
import { encodePhoto } from './encode.ts';
import { EncoderRuntimeError } from '../_shared/runtime-wasm.ts';

const assert = (value: unknown, message: string) => { if (!value) throw new Error(message); };
Deno.test('normalizes JPEGs, strips metadata, and creates a bounded thumbnail', async () => {
  await initializeImageMagick(await Deno.readFile(new URL('x86/magick.wasm', import.meta.resolve('npm:@imagemagick/magick-wasm@0.0.44'))));
  const input = ImageMagick.read(MagickColors.Red, 1200, 1600, image => {
    image.comment = 'private-location-metadata';
    return image.write(MagickFormat.Jpeg, bytes => Uint8Array.from(bytes));
  });
  const result = await encodePhoto(input);
  assert(result.width === 1200 && result.height === 1600, 'Main image dimensions changed');
  assert(result.photo.length <= 1048576, 'Main image exceeded bucket limit');
  ImageMagick.read(result.photo, image => { assert(!image.comment && !image.profileNames.length, 'Metadata leaked'); });
  ImageMagick.read(result.thumb, image => { assert(Math.max(image.width, image.height) <= 400, 'Thumbnail too large'); });
});
Deno.test('encoder bootstrap failures are distinguished from invalid user photos',async()=>{
  const previousFlag=Deno.env.get('COMMUNITY_BUNDLED_RUNTIME');
  const previousUrl=Deno.env.get('SUPABASE_URL');
  try {
    Deno.env.set('COMMUNITY_BUNDLED_RUNTIME','true');
    Deno.env.set('SUPABASE_URL','invalid-test-gateway');
    const fresh=await import('./encode.ts?bootstrap-failure-test');
    const input=ImageMagick.read(MagickColors.Red,64,64,image=>image.write(MagickFormat.Jpeg,bytes=>Uint8Array.from(bytes)));
    let rejected=false;
    try { await fresh.encodePhoto(input); }
    catch(error) { rejected=error instanceof EncoderRuntimeError; }
    assert(rejected,'A runtime failure was misclassified as a bad photo');
  } finally {
    if(previousFlag===undefined) Deno.env.delete('COMMUNITY_BUNDLED_RUNTIME'); else Deno.env.set('COMMUNITY_BUNDLED_RUNTIME',previousFlag);
    if(previousUrl===undefined) Deno.env.delete('SUPABASE_URL'); else Deno.env.set('SUPABASE_URL',previousUrl);
  }
});
Deno.test('rejects forged JPEGs and over-limit upload bytes', async () => {
  for (const input of [new TextEncoder().encode('<svg></svg>'), new Uint8Array([255,216,255,0]), new Uint8Array(1048577)]) {
    let rejected = false;
    try { await encodePhoto(input); } catch { rejected = true; }
    assert(rejected, 'Invalid image accepted');
  }
});
