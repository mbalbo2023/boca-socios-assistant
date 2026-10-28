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
- Master key: base64 32-byte random secret mounted via Compose secrets at
  /run/secrets/boca_master_key; never in DB/repo/Docker image or Actions logs.
- Key file provisioned at an owner-controlled path outside the source tree,
  never shared with another application. Access limited to the Boca identity.
- Key version is part of each record; key rotation requires a tested,
  explicit migration with old/new keys and recovery verification.
- Database file permissions 0600, private parent directory, distinct
  named Docker volume. Enforce host disk encryption and encrypted backups
  before real personal data is onboarded.

## Key custody caveats

Loss of the encryption key makes stored passwords unrecoverable; leak of
both database and key exposes passwords. Do not put the encryption key
beside the database in a backup. Do not give the key to a coding agent.
The owner will authorize a separate one-time deployment secret workflow.

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
- Rotate any real password that has previously been disclosed outside the
  approved encrypted enrollment channel before using it in production.

## Boundary with third parties

Do not manufacture signed Queue-it tokens, change queue proof, bypass WAF or
CAPTCHA, probe nonpublic endpoints or run synthetic load against Boca.
Live interactions require a separate signed-off test plan and resource cap.

