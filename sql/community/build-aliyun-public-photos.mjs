import { readFile, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const directory = dirname(fileURLToPath(import.meta.url));
const source = await readFile(join(directory, '009_public_photo_consent.sql'), 'utf8');
if (!source.startsWith('begin;\n') || !source.trimEnd().endsWith('commit;')) throw new Error('Unexpected migration boundary');
const output = resolve(process.argv[2] || join(directory, '009_public_photo_consent_aliyun.sql'));
const adapter = await readFile(join(directory, 'aliyun-invoker.sql'), 'utf8');
const end = adapter.indexOf('-- Existing checks');
if (end < 0 || !adapter.startsWith('-- Aliyun disallows')) throw new Error('Unexpected dispatcher boundary');
const dispatcher = adapter.slice(0, end).replace('create function public.meet_api(', 'create or replace function public.meet_api(');
await writeFile(output, source.replace(/\bsecurity definer\b/gi, 'security invoker')
  .replace('to authenticated,service_role;', 'to service_role;')
  .replace("notify pgrst, 'reload schema';", () => `${dispatcher}\nnotify pgrst, 'reload schema';`));
console.log(output);
