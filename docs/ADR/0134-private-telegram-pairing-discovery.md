# ADR 0134 — Private Telegram chat discovery without external ID bots

**2026-11-04 ART · Issue #168 / BETA #45 · DRAFT CODE CONTRACT ONLY.**

## Owner decision and actual installed state

The owner has a BotFather token, authorized Telegram notifications, and
successfully authenticated the Samsung Chrome panel at `localhost:8443`.
The installed release (`main=cabce9f1e452e63ded115f447559a358dc0f4d1b`)
is the **controller-only** simulation BETA; no Telegram token, destination,
sender or physical delivery has been verified. Browser-worker is uninstalled.
The owner cancelled multi-session, master-key rotation/deletion, live Boca
login/queue/reservation/purchases, Site integration and backups. Do not
reintroduce these features as a side effect of Telegram setup.

The existing `/telegram/configurar` page remains intentionally disabled
without the authenticated `telegram-prepare` recipient receipt. It currently
expects both a token and positive private-chat ID and creates a v1 sealed
envelope plus two owner pins. This candidate does **not** change that deployed
contract or claim that the token can be entered into the old panel yet.

## Owner-friendly pairing proposal

Avoid third-party ID-discovery bots and token-bearing browser URL/history.
The future private setup page can instead generate a 24–64 character
cryptographically random, base64url-safe pairing code in local WebCrypto.
The owner opens **their own BotFather-created bot** and sends exactly
`/start <pairing-code>` in its private conversation. The page locally seals
the bot token plus pairing code under a recipient X25519 key from a verified
protected `telegram-prepare` receipt. That would be a deliberately versioned
new envelope; the existing v1 token+chat envelope must **not** silently be
repurposed. Neither token nor pairing code may appear in public Actions logs,
issues, PRs, CLI arguments, browser URL, or the app HTTP request body.

A separate, explicitly reviewed protected operation would retrieve Bot API
`getUpdates` using the token **only inside dedicated Telegram custody**.
It must perform TLS/digest/rootless/volume/owner/active-session gates, reject
existing webhook configuration or conflicts without modifying them, and
accept exactly one fresh private message whose sender ID equals the private
chat ID and whose text matches the pairing code. No guessing by username,
most recent chat or multiple candidates. Telegram's Bot API `getUpdates` and
private Chat fields are documented at https://core.telegram.org/bots/api .
The chosen ID would be stored privately with the token; then the existing
`getMe`, `getChat`, bot/destination owner pin and single synthetic notice
gates must be reconciled, with independent human receipt confirmation.
Do not send a real message or start a sender during discovery by default.

## Implemented scope in this candidate

`src/boca_socios/telegram_private_chat_discovery.py` provides a **pure**
strict parser for the future protected `getUpdates` response and an immutable
in-memory candidate (`chat_id`, `update_id`). It never touches token, HTTP,
Docker, browser or disk. It rejects oversized/non-UTF-8/noncanonical JSON,
duplicate keys/IDs, response failures, non-private/group/bot messages,
sender/chat mismatch, malformed IDs, old/future timestamps, incorrect code,
missing or multiple confirmations. Errors contain no token, pairing code or
chat ID. `not_before` and `now` must be supplied from trusted host state by
the future adapter, not inferred from untrusted Telegram messages. No
`getUpdates` offset is advanced, so this contract does not consume updates.
Tests use entirely fictitious JSON and require no network or real token.

`src/boca_socios/panel/telegram_setup_ui.py` additionally exposes the
**unrouted** `pairing_page()` prototype, its independent `PAIRING_SCRIPT` and
script-hash-only `PAIRING_CSP`. Existing V1 `page()`, `SCRIPT`, `CSP` and installed
route remain untouched. On `http://localhost:8443` only, the V2 page checks
the canonical fingerprint-checked public recipient receipt, uses native
WebCrypto X25519/HKDF/AES-GCM and generates a fresh **192-bit** pairing code.
The code may be copied as `/start <code>` directly into the owner's private
bot chat. The bot token is entered only in a password field in that local
page, never inserted into the address bar, copied with `/start` or sent in
plaintext to the server. On seal, token+code are encrypted into a
purpose/version/domain-separated V2 envelope and the token field is erased.
On navigation, local input/ciphertext/code fields are cleared.

`src/boca_socios/telegram_pairing_bootstrap.py` provides only the **offline**
strict decoder `unseal_pairing()`. It does **not** install or store the token,
resolve a Telegram chat ID, invoke the Bot API, activate senders, alter existing
V1 (`bot_token + chat_id`) custody or touch the droplet. Cross-language native
Node WebCrypto-to-Python tests verify the exact new envelope, fingerprint,
AEAD tamper rejection, V1/V2 separation, negative privacy paths and CSP.

`src/boca_socios/telegram_pairing_resolver.py` now adds a **source-only,
non-routed, non-dispatched** read-only Bot API resolver. Its four allowlisted
HTTPS operations are `getMe`, `getWebhookInfo`, `getUpdates` and `getChat`.
It rejects token-bot ID mismatch, any active/unknown webhook, absent/stale/
duplicate/group pairing, mismatched `getChat`, non-200 responses, redirects,
oversize payloads, malformed JSON and transport errors without reflecting
token-bearing URLs or chat IDs. `getUpdates` uses no offset and does not edit
`allowed_updates` or webhook state; this is a **non-acknowledging peek** of
pending updates, not a durable consumer. Native Python SSL uses certificate
verification, hostname verification, a 3-second connection timeout and an
allowlisted fixed host. A host adapter still must enforce dedicated egress,
rootless identity, read-only mounts, exact image/source, stopped controller,
owner authorization and secret-safe output capture before allowing this call.
Tests inject a fake transport, so **no real Telegram request was executed**.

On unique discovery, the resolver builds an **in-memory V1 sealed ciphertext**
using existing `telegram_bootstrap.seal_for_recipient()`. This is a handoff for
the already-tested offline V1 installer; no new write logic is introduced.
The result also carries a redacted provisional receipt binding source SHA,
recipient fingerprint, numeric bot ID, update ID, keyed chat identity HMAC and
replay-fence HMAC, with `notification_receipt=UNVERIFIED` and
`READY_FOR_PROTECTED_INSTALL`. The Python dataclasses omit ciphertext, keyed
chat proof and replay fence from their log representation. This is **not a
physical install receipt**.

`src/boca_socios/telegram_pairing_install.py` now coordinates **local offline
synthetic V2 custody** using the existing V1 `telegram_bootstrap.install`
without changing its file format, API or physical behavior. It checks a fresh
resolution receipt (maximum 10 minutes from the trusted resolver clock),
source SHA, recipient key, bot ID, positive private chat, HMAC owner pin and
single-use fence *before* any secret file write. Under an exclusive nonblocking
directory lock it rejects any existing `bot_token`, `chat_id`, final marker or
staging residue, writes the V1 pair once with the already-tested rootless
exclusive-create installer, verifies the pair, then stages a keyed-integrity
V2 receipt file as 0400 with fsync. A hardlink creates a final marker without
overwriting an existing one; removing staging is the **last visibility event**
under that lock, followed by directory fsync. A V2-gated reader requires the
completed marker with nlink=1, no staging file, V1 pair integrity, exact SHA,
recipient identity and HMAC metadata. Public receipt contains only SHA,
recipient fingerprint, bot ID and `CUSTODY_COMMITTED_NO_SEND` /
`notification_receipt=UNVERIFIED`; no token, chat ID or HMACs.

**Important atomicity boundary:** Linux cannot atomically create the three
separate legacy entries (`bot_token`, `chat_id`, fence) together. The new marker
provides a fail-closed *V2 visibility commit*, **not atomic physical multi-file
installation**. A crash between V1 writes or marker stages intentionally
preserves partial files and locks out replay/second install; no cleanup or
rollback is attempted. Old V1 verification alone could report a complete pair
before the V2 marker is committed; therefore **the future host/sender MUST
require `verify_v2_custody` and a completed protected workflow receipt before
any sending**. This host gate is NOT implemented in this PR and remains NO_GO.
The local `flock` is advisory and the legacy V1 installer does not acquire
it; only a future exact-identity Boca host lease may exclude other V1
operations. Until the host confirms such exclusivity and the real rootless
filesystem supports the marker hardlink/fsync pattern, no physical GO follows.
The module has no CLI, startup hook, route, network, deployment action or
access to the real host; tests only use isolated temporary directories with
fake BotFather-format tokens and simulated crash points.

The protected host wrapper also needs a positive **no competing Telegram
poller** assertion. `getUpdates` without `offset` does not acknowledge updates,
but a concurrent consumer or previous bot-wide `allowed_updates` setting can
cause a missing message. Do not clear pending updates, delete webhooks or change
subscription settings automatically as a workaround. The safe response is
NO_GO and a newly generated owner code/recipient envelope after diagnosing
the conflicting integration. An issued code is accepted for at most one hour.

The new `pairing_page()` is **NOT YET ROUTED**. No new URL is active in the
deployed controller. The V2 ciphertext must **NOT** be submitted to the old
`telegram-install` V1 workflow. Tests run with fake credentials only; not a
receipt of physical Telegram delivery. Any run's preparatory receipt must
match the exact stopped controller and private recipient key at cutover time.

## Physical sequence and remaining work — NOT YET AVAILABLE

1. Keep the original controller running until a reviewed, exact-SHA
   transition/custody operation exists; no `beta-browser-install` new-only
   attempt against the installed singleton.
2. The source-only V2 local seal, decoder, read-only injectable Bot API
   resolver and fail-closed V2 custody coordinator exist. Integrate a V2 route behind existing owner authentication,
   trusted recipient link and protected host wrapper that executes resolver
   only within the Boca-specific network/custody identity. Capture V1 sealed
   handoff privately and run coordinator with exclusive actual host lease;
   require final marker verification and genuine protected receipt before
   lifting sender OFF. Test a real private `getUpdates` receipt
   once physically available. Keep V1 workflow rejecting raw V2 ciphertext.
3. Stage Telegram 0007 migration and recipient key with controller stopped,
   under the sole protected Boca Actions workflow. Currently these are
   distinct `telegram-migrate` and `telegram-prepare` operations, each
   requiring verified stopped identity and Boca-only daemon stop. The
   controller-only matching resume path is **`beta-start`**, not
   `beta-browser-start` while worker uninstalled. Any combined workflow
   needs its own strict identity/cleanup review; don't dispatch it today.
4. Owner pairs token in private Chrome and sends the one-time command **within
   the protected adapter's one-hour matching window**;
   protected discovery and identity verification bind the private destination.
   One-shot notification and human receipt precede sender activation.
5. After any stop/restart, the old session cookie is invalid and owner
   re-authentication may be necessary; the passkey enrollment is preserved.

Until the adapter/host wrapper/workflow are implemented, reviewed, GREEN and
physically dispatched with actual receipts, Telegram remains **OFF / NO_GO**.
No third-party ID bot, provider call, real-token handling, owner input or host
action was executed by this source-only PR. Keep all pending state visible
in #45 per Rule 84.
