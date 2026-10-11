begin;

-- Only a new, explicitly consented submission opts photos into public viewing.
create or replace function public.submit_meet_post(
  p_nickname text,p_age integer,p_gender text,p_city text,p_occupation text,
  p_title text,p_about text,p_looking_for text,p_contact text,p_consent boolean,p_share_contact boolean,
  p_photo_ids uuid[],p_public_photos boolean
) returns bigint language plpgsql security definer set search_path='' as $$
declare v_id bigint;
begin
  v_id:=public.submit_meet_post(p_nickname,p_age,p_gender,p_city,p_occupation,p_title,p_about,p_looking_for,p_contact,p_consent,p_share_contact,p_photo_ids);
  if p_public_photos is true then
    update public.meet_posts set consent_version='2026-10-11-public-photos' where id=v_id;
  end if;
  return v_id;
end $$;

revoke all on function public.submit_meet_post(text,integer,text,text,text,text,text,text,text,boolean,boolean,uuid[],boolean) from public,anon,authenticated;
grant execute on function public.submit_meet_post(text,integer,text,text,text,text,text,text,text,boolean,boolean,uuid[],boolean) to authenticated,service_role;

notify pgrst, 'reload schema';
commit;
