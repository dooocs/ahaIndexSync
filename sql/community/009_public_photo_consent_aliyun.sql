begin;

-- Only a new, explicitly consented submission opts photos into public viewing.
create or replace function public.submit_meet_post(
  p_nickname text,p_age integer,p_gender text,p_city text,p_occupation text,
  p_title text,p_about text,p_looking_for text,p_contact text,p_consent boolean,p_share_contact boolean,
  p_photo_ids uuid[],p_public_photos boolean
) returns bigint language plpgsql security invoker set search_path='' as $$
declare v_id bigint;
begin
  v_id:=public.submit_meet_post(p_nickname,p_age,p_gender,p_city,p_occupation,p_title,p_about,p_looking_for,p_contact,p_consent,p_share_contact,p_photo_ids);
  if p_public_photos is true then
    update public.meet_posts set consent_version='2026-10-11-public-photos' where id=v_id;
  end if;
  return v_id;
end $$;

revoke all on function public.submit_meet_post(text,integer,text,text,text,text,text,text,text,boolean,boolean,uuid[],boolean) from public,anon,authenticated;
grant execute on function public.submit_meet_post(text,integer,text,text,text,text,text,text,text,boolean,boolean,uuid[],boolean) to service_role;

-- Aliyun disallows new SECURITY DEFINER functions. Only the service role may
-- call this dispatcher, after the Edge function has verified the actor's JWT.
create or replace function public.meet_api(p_action text,p_actor uuid,p_params jsonb default '{}')
returns jsonb language plpgsql security invoker set search_path='' as $$
declare v_result jsonb;
begin
  if current_user <> 'service_role' then
    raise exception 'Server role required' using errcode='42501';
  end if;
  if p_action not in ('list_meet_posts','meet_post_count','get_meet_post','get_meet_contact','submit_meet_post','withdraw_meet_post','list_meet_photos') then
    raise exception 'Unknown action' using errcode='22023';
  end if;
  if p_actor is null and p_action not in ('list_meet_posts','meet_post_count','get_meet_post') then
    raise exception 'Login required' using errcode='42501';
  end if;
  -- Transaction-local claims cannot leak across pooled requests. The actor is
  -- never accepted from the browser body, only from GoTrue's getUser response.
  perform set_config('request.jwt.claim.sub',coalesce(p_actor::text,''),true);
  perform set_config('request.jwt.claims',jsonb_build_object('sub',p_actor,'role','authenticated')::text,true);
  case p_action
    when 'list_meet_posts' then
      select coalesce(jsonb_agg(to_jsonb(p)),'[]'::jsonb) into v_result
        from public.list_meet_posts((p_params->>'p_before')::bigint,(p_params->>'p_limit')::integer) p;
    when 'meet_post_count' then v_result := to_jsonb(public.meet_post_count());
    when 'get_meet_post' then
      select coalesce(jsonb_agg(to_jsonb(p)),'[]'::jsonb) into v_result
        from public.get_meet_post((p_params->>'p_id')::bigint) p;
    when 'get_meet_contact' then v_result := to_jsonb(public.get_meet_contact((p_params->>'p_id')::bigint));
    when 'withdraw_meet_post' then perform public.withdraw_meet_post(); v_result := 'null'::jsonb;
    when 'list_meet_photos' then
      select coalesce(jsonb_agg(to_jsonb(p)),'[]'::jsonb) into v_result from public.list_meet_photos(
        array(select jsonb_array_elements_text(coalesce(p_params->'p_posts','[]'::jsonb))::bigint),
        coalesce((p_params->>'p_own')::boolean,false)) p;
    when 'submit_meet_post' then
      v_result := to_jsonb(public.submit_meet_post(
        p_params->>'p_nickname',(p_params->>'p_age')::integer,p_params->>'p_gender',p_params->>'p_city',
        p_params->>'p_occupation',p_params->>'p_title',p_params->>'p_about',p_params->>'p_looking_for',
        p_params->>'p_contact',(p_params->>'p_consent')::boolean,(p_params->>'p_share_contact')::boolean,
        case when jsonb_typeof(p_params->'p_photo_ids')='array' then
          array(select jsonb_array_elements_text(p_params->'p_photo_ids')::uuid) else null end,
        coalesce((p_params->>'p_public_photos')::boolean,false)));
  end case;
  return v_result;
end $$;


notify pgrst, 'reload schema';
commit;
