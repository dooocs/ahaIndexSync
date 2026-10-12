begin;
create function pg_temp.assert_ok(ok boolean,label text) returns void language plpgsql as $$
begin if ok is distinct from true then raise exception 'FAILED: %',label; end if; end $$;
create function pg_temp.expect_error(statement text,expected text) returns void language plpgsql as $$
begin begin execute statement; exception when others then if sqlstate=expected then return; end if; raise; end;
raise exception 'Expected % for %',expected,statement; end $$;
insert into auth.users(id,email,email_confirmed_at,is_anonymous) values('55555555-1111-4111-8111-111111111111','review-sql@example.test',now(),false);
insert into public.meet_posts(owner_id,nickname,age,gender,city,title,about,consent_version)
values('55555555-1111-4111-8111-111111111111','Review fixture',28,'女','杭州','Review fixture','This is a temporary moderation test post.','test');
select set_config('review.test.id',(select id::text from public.meet_posts where owner_id='55555555-1111-4111-8111-111111111111'),true);
set local role anon;
select pg_temp.expect_error($q$select public.get_meet_review_post(current_setting('review.test.id')::bigint)$q$,'42501');
select pg_temp.expect_error('select * from public.meet_review_events','42501');
set local role authenticated;
select pg_temp.expect_error($q$select public.review_meet_post(current_setting('review.test.id')::bigint,repeat('a',32),'published','','link:1234567890abcdef')$q$,'42501');
reset role;
select set_config('review.test.version',(public.get_meet_review_post(current_setting('review.test.id')::bigint)->>'version'),true);
update public.meet_posts set about='Changed after the reviewer loaded the page.' where id=current_setting('review.test.id')::bigint;
select pg_temp.expect_error($q$select public.review_meet_post(current_setting('review.test.id')::bigint,current_setting('review.test.version'),'published','','link:1234567890abcdef')$q$,'PT409');
select set_config('review.test.version',(public.get_meet_review_post(current_setting('review.test.id')::bigint)->>'version'),true);
set local role service_role;
select public.review_meet_post(current_setting('review.test.id')::bigint,current_setting('review.test.version'),'rejected','Please complete your profile.','link:1234567890abcdef');
select pg_temp.assert_ok((select review_reason='Please complete your profile.' and status='rejected' from public.meet_posts where id=current_setting('review.test.id')::bigint),'reason persisted');
select pg_temp.assert_ok((select count(*)=1 from public.meet_review_events where post_id=current_setting('review.test.id')::bigint),'audit entry');
select pg_temp.expect_error($q$select public.review_meet_post(current_setting('review.test.id')::bigint,current_setting('review.test.version'),'published','','link:1234567890abcdef')$q$,'PT409');
reset role;
update public.meet_posts set status='pending' where id=current_setting('review.test.id')::bigint;
select pg_temp.assert_ok((select review_reason='' and reviewed_at is null from public.meet_posts where id=current_setting('review.test.id')::bigint),'resubmission clears feedback');
select public.review_meet_post(current_setting('review.test.id')::bigint,public.get_meet_review_post(current_setting('review.test.id')::bigint)->>'version','published','','link:1234567890abcdef');
select pg_temp.assert_ok((select status='published' and expires_at>now()+interval '29 days' from public.meet_posts where id=current_setting('review.test.id')::bigint),'approval expires after 30 days');
select pg_temp.expect_error($q$select public.review_meet_post(current_setting('review.test.id')::bigint,public.get_meet_review_post(current_setting('review.test.id')::bigint)->>'version','withdrawn','','link:1234567890abcdef')$q$,'22023');
select public.review_meet_post(current_setting('review.test.id')::bigint,public.get_meet_review_post(current_setting('review.test.id')::bigint)->>'version','withdrawn','Removed after review.','link:1234567890abcdef');
select pg_temp.expect_error($q$select public.review_meet_post(current_setting('review.test.id')::bigint,public.get_meet_review_post(current_setting('review.test.id')::bigint)->>'version','published','','link:1234567890abcdef')$q$,'22023');
rollback;
