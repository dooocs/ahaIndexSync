begin;
create extension if not exists pg_cron with schema pg_catalog;
create extension if not exists http with schema extensions;

-- This Aliyun image advertises pg_net but has no installation script. Use the
-- available HTTP extension for the existing hourly private cleanup endpoint.
create function public.configure_meet_photo_cleanup(p_secret text,p_url text) returns void
language plpgsql security invoker set search_path='' as $body$
declare v_id uuid; v_job bigint;
begin
  if p_secret is null or char_length(p_secret)<48 or p_url is null or
     p_url !~ '^https://spb-[a-z0-9]+(-vpc)?\.supabase\.opentrust\.net/functions/v1/meet-photo-cleanup$' then
    raise exception 'Invalid cleanup configuration' using errcode='22023';
  end if;
  select id into v_id from vault.secrets where name='community_photo_cleanup_key';
  if v_id is null then perform vault.create_secret(p_secret,'community_photo_cleanup_key');
  else perform vault.update_secret(v_id,p_secret); end if;
  select id into v_id from vault.secrets where name='community_photo_cleanup_url';
  if v_id is null then perform vault.create_secret(p_url,'community_photo_cleanup_url');
  else perform vault.update_secret(v_id,p_url); end if;
  select jobid into v_job from cron.job where jobname='community-photo-cleanup';
  if v_job is not null then perform cron.unschedule(v_job); end if;
  perform cron.schedule('community-photo-cleanup','17 * * * *',$job$
    set http.curlopt_timeout_ms = '60000';
    select status from extensions.http((
      'POST',
      (select decrypted_secret from vault.decrypted_secrets where name='community_photo_cleanup_url'),
      array[extensions.http_header('X-Community-Authorization','Bearer '||(select decrypted_secret from vault.decrypted_secrets where name='community_photo_cleanup_key'))],
      'application/json','{}'
    )::extensions.http_request);
  $job$);
end $body$;
revoke all on function public.configure_meet_photo_cleanup(text,text) from public,anon,authenticated;
grant execute on function public.configure_meet_photo_cleanup(text,text) to service_role;
commit;
