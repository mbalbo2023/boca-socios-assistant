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


## Polling and bounded Firefox task-budget diagnosis after 18724f8

Evidence6889022274: CI1255 reports 9331 tests and 34 subtests PASS, with a UI
live_rows_poll NO_GO and no PNG. Image Security1083 passed both strict scans.
Full3#5 reports Firefox new_page NO_GO with pids.peak128/max128 and an
identity-guarded event delta of 1; memory OOM deltas are zero.
Proposal6889045401 and four actual pre-code GO votes6889058150 authorize only
two visual files and three diagnostic/contract files; root owns documents.

Visual author: replace boolean DOM expressions with the same conditions in
functions, retaining RAF and timeouts. response.body avoids the verified
Python orphan task. Capture a closed primary-error category and exact
bool/UNKNOWN states before cleanup without payloads; do not attribute CI1255
to CSP without direct proof.

QA author: closed full3/default or firefox-pids input through environment/case;
default128 unchanged. The experimental mode runs only Firefox192/256,
sequentially and once each. Require observed pids.max as the exact integer
before driver/launch; UNKNOWN or mismatch is NO_GO. Capture preclose after
goto/connection; all three closes remain required. Keep the primary failure,
late suffix and accumulated NO_GO. No runtime, resource, sandbox or timeout
changes; no claim of physical capacity for 50 contexts.

Use focused meaningful regressions and independent cross-review before a
single consolidated publication in PR517. Seven proposed paths do not belong
to FULL47/PAIR83; no package rebuild. New hosted proof and promotion remain
pending, with no server operation during this correction.

Final code review6889186686 records actual GO votes from all four roles, with
authors excluded from independent approval of their files. Visual18 RED then
45 affected PASS; diagnostic37 RED then58 affected PASS at final verification.
Architecture ran four focal cases per scope plus independent inert attacks;
QA ran four visual cases. Counts overlap. Lint, formatting, YAML, Bash, AST
and diff-check pass. Publish the seven paths together, then request the
Firefox-only comparison once and inspect hosted UI evidence on the new SHA.
pids_budget_verified is attribution only: UNKNOWN cannot certify a budget,
and a positive event delta remains evidence of pressure even with functional
PASS. No host operation or new dimensioning decision follows from this vote.

## Controls before histories after actual CI1256 screenshot inspection

Evidence6889286186 closes CI1256 on2c35d22:9386 tests+34subtests, both builds
and strict scans, UI and cleanup PASS. Both artifact14146554703 PNGs were
integrity-verified and inspected; they are synthetic, not installed-panel proof.
Firefox192/256 minimum probes PASS with peak144/143 tasks and zero pids/OOM
events. Runtime128 versus that measurement is a separate design question.

Proposal6889343476 and four actual design votes6889346780 authorize only
engine_view.py/test_engine_view.py plus these documents. A separate author
extracts session histories from _section; page emits both controls first,
then H2 common/H3 by engine/H4 rows. Preserve forms, IDs, fences, entered
values and the current ID-based polling. Reuse _PHASES for outcome/queue_state,
adding only ACCESS_OBSERVED as the existing TARGET_OBSERVED label. Accept
recognized strings only; all other types/codes use Sin dato. phase unchanged.
Focused RED/GREEN regressions cover order0/2/50, identities/private links and
SSR/real-JS translations. Four independent final code votes, affected package
intersection and exact-SHA hosted visual proof remain required. No new runtime
budget, benchmark, host operation or repeated certified baseline tests.

Final review6889461596 records four independent GO votes, excluding the code
author. Author26 affected PASS; architecture4 focal PASS, QA2 focal PASS,
operation an inert50-only-in-A counterexample PASS. Counts overlap. Seven
documents passed factual review after fixing PR0 to follow integration.
Publish nine scoped paths together; no source intersects FULL47/PAIR83.
All roles keep existing caps and reject a new pool3/50 predeploy gate.
Existing installed observers prove health/custody, not pool consumption;
the counter readers are currently CI-integrated. An additional installed
numeric measurement needs a reviewed protected-Action adaptation, not a
claim that the current status receipt already supplies it. Exact-SHA hosted
UI/gates, promotion/postflight and physical acceptance remain separate.
