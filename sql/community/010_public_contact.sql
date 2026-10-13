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
) returns bigint language plpgsql security definer set search_path='' as $$
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
language sql stable security definer set search_path='' as $$
  select c.contact from public.meet_contacts c join public.meet_posts p on p.id=c.post_id
  where p.id=p_id and p.status='published' and p.expires_at>now()
    and c.share_contact and c.public_contact and c.contact<>'';
$$;

revoke all on function public.meet_contacts_public_guard() from public,anon,authenticated;
revoke all on function public.submit_meet_post(text,integer,text,text,text,text,text,text,text,boolean,boolean,uuid[],boolean,boolean) from public,anon,authenticated;
grant execute on function public.submit_meet_post(text,integer,text,text,text,text,text,text,text,boolean,boolean,uuid[],boolean,boolean) to authenticated,service_role;
revoke all on function public.get_public_meet_contact(bigint) from public,anon,authenticated;
grant execute on function public.get_public_meet_contact(bigint) to anon,authenticated,service_role;

notify pgrst, 'reload schema';
commit;
