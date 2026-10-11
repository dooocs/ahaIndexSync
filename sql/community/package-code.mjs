import { lstat, readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const directory = dirname(fileURLToPath(import.meta.url));
const root = resolve(directory, '../..');
const output = resolve(process.argv[2] || join(tmpdir(), 'amazingindex-community-code.tar.gz'));
const files = [
  '001_community_mvp.sql', '002_community_photos.sql', '003_photo_cleanup_schedule.sql',
  '004_photo_consent.sql', '005_private_review.sql', '006_review_conflict.sql', '008_direct_photo_upload.sql',
  '007_aliyun_cleanup_url.sql', 'aliyun-preflight.sql', 'aliyun-invoker.sql', 'aliyun-cleanup.sql', 'aliyun-runtime-assets.sql', 'build-aliyun.mjs', 'bundle-functions.mjs', 'tests.sql', 'photos-tests.sql',
  'review-tests.sql', 'README.md', 'package-code.mjs', 'email-templates.mjs',
  'email-templates.test.mjs', 'build-aliyun-photo-update.mjs', 'supabase/config.toml',
  'supabase/functions/_shared/gateway-config.ts',
  'supabase/functions/_shared/gateway-config.test.ts',
  'supabase/functions/_shared/request-authorization.ts',
  'supabase/functions/_shared/request-authorization.test.ts',
  'supabase/functions/_shared/photo-storage.ts',
  'supabase/functions/_shared/runtime-wasm.ts','supabase/functions/_shared/runtime-wasm.test.ts',
  'supabase/functions/meet-photos/index.ts', 'supabase/functions/meet-photos/encode.ts',
  'supabase/functions/meet-photos/encode.test.ts',
  'supabase/functions/meet-photo-cleanup/index.ts',
  'supabase/functions/meet-review/index.ts', 'supabase/functions/meet-review/auth.ts',
  'supabase/functions/meet-review/auth.test.ts',
  'supabase/functions/meet-api/index.ts', 'supabase/functions/meet-api/actions.ts',
  'supabase/functions/meet-api/actions.test.ts',
].map(file => `sql/community/${file}`);

// Never recurse into a project directory: CLI state and credentials stay outside.
for (const file of files) {
  const parts = file.split('/');
  for (let i = 1; i <= parts.length; i++) {
    const info = await lstat(join(root, ...parts.slice(0, i)));
    if (info.isSymbolicLink() || (i === parts.length && !info.isFile())) {
      throw new Error('The community package requires regular source files.');
    }
  }
}
const result = spawnSync('tar', ['-czf', output, '-C', root, ...files], {
  env: { ...process.env, COPYFILE_DISABLE: '1' }, encoding: 'utf8', timeout: 30000,
});
if (result.status !== 0) throw new Error('Could not create the community code package.');
const listing = spawnSync('tar', ['-tzf', output], { encoding: 'utf8', timeout: 30000 });
const actual = listing.stdout.trim().split('\n').sort();
if (listing.status !== 0 || JSON.stringify(actual) !== JSON.stringify([...files].sort())) {
  throw new Error('The community package contains unexpected entries.');
}
const sha256 = createHash('sha256').update(await readFile(output)).digest('hex');
console.log(JSON.stringify({ output, files: files.length, sha256 }));
