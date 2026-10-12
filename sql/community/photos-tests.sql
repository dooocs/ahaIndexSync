begin;
insert into auth.users(id,email,email_confirmed_at) values
 ('11111111-1111-4111-8111-111111111111','photo-owner@example.test',now()),
 ('22222222-2222-4222-8222-222222222222','photo-reader@example.test',now());
select set_config('request.jwt.claim.sub','11111111-1111-4111-8111-111111111111',true);
set local role service_role;
select public.reserve_meet_photo('11111111-1111-4111-8111-111111111111','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa');
update public.meet_photos set state='ready',width=800,height=1000,bytes=100000 where id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
reset role;
set local role authenticated;
do $$ begin
  begin
    perform public.reserve_meet_photo(auth.uid(),'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb');
    raise exception 'Client could reserve an upload';
  exception when insufficient_privilege then null; end;
  begin
    perform public.submit_meet_post_text('测试',28,'女','杭州','','图片测试','这是一段足够长的自动化测试自我介绍，用于验证图片权限。','','',true,false);
    raise exception 'Client bypassed photo wrapper';
  exception when insufficient_privilege then null; end;
  begin
    perform public.submit_meet_post('测试',28,'女','杭州','','图片测试','这是一段足够长的自动化测试自我介绍，用于验证图片权限。','','',true,false,array['aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa']::uuid[]);
    raise exception 'Duplicate photos accepted';
  exception when invalid_parameter_value then null; end;
end $$;
select public.submit_meet_post('测试',28,'女','杭州','','图片测试','这是一段足够长的自动化测试自我介绍，用于验证图片权限。','','',true,false,array['aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa']::uuid[]);
select set_config('test.photo_post',(select id::text from public.meet_posts where owner_id=auth.uid()),true);
do $$ begin
  if (select count(*) from public.list_meet_photos('{}',true))<>1 then raise exception 'Owner preview failed'; end if;
end $$;
reset role;
select set_config('request.jwt.claim.sub','22222222-2222-4222-8222-222222222222',true);
set local role authenticated;
do $$ begin
  if exists(select 1 from public.list_meet_photos(array[current_setting('test.photo_post')::bigint],false)) then raise exception 'Pending photo visible'; end if;
  begin
    perform public.submit_meet_post('测试',28,'男','上海','','图片测试','这是一段足够长的自动化测试自我介绍，用于验证图片权限。','','',true,false,array['aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa']::uuid[]);
    raise exception 'Stolen photo accepted';
  exception when invalid_parameter_value then null; end;
end $$;
reset role;
update public.meet_posts set status='published' where owner_id='11111111-1111-4111-8111-111111111111';
select set_config('test.photo_post',(select id::text from public.meet_posts where owner_id='11111111-1111-4111-8111-111111111111'),true);
set local role authenticated;
do $$ begin
  if (select count(*) from public.list_meet_photos(array[current_setting('test.photo_post')::bigint],false))<>1 then raise exception 'Published photo unavailable'; end if;
end $$;
reset role;
update public.meet_posts set expires_at=now()-interval '1 second' where owner_id='11111111-1111-4111-8111-111111111111';
set local role authenticated;
do $$ begin
  if exists(select 1 from public.list_meet_photos(array[current_setting('test.photo_post')::bigint],false)) then raise exception 'Expired photo visible'; end if;
end $$;
reset role;
set local role anon;
do $$ begin
  begin perform public.list_meet_photos('{}',true); raise exception 'Anonymous photo access';
  exception when insufficient_privilege then null; end;
end $$;
reset role;
delete from auth.users where id='11111111-1111-4111-8111-111111111111';
do $$ begin
  if exists(select 1 from public.meet_photos where owner_id='11111111-1111-4111-8111-111111111111') then raise exception 'Photo cascade failed'; end if;
  if not exists(select 1 from public.meet_photo_deletions where id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa') then raise exception 'Storage cleanup not queued'; end if;
end $$;
rollback;
