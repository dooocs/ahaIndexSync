-- Aliyun disallows new SECURITY DEFINER functions. Only the service role may
-- call this dispatcher, after the Edge function has verified the actor's JWT.
create function public.meet_api(p_action text,p_actor uuid,p_params jsonb default '{}')
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
          array(select jsonb_array_elements_text(p_params->'p_photo_ids')::uuid) else null end));
  end case;
  return v_result;
end $$;

-- Existing checks need only these Auth metadata columns, not passwords or
-- tokens. They remain unavailable to browser roles.
grant usage on schema auth to service_role;
grant select(id,email_confirmed_at,is_anonymous,banned_until) on auth.users to service_role;

-- Account erasure must still queue photo deletion under GoTrue's own role.
grant insert on public.meet_photo_deletions to supabase_auth_admin;
create policy meet_auth_delete_queue on public.meet_photo_deletions
  for insert to supabase_auth_admin with check (true);

do $$ declare f regprocedure;
begin
  for f in select oid::regprocedure from pg_proc where pronamespace='public'::regnamespace
    and proname in ('submit_meet_post','submit_meet_post_text','withdraw_meet_post','list_meet_posts',
      'get_meet_post','get_meet_contact','meet_publish_expiry','queue_meet_photo_deletion','reserve_meet_photo',
      'list_meet_photos','meet_post_count','sweep_meet_photos','configure_meet_photo_cleanup','clear_meet_review',
      'meet_review_snapshot','get_meet_review_post','review_meet_post','meet_api')
  loop
    execute format('revoke all on function %s from public,anon,authenticated',f);
    execute format('grant execute on function %s to service_role',f);
  end loop;
end $$;
