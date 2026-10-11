import { readFile, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const directory = dirname(fileURLToPath(import.meta.url));
const files = ['001_community_mvp.sql','002_community_photos.sql','aliyun-cleanup.sql',
  '004_photo_consent.sql','005_private_review.sql','006_review_conflict.sql','008_direct_photo_upload.sql'];
const bodies = [];
for (const file of files) {
  const source = await readFile(join(directory,file),'utf8');
  if (!/^begin;\s/i.test(source.replace(/^(--[^\n]*\n)*/,'').trim()) || !/commit;\s*$/i.test(source)) {
    throw new Error(`Unexpected migration boundary in ${file}`);
  }
  // Mechanical compatibility rewrite of our fixed, reviewed migration files.
  // One enclosing transaction prevents any intermediate client RPC grants.
  bodies.push(source.replace(/^begin;\s*$/mi,'').replace(/^commit;\s*$/mi,'')
    .replace(/\bsecurity definer\b/gi,'security invoker'));
}
const adapter = await readFile(join(directory,'aliyun-invoker.sql'),'utf8');
const output = resolve(process.argv[2] || '/tmp/amazingindex-community-aliyun.sql');
await writeFile(output,`begin;\n${bodies.join('\n')}\n${adapter}\nnotify pgrst, 'reload schema';\ncommit;\n`,{mode:0o600});
console.log(JSON.stringify({output,migrations:files.length,mode:'service-role-only-invoker'}));
