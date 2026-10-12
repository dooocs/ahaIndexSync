begin;
-- A stale review is an HTTP conflict, not a retryable serialization failure.
create or replace function public.review_meet_post(p_id bigint,p_version text,p_status text,p_reason text,p_reviewer text)
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
  if md5(v_snapshot::text)<>p_version then raise exception 'Post changed' using errcode='PT409'; end if;
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
commit;
