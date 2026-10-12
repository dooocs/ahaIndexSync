-- Dedicated community project only. Private objects are accessed through the Edge function.
begin;
do $$ begin
  if to_regclass('public.raw_items') is not null then raise exception 'Not a community project'; end if;
end $$;

insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values ('meet-photos','meet-photos',false,1048576,array['image/jpeg'])
on conflict (id) do update set public=false,file_size_limit=1048576,allowed_mime_types=array['image/jpeg'];

create table public.meet_photos (
  id uuid primary key,
  owner_id uuid not null references auth.users(id) on delete cascade,
  post_id bigint references public.meet_posts(id) on delete cascade,
  sort_order smallint not null default 0 check (sort_order between 0 and 2),
  state text not null default 'uploading' check (state in ('uploading','ready')),
  width integer check (width between 1 and 1600),
  height integer check (height between 1 and 1600),
  bytes integer check (bytes between 1 and 1048576),
  created_at timestamptz not null default now(),
  check (state <> 'ready' or (width is not null and height is not null and bytes is not null))
);
create index meet_photos_owner on public.meet_photos(owner_id);
create index meet_photos_post on public.meet_photos(post_id,sort_order);
create table public.meet_photo_upload_limits (
  owner_id uuid primary key references auth.users(id) on delete cascade,
  day date not null,
  attempts integer not null
);
-- No owner FK: queued object deletions must survive account erasure.
create table public.meet_photo_deletions (
  id uuid primary key,
  owner_id uuid not null,
  created_at timestamptz not null default now()
);
alter table public.meet_photos enable row level security;
alter table public.meet_photo_upload_limits enable row level security;
alter table public.meet_photo_deletions enable row level security;
revoke all on public.meet_photos,public.meet_photo_upload_limits,public.meet_photo_deletions from public,anon,authenticated;
grant all on public.meet_photos,public.meet_photo_upload_limits,public.meet_photo_deletions to service_role;

create function public.queue_meet_photo_deletion() returns trigger
language plpgsql security definer set search_path='' as $$
begin
  insert into public.meet_photo_deletions(id,owner_id) values(old.id,old.owner_id) on conflict do nothing;
  return old;
end $$;
create trigger queue_meet_photo_deletion before delete on public.meet_photos for each row execute function public.queue_meet_photo_deletion();

create function public.reserve_meet_photo(p_owner uuid,p_id uuid) returns void
language plpgsql security definer set search_path='' as $$
declare v_attempts integer;
begin
  if not exists(select 1 from auth.users where id=p_owner and email_confirmed_at is not null and not coalesce(is_anonymous,false)
    and (banned_until is null or banned_until<=now())) then raise exception 'Verified email required' using errcode='42501'; end if;
  perform pg_advisory_xact_lock(hashtextextended(p_owner::text,0));
  if (select count(*) from public.meet_photos where owner_id=p_owner)>=6 then
    raise exception 'Too many uploaded photos' using errcode='22023';
  end if;
  insert into public.meet_photo_upload_limits(owner_id,day,attempts) values(p_owner,current_date,1)
  on conflict(owner_id) do update set day=current_date,attempts=case when meet_photo_upload_limits.day=current_date then meet_photo_upload_limits.attempts+1 else 1 end
  returning attempts into v_attempts;
  if v_attempts>30 then raise exception 'Daily upload rate limit' using errcode='P0001'; end if;
  insert into public.meet_photos(id,owner_id) values(p_id,p_owner);
end $$;

-- The old write implementation remains private; only the photo-aware wrapper is exposed.
alter function public.submit_meet_post(text,integer,text,text,text,text,text,text,text,boolean,boolean) rename to submit_meet_post_text;
revoke all on function public.submit_meet_post_text(text,integer,text,text,text,text,text,text,text,boolean,boolean) from public,anon,authenticated;
create function public.submit_meet_post(
  p_nickname text,p_age integer,p_gender text,p_city text,p_occupation text,
  p_title text,p_about text,p_looking_for text,p_contact text,p_consent boolean,p_share_contact boolean,
  p_photo_ids uuid[]
) returns bigint language plpgsql security definer set search_path='' as $$
declare v_id bigint; v_user uuid:=auth.uid();
begin
  if v_user is null then raise exception 'Login required' using errcode='42501'; end if;
  perform pg_advisory_xact_lock(hashtextextended(v_user::text,0));
  if p_photo_ids is null or cardinality(p_photo_ids)>3
    or cardinality(p_photo_ids)<>(select count(distinct id) from unnest(p_photo_ids) as id) then
    raise exception 'Choose up to 3 distinct photos' using errcode='22023';
  end if;
  perform 1 from public.meet_photos where id=any(p_photo_ids) and owner_id=v_user for update;
  if cardinality(p_photo_ids)<>(select count(*) from public.meet_photos where id=any(p_photo_ids) and owner_id=v_user and state='ready') then
    raise exception 'Invalid photo ownership or state' using errcode='22023';
  end if;
  v_id:=public.submit_meet_post_text(p_nickname,p_age,p_gender,p_city,p_occupation,p_title,p_about,p_looking_for,p_contact,p_consent,p_share_contact);
  delete from public.meet_photos where post_id=v_id and not(id=any(p_photo_ids));
  update public.meet_photos p set post_id=v_id,sort_order=s.ordinality-1
    from unnest(p_photo_ids) with ordinality s(id,ordinality) where p.id=s.id;
  return v_id;
end $$;

create function public.list_meet_photos(p_posts bigint[] default '{}',p_own boolean default false)
returns table(id uuid,owner_id uuid,post_id bigint,sort_order smallint,width integer,height integer)
language plpgsql stable security definer set search_path='' as $$
begin
  if auth.uid() is null or not exists(select 1 from auth.users where users.id=auth.uid() and email_confirmed_at is not null and not coalesce(is_anonymous,false)
    and (banned_until is null or banned_until<=now())) then raise exception 'Verified email required' using errcode='42501'; end if;
  if cardinality(p_posts)>20 then raise exception 'Too many posts' using errcode='22023'; end if;
  return query select f.id,f.owner_id,f.post_id,f.sort_order,f.width,f.height from public.meet_photos f
  left join public.meet_posts p on p.id=f.post_id
  where f.state='ready' and (
    (p_own and f.owner_id=auth.uid()) or
    (f.post_id=any(p_posts) and (f.owner_id=auth.uid() or (p.status='published' and p.expires_at>now())))
  ) order by f.post_id,f.sort_order,f.created_at limit 66;
end $$;

create function public.meet_post_count() returns bigint language sql stable security definer set search_path='' as $$
  select count(*) from public.meet_posts where status='published' and expires_at>now();
$$;

create function public.sweep_meet_photos() returns void language plpgsql security definer set search_path='' as $$
begin
  delete from public.meet_photos where (state='uploading' and created_at<now()-interval '15 minutes')
    or (post_id is null and created_at<now()-interval '24 hours');
end $$;

revoke all on function public.queue_meet_photo_deletion(),public.reserve_meet_photo(uuid,uuid),public.sweep_meet_photos(),public.list_meet_photos(bigint[],boolean),public.meet_post_count(),public.submit_meet_post(text,integer,text,text,text,text,text,text,text,boolean,boolean,uuid[]) from public,anon,authenticated;
grant execute on function public.reserve_meet_photo(uuid,uuid),public.sweep_meet_photos() to service_role;
grant execute on function public.list_meet_photos(bigint[],boolean),public.submit_meet_post(text,integer,text,text,text,text,text,text,text,boolean,boolean,uuid[]) to authenticated;
grant execute on function public.meet_post_count() to anon,authenticated;
drop function public.list_meet_posts(bigint,integer);
drop function public.get_meet_post(bigint);
create function public.list_meet_posts(p_before bigint default null, p_limit integer default 20)
returns table(id bigint,nickname text,age integer,gender text,city text,occupation text,title text,about text,looking_for text,created_at timestamptz,expires_at timestamptz,photo_count bigint)
language sql stable security definer set search_path = '' as $$
  select p.id,p.nickname,p.age,p.gender,p.city,p.occupation,p.title,p.about,p.looking_for,p.created_at,p.expires_at,(select count(*) from public.meet_photos f where f.post_id=p.id and f.state='ready')
  from public.meet_posts p
  where p.status='published' and p.expires_at>now()
    and (p_before is null or p.id<p_before)
  order by p.id desc limit least(greatest(coalesce(p_limit,20),1),50);
$$;

create function public.get_meet_post(p_id bigint)
returns table(id bigint,nickname text,age integer,gender text,city text,occupation text,title text,about text,looking_for text,created_at timestamptz,expires_at timestamptz,photo_count bigint)
language sql stable security definer set search_path = '' as $$
  select p.id,p.nickname,p.age,p.gender,p.city,p.occupation,p.title,p.about,p.looking_for,p.created_at,p.expires_at,(select count(*) from public.meet_photos f where f.post_id=p.id and f.state='ready')
  from public.meet_posts p where p.id=p_id and ((p.status='published' and p.expires_at>now()) or p.owner_id=auth.uid());
$$;
revoke all on function public.list_meet_posts(bigint,integer),public.get_meet_post(bigint) from public,anon,authenticated;
grant execute on function public.list_meet_posts(bigint,integer),public.get_meet_post(bigint) to anon,authenticated;
commit;
