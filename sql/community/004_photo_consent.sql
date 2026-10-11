begin;
create or replace function public.submit_meet_post(
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
  update public.meet_posts set consent_version='2026-10-10-photos' where id=v_id;
  return v_id;
end $$;
commit;
