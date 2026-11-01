# Data protection and credential requirements

## User's explicit product decision

The product is allowed to store Boca Socios usernames and passwords in its
database to support consented login. Because the original password must be
recoverable for third-party authentication, store **reversible authenticated
encryption**, not an ordinary password hash.

## Design implemented in foundation

- AES-256-GCM, unique 96-bit nonce for each credential write.
- Bind ciphertext to the member_id through authenticated additional data.
- SQLite holds: member_id, key_id, nonce and ciphertext. No plaintext
  password column or secret-bearing audit log.
- Master key: base64 32-byte random secret created once in a Boca-only Docker
  volume and mounted read-only at /run/secrets/boca_master_key; never in DB,
  repository, image or Actions logs.
- The Linux-targeted vault requires `O_NOFOLLOW` (fails closed if absent), checks
  regular-file type, ownership, bounded length and owner-only permissions
  using the opened descriptor. The former 0444 file-secret exception is
  removed; the key volume has a 0400 file owned by container UID 10001.
- Before real enrollment, prove actual rootless UID mapping, read-only mount
  and key metadata on the target. Never rewrite/chmod the mounted key in the
  controller. Recovery custody is a later milestone after a reliable product.
- Key version is part of each record; key rotation requires a tested,
  explicit migration with old/new keys and recovery verification.
- Database file permissions 0600, private parent directory, distinct
  named Docker volume. Enforce host disk encryption and encrypted backups
  before real personal data is onboarded.

## Key custody caveats

Loss of the encryption key makes stored passwords unrecoverable; leak of
both database and key exposes passwords. Do not put the encryption key
beside the database in a backup. Do not give the key to a coding agent.
Any future master-key provisioning is a separate, technically reviewed
milestone. The proposed first-install workflow generates the key inside the
isolated rootless namespace; this simulation-only gate does not enable real
credential enrollment. Do not recreate the existing SSH deployment secret.

## Access policy

- No conversationally supplied secrets may enter repository history.
- The integrated enrollment UI code must be served through a protected owner-only interface with
  encryption at the server boundary, TLS, request size limits, CSRF/session
  protection and no request body logging.
- On failure to decrypt or read key: fail closed, no plaintext fallback.
- `check-beta-owner/config` #189 validates owner passkey/TLS files without
  opening a listener or database; #191 gates new-only installation on those
  checks. Neither command creates a real owner credential or a private tablet
  route. The protected `beta-install`/`beta-acceptance` jobs #191/#200 have
  not run on the host.
- Telegram's default-off worker #188, sealed helper #199, protected
  schema/custody #203 and one-shot identity/send gate #204 have only synthetic
  tests. No bot token, numeric private chat destination, host volume or Bot API
  delivery has been verified.
  Never put plaintext values in workflow inputs or logs.
- Redact emails from logs and use opaque member identifiers.
- Do not export cookies, auth state, Queue-it passes, HAR or passwords to
  Telegram, untrusted browser tools or GitHub Actions artifacts.
- Prepare deletion of member + credential + audit redaction and documented
  backup-retention before enabling real user enrollment.
- Docker images must build runtime Python dependencies using `uv sync --locked`
  (also reject lock/pyproject divergence) and a reviewed base image manifest digest; modifying
  the digest or dependency graph requires an isolated CI review. This is a
  **reproducible dependency selection**, not a guarantee of bit-for-bit
  identical images or a substitute for vulnerability scanning.
- Rotate any real password that has previously been disclosed outside the
  approved encrypted enrollment channel before using it in production.

## Boundary with third parties

Do not manufacture signed Queue-it tokens, change queue proof, bypass WAF or
CAPTCHA, probe nonpublic endpoints or run synthetic load against Boca.
Live interactions remain disabled until a separate technically reviewed,
consented test milestone with a resource cap.

