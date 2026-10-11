import { readFile, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const directory = dirname(fileURLToPath(import.meta.url));
const source = await readFile(join(directory, '008_direct_photo_upload.sql'), 'utf8');
if (!source.startsWith('begin;\n') || !source.trimEnd().endsWith('commit;')) {
  throw new Error('Unexpected photo migration boundary');
}
const output = resolve(process.argv[2] || join(directory, '008_direct_photo_upload_aliyun.sql'));
await writeFile(output, source.replace(/\bsecurity definer\b/gi, 'security invoker'));
console.log(output);
