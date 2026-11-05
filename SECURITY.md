# Security configuration and API changes

## Upgrade

Run `python manage.py migrate` before restarting the API and Celery processes.
Existing JWTs and pending OTPs are deliberately invalidated; users must log in
again. The data migration hashes existing security answers. Security questions
are retired as authorization: they cannot approve transfers or withdrawals.

## Browser authentication

1. GET `/api/v1/auth/csrf/` and retain its `csrfToken` and CSRF cookie.
2. Send `X-CSRFToken: <csrfToken>` and cookies on unsafe browser requests,
   including login, OTP verification, refresh, and logout.
3. POST email and password to `/api/v1/auth/login/`. Retain `challenge_id`.
4. POST `challenge_id` and `otp` to `/api/v1/auth/verify-otp/`.

The old `/very-otp/` URL remains as an alias, but now requires a challenge ID.
Challenges store hashed codes, expire after five minutes, allow five guesses,
and have a 60-second resend cooldown per user/purpose. Issuing a new challenge
invalidates the prior one for that purpose. Login and transaction verification
are distinct purposes. Login/verification use an IP throttle, in addition to
per-user lockouts and persistent per-challenge attempt counters.

Logout invalidates **all** of the user's existing access and refresh tokens.
Password changes also invalidate tokens and pending challenges. Refresh tokens
rotate and are blacklisted after use. Production uses Redis for shared throttles.

## Transactions

Transfer and withdrawal initiation return a `challenge_id` and email an OTP.
Confirmation requires that ID and OTP; the server uses the account, amount, and
recipient stored in the challenge. Username-only withdrawal confirmation is no
longer supported. `/verify-security-question/` returns HTTP 410.

Deposits and card top-ups require an `Idempotency-Key` header. Reuse the same key
for a retry of the same operation; different data or resource paths with that key
are rejected. Successful transfer/withdrawal confirmations use the challenge as
their idempotency key. Retrying them returns the original transaction.

Money changes lock accounts and write their transaction record atomically.
Accounts must still be active and verified at execution. The database disallows
negative account balances. Single-request and cumulative daily outgoing limits
use `DAILY_USD_LIMIT`, `DAILY_GBP_LIMIT`, and `DAILY_NGN_LIMIT` (initial values:
10000, 10000, and 1000000). Limits include card top-ups and reset at midnight in
the configured Django timezone. Review these product-policy defaults.

Deposits and account verification produce staff audit records. The admin cannot
edit transaction/audit records or directly modify balances. Only superusers can
create/change users through admin. Database administrators can still alter audit
tables: use restricted database roles and independent audit-log storage in a
production deployment.

## Production deployment

Use `DJANGO_SETTINGS_MODULE=config.settings.production` on the API, worker, and
Beat. Set `SECRET_KEY`, `SIGNING_KEY`, explicit comma-separated `ALLOWED_HOSTS`,
and HTTPS-only `CSRF_TRUSTED_ORIGINS`. Set `REDIS_URL` for shared rate limiting.
Production enables secure cookies, HTTPS redirects, HSTS, and safe error logging.

`docker/production/nginx.conf` is a TLS ingress configuration. Mount it as
`/etc/nginx/conf.d/default.conf`, mount valid certificates read-only at
`/etc/nginx/tls/fullchain.pem` and `/etc/nginx/tls/privkey.pem`, and publish 443.
Set `TRUST_HTTPS_PROXY=True` only when the backend is reachable exclusively through
this ingress or another trusted proxy that replaces forwarding headers.
The local HTTP nginx configuration is for development and does not terminate TLS.

PostgreSQL, Mailpit, and Flower host ports now bind to loopback in local Compose.
Do not expose these development services publicly. Certificate provisioning,
firewall rules, database/storage encryption, secret rotation, and off-host audit
storage require deployment-specific configuration.

## Backups and validation

Mount a strong passphrase file read-only inside PostgreSQL and set
`BACKUP_PASSPHRASE_FILE` to its container path. Set
`BACKUP_ENCRYPTION_REQUIRED=true` to reject unencrypted backup creation. GnuPG
creates AES-256 encrypted `.dump.gpg` archives; keep the key independently of
the backup volume. Restore supports both encrypted and legacy `.dump` archives.

Set `BACKUP_REMOTE_DEST=backup@host:/backups`, `BACKUP_SSH_KEY_FILE`, and
`BACKUP_KNOWN_HOSTS_FILE` to automatically copy completed encrypted backups by
SSH. Mount both SSH files read-only. Host-key checking is required. A failed
upload returns an error and retains the local archive. No remote credentials or
destination are provisioned by the repository.

Periodically restore an encrypted off-host copy into an isolated PostgreSQL
instance and run application integrity checks. Run tests using
`python manage.py test core_apps.user_auth core_apps.accounts core_apps.cards`.
The concurrency tests run on PostgreSQL and are skipped on SQLite.
