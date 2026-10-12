import { createClient } from 'npm:@supabase/supabase-js@2.103.0';
import { admin, url } from '../_shared/photo-storage.ts';
import { requestAction, requestFailure } from './actions.ts';
import { requestAuthorization } from '../_shared/request-authorization.ts';

const headers = { 'Access-Control-Allow-Origin':'*', 'Access-Control-Allow-Headers':'authorization, apikey, content-type, x-client-info, x-community-authorization', 'Access-Control-Allow-Methods':'POST, OPTIONS', 'Cache-Control':'private, no-store' };
const reply = (data: unknown,status=200) => Response.json(data,{status,headers});

Deno.serve(async req => {
  if (req.method==='OPTIONS') return new Response(null,{headers});
  if (req.method!=='POST') return reply({error:{code:'22023',message:'Invalid request'}},405);
  try {
    const reader = req.body?.getReader();
    if (!reader) throw new Error('invalid_request');
    const chunks: Uint8Array[] = []; let size=0;
    while (true) {
      const {value,done} = await reader.read(); if (done) break;
      size+=value.length;
      if (size>20000) { await reader.cancel(); return reply({error:{code:'22023',message:'Request too large'}},413); }
      chunks.push(value);
    }
    const {action,params,needsUser} = requestAction(JSON.parse(await new Blob(chunks.map(c=>Uint8Array.from(c))).text()));
    const authorization = requestAuthorization(req.headers);
    const token = authorization?.startsWith('Bearer ') ? authorization.slice(7) : null;
    let actor: string | null = null;
    if (token && token!==Deno.env.get('SUPABASE_ANON_KEY')) {
      const auth = createClient(url,Deno.env.get('SUPABASE_ANON_KEY')!,{
        auth:{persistSession:false,autoRefreshToken:false},
        global:{fetch:(url,options)=>fetch(url,{...options,signal:AbortSignal.timeout(15000)})},
      });
      const {data:{user},error} = await auth.auth.getUser(token);
      if (error && (error.name==='AuthRetryableFetchError' || (error.status && error.status>=500))) {
        return reply({error:{code:'503',message:'Community service unavailable'}},503);
      }
      if (error || !user?.email_confirmed_at || user.is_anonymous ||
        (user.banned_until && Date.parse(user.banned_until)>Date.now())) {
        return reply({error:{code:'42501',message:'Verified email required'}},401);
      }
      actor=user.id;
    }
    if (needsUser && !actor) return reply({error:{code:'42501',message:'Verified email required'}},401);
    // Never use any actor/owner fields from the submitted body.
    const {data,error} = await admin.rpc('meet_api',{p_action:action,p_actor:actor,p_params:params});
    if (error) {
      if (['22023','22P02','23514','23502'].includes(error.code)) return reply({error:{code:'22023',message:'Invalid post'}},400);
      if (error.code==='42501') return reply({error:{code:'42501',message:'Verified email required'}},401);
      if (error.code==='P0001' && error.message==='Please wait 60 seconds') return reply({error:{code:'P0001',message:'Please wait 60 seconds'}},429);
      console.error('meet-api database failure',error.code);
      return reply({error:{code:'503',message:'Community service unavailable'}},503);
    }
    return reply({data});
  } catch (error) {
    const failure=requestFailure(error);
    if (failure.status===503) console.error('meet-api internal request failure');
    return reply({error:failure.error},failure.status);
  }
});
