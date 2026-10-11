begin;

-- Browser uploads are scoped to a short-lived, owner-created reservation.
alter table public.meet_photos drop constraint if exists meet_photos_sort_order_check;
alter table public.meet_photos add constraint meet_photos_sort_order_check check (sort_order between 0 and 5);

grant select on public.meet_photos to authenticated;
grant insert (id,owner_id) on public.meet_photos to authenticated;
grant update (state,width,height,bytes) on public.meet_photos to authenticated;
create policy meet_photo_owner_read on public.meet_photos for select to authenticated
  using (owner_id=auth.uid());
create policy meet_photo_owner_reserve on public.meet_photos for insert to authenticated
  with check (owner_id=auth.uid() and post_id is null and state='uploading');
create policy meet_photo_owner_finish on public.meet_photos for update to authenticated
  using (owner_id=auth.uid() and post_id is null and state='uploading' and created_at>now()-interval '15 minutes')
  with check (owner_id=auth.uid() and post_id is null and state='ready');

create function public.limit_meet_photo_reservations() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  perform pg_advisory_xact_lock(hashtextextended(new.owner_id::text,0));
  if (select count(*) from public.meet_photos where owner_id=new.owner_id)>=12 then
    raise exception 'Too many uploaded photos' using errcode='22023';
  end if;
  return new;
end $$;
create trigger limit_meet_photo_reservations before insert on public.meet_photos
  for each row execute function public.limit_meet_photo_reservations();
revoke all on function public.limit_meet_photo_reservations() from public,anon,authenticated;

create policy meet_photo_reserved_insert on storage.objects for insert to authenticated
  with check (bucket_id='meet-photos' and exists (
    select 1 from public.meet_photos p
    where p.owner_id=auth.uid() and p.post_id is null and p.state='uploading'
      and p.created_at>now()-interval '15 minutes'
      and name in (
        p.owner_id::text||'/'||p.id::text||'/photo.jpg',
        p.owner_id::text||'/'||p.id::text||'/thumb.jpg'
      )
  ));

create or replace function public.submit_meet_post(
  p_nickname text,p_age integer,p_gender text,p_city text,p_occupation text,
  p_title text,p_about text,p_looking_for text,p_contact text,p_consent boolean,p_share_contact boolean,
  p_photo_ids uuid[]
) returns bigint language plpgsql security definer set search_path='' as $$
declare v_id bigint; v_user uuid:=auth.uid();
begin
  if v_user is null then raise exception 'Login required' using errcode='42501'; end if;
  perform pg_advisory_xact_lock(hashtextextended(v_user::text,0));
  if p_photo_ids is null or cardinality(p_photo_ids)>6
    or cardinality(p_photo_ids)<>(select count(distinct id) from unnest(p_photo_ids) as id) then
    raise exception 'Choose up to 6 distinct photos' using errcode='22023';
  end if;
  perform 1 from public.meet_photos where id=any(p_photo_ids) and owner_id=v_user for update;
  if cardinality(p_photo_ids)<>(select count(*) from public.meet_photos where id=any(p_photo_ids) and owner_id=v_user and state='ready') then
    raise exception 'Invalid photo ownership or state' using errcode='22023';
  end if;
  if exists (
    select 1 from unnest(p_photo_ids) f(id)
    where not exists (select 1 from storage.objects o where o.bucket_id='meet-photos' and o.name=v_user::text||'/'||f.id::text||'/photo.jpg')
       or not exists (select 1 from storage.objects o where o.bucket_id='meet-photos' and o.name=v_user::text||'/'||f.id::text||'/thumb.jpg')
  ) then raise exception 'Photo upload incomplete' using errcode='22023'; end if;
  v_id:=public.submit_meet_post_text(p_nickname,p_age,p_gender,p_city,p_occupation,p_title,p_about,p_looking_for,p_contact,p_consent,p_share_contact);
  delete from public.meet_photos where post_id=v_id and not(id=any(p_photo_ids));
  update public.meet_photos p set post_id=v_id,sort_order=s.ordinality-1
    from unnest(p_photo_ids) with ordinality s(id,ordinality) where p.id=s.id;
  update public.meet_posts set consent_version='2026-10-10-photos' where id=v_id;
  return v_id;
end $$;

create or replace function public.list_meet_photos(p_posts bigint[] default '{}',p_own boolean default false)
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
  ) order by f.post_id,f.sort_order,f.created_at limit 132;
end $$;

-- Keep the private read and deletion model; no browser SELECT/DELETE/UPDATE on Storage.
notify pgrst, 'reload schema';
commit;
