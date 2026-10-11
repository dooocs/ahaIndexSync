import { mkdir, readFile, stat, rename } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const directory=dirname(fileURLToPath(import.meta.url));
const output=resolve(process.argv[2] || '/tmp/amazingindex-community-functions');
for (const slug of ['meet-api','meet-photos','meet-public-photos','meet-review','meet-photo-cleanup']) {
  const target=join(output,slug); await mkdir(target,{recursive:true,mode:0o700});
  const file=join(target,'index.js');
  const result=spawnSync(process.env.DENO || 'deno',['bundle','--platform','deno','--packages','bundle','--minify','--no-lock',
    '--output',file,join(directory,'supabase/functions',slug,'index.ts')],{encoding:'utf8',timeout:120000});
  if (result.status!==0) throw new Error(`Cannot bundle ${slug}: ${result.stderr}`);
  const check=spawnSync(process.env.DENO || 'deno',['check','--no-npm','--no-remote',file],{encoding:'utf8',timeout:30000});
  if (check.status!==0) throw new Error(`External dependency remains in ${slug}`);
  if (!(await readFile(file,'utf8')).includes('Deno.serve')) throw new Error(`Missing handler in ${slug}`);
  console.log(JSON.stringify({slug,bytes:(await stat(file)).size,bundled:true}));
  await rename(file,join(target,'index.ts'));
}
