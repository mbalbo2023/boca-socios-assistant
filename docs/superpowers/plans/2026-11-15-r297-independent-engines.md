# R297 — Independent owner engines implementation plan

**Goal:** make queue/token observation and member browser work independently
startable/stoppable in the existing private panel and worker.

**Architecture:** two durable logical activations, one supervised physical worker,
bounded correlated IPC and a shared pool of ordinary Playwright browser types.
Existing observers/parsers/auth/vault/monitors remain the implementation units.

**Tech stack:** Python3.12, SQLite audit_events, asyncio/AF_UNIX, Playwright1.64.1,
existing WSGI/HTML panel and protected Boca GitHub Actions.

**Spec:** ADR0302 and issue417 comment6886406162 (DUAL-01..12).

## Global constraints

- Same PR517/feature417-r295-beta-followups; base b23dc20. No other candidate.
- SIMULATION_ONLY; no real ticket request, provider session or notification by
  the agent. No host action in this implementation phase.
- BLACKBOX synthetic.py/ipc_worker.py remains unread/unmodified.
- One physical authority, existing DB/socket/panel/port/outbox/vault. No GET
  migration, new server or copied parser. No elevated resource/package caps.
- Source-bearing changes require exact source/bundle pin reconciliation.
- No duplicate base tests. Focal delta tests first; required CI for final SHA.
- One writer per file. Full final review is independent of implementation.

## Task1 — Durable engine authority (ledger implementer)

Create `panel/engine_intents.py`, tests `test_engine_intents.py`.
Own only these files plus the narrow `_work_finished` hold guard in
`panel/lifecycle_intents.py` (coordinate that edit with root).

Define typed `EngineActivation`: engine, activation_id, generation, boot_id,
physical_start_id, member_id, counts by browser type, state and timestamps.
`EngineIntentStore` reuses Database and existing lifecycle insertion/reading
helpers inside BEGIN IMMEDIATE. Expose start, stop, transition, snapshot,
publish_if_current, release and recover_cold. No external I/O inside a DB lock.
Return the existing physical intent that needs waking, rather than waking it.
New namespace holds/releases fence automatic work STOP; same transaction
reserves global50, commits intent and binds physicalSTART. Legacy namespace and
readers retain compatibility. Preserve credentials and historical events.

Verify real SQLite behavior: doubleSTART, changed member/counts conflict,
both engine orders, release one preserves other, last release issues oneSTOP,
STOP/restart generation fencing, revocation blocks publish,50global, physical
receipt failure, cross-engine/replayed UUIDs and cold recovery.

## Task2 — Scoped worker/session execution (browser implementer)

Create `browser/engine_protocol.py`, `browser/engine_sessions.py`,
`browser/engine_client.py`; extend ipc_protocol/server and automatic_observer.
Own corresponding new focused tests; do not edit controller/panel/runtime.

Protocol identity fields: engine (`queues_tokens`/`browsers_members`),
activation_id UUID, generation positive integer, session_id UUID and browser
(`chromium`/`firefox`/`webkit`). Commands: observe, prepare_login, login, close.
Outer replies echo the complete identity; nested observations/auth use existing
strict codecs. Frames remain bounded and authenticate kernel peer/socket/EOF.
Cancellation uses an independent connection, fences before awaiting teardown,
and does not queue behind another session. Max50 live contexts and at most two
engine activations; stale identity/replay cannot create a context after close.

Pool loans one ordinary browser process per type to existing
AutomaticQueueObserver instances. Launches are paced and bounded. Inject a
shared async initialization lock around BLACKBOX output suppression. Closing
one observer releases only its context/loan. Retention after auth is explicit;
never claim DOM authentication from an HTTP token alone. No handoff/cookie copy.
Legacy IPC modes/tests remain compatible. No new listener or worker entrypoint.

Verify independent A/B polling, STOP during another blocked poll/login,
identity mismatch, replay, generation, timeout, bounded uncooperative close,
three type dispatch,50global, isolated pages and retained-session inspection.
Mock only browser/OS/network boundaries; exercise actual registry/protocol.

## Task3 — Controller coordination and dashboard (root integration)

Create `integration/engine_sessions.py` to bind the two stores and scoped clients
to the existing OnDemandBotSession callbacks. Adapt runtime and integration/beta
only for aggregate activation-start/stop callbacks; preserve engine_socket and
host runner. Worker physical APPLIED receipt gates every first session.

Control loop owns per-engine cancellation/tasks and per-session private
observations. Publish only under engine/member/physical activation fence.
Cold startup reconciles stale jobs without reopening them. Shutdown cancels and
drains local tasks before the controller engine acknowledges STOPPED. Uncertain
remote scopes retain holds until scoped ACK or physical STOP/APPLIED. Last release wakes the
existing physical STOP UUID; second START never resets the first.

Extend private_http/private_ui/monitor surfaces: two sections, four controls,
member selector for B, counts per browser type, observed phase/time, current
URL inspection, queue metadata and requested/created/active/closed totals.
Reuse existing owner session/CSRF/idempotency and private reveal/copy contracts;
do not send bearer in aggregate polling or logs. Existing controls remain
compatible or clearly route to the aggregate stop.

Test actual coordinator+SQLite with fake IPC boundary, four combinations and
cross-stop; HTTP controls with real authorization/form reservation; live
metadata projection cannot claim receipt success/current physical health.

## Task4 — Qualification, docs and publication (root + independent reviewers)

Confirm all three browser binary/dependency paths from the pinned image; do
not weaken security checks to enable a missing type. Add offline evidence for
enabled engines and truthful unavailable states. Reconcile source ZIP closure,
pins and unchanged resource budgets. Read current exact-head Actions first.

Update current AGENTS/README/DEVELOPMENT_POLICY headers and the requirement
matrix with implemented, verified and pending physical criteria. Run only
meaningful focal tests/lint/type checks and required closure checks, then get
architecture, QA/product and development/operations code votes. Fix objections
before one consolidated push to the existing branch; no force overwrite of an
unexpected remote head. Required final-SHA CI and GitHub factual checkpoint.

The final product objective remains consolidated BETA promotion and physical
acceptance; this implementation phase does not label CI as deployment or
invent user/device/provider evidence.

## Review-driven additions within the registered contracts

- Same-snapshot credential read authority and final exchange admission reuse
  BocaMemberAuthService and authenticate_member; no second vault or auth stack.
- Scoped CLOSE retry preserves the normal-call fence. Completed local tasks,
  activation ACK and physical STOP proof are distinct evidence.
- Explicit aggregate STOP recovery can certify a stable already-exited worker
  execution under the existing protected lease. START compensation cannot mint
  this authority. The exact changed host closure receives a new immutable pin.
- The owner's follow-up visual QA request is recorded in issue417 comment6886936337.
  Reuse the existing network-none real-Chromium CI path with engine_view fixtures,
  native forms, polling and fixed-data PNG artifacts. This does not create an
  authenticated droplet screenshot capability or waive physical acceptance.
- A supported cold upgrade may preserve legacy START/APPLIED, FAILED or UNCERTAIN
  with no DUAL activations. Reuse the existing owner bot-STOP form and wake for
  explicit recovery only when an atomic writer-locked check finds no logical
  holds. Preserve history, reuse an existing pending STOP, and require the real
  STOP/APPLIED receipt before engine START. A stale recovery form cannot stop a
  newly admitted engine. The recovered state does not manufacture an activation.

## Required image correction after exact-candidate CI

Design and four real pre-implementation GO votes are recorded in issue417
comments6887845873 and6887901648. Current Firefox SIGSEGV/WebKit missing codec
library block promotion; do not weaken CHECK_FAILED, STOP or custody semantics.

- Image implementer owns Dockerfile.browser, closed two-architecture Python
  download JSON, test_browser_apt_cve_2026_109518.py and browser packaging tests.
  Use pinned official Playwright1.64.1-resolute digest with explicitly verified
  CPython3.12.16/build20261110 under root-owned /opt/boca-python. Preserve uv0.13.4
  and lock; absolute interpreter selection and no later Python downloads.
  Pin same-suite corrected APT/Brotli/GStreamer before and after all3 dependency
  installation. Remove whole build tools/ensurepip for system and managed Python.
- Root owns only the existing APT mirror helper and its tests, adding closed
  --suite resolute selection while preserving default Noble behavior and all
  signature, recognized-source and mixed-pocket rejection requirements.
- Consolidate the independently reviewed visual callback correction into this
  follow-up. Architecture and QA independently review final changes before one
  publication to the same PR. Verify untouched FULL/PAIR package membership.
- Require exact-source build, unchanged strict scans, actual full3 launch/goto/
  close and real Chromium visual artifact inspection. No host operation or
  promotion is justified by the design vote alone.

## Bounded diagnostic follow-up after CI1253

Issue417 comments6888166845/6888180796 register the observed failures and four
actual design GO votes before code. Keep the built Resolute image unchanged.
The full3 implementer owns only the manual diagnostic workflow and its tests:
separate explicit context/page phases, retain original evidence before cleanup,
close protocol/XPCOM categories, reject hexadecimal codes as process exits and
require successful cleanup for PASS. The visual implementer owns only its runner
and tests: fixed step/viewport and bounded counts, preserving every timeout and
proof check. Root owns documentation. QA/root and cross-reviewers independently
review the resulting changes before publication. A subsequent hosted run may
diagnose the failures; do not relabel this instrumentation as a runtime fix.

Final cross-review is recorded in issue417 comment6888353010: architecture,
operation/visual, QA and root delivered actual GO votes with authors excluded
from independent approval of their own files. Full3 author39+5 and visual
author34 PASS; independent focal counts4/13/18/13 overlap. Lint/format/diff-check
PASS and the six paths do not alter FULL/PAIR. Publish only this diagnostic delta
and require its hosted evidence. Image security1082 on parentab3f189 is a separate
first scan of the new image; it cannot certify a future candidate SHA.

## Three disjoint follow-ups after 14cd9a0

Observed results: issue417comment6888453403. Pre-code proposal: comment6888524385.
Architecture owns only Dockerfile.browser and focused packaging tests for exact
whole-Pebble removal; visual owns its runner/tests for native303 loopback fixtures
inside the ephemeral network-none CI container; QA owns full3 workflow/tests
for passive resource and separately classified late-exit evidence. Root owns
documents and publication. Do not change production HTTP, Compose, seccomp,
caps, timeouts, strict scans or BLACKBOX. Confirm every actual design vote,
cross-review code and publish a consolidated delta in PR517. Hosted success,
screenshots and physical acceptance cannot be inferred from those reviews.

Actual pre-code votes are recorded in comments6888549299/6888565397. The visual
fixture uses isolated per-viewport listener/state, bounded headers and body,
terminal rejection and mandatory bounded thread cleanup. The proposed serialized
fixture is140828 bytes under the existing160000 cap. All three owners may now
implement their disjoint scopes; final independent review remains mandatory.

Final code votes are recorded in issue417 comment6888843482. Architecture,
QA, operation/visual and root delivered actual GO decisions, with each author
excluded from independent approval of their own changes. Review closed the
cgroup continuity omission and two concrete socket teardown races. The visual
P2 temporarily withdrew GO; its corrected successor checks final descriptors
after bounded thread drain and preserves real errors and the primary fault.
Author evidence: image42 PASS; full3 63 PASS; visual79 before P2 and15 affected
PASS after its correction. Independent focal results overlap. Lint, formatting,
diff-check and the empty FULL47/PAIR83 source intersection are verified. Publish
the nine scoped paths together in PR517, then obtain hosted evidence before any
promotion. Do not infer Firefox availability or physical acceptance from votes.
