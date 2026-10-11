begin;
do $$ begin
  if to_regclass('public.raw_items') is not null then
    raise exception 'Unexpected database target';
  end if;
  if to_regprocedure('public.meet_api(text,uuid,jsonb)') is null then
    raise exception 'Install the Aliyun community adapter first';
  end if;
end $$;
-- This bucket contains only the pinned image-processing binary, no user data.
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values ('community-runtime','community-runtime',false,16000000,array['application/wasm'])
on conflict(id) do update set public=false,file_size_limit=16000000,allowed_mime_types=array['application/wasm'];
commit;
