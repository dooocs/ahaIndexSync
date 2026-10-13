begin;

-- Public contact viewing, opt-in per submission (same pattern as 009 public photos).
-- Posts submitted before this migration keep their original audience: contact stays
-- visible to verified signed-in users only, until the author resubmits under the
-- public-contact terms.
alter table public.meet_contacts add column if not exists public_contact boolean not null default false;
alter table public.meet_contacts drop constraint if exists meet_contacts_public_requires_share;
alter table public.meet_contacts add constraint meet_contacts_public_requires_share
  check (not public_contact or (share_contact and contact <> ''));

-- Every contact write recomputes public visibility. It can only become true inside a
-- submission that explicitly carried p_public_contact=true (transaction-local flag),
-- so old cached clients, edits without the new consent, or other writers reset it.
create or replace function public.meet_contacts_public_guard() returns trigger
language plpgsql set search_path='' as $$
begin
  new.public_contact := coalesce(current_setting('community.public_contact', true), '') = 'on'
    and new.share_contact and new.contact <> '';
  return new;
end $$;
drop trigger if exists meet_contacts_public_guard on public.meet_contacts;
create trigger meet_contacts_public_guard before insert or update on public.meet_contacts
  for each row execute function public.meet_contacts_public_guard();

create or replace function public.submit_meet_post(
  p_nickname text,p_age integer,p_gender text,p_city text,p_occupation text,
  p_title text,p_about text,p_looking_for text,p_contact text,p_consent boolean,p_share_contact boolean,
  p_photo_ids uuid[],p_public_photos boolean,p_public_contact boolean
) returns bigint language plpgsql security invoker set search_path='' as $$
declare v_id bigint;
begin
  perform set_config('community.public_contact', case when p_public_contact is true then 'on' else '' end, true);
  v_id:=public.submit_meet_post(p_nickname,p_age,p_gender,p_city,p_occupation,p_title,p_about,p_looking_for,
    p_contact,p_consent,p_share_contact,p_photo_ids,p_public_photos);
  perform set_config('community.public_contact', '', true);
  return v_id;
end $$;

-- Anonymous read: only consented-public contacts of published, unexpired posts.
create or replace function public.get_public_meet_contact(p_id bigint) returns text
language sql stable security invoker set search_path='' as $$
  select c.contact from public.meet_contacts c join public.meet_posts p on p.id=c.post_id
  where p.id=p_id and p.status='published' and p.expires_at>now()
    and c.share_contact and c.public_contact and c.contact<>'';
$$;

revoke all on function public.meet_contacts_public_guard() from public,anon,authenticated;
revoke all on function public.submit_meet_post(text,integer,text,text,text,text,text,text,text,boolean,boolean,uuid[],boolean,boolean) from public,anon,authenticated;
grant execute on function public.submit_meet_post(text,integer,text,text,text,text,text,text,text,boolean,boolean,uuid[],boolean,boolean) to service_role;
revoke all on function public.get_public_meet_contact(bigint) from public,anon,authenticated;
grant execute on function public.get_public_meet_contact(bigint) to service_role;

-- Aliyun disallows new SECURITY DEFINER functions. Only the service role may
-- call this dispatcher, after the Edge function has verified the actor's JWT.
create or replace function public.meet_api(p_action text,p_actor uuid,p_params jsonb default '{}')
returns jsonb language plpgsql security invoker set search_path='' as $$
declare v_result jsonb;
begin
  if current_user <> 'service_role' then
    raise exception 'Server role required' using errcode='42501';
  end if;
  if p_action not in ('list_meet_posts','meet_post_count','get_meet_post','get_public_meet_contact','get_meet_contact','submit_meet_post','withdraw_meet_post','list_meet_photos') then
    raise exception 'Unknown action' using errcode='22023';
  end if;
  if p_actor is null and p_action not in ('list_meet_posts','meet_post_count','get_meet_post','get_public_meet_contact') then
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
    when 'get_public_meet_contact' then v_result := to_jsonb(public.get_public_meet_contact((p_params->>'p_id')::bigint));
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
        coalesce((p_params->>'p_public_photos')::boolean,false),
        coalesce((p_params->>'p_public_contact')::boolean,false)));
  end case;
  return v_result;
end $$;


notify pgrst, 'reload schema';
commit;
