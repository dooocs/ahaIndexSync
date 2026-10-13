import { readFile, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// Generates the Aliyun variant of 010: no SECURITY DEFINER, service-role grants only,
// and the refreshed meet_api dispatcher (public action get_public_meet_contact).
const directory = dirname(fileURLToPath(import.meta.url));
const source = await readFile(join(directory, '010_public_contact.sql'), 'utf8');
if (!source.startsWith('begin;\n') || !source.trimEnd().endsWith('commit;')) throw new Error('Unexpected migration boundary');
const output = resolve(process.argv[2] || join(directory, '010_public_contact_aliyun.sql'));
const adapter = await readFile(join(directory, 'aliyun-invoker.sql'), 'utf8');
const end = adapter.indexOf('-- Existing checks');
if (end < 0 || !adapter.startsWith('-- Aliyun disallows')) throw new Error('Unexpected dispatcher boundary');
const dispatcher = adapter.slice(0, end).replace('create function public.meet_api(', 'create or replace function public.meet_api(');
const converted = source.replace(/\bsecurity definer\b/gi, 'security invoker')
  .replace(/ to anon,authenticated,service_role;/g, ' to service_role;')
  .replace(/ to authenticated,service_role;/g, ' to service_role;');
if (/security definer|to anon|to authenticated/i.test(converted)) throw new Error('Browser-role grant or definer left in Aliyun output');
await writeFile(output, converted.replace("notify pgrst, 'reload schema';", () => `${dispatcher}\nnotify pgrst, 'reload schema';`));
console.log(output);
