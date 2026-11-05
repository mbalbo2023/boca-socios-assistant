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

## Standalone protected dispatch rejected — final source-only cut (04/11/2026)

An initial design considered `.github/workflows/boca-telegram-pairing.yml` as
another manually dispatched protected installer. **It was rejected before
implementation**. The installed controller-only release and exclusive Boca
daemon are already governed by the exact-SHA stop/start, resource, Docker
identity and source-authorization gates in
`.github/workflows/boca-first-deploy.yml` / `host_first_deploy.py`. Its host
logic is streamed to the rootless SSH session for each step; it is not a
stable, independently callable installed service. A second `workflow_dispatch`
could check the daemon, release the lease, then observe or modify a *different*
runtime at install time (TOCTOU), while duplicating gates susceptible to
drift. Two independent host control planes would also contravene the sole
manual deploy workflow rule. The approved route is **one exact-SHA governed
cutover**, coordinated with the host-first-deploy writer for issue #227,
without exposing a second host-dispatch option.

The new `.github/workflows/boca-telegram-pairing.yml` is therefore deliberately
**PR-only**. It runs deterministic fake-data Telegram contracts, static
format/lint/type/isolation checks on a disposable GitHub runner and logs only
`TELEGRAM_V2_HOST_AUTHORIZED=false`, `TELEGRAM_V2_CUSTODY=UNVERIFIED`,
`TELEGRAM_V2_SENDER=OFF`, `TELEGRAM_V2_NOTIFICATION_RECEIPT=UNVERIFIED`.
It has no `workflow_dispatch` or `workflow_call`, repository write permission,
secret, environment, self-hosted runner, Docker/SSH operation, actual token,
Telegram API call, output artifact or deployment action. A GREEN PR-only job
is **not** an acceptance receipt for any production operation.

`src/boca_socios/telegram_pairing_host_contract.py` defines a typed *untrusted
claim shape* and a non-operational review result for the eventual host adapter.
It enumerates the required logical order: pinned main/release → positive
owner/stopped-singleton inventory → isolated schema 0007 migration →
X25519 recipient preparation → temporary controller resume for authenticated
Chrome pairing → stop/recheck **same digest and SHA under exclusive Boca
lease** → bounded allowlisted Bot API discovery → V1 ciphertext handoff plus
V2 visibility marker → `verify_v2_custody` → controller resume with engine and
sender OFF → synthetic acceptance → independent human notification receipt.
Sender activation, if ever approved, is a *separately governed* step. The
review function checks the consistency of **caller-supplied claims** but
always returns `authorized=False`, `executable=False` and
`human_receipt=UNVERIFIED` even when every claim is positive. It cannot prove
real host observations, protect against races or be used as an operational
gate. Negative tests reject fake `True` values, wrong daemon/source/digest,
unexpected port, clock skew, UID mismatch, missing lease and incomplete
custody. No actual host I/O is available in this module.

**Outstanding host integration (NO_GO):** implement these checks inside the
single existing Boca-first-deploy host transaction under issue #227, with
positive identity reinspection immediately before each side effect, state
handoff across the owner Chrome interaction, a dedicated egress/secret custody
boundary, a robust failure/resume state machine and bona fide redacted
protected receipts. The old installed SHA is **not** a V2 sender/installer.
Do not run its old V1 `telegram-install` against a V2 envelope; do not stop or
restart the running 8443 controller for this candidate. The precise moment
and mechanism of Telegram's physical one-shot notice and human confirmation
remain unverified; keep delivery OFF until received and recorded. Preserve
the owner passkey and real database/volumes, touch no other service, and do
not convert cleanup into broad Docker pruning. The cutover writer owns
`.github/workflows/boca-first-deploy.yml` and
`src/boca_socios/host_first_deploy.py`; neither was edited here.

## Incremental sidecar contract to canonical cutover #227 — 05/11/2026

`src/boca_socios/telegram_pairing_cutover.py` now offers a **source-only,
injected** adapter for the *single* Boca protected host transaction, without
creating a second workflow or dispatch. The canonical cutover owner owns the
host lock, exact-ID Docker/volume inspection and owner-authenticated handoff.
Its proposed Python API is:

`execute_protected_pairing(coordinates, owner_receipt, owner_receipt_key,
sealed_v2_envelope, recipient, private_key, directory, trusted_clock,
recheck_host, consume_owner_nonce, api_fetch)` (all keyword-only).

`CutoverCoordinates` pins numeric attempt, source SHA, OCI image digest,
owner-subject SHA256, lease SHA256, exact controller container ID and recipient
fingerprint. `OwnerPairingReceipt` binds those fields, V2 envelope SHA256,
unique 256-bit nonce and a maximum 600-second issuance/expiry window under
purpose-separated HMAC-SHA256 of a private 32-byte authenticated-owner key.
**No issuer or key export is implemented here.** Only the future authenticated
Chrome route in an approved protected transaction may issue that proof; the
adapter never accepts an unsigned JSON claim, token-containing CLI argument,
environment boolean or `HostContractReview` as authorization.

The protected host must provide an authoritative `recheck_host(phase,
coordinates)` and retain the **same exclusive lease**. It is invoked before
any Bot API request, immediately before each exact ordered `getMe`,
`getWebhookInfo`, `getUpdates` and `getChat`, before custody writes and after
marker verification. Every observation must match exact attempt, source,
image, owner, lease, controller, fingerprint, rootless UID10001, owner-auth,
stopped singleton, sender OFF, schema0007, recipient custody, dedicated
Telegram egress, no competing poller and unrelated workload preservation;
clock age must be at most 30 seconds. These typed observations are only
**claims unless produced under the genuine host reinspection/lock**. A caller
that invents `True` values cannot independently establish authority.

The protected host also owns a **durable, atomic, single-consumer nonce
ledger** (`consume_owner_nonce`). A valid owner HMAC is checked before any
effects, and its nonce is consumed under the same lease **before** the first
provider read. Without an authoritative consumer, pairing is NO_GO. Any
replay, mismatch, expired owner proof, unavailable host recheck, webhook,
ambiguous private chat or transport error aborts without attempting custody.
After unique read-only discovery, the adapter rechecks all gates and uses the
existing `install_v2_plan` visibility-atomic marker, then requires
`verify_v2_custody` and a final host recheck. Failure after any local write
preserves files as NO_GO; no retries, rollback, purge or sender activation.
The only success receipt contains attempt, source, recipient, bot ID and
`CUSTODY_COMMITTED_NO_SEND`; human receipt remains `UNVERIFIED` and sender
state remains `OFF`. No actual Telegram notification is sent.

The CLI contract (`python -m boca_socios.telegram_pairing_cutover
preflight|commit|verify`) deliberately returns `NO_GO` and performs **zero**
host, network, filesystem or Bot API effects. It cannot be made operational
with a truthy flag. `CLEANUP_TARGETS=()` because the adapter creates no
containers, networks, IPC entries or disposable volumes. The existing
rootless Telegram secret volume, private marker and persistent Boca data
must **never** be cleanup targets even after a deploy failure; selective
recovery and eventual postdeploy cleanup belong to the canonical #227 host
code. No `host_first_deploy.py`, canonical workflow, BLACKBOX or Porota change
was made in this Telegram DRAFT.

Offline tests provide invented owner HMAC and BotFather-format credentials,
fake read-only provider, fake same-lease rechecks, in-memory nonce consumer and
fake custody adapter to prove ordering, replay and redacted NO_GO. They are
**not** physical owner authentication, provider access or host verification.
The cutover writer has agreed to consume this as an **optional code-only
callback** after candidate acceptance, *inaccessible* from current
`phase()`/GitHub workflow until all physical receipts and gates exist.

## End-to-end offline synthetic notice acceptance — 05/11/2026

The adapter and the existing one-shot Telegram delivery fence are now
exercised **together** by `tests/test_telegram_pairing_cutover_notice.py`.
On a disposable test directory it constructs a real local X25519 recipient,
encrypts an invented BotFather-format token + pairing code in the unrouted
Chrome V2 implementation, validates an owner HMAC/nonce and the seven
same-lease callback phases, resolves a single fake private `/start` through
all four read-only Bot API method fixtures, and installs the **real** local
V1 secret pair and V2 visibility marker with UID mapped only for pytest.
It then creates a temporary exact schema-0007 SQLite ledger and drives the
preexisting `telegram_one_shot.deliver_once()` through a fake in-memory
`TelegramSender` that returns `TelegramAck(42)` or raises an ambiguous
transport error. There is **exactly one** simulated heartbeat attempt; a
second attempt is blocked by the durable SQLite intent fence in both cases.
`verify_ready` accepts only the synthetic API-accepted fixture and rejects
ambiguity. A second owner pairing with the consumed nonce is denied before
even a Telegram read. Assertions preserve V2 source/recipient marker and
public receipt with `sender_state=OFF`, `human_notification_receipt=UNVERIFIED`.
Token and private chat are absent from the redacted receipt and captured
stdout; test provider and host callbacks are synthetic, with no real API,
message, tunnel, Docker, protected dispatch, host mutation or Boca navigation.

**This is intentionally not human receipt evidence.** Even a successful
provider-acceptance simulation and durable marker cannot enable the sender.
Physical owner authorization, trusted one-use nonce backend, exact-image
same-lease host inspection, dedicated provider egress, real private Telegram
confirmation and separately recorded human notification receipt are still
NO_GO requirements of the sole governed #227 cutover. The installed controller
remains unchanged; no second workflow, deployment or cleanup target is added.

## Compatibilidad de almacenamiento con Opción B — corrección #315/#321

**Decisión del propietario 04/11/2026 ART:** usar un SQLite de sesión Chrome
**independiente** (`/data/boca_owner_session.sqlite3`) dentro del volumen de
datos Boca ya existente, sin agregar el ledger 0008 al SQLite legacy
`/data/boca.sqlite3`. Véase el [GO arquitectónico #321](https://github.com/mbalbo2023/boca-socios-assistant/issues/321#issuecomment-6647073475) y el RCA del
controlador físico `cabce9f1`, que reconoce sólo migraciones 0001–0007. La
alternativa A previa permitía 0008 con checksum conocido en el archivo
principal; **queda reemplazada**, no debe usarse como base para un cutover.

El verificador de Telegram `telegram_storage_gate.verify()` opera únicamente
sobre `/data/boca.sqlite3`. Su lista permitida ahora incluye versiones
0001/0002/0003/0005/0006, 0007 cuando Telegram está habilitado, y 0004 sólo
como política de claves opcional con checksum válido; **rechaza 0008 aun si
posee el antiguo checksum esperado y la tabla `owner_browser_session`**.
`telegram_storage_gate.migrate()` sigue agregando únicamente 0007 a esa base
y no abre, crea ni altera el SQLite vecino para Chrome. La autorización de
Opción B es sólo para código/QA/PR DRAFT: no implica migración física, GO de
release, limpieza real, uso del token, envío Telegram o habilitación del bot.

Regresión prevista: los tests de `test_telegram_storage_gate.py` reproducen
la versión 0008 de la alternativa A y comprueban rechazo sin DDL, incluso
antes o después de 0007 y con 0004 opcional. Otro test instala un SQLite
vecino sintético para confirmar que la migración de Telegram no lo modifica.
Registrar QA y SHA exactos en #315 al publicar el PR, nunca reutilizar el
GREEN histórico del HEAD anterior.

## RCA P0 R21: secretos Telegram en SSH argv — corrección candidata #315

**Hallazgo observado el 05/11/2026 ART; no hubo token real ni prueba de fuga.**
Los cuatro bloques del workflow único `boca-first-deploy.yml` interpolaban
un HMAC de chat/identidad del dueño y, para `telegram-install`, un sobre
cifrado de bot en `remote_command` construido con `shlex.join`. Los destinos
eran `browser-telegram-preflight`, `browser-*` lifecycle cuando Telegram
estaba listo, `browser-telegram-cleanup` y `telegram-migrate/prepare/install/
verify/test`. Pese al canal cifrado SSH, el comando quedaba en **argv** del
proceso SSH/host, visible para observación de procesos. El environment
protegido de Actions no elimina esa exposición. RCA y estado factual
previo: [issue #315, comentario R20](https://github.com/mbalbo2023/boca-socios-assistant/issues/315#issuecomment-6649930992).

La rama DRAFT corrige los cuatro *call sites* mediante una sola conexión
SSH por operación, con datos **exclusivamente por el pipe de stdin**. El
runner construye un frame binario acotado (magic, longitud de 32 bits y
JSON estricto) que incluye el helper `host_first_deploy.py` exacto, su
SHA-256 y la lista de operandos del CLI —con sobre/HMAC/owner únicamente
como datos del pipe, sin crear archivos temporales de secretos. El comando
remoto es un bootstrap Python estándar **estático**, independiente de cada
valor privado. Rechaza antes de ejecutar el helper: frame truncado o
sobrante, tamaño excesivo, claves JSON repetidas/desconocidas, SHA distinto,
fases o flags no permitidos. Luego define `sys.argv` sólo en memoria Python
para conservar `argparse` y todos los controles del helper existente; no
reescribe `/proc/*/cmdline`. El workflow usa `env -u` para que SSH no herede
el sobre, bot-ID, HMAC ni owner-subject, y `pipefail` para propagar un emisor
fallido. Preflight 120 s, lifecycle 600 s y cleanup 180 s conservan sus
presupuestos; los recibos y validaciones de cada fase también se conservan.

Regresiones offline con valores **ficticios** verifican los cuatro bloques
con un solo SSH, ausencia de interpolación de secretos, ausencia de secretos
de `/proc/self/cmdline` en el proceso remoto, compatibilidad exacta del parser
para fases Telegram y lifecycle, frame byte-exacto y SHA-256, y rechazo de
framing/JSON/digest inválidos antes de ejecutar código. El conjunto no
necesita Telegram, token, Docker, SSH real, host ni datos de Boca. Se mantiene
la Opción B del mismo DRAFT: 0008 en SQLite legacy es NO_GO y la sesión
Chrome va a SQLite vecino del volumen Boca. La corrección no activa V2 ni
resuelve los gates de nonce, lease, egress, aviso humano o sender; todos
siguen **OFF / NO_GO** hasta integración final, exact-SHA Actions, merge
autorizado y recibos físicos. Otros argumentos privados de owner/Site fuera
de los cuatro bloques Telegram son scope separado y **no quedan cubiertos**.

**Evidencia local R21 (no hosted):** primero se conservó una regresión RED
que detectaba el antiguo SSH `remote_command`; tras el cambio, 170 pruebas
en los scopes Telegram/host/legacy pasaron y el suite completo pasó
**2617 tests + 31 subtests** en 60,10 s. `uv sync --frozen --offline`, Ruff
check, Ruff format (397 archivos), MyPy (89 fuentes), policy de aislamiento
y `git diff --check` completaron sin defectos. Estos números corresponden
a la candidata local; no equivalen a CI exact-SHA, seguridad de imágenes,
GO del titular ni aceptación en el droplet.
