-- Apply only to the dedicated AmazingIndex community project.
-- Review is performed by operators in the Supabase dashboard for this MVP.
begin;

do $$ begin
  if to_regclass('public.raw_items') is not null then
    raise exception 'Refusing to install community tables in the news pipeline project';
  end if;
end $$;

create table public.meet_posts (
  id bigint generated always as identity primary key,
  owner_id uuid not null unique references auth.users(id) on delete cascade,
  nickname text not null check (char_length(btrim(nickname)) between 1 and 30),
  age integer not null check (age between 18 and 100),
  gender text not null check (gender in ('女', '男', '其他')),
  city text not null check (char_length(btrim(city)) between 1 and 40),
  occupation text not null default '' check (char_length(occupation) <= 60),
  title text not null check (char_length(btrim(title)) between 2 and 60),
  about text not null check (char_length(btrim(about)) between 20 and 2000),
  looking_for text not null default '' check (char_length(looking_for) <= 1000),
  status text not null default 'pending' check (status in ('pending', 'published', 'rejected', 'withdrawn')),
  consent_version text not null,
  consent_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '30 days')
);

create table public.meet_contacts (
  owner_id uuid primary key references auth.users(id) on delete cascade,
  post_id bigint not null unique references public.meet_posts(id) on delete cascade,
  contact text not null default '' check (char_length(contact) <= 100),
  share_contact boolean not null default false,
  check (contact = '' or share_contact)
);

create index meet_posts_published_id on public.meet_posts(id desc) where status = 'published';

alter table public.meet_posts enable row level security;
alter table public.meet_contacts enable row level security;
revoke all on public.meet_posts, public.meet_contacts from public, anon, authenticated;
revoke all on sequence public.meet_posts_id_seq from public, anon, authenticated;
grant select on public.meet_posts, public.meet_contacts to authenticated;
grant all on public.meet_posts, public.meet_contacts to service_role;
grant all on sequence public.meet_posts_id_seq to service_role;

create policy meet_posts_owner_read on public.meet_posts for select to authenticated using ((select auth.uid()) = owner_id);
create policy meet_contacts_owner_read on public.meet_contacts for select to authenticated using ((select auth.uid()) = owner_id);

-- Clients cannot write table rows or set owner/status/timestamps themselves.
create function public.submit_meet_post(
  p_nickname text, p_age integer, p_gender text, p_city text, p_occupation text,
  p_title text, p_about text, p_looking_for text, p_contact text,
  p_consent boolean, p_share_contact boolean
) returns bigint language plpgsql security definer set search_path = '' as $$
declare
  v_user uuid := auth.uid();
  v_id bigint;
  v_updated timestamptz;
begin
  if v_user is null or not exists (
    select 1 from auth.users where id = v_user and email_confirmed_at is not null and not coalesce(is_anonymous, false)
      and (banned_until is null or banned_until <= now())
  ) then raise exception 'Verified email required' using errcode = '42501'; end if;
  if p_consent is distinct from true or (coalesce(btrim(p_contact), '') <> '' and p_share_contact is distinct from true) then
    raise exception 'Explicit consent required' using errcode = '22023';
  end if;
  -- Serialize submissions per user, including the first insert.
  perform pg_advisory_xact_lock(hashtextextended(v_user::text, 0));
  select updated_at into v_updated from public.meet_posts where owner_id = v_user;
  if v_updated > now() - interval '60 seconds' then raise exception 'Please wait 60 seconds'; end if;
  insert into public.meet_posts(owner_id,nickname,age,gender,city,occupation,title,about,looking_for,consent_version)
  values (v_user,btrim(p_nickname),p_age,p_gender,btrim(p_city),btrim(coalesce(p_occupation,'')),btrim(p_title),btrim(p_about),btrim(coalesce(p_looking_for,'')),'2026-10-08')
  on conflict (owner_id) do update set
    nickname=excluded.nickname,age=excluded.age,gender=excluded.gender,city=excluded.city,
    occupation=excluded.occupation,title=excluded.title,about=excluded.about,looking_for=excluded.looking_for,
    status='pending',consent_version=excluded.consent_version,consent_at=now(),updated_at=now(),expires_at=now()+interval '30 days'
  returning id into v_id;
  insert into public.meet_contacts(owner_id,post_id,contact,share_contact)
  values (v_user,v_id,btrim(coalesce(p_contact,'')),coalesce(p_share_contact,false))
  on conflict (owner_id) do update set contact=excluded.contact,share_contact=excluded.share_contact;
  return v_id;
end $$;

create function public.withdraw_meet_post() returns void language plpgsql security definer set search_path = '' as $$
begin
  if auth.uid() is null then raise exception 'Login required' using errcode = '42501'; end if;
  perform pg_advisory_xact_lock(hashtextextended(auth.uid()::text, 0));
  update public.meet_posts set status='withdrawn',updated_at=now() where owner_id=auth.uid();
end $$;

create function public.list_meet_posts(p_before bigint default null, p_limit integer default 20)
returns table(id bigint,nickname text,age integer,gender text,city text,occupation text,title text,about text,looking_for text,created_at timestamptz,expires_at timestamptz)
language sql stable security definer set search_path = '' as $$
  select p.id,p.nickname,p.age,p.gender,p.city,p.occupation,p.title,p.about,p.looking_for,p.created_at,p.expires_at
  from public.meet_posts p
  where p.status='published' and p.expires_at>now()
    and (p_before is null or p.id<p_before)
  order by p.id desc limit least(greatest(coalesce(p_limit,20),1),50);
$$;

create function public.get_meet_post(p_id bigint)
returns table(id bigint,nickname text,age integer,gender text,city text,occupation text,title text,about text,looking_for text,created_at timestamptz,expires_at timestamptz)
language sql stable security definer set search_path = '' as $$
  select p.id,p.nickname,p.age,p.gender,p.city,p.occupation,p.title,p.about,p.looking_for,p.created_at,p.expires_at
  from public.meet_posts p where p.id=p_id and ((p.status='published' and p.expires_at>now()) or p.owner_id=auth.uid());
$$;

create function public.get_meet_contact(p_id bigint) returns text
language plpgsql stable security definer set search_path = '' as $$
declare v_contact text;
begin
  if auth.uid() is null or not exists (
    select 1 from auth.users where id=auth.uid() and email_confirmed_at is not null and not coalesce(is_anonymous,false)
      and (banned_until is null or banned_until <= now())
  ) then raise exception 'Verified email required' using errcode = '42501'; end if;
  select c.contact into v_contact from public.meet_contacts c join public.meet_posts p on p.id=c.post_id
  where p.id=p_id and ((p.status='published' and p.expires_at>now() and c.share_contact) or p.owner_id=auth.uid());
  return v_contact;
end $$;

create function public.meet_publish_expiry() returns trigger language plpgsql set search_path = '' as $$
begin
  if new.status='published' and old.status is distinct from 'published' then
    new.expires_at := now() + interval '30 days';
  end if;
  return new;
end $$;
create trigger meet_publish_expiry before update on public.meet_posts for each row execute function public.meet_publish_expiry();

revoke all on function public.submit_meet_post(text,integer,text,text,text,text,text,text,text,boolean,boolean) from public,anon,authenticated;
revoke all on function public.withdraw_meet_post() from public,anon,authenticated;
revoke all on function public.list_meet_posts(bigint,integer) from public,anon,authenticated;
revoke all on function public.get_meet_post(bigint) from public,anon,authenticated;
revoke all on function public.get_meet_contact(bigint) from public,anon,authenticated;
revoke all on function public.meet_publish_expiry() from public,anon,authenticated;
grant execute on function public.submit_meet_post(text,integer,text,text,text,text,text,text,text,boolean,boolean),public.withdraw_meet_post(),public.get_meet_contact(bigint) to authenticated;
grant execute on function public.list_meet_posts(bigint,integer),public.get_meet_post(bigint) to anon,authenticated;
commit;
