begin;
alter table public.meet_posts add column review_reason text not null default '' check (char_length(review_reason)<=500);
alter table public.meet_posts add column reviewed_at timestamptz;

create table public.meet_review_events (
  id bigint generated always as identity primary key,
  post_id bigint references public.meet_posts(id) on delete set null,
  from_status text not null,
  to_status text not null,
  reason text not null,
  reviewer text not null,
  created_at timestamptz not null default now()
);
alter table public.meet_review_events enable row level security;
revoke all on public.meet_review_events from public,anon,authenticated;
revoke all on sequence public.meet_review_events_id_seq from public,anon,authenticated;
grant all on public.meet_review_events to service_role;
grant all on sequence public.meet_review_events_id_seq to service_role;

create function public.clear_meet_review() returns trigger language plpgsql set search_path='' as $$
begin
  if new.status='pending' then new.review_reason:=''; new.reviewed_at:=null; end if;
  return new;
end $$;
create trigger clear_meet_review before update on public.meet_posts for each row execute function public.clear_meet_review();

-- The same snapshot is displayed and compared under the submit/withdraw lock.
create function public.meet_review_snapshot(p_id bigint) returns jsonb
language sql stable security definer set search_path='' as $$
  select jsonb_build_object(
    'post',to_jsonb(p),
    'contact',(select jsonb_build_object('contact',c.contact,'share_contact',c.share_contact) from public.meet_contacts c where c.post_id=p.id),
    'photos',coalesce((select jsonb_agg(to_jsonb(f) order by f.sort_order,f.id) from public.meet_photos f where f.post_id=p.id),'[]'::jsonb)
  ) from public.meet_posts p where p.id=p_id;
$$;
create function public.get_meet_review_post(p_id bigint) returns jsonb
language sql stable security definer set search_path='' as $$
  select case when s is null then null else jsonb_build_object('snapshot',s,'version',md5(s::text)) end
  from (select public.meet_review_snapshot(p_id) as s) q;
$$;

create function public.review_meet_post(p_id bigint,p_version text,p_status text,p_reason text,p_reviewer text)
returns void language plpgsql security definer set search_path='' as $$
declare v_owner uuid; v_snapshot jsonb; v_previous text;
begin
  if p_status is null or p_status not in ('published','rejected','withdrawn')
    or p_version is null or p_version !~ '^[0-9a-f]{32}$'
    or p_reviewer is null or p_reviewer !~ '^link:[0-9a-f]{16}$'
    or p_reason is null or char_length(btrim(p_reason))>500
    or (p_status in ('rejected','withdrawn') and btrim(p_reason)='') then
    raise exception 'Invalid review' using errcode='22023';
  end if;
  select owner_id into v_owner from public.meet_posts where id=p_id;
  if v_owner is null then raise exception 'Post missing' using errcode='P0002'; end if;
  perform pg_advisory_xact_lock(hashtextextended(v_owner::text,0));
  perform 1 from public.meet_posts where id=p_id for update;
  v_snapshot:=public.meet_review_snapshot(p_id);
  if v_snapshot is null then raise exception 'Post missing' using errcode='P0002'; end if;
  if md5(v_snapshot::text)<>p_version then raise exception 'Post changed' using errcode='40001'; end if;
  v_previous:=v_snapshot->'post'->>'status';
  if not ((v_previous='pending' and p_status in ('published','rejected'))
    or (v_previous='published' and p_status='withdrawn')) then
    raise exception 'Invalid transition' using errcode='22023';
  end if;
  if p_status='published' and not exists (
    select 1 from auth.users where id=v_owner and email_confirmed_at is not null
      and not coalesce(is_anonymous,false) and (banned_until is null or banned_until<=now())
  ) then raise exception 'Verified owner required' using errcode='22023'; end if;
  update public.meet_posts set status=p_status,review_reason=btrim(p_reason),reviewed_at=now() where id=p_id;
  insert into public.meet_review_events(post_id,from_status,to_status,reason,reviewer)
    values(p_id,v_previous,p_status,btrim(p_reason),p_reviewer);
end $$;

revoke all on function public.clear_meet_review(),public.meet_review_snapshot(bigint),public.get_meet_review_post(bigint),public.review_meet_post(bigint,text,text,text,text) from public,anon,authenticated;
grant execute on function public.get_meet_review_post(bigint),public.review_meet_post(bigint,text,text,text,text) to service_role;
commit;
