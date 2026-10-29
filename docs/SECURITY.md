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
  using the opened descriptor. The previous 0444 file-secret exception is
  removed. The approved key volume has a 0400 file owned by container UID
  10001 and is separate from the database volume.
- Before real enrollment, prove actual rootless UID mapping, read-only mount,
  metadata, backup custody and recovery on the target. Never rewrite or chmod
  the mounted key in the controller.
- Key version is part of each record; key rotation requires a tested,
  explicit migration with old/new keys and recovery verification.
- Database file permissions 0600, private parent directory, distinct
  named Docker volume. Enforce host disk encryption and encrypted backups
  before real personal data is onboarded.

## Key custody caveats

Loss of the encryption key makes stored passwords unrecoverable; leak of
both database and key exposes passwords. Do not put the encryption key
beside the database in a backup. Do not give the key to a coding agent.
The first-install workflow generates the key inside the isolated rootless
namespace; a separate, reviewed key-volume recovery plan is needed before
real credentials can be stored.

## Access policy

- No conversationally supplied secrets may enter repository history.
- Future credential enrollment uses a protected owner-only interface with
  encryption at the server boundary, TLS, request size limits, CSRF/session
  protection and no request body logging.
- On failure to decrypt or read key: fail closed, no plaintext fallback.
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
Live interactions require a separate signed-off test plan and resource cap.

