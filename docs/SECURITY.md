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
  encryption at the server boundary, request size limits, CSRF/session
  protection and no request body logging.
  The selected BETA route is exactly `http://localhost:8443` over SSH,
  publishing only host `127.0.0.1:8443`. ADR0091 supersedes the historical
  HTTPS/TLS bootstrap route; certificates, CA installation and Termux are not
  required or permitted. SSH protects the remote transport; the tablet must
  retain control of its local forwarded port.
- On failure to decrypt or read key: fail closed, no plaintext fallback.
- `check-beta-owner/config` #189 validates owner passkey/TLS files without
  opening a listener or database; #191 gates new-only installation on those
  checks. Neither command creates a real owner credential or a private tablet
  route. The protected `beta-install`/`beta-acceptance` jobs #191/#200 have
  not run on the host.
- The local owner ceremony #217 requires a discoverable passkey with user
  verification. Its private key remains with the selected Android credential
  provider, never in a Chrome cookie or host volume. The `__Host-boca_session`
  cookie is HttpOnly/Secure/SameSite Strict and expires by server policy after
  15 minutes idle, 8 hours absolute or process restart. Device persistence and
  cross-platform use are physical acceptance gates. No TLS certificate or
  certificate rotation applies to the selected SSH-only BETA route.
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
- The separate UID10002 browser image is subject to the same blocking
  HIGH/CRITICAL OS+library Trivy policy as the controller. Historically, #241 tracked a
  confirmed browser scan failure from release PR #239; its code-only
  candidate removes the unused vulnerable GStreamer Bad plug-in **and shared
  library**, and pins six fixed Python base packages plus four audited
  virtualenv dependencies, while preserving locked Playwright and the
  Chromium sandbox. The changed image must pass **both** strict hosted
  image-security and release PR scans plus the no-network synthetic Chromium
  smoke before any browser digest can be released. No suppressions or
  assumption of host installation are permitted.
  A later hosted #241 scan exposed vulnerable `pip` vendor libraries,
  `setuptools/_vendor`, `virtualenv` and Ubuntu `libbrotli1` despite fixed
  global package metadata. The next code-only cut updates `libbrotli1`
  to its Noble security version, fixes build-time virtualenv, and removes
  complete unused Python build-tool distributions (including the actual
  vendored code and seed caches) **after** the locked Browser Worker venv
  is built. The correction was integrated by #242. Exact baseline
  `032de0ebb923b4f80154e93cee3dfd1b254687ed` passed
  [security 41459831000](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41459831000)
  and [CI 41459830809](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41459830809).
  This verifies that code cut, not published current digests or host execution;
  every changed candidate still requires its own scans and release evidence.
- Rotate any real password that has previously been disclosed outside the
  approved encrypted enrollment channel before using it in production.

## Private Telegram setup and protected lifecycle

PR #255's authenticated `/telegram/configurar` page accepts only the public
recipient receipt from an approved `telegram-prepare` run in its fragment.
It clears that fragment before enabling credential entry, validates canonical
receipt/fingerprint and X25519, then uses the existing HKDF/AES-GCM envelope
contract. Route-specific CSP denies connections and form submission; POST
never reads a credential body. No token/chat plaintext is sent to the panel,
Actions, logs or web storage. Browser strings cannot promise physical erasure.

Only three outputs are copied: ciphertext to `telegram_envelope`; canonical
bot ID to `BOCA_TELEGRAM_EXPECTED_BOT_ID`; HMAC-SHA256(token, private-chat ID)
to `BOCA_TELEGRAM_EXPECTED_CHAT_HMAC`. The latter two are protected environment
Secrets. The UI admits positive canonical IDs below 2^52 and exposes no chat
ID. Receipt fingerprint consistency is not issuer authentication: verify the
protected source run before supplying its public link. The offline Chromium
receipt in PR #255 proves this synthetic UI, not Android/GPM or a real send.

The lifecycle/recovery candidate in PR #253 requires exact current SHA,
matching dual release and installed marker. Freeze main from release through
owner enrollment, installation, Telegram and recovery; even a documentation
merge would change the required source. Write operational receipts to
[checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6563012208).
Do not reuse an old readiness proof after a source upgrade. A failed sender
attempt is cleaned by its own runtime label; SSH loss means INDETERMINADO,
not permission for a retry. Explicit recovery validates the old failed run
and preserves all volumes, controller/browser and foreign resources.

## Boundary with third parties

Do not manufacture signed Queue-it tokens, change queue proof, bypass WAF or
CAPTCHA, probe nonpublic endpoints or run synthetic load against Boca.
The authorized initial-document observation ran in41481095746 with isolation
and cleanup PASS but semantic UNKNOWN. It did not log in or validate the full
site. Any additional requests need the distinct bounded approval described in
[the public report](quality/public-source-validation-2026-11-02.md); no automatic
retry or allowance expansion follows from UNKNOWN.

