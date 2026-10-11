# Community MVP database

This directory targets the **separate community Supabase project**, not the news
pipeline database. Do not include it in a bulk pipeline migration run.

Apply `001_community_mvp.sql` once to a fresh Supabase project. Auth must use verified
email sign-in. No client may write tables directly. Mutation RPCs derive ownership
from `auth.uid()` and keep every submission pending until manual review.

For the MVP, operators review `meet_posts` in the Supabase dashboard. Check that the
author is an adult, the text is appropriate, and no private contact details appear
in public text. Set `status` to `published` or `rejected`. Publishing starts a
30-day visibility window. Editing returns a published post to `pending`.

`meet_contacts` is separate and never included in anonymous read RPCs. Only verified
users can request contact information for a published, unexpired post with the
author's explicit consent. Previously copied information cannot be recalled.

The owner can withdraw immediately. For erasure, delete the Auth user via the
Supabase dashboard's Auth administration flow; both tables cascade on deletion.
For abuse, withdraw their post and ban the Auth user. The MVP does not include an
admin website, comments, direct messages, matching, or paid features.

Run `tests.sql` against a disposable test database after the migration. It uses a
transaction and rolls back all fixtures. Never weaken RLS to make UI testing pass.

The dedicated closed-test project is `cfbzfbhpsbcthtwtpyfu`, created on the Free
plan in Singapore. `supabase/config.toml` preserves email confirmation, default
email templates, TOTP defaults, and a 600-second login-link expiry. With the Free
default email provider, custom templates are rejected; the frontend uses the
default emailed link and `/auth/callback/`, not an OTP input. Default SMTP only
delivers to organization team members, at two emails per hour.

From this directory, use `supabase config push --project-ref cfbzfbhpsbcthtwtpyfu`
and review the diff before confirming. If the local shell uses a SOCKS proxy,
remove proxy variables for this command only (see the frontend community guide).
Before a public rollout, configure custom SMTP and change Site URL/callback
allowlist to the production HTTPS origin. Never point these migrations or this
configuration command at the existing news project.

## Photo extension

Apply `002_community_photos.sql`, `003_photo_cleanup_schedule.sql`, then
`004_photo_consent.sql` after 001. Keep `tests.sql` paired with 001; run
`photos-tests.sql` after 002 or 004 on a disposable database. All tests roll back.
Deploy `supabase/functions/meet-photos` and `meet-photo-cleanup` with the checked-in
function config. The upload endpoint validates user JWTs itself; cleanup validates
its cron secret. Never expose either service credentials or the cleanup secret.

Photos are private, optional, and limited to six per post. The authenticated
author can preview drafts; other verified users can view only live approved posts.
The SQL wrapper associates photos atomically and resets review on edits. Operators
must inspect private Storage images alongside text before setting `published`.

Apply `008_direct_photo_upload.sql` after the earlier migrations. It grants
authenticated users a scoped, short-lived INSERT path for their own reserved
objects, while retaining private reads and manual review. Browsers encode a
main JPEG and thumbnail and send both directly to Storage; they then mark their
metadata row ready. The bucket remains private, JPEG-only and 1 MiB/object.
The SQL submission wrapper checks that both Storage objects exist. The browser
cannot overwrite or delete Storage objects directly, and cannot update ready
metadata. At most six photos can be attached to a post; twelve total metadata
rows allow replacement while editing a six-photo post. Existing cleanup still
needs a working scheduled invocation for abandoned reservations.

For an existing Aliyun instance, generate only the incremental compatible SQL:

```sh
node sql/community/build-aliyun-photo-update.mjs
```

Run the generated `008_direct_photo_upload_aliyun.sql` once in that project's
SQL Editor. Do not reapply the full generated installation or point this at the
news database. Verify the direct authenticated Storage upload before releasing
the frontend.

Set `COMMUNITY_CLEANUP_SECRET` in Edge secrets, then use the server-only
`configure_meet_photo_cleanup(secret, url)` RPC to store it in Vault and schedule
hourly cleanup. This secret must be a cryptographically random string of at least
48 characters, not a public API key. Deleting a user cascades photo metadata but
preserves the deletion queue until Storage deletion succeeds. Check pg_net HTTP
responses and outstanding queue age for cleanup failures.

The frontend guide `ahaIndex2/docs/community-mvp.md` documents limits, signed-URL
expiry, UI behavior and verification. ImageMagick is pinned to 0.0.44; its WASM
binary lives under `dist/x86/`, not the path in older Supabase examples.

## Aliyun target

### Chinese email templates

`email-templates.mjs` defines Chinese subjects and HTML bodies for all 13 Auth
email types, including verification, sign-in, invitations and security notices.
Apply `communityEmailSettings()` with the target's authenticated
`PATCH /auth/v1/modify/settings` endpoint, then read back every changed field.
The payload changes only subjects and bodies: it does not contain SMTP
credentials, enable new email notifications, or bypass email verification.
Keep the generated `{{ .ConfirmationURL }}` intact for link-based sign-in;
reauthentication uses `{{ .Token }}`. A blank dashboard password input does not
indicate that its write-only SMTP password is missing.

Run `node --test sql/community/email-templates.test.mjs` before applying the
templates. SMTP API acceptance is not proof of receipt; verify a real Chinese
email and the browser callback separately. Never commit a real confirmation
link, OTP, session, or SMTP authorization code.

For a fresh Aliyun project, run `aliyun-preflight.sql` first. It reads metadata
only, including API role timeout settings and extension availability. Do not
apply the ordinary cloud migrations directly on the current Aliyun image:
`adbpg_enable_security_definer` is disabled and cannot be set by the project
administrator. Generate the atomic Aliyun installation instead:

```sh
node sql/community/build-aliyun.mjs
```

The generated SQL uses SECURITY INVOKER, preserves owner-only table reads and
RLS, and revokes all browser access to business RPCs. The `meet-api` Edge function
verifies the JWT with GoTrue and invokes a fixed service-role-only dispatcher.
Actor IDs come from the verified user, never the browser request body. The server
role can read only the Auth metadata columns required by the existing checks.
Set `COMMUNITY_RPC_MODE=edge` in function secrets for Aliyun photo listing.

`aliyun-cleanup.sql` replaces the ordinary pg_net cleanup migration. The tested
image advertises pg_net but has no installation script or available versions;
the HTTP extension is actually installable. The hourly job calls the same
private cleanup endpoint with a Vault secret and a bounded HTTP timeout. Verify
the function, secret and connectivity before enabling cron.
This migration is code/configuration only: do not copy old Auth users, posts,
contacts, or Storage objects. A successful Auth health check alone is not a
completed migration or evidence that mail and private-image delivery work.

On 2026-10-11 the target schema was committed successfully, and Auth settings
were read back to confirm email verification and local/production callback URLs.
The general Aliyun Supabase CLI returned successful deployment exit codes but
function listing was empty and business endpoints returned HTTP 503 with
`FC deployment is not ready`. The official standalone `functions-cli` deployed
a no-dependency `community-health` function with ACTIVE status and an actual
HTTP 200 response. Use that deployment path and verify real HTTP responses;
the four business functions were subsequently deployed through that path.
The pure 34-file archive was manually uploaded and its hash verified before
deployment. Privileged keys stayed in Cloud Shell; no old user data was copied.

Standalone function deployment requires `SUPABASE_API_URL` and a server-only
`SUPABASE_API_KEY` in the command environment. Do not export either privileged
credentials or old user data to enable local testing. Bundle dependencies or
verify instance outbound access before deploying npm-dependent code; the
no-dependency health check does not prove those imports can run.

Bundle the business functions before deploying in a project without public npm
access. This produces standalone handler directories and checks that module
resolution succeeds with both npm and remote imports disabled:

```sh
DENO=/path/to/deno node sql/community/bundle-functions.mjs /tmp/community-functions
```

For bundled photo processing, apply `aliyun-runtime-assets.sql` after the base
adapter and upload only the pinned `@imagemagick/magick-wasm@0.0.44` binary to
`community-runtime/magick-0.0.44.wasm`. The private bucket is separate from user
photos. Its binary must be 15447097 bytes with SHA-256
`b7d6710436b150dc5bd1ca04d80b6b7614c54854d7470f888f7e69a2a41b00e4`.
Set `COMMUNITY_BUNDLED_RUNTIME=true` via the standalone functions-cli secrets
command. The encoder fetches that fixed private asset through the internal
gateway and verifies it before initialization; no third-party runtime download
is required. Normal unbundled official-cloud deployments keep their npm asset
loader. The private binary upload and authenticated download were verified on
the target. Real tests created a synthetic verified user, uploaded a standard
JPEG, submitted a photo post, downloaded its signed image, and confirmed that
the pending post stays hidden from anonymous readers. Actual review API tests
also verified publication, stale-snapshot rejection and withdrawal visibility.
The local frontend now targets Aliyun and passes the anonymous readiness check;
a real login-email request succeeded, but receipt and callback remain unverified.
Real mail delivery, two-user privacy, cleanup cron and frontend release remain
unverified.

The latest read-only target audit confirmed six RLS-protected tables, zero
browser business-RPC grants, no authenticated direct post writes, strict
owner-read policies, and the private JPEG bucket. Real anonymous API probes
were denied with 401/42501, while the service-role public dispatcher returned
200. Automatic archive upload remained blocked; the human completed the upload.
Temporary Cloud Shell files expire with its VM. Already deployed source was
recovered from the target for hash-guarded mechanical artifact updates, without
transmitting local files through an alternative upload channel.

Live tests found that the standard Authorization header did not preserve the
expected credential through the function gateway. Clients duplicate it as
`X-Community-Authorization` only for this project's Aliyun function endpoints;
the handlers prefer that header and still validate GoTrue JWTs, HMAC review
sessions or the private cleanup secret. Auth/REST requests and other origins
are not modified. The same review key now exchanges for a session and lists
pending posts with HTTP 200; a forged session returns 401.

Cold portrait uploads initially terminated the worker, reporting approximately
230 MB peak memory. The fixed-size WASM loader now streams into one preallocated
buffer instead of retaining chunks and a second full copy. After fresh function
deployments, first uploads at 1200x1600 and 1600x1600 both returned HTTP 200.
Malformed image uploads returned 400. The original image limits are unchanged.

Edge Functions prefer Aliyun's `SUPABASE_LOCAL_URL` for Auth, database, and
Storage requests. Signed photo links are converted back to `SUPABASE_URL` before
being returned to a browser; their object path, token, and 120-second lifetime
are preserved. Unexpected origins and non-private photo paths are rejected.
Projects without a local gateway override continue using their public API URL.

Create the code package with the explicit source-file list. The script checks the
archive contents and excludes CLI link state, environment files, and local data:

```sh
node sql/community/package-code.mjs
```

Run the gateway, image encoding, and review-session tests locally before deploying:

```sh
deno test --allow-read --allow-env sql/community/supabase/functions/_shared/gateway-config.test.ts sql/community/supabase/functions/meet-photos/encode.test.ts sql/community/supabase/functions/meet-review/auth.test.ts
deno test sql/community/supabase/functions/meet-api/actions.test.ts
deno check sql/community/supabase/functions/meet-api/index.ts sql/community/supabase/functions/meet-photos/index.ts sql/community/supabase/functions/meet-photo-cleanup/index.ts sql/community/supabase/functions/meet-review/index.ts
```
