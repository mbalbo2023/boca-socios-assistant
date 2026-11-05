# ADR 0147 — Owner Chrome Telegram V2 encrypted staging, no install authority

**05/11/2026 ART · Boca #45 / Telegram #315 · Candidate only, not deployed.**

## Context and decision

The exact installed Boca BETA has not received, paired or sent through the
owner's Telegram bot. The authenticated V2 preview GET `/telegram/emparejar`
already exists in the #319 candidate. Its WebCrypto code originally produced
a ciphertext for manual copying but could not submit it (`POST` was 404).
The pure `telegram_pairing_issuer` from Telegram PR #317 creates a signed
owner receipt **only if** a genuine protected owner/lease/key context supplies
the exact coordinates. The private WSGI controller has no such host lease or
HMAC key and must not be promoted into a second privileged dispatch channel.

We add a passive, one-slot, encrypted-only owner handoff. This makes the
Chrome action possible without claiming that Telegram is connected:

1. A valid durable owner session, verified by the configured passkey binding,
   opens `/telegram/emparejar` with a public recipient `#recipient` fragment.
   The browser erases that fragment from history before processing the receipt.
2. Native WebCrypto creates the random `/start <code>`, seals the dedicated
   bot token plus code under the recipient X25519 public key and erases the
   plaintext token field. The owner sends the code **only to their own bot**.
3. Only when an explicit `telegram_pairing_stager` callback is injected, the
   page receives one process-local CSRF/operation binding and enables a
   same-origin POST to `/telegram/emparejar`. The only secret-related input in
   the HTTP body is the **already encrypted** canonical V2 envelope. Its
   payload and nonce do not enter URLs, query strings, browser storage or
   GitHub Actions logs. CSP permits `connect-src 'self'` only for this variant.
4. The callback validates the strict V2 public header, recipient fingerprint,
   canonical envelope and length; it does **not** decrypt anything. A
   pre-existing rootless-owned Boca volume directory accepts a single
   `boca_telegram_pairing_stage_v2.json` file. A 0600 fsynced temporary file
   is published via an atomic no-overwrite hard link; temporary residue is
   removed after success/failure. No new port, schema migration, container,
   credential or backup is created. An existing final file or symlink is not
   replaced, purged, rotated or deleted by this code.
5. The HTTP response is `202 STAGED_PENDING_PROTECTED_CUTOVER`, with
   `telegram_connected=false`, `sender=OFF`, and
   `notification_receipt=UNVERIFIED`. On exceptions or duplicate submissions,
   responses are fixed and redacted. The browser explicitly says Telegram is
   **not** connected. The final ciphertext and local code fields are erased
   after a successful staging response.

The staging file contains only the encrypted V2 envelope, its SHA256, the
recipient fingerprint, an unprivileged random stage identifier and an
informational timestamp. The stage ID **is not a protected owner nonce** and
does not authorize any provider request, custody commit or one-shot send.

## Activation, ownership, and remaining P0 blocker

`PrivatePanelApplication` now accepts optional
`telegram_pairing_stager: Callable[[bytes], PairingStageReceipt] | None`,
default `None`. With `None` the installed/legacy behavior is preserved:
preview GET remains available, POST fails 404, no stage and no Bot API.
Runtime/host owner may explicitly wire
`functools.partial(stage_private_telegram_pairing, Path('/data') / STAGING_FILENAME)`
only when Boca's existing volume is genuinely mounted, owned by UID 10001,
and writable without modifying other services; the stager itself refuses a
missing, wrong-owner, group/world-writable or symlink directory. This runtime
injection is **not part of this branch** and is subject to separate exact-SHA
integration and protected release approval.

The major P0 is still the **protected same-lease consumption** of the stage
and authentic owner-signed cutover receipt. No completed code currently
proves an atomic durable one-use owner nonce in the privileged Boca host,
matches source/image/controller/recipient under the exclusive lease, executes
the bounded Telegram Bot API read, commits V2 custody, performs a synthetic
notice or confirms a human receipt. The existing `execute_protected_pairing`
adapter explicitly requires these from the sole Boca first-deploy transaction.
The stage alone is insufficient evidence; Telegram integration remains
**NO_GO / SENDER OFF / ZERO REAL NOTIFICATIONS**.

The protected cutover owner must define the verified stage consumer and
one-use nonce ledger under that same lease, and report genuine receipts. Do
not retrofit the legacy SQLite 0008 (Option B stores owner Chrome sessions
in an independent SQLite file). Do not add a standalone GitHub dispatch,
expose the bot token, run a Bot API call from HTTP, or change Docker/Porota.

## Offline evidence only

`test_telegram_pairing_staging.py` covers real native-WebCrypto V2 envelopes,
0600 atomic one-slot staging, no plaintext, no overwrite, symlink and unsafe
directories, and invalid input. `test_telegram_pairing_panel_handoff.py`
covers owner authentication, same-origin CSRF, one-shot operation, fixed
`202 STAGED` response, disabled-mode failure, and redacted failures.
`test_telegram_pairing_ui.py` runs the actual V2 JavaScript in Node WebCrypto
with a fake localhost fetch and verifies only ciphertext crosses the boundary.
No real Telegram API, token, bot update, notification, SSH, Docker or droplet
action is part of these tests.

**Regla 84:** Source-only SHA, PR-only Actions, QA results, missing host link
and physical NO_GO must be recorded on issue #315 and canonical #45 before
any protected merge/release/deploy decision.
