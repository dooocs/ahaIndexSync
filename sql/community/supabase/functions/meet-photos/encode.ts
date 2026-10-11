import { ImageMagick, MagickImageInfo, MagickReadSettings, MagickFormat, ResourceLimits, initializeImageMagick } from 'npm:@imagemagick/magick-wasm@0.0.44';
import { communityGateways } from '../_shared/gateway-config.ts';
import { runtimeWasm, EncoderRuntimeError } from '../_shared/runtime-wasm.ts';

let initialized: Promise<void> | undefined;
async function initialize() {
  try {
    const bytes = Deno.env.get('COMMUNITY_BUNDLED_RUNTIME') === 'true'
      ? await runtimeWasm(communityGateways(Deno.env.get('SUPABASE_URL')!,Deno.env.get('SUPABASE_LOCAL_URL')),Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!)
      : await Deno.readFile(new URL('x86/magick.wasm', import.meta.resolve('npm:@imagemagick/magick-wasm@0.0.44')));
    await initializeImageMagick(bytes);
    ResourceLimits.width = 1601n;
    ResourceLimits.height = 1601n;
    ResourceLimits.memory = 96n * 1024n * 1024n;
    ResourceLimits.maxMemoryRequest = 96n * 1024n * 1024n;
    ResourceLimits.disk = 0n;
    ResourceLimits.listLength = 16n;
  } catch { throw new EncoderRuntimeError(); }
}

export async function encodePhoto(bytes: Uint8Array) {
  if (bytes.length > 1048576 || bytes.length < 4 || bytes[0] !== 255 || bytes[1] !== 216 || bytes[2] !== 255) throw new Error('invalid_image');
  // Read-only photo requests do not need to initialize the image encoder.
  await (initialized ??= initialize().catch(error => { initialized = undefined; throw error; }));
  const info = MagickImageInfo.create(bytes, new MagickReadSettings({ format: MagickFormat.Jpeg }));
  if (info.width < 1 || info.height < 1 || info.width > 1600 || info.height > 1600) throw new Error('invalid_image');
  return ImageMagick.read(bytes, MagickFormat.Jpeg, image => {
    image.autoOrient();
    image.strip();
    image.quality = 80;
    const width = image.width, height = image.height;
    const photo = image.write(MagickFormat.Jpeg, data => Uint8Array.from(data));
    const scale = Math.min(1, 400 / Math.max(width, height));
    image.resize(Math.max(1, Math.round(width * scale)), Math.max(1, Math.round(height * scale)));
    image.quality = 72;
    const thumb = image.write(MagickFormat.Jpeg, data => Uint8Array.from(data));
    if (photo.length > 1048576 || thumb.length > 1048576) throw new Error('invalid_image');
    return { width, height, photo, thumb };
  });
}
