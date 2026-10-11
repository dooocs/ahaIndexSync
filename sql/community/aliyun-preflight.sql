-- Read metadata only. No user, post, contact, photo, or credential rows.
begin read only;
select jsonb_build_object(
  'database', current_database(),
  'user', current_user,
  'version', current_setting('server_version'),
  'statement_timeout', current_setting('statement_timeout'),
  'lock_timeout', current_setting('lock_timeout'),
  'news_table_present', to_regclass('public.raw_items') is not null,
  'community_table_present', to_regclass('public.meet_posts') is not null,
  'roles', (select jsonb_agg(jsonb_build_object('role', rolname, 'settings',
    array(select s from unnest(rolconfig) s where split_part(s, '=', 1) in ('statement_timeout', 'lock_timeout'))))
    from pg_roles where rolname in ('anon', 'authenticated', 'authenticator', 'service_role')),
  'database_role_settings', (select jsonb_agg(jsonb_build_object(
    'role', coalesce(r.rolname, 'all'), 'settings',
    array(select c from unnest(s.setconfig) c where split_part(c, '=', 1) in ('statement_timeout', 'lock_timeout'))))
    from pg_db_role_setting s left join pg_roles r on r.oid = s.setrole
    where s.setdatabase = 0 or s.setdatabase = (select oid from pg_database where datname = current_database())),
  'extensions', (select jsonb_agg(jsonb_build_object('name', name, 'installed', installed_version))
    from pg_available_extensions where name in ('pgcrypto', 'pg_cron', 'pg_net', 'supabase_vault')),
  'auth_columns', (select jsonb_agg(column_name order by column_name)
    from information_schema.columns where table_schema = 'auth' and table_name = 'users'
    and column_name in ('id', 'is_anonymous', 'email_confirmed_at', 'banned_until')),
  'storage_tables_present', to_regclass('storage.objects') is not null and to_regclass('storage.buckets') is not null
) as preflight;
commit;
