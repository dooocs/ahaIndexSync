-- Run after 001_community_mvp.sql in a disposable Supabase-compatible database.
begin;
create function pg_temp.assert_ok(ok boolean, label text) returns void language plpgsql as $$
begin if ok is distinct from true then raise exception 'FAILED: %', label; end if; end $$;
create function pg_temp.expect_error(statement text, expected text) returns void language plpgsql as $$
begin
  begin execute statement;
  exception when others then
    if sqlstate = expected then return; end if;
    raise;
  end;
  raise exception 'Expected SQLSTATE % for %', expected, statement;
end $$;

insert into auth.users(id,email,email_confirmed_at,is_anonymous) values
 ('11111111-1111-4111-8111-111111111111','community-a@example.test',now(),false),
 ('22222222-2222-4222-8222-222222222222','community-b@example.test',now(),false),
 ('33333333-3333-4333-8333-333333333333','community-unverified@example.test',null,false);

set local role anon;
select pg_temp.assert_ok((select count(*)=0 from public.list_meet_posts()), 'empty feed');
select pg_temp.expect_error('select * from public.meet_contacts', '42501');
select pg_temp.expect_error('select public.get_meet_contact(1)', '42501');
select pg_temp.expect_error('select public.withdraw_meet_post()', '42501');

set local role authenticated;
select set_config('request.jwt.claim.sub','33333333-3333-4333-8333-333333333333',true);
select pg_temp.expect_error($q$select public.submit_meet_post('Unverified',28,'男','杭州','','Hello world','This is a complete introduction for a test user.','','',true,false)$q$, '42501');
select set_config('request.jwt.claim.sub','11111111-1111-4111-8111-111111111111',true);
select pg_temp.expect_error($q$select public.submit_meet_post('Alice',17,'女','杭州','','Hello world','This is a complete introduction for a test user.','','',true,false)$q$, '23514');
select pg_temp.expect_error($q$select public.submit_meet_post('Alice',28,'女','   ','','Hello world','This is a complete introduction for a test user.','','',true,false)$q$, '23514');
select pg_temp.expect_error($q$select public.submit_meet_post('Alice',null,'女','杭州','','Hello world','This is a complete introduction for a test user.','','',true,false)$q$, '23502');
select pg_temp.expect_error($q$select public.submit_meet_post('Alice',28,'不公开','杭州','','Hello world','This is a complete introduction for a test user.','','',true,false)$q$, '23514');
select pg_temp.expect_error($q$select public.submit_meet_post('Alice',28,'','杭州','','Hello world','This is a complete introduction for a test user.','','',true,false)$q$, '23514');
select pg_temp.expect_error($q$select public.submit_meet_post('Alice',28,'女','杭州','','Hello world','This is a complete introduction for a test user.','','',false,false)$q$, '22023');
select pg_temp.expect_error($q$select public.submit_meet_post('Alice',28,'女','杭州','','Hello world','This is a complete introduction for a test user.','','private-contact',true,false)$q$, '22023');
select public.submit_meet_post('Alice',28,'女','杭州','Engineer','Hello world','This is a complete introduction for a test user.','A kind person','private-contact',true,true);
select pg_temp.assert_ok((select count(*)=1 from public.meet_posts), 'owner can read pending post');
select pg_temp.assert_ok((select count(*)=0 from public.list_meet_posts()), 'pending excluded from feed');
select pg_temp.expect_error($q$update public.meet_posts set status='published'$q$, '42501');
select pg_temp.expect_error($q$delete from public.meet_posts$q$, '42501');
select pg_temp.expect_error($q$update public.meet_contacts set share_contact=false$q$, '42501');
select pg_temp.expect_error($q$select public.submit_meet_post('Alice',28,'女','杭州','','Hello again','This is a complete introduction for a test user.','','',true,false)$q$, 'P0001');
select set_config('request.jwt.claim.sub','22222222-2222-4222-8222-222222222222',true);
select pg_temp.assert_ok((select count(*)=0 from public.meet_posts), 'other user cannot read raw rows');
select pg_temp.assert_ok((select count(*)=0 from public.meet_contacts), 'other user cannot read private contacts');
select public.withdraw_meet_post();

reset role;
select pg_temp.assert_ok((select status='pending' from public.meet_posts), 'other user cannot withdraw owner post');
select set_config('community.test.post_id',(select id::text from public.meet_posts),true);
update public.meet_posts set status='published';
set local role anon;
select set_config('request.jwt.claim.sub','',true);
select pg_temp.assert_ok((select count(*)=1 from public.list_meet_posts()), 'published visible');
select pg_temp.assert_ok((select city='杭州' and age=28 and gender='女' from public.list_meet_posts()), 'required details are publicly displayed');
select pg_temp.assert_ok((select count(*)=0 from public.list_meet_posts(current_setting('community.test.post_id')::bigint)), 'cursor excludes previous page');
select pg_temp.assert_ok((select count(*)=1 from public.get_meet_post(current_setting('community.test.post_id')::bigint)), 'published detail visible');

set local role authenticated;
select set_config('request.jwt.claim.sub','22222222-2222-4222-8222-222222222222',true);
select pg_temp.assert_ok(public.get_meet_contact(current_setting('community.test.post_id')::bigint)='private-contact','verified user can see consented contact');
reset role;
update auth.users set banned_until=now()+interval '1 day' where id='22222222-2222-4222-8222-222222222222';
set local role authenticated;
select pg_temp.expect_error($q$select public.get_meet_contact(current_setting('community.test.post_id')::bigint)$q$,'42501');
reset role;
update auth.users set banned_until=null;
update public.meet_posts set expires_at=now()-interval '1 second';
set local role authenticated;
select pg_temp.assert_ok(public.get_meet_contact(current_setting('community.test.post_id')::bigint) is null,'expired contact hidden');
select pg_temp.assert_ok((select count(*)=0 from public.list_meet_posts()),'expired feed hidden');
reset role;
update public.meet_posts set expires_at=now()+interval '30 days',updated_at=now()-interval '2 minutes';
set local role authenticated;
select set_config('request.jwt.claim.sub','11111111-1111-4111-8111-111111111111',true);
select public.submit_meet_post('Alice',28,'女','杭州','','Updated introduction','This is an updated introduction for a test user.','','',true,false);
select pg_temp.assert_ok((select count(*)=1 from public.meet_posts),'one post per user');
select pg_temp.assert_ok((select status='pending' from public.meet_posts),'edit requires re-review');
select pg_temp.assert_ok((select count(*)=0 from public.list_meet_posts()),'edited post no longer public');
select public.withdraw_meet_post();
select pg_temp.assert_ok((select status='withdrawn' from public.meet_posts),'owner withdraws');
select set_config('request.jwt.claim.sub','22222222-2222-4222-8222-222222222222',true);
select pg_temp.assert_ok((select count(*)=0 from public.get_meet_post(current_setting('community.test.post_id')::bigint)),'withdrawn detail hidden');
select pg_temp.assert_ok(public.get_meet_contact(current_setting('community.test.post_id')::bigint) is null,'withdrawn contact hidden');
reset role;
delete from auth.users where id='11111111-1111-4111-8111-111111111111';
select pg_temp.assert_ok((select count(*)=0 from public.meet_posts),'account deletion cascades posts');
select pg_temp.assert_ok((select count(*)=0 from public.meet_contacts),'account deletion cascades contacts');
rollback;
