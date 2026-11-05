# ADR 0139 — Boca-only postdeploy cleanup implementation (issue #323)

Date: 2026-11-04 ART  
Status: **DRAFT / CODE_ONLY / physical NO_GO**  
Scope: #227 orchestration and generic Boca installs/updates; implementation of
the owner's permanent requirement #323 (see canonical ADR0138).

## Contract

Postdeploy cleanup is a **mandatory finalizer on both SUCCESS and FAILURE** of
every first-install, beta-install, update and future cutover, not merely an
error handler. This PR introduces `host_boca_cleanup.py` as an independently
testable implementation; it remains **unwired to all live workflows**.

`host_boca_attempt.py` now supplies the code-only **producer** missing from
historical first/beta installers: a reviewed controller-only Compose overlay
with an exact first/beta/update attempt label and source SHA, plus pre-effect
`intent` and post-effect `result` as separate canonical, durable O_EXCL
receipts under the **same job flock**. A result is read back and bound by the
SHA256 of the immutable intent before any preserve/retire ID can be derived.
SUCCESS preserves only the exact accepted controller ID; FAILURE can name
only the exact created ID as a cleanup candidate (and it still must be
positively labelled, stopped and unused). Missing result, symlink, unknown
transition and mismatched ID are NO_GO; `update` original-ID retirement is
explicitly unimplemented/NO_GO. These receipts do not themselves prove that
Docker effects occurred; a future protected workflow must inspect exact
runtime labels and health before writing them.
The isolated `finalize_attempt()` facade now reopens both immutable markers,
validates the canonical **actually held** flock, probes exact Docker labels
(project/service/operation attempt/source SHA), and only then calls the
Boca-only postflight engine. A forged `BocaJobLease(active=True)` with a
different or unlocked FD cannot authorize it: a separately opened contender
must be blocked while a duplicate of the owner's original OFD retains the
canonical lock. This source facade remains unreachable from the live CLI.

1. The protected job must retain a single non-reentrant Boca UID10001 flock
   across its install and finalizer. The cleanup module provides a Boca-only
   cooperative lock at the same canonical
   `/run/user/10001/boca-socios-protected-job.lock` used by the #321
   attestor (which borrows that FD). Older workflows do not yet
   acquire it, so this alone does not establish global exclusivity.
2. First perform an **ID-only global Docker census**, comparing it with the
   precise Boca project-label filter. If **any foreign container**, foreign
   network (excluding built-in Docker networks) or foreign volume appears in
   the dedicated rootless daemon, **NO_GO before inspect**. Inspect *only*
   project-filtered Boca resources, using narrowly allowlisted fields
   (ID, labels, running, mounts, network membership, image references);
   **never read foreign Config.Env, mount metadata or other workload
   configuration**. Image IDs may repeat per tag, but are deduplicated.
   Docker CLI is pinned to the dedicated rootless socket with an explicit
   `--host`; inherited Docker context/TLS overrides cause NO_GO and the
   child process receives no unrelated environment secrets.
3. A stopped container is **not inherently garbage**. The protected job must
   provide `preserve_containers` exact installed/stopped controller, parked
   legacy and worker IDs, plus `retire_containers` explicit IDs from
   authenticated attempt receipts. Removal requires positive Boca project,
   name, immutable attempt label, exact retired ID and stopped state.
   A temporary volume/network requires Boca project + matching attempt and
   zero known references. Owner/data/key/Telegram volumes are **never eligible**.
4. A stale image may be removed by **full image ID**, only if no container
   (running **or stopped**, from any project) references it and the exact Boca
   repository provenance label is present, with no foreign repository tags.
   Multi-tag image IDs are deduplicated in inventory; `docker image rm <ID>`
   without force must succeed. `docker image rm <tag>` alone is insufficient
   evidence because it may merely untag one alias; a fresh global **ID-only**
   census must prove that exact image object ID is absent afterward.
5. Before each `docker rm`, `docker image rm`, `docker network rm` or
   `docker volume rm`, read a **fresh full inventory**, recompute the eligible
   set and reject drift. Every deleted exact resource must disappear in the
   immediately following inventory. If deletion fails/loses its receipt, do
   not retry or use broad prune.
6. Repeat within a fixed 32-target budget because removing a stopped orphan
   container can then make its old image/IPC volume eligible. Final postflight
   must enumerate **zero known eligible Boca images and other resources**.
   Unexpected disappearance of unrelated resources is a NO_GO.
7. An unproven possibly-Boca resource is **retained** and named in an
   `INDETERMINATE` receipt. A legacy first/beta attempt without an immutable
   attempt label is **NO_GO until the producer/Compose marker contract is
   migrated**; accepting a stopped legacy by name alone is forbidden.
   Known residue or observed drift is `NO_GO`;
   only a complete, exact positive postflight is `ACCEPT`. The receipt
   records outcome, attempt, resource ID list, disk/inodes and reasons, without
   environment variables, credentials, filenames containing secrets or
   unrestricted Docker output.

## Evidence / remaining deployment blocker

- Offline tests cover SUCCESS and FAILURE finalization; image cleanup after
  attempt container release; multi-tag and dangling provenance; unknown
  provenance; protected active image and persistent owner/data/key volumes;
  stopped foreign container retaining a Boca image; exact attempt mismatch;
  lost deletion receipt; unrelated container drift; flock exclusivity;
  exact-ID preservation of stopped installed controller/parked worker;
  unlabelled historical beta NO_GO; foreign secret never inspected; malicious
  DOCKER_CONTEXT and inherited token isolation; image untag-only still NO_GO.
  Ten additional producer tests cover first/beta/update label overlays,
  O_EXCL intent/result, exact-ID preserve/retire, forged/missing receipts,
  unsafe symlinks and update hard-stop.
- Local QA for the code-only producer: **34 focused tests PASS**;
  full suite **2533 passed + 31 subtests passed**; Ruff lint/format
  (395 files), Mypy (87 source files), repository policy and whitespace PASS.
- `synthetic.py` and `ipc_worker.py` remain BLACKBOX; no Boca login,
  reservation or purchase and no Docker host operation has been dispatched.
- **Physical NO_GO** until a reviewed, single protected finalizer actually
  runs `if: always()` after every install/update phase (including failed
  phases), authenticates its release/attempt and lease, streams the exact
  reviewed helper into the dedicated rootless SSH identity, records the
  receipt and fails acceptance on `NO_GO`/`INDETERMINATE`. Merely publishing
  this module does not satisfy the operational requirement. First/beta
  workflows must run the approved Compose overlay from the same protected
  job *before* any effects, construct the O_EXCL intent and result from
  genuine Docker exact-ID receipts, hold the canonical lease throughout,
  and invoke the finalizer with `if: always()`. There is no such YAML wiring
  today; source-only success is not host evidence.
- **Transaction architecture blocker:** existing `first-install` and
  `beta-install` YAML call independent SSH Python processes for preflight,
  staging, Compose config, effectful apply and failure-only cleanup. A flock
  FD cannot survive between those processes as an authenticated, continuously
  held same-open-file-description lock. To meet #323 the job must invoke one
  protected host transaction (pre-effect intent, reviewed Compose label
  overlay, apply/inspect, result, `try/finally` cleanup/postflight, release
  lease) and end with an `if: always()` Actions receipt assertion. If SSH or
  host process dies before a trusted result, no guessed cleanup is allowed:
  the assertion fails NO_GO and requires exact Boca-only read-only recovery.
  No ZIP/host runner or lifecycle workflow has yet passed this gate.
- **Transport code-only checkpoint:** a deterministic allowlisted
  `build_protected_boca_bundle.py` now packages only first-deploy/rootless,
  #323 attempt+cleanup+transaction modules and reviewed base Compose YAML
  into a bounded ZIP. It explicitly excludes `synthetic.py`/`ipc_worker.py`.
  `boca_protected_memfd_bootstrap.py` verifies ZIP SHA256, exact entry names,
  regular-file modes and sizes before `execv` of that digest-checked payload
  through Linux memfd (no host disk write). Six offline tests exercise real
  memfd selftest, byte-for-byte reproducibility, tampered SHA, injected
  BLACKBOX name and overwrite/symlink attempts. The packaged transaction
  deliberately returns `NO_GO transaction_not_wired` on any effectful mode.
  Existing CLI/workflow remains unchanged; `host_first_deploy` opts into a
  reviewed second Compose `-f` only within an in-process protected context,
  never via a legacy CLI argument. Positive install/rollback wiring and the
  YAML `if: always()` assertion are STILL PENDING and no deployment is safe.
  Bundle checkpoint QA: **6 transport focal tests PASS**, full frozen suite
  **2539 pytest + 31 subtests PASS**, Ruff lint/format **399 files**, Mypy
  **88 source files** and repository policy PASS. A prior overlapping full
  run hit one 5-second shell-fixture timeout and an inspect.getsource line
  race while this module was actively edited; after freezing sources both
  previously failing tests and the full 2539-test run passed unchanged.
- No `docker system prune`, `docker image prune`, `docker container prune`,
  cross-project deletion, guessed image identity, host-side backup, or broad
  filesystem purge.

See ADR0138 and [issue #323](https://github.com/mbalbo2023/boca-socios-assistant/issues/323)
for the global owner decision. This ADR describes only the isolated code
contract and open gates.

## A45-R11: existing-controller Cutover A sequencing (code-only)

The earlier `host_boca_transaction.run_transaction` handles only **new-only**
`first-install` and `beta-install`. It cannot be repurposed for the currently
RUNNING controller: doing so would violate its empty-namespace assumptions,
confuse the old controller with the attempt and risk losing the known-good
Samsung Chrome endpoint. The separate existing-controller identity, park,
worker and compensation primitives in `host_first_deploy.py` remain code-only.

`host_boca_cutover.run_cutover_a()` now formalizes an **inert injectable**
single-process ordering contract for existing-controller cutover:

### R11 reviewed-transport and stage-only Compose increment

The authenticated memfd ZIP now includes the reviewed browser Compose overlay,
seccomp profile, isolated cutover stage helper and sequencing module. It
accepts **exactly two** source profiles: standalone `core` before #321 merges,
or `core + owner_session_disk_bootstrap.py + 0001_owner_browser_session.sql`
after Option B integration. Partial Option B, third-party ZIP entries, BLACKBOX
and unreviewed code are rejected. The auth-owned stdlib-only helper is packaged
under the private import name `boca_socios.owner_session_disk_bootstrap` to
avoid executing the real `panel/__init__.py` and its transitive UI imports.
The `core` profile can **never** authorize physical cutover because the Option
B ledger dependency is absent. The legacy controller SQLite file remains
schema 0001–0007 and is neither opened nor migrated by ZIP selftest.

The existing strict `_browser_compose_model` validator can now receive three
*optional, all-or-nothing* paths, and only when they are exactly
`/srv/boca-socios/cutover-a-<run>/compose.beta.yaml`,
`compose.beta.browser.yaml` and `seccomp_profile.json`; it refuses partial,
outside or traversal variants **before** Docker. The legacy default path and
environment remain byte-for-byte unchanged to all existing callers. An offline
fake Docker regression asserts the reviewed staged model and exact arguments,
including seccomp path; no host transition has been dispatched. The caller
must independently prove stage-marker/files/inode SHA before using this model.

This increment **does not** claim a complete HostCutoverBackend, atomic
promotion of reviewed files or a protected effectful workflow. All remain
physical NO_GO pending exact-ID positive receipts and selective postflight.

Independent #323 architectural review also found a concrete *false ACCEPT*
path in generic cleanup: a Docker target could remain in inventory under the
same immutable ID but cease to match the eligibility predicate (new attachment,
different name/labels). Merely checking that it disappeared from the proposed
deletion set did **not** prove deletion. Cleanup now requires positive *absence*
of every removed container/network/image **ID** or volume **name**, in addition
to image global ID-only census; an unknown post-delete classification returns
an explicit NO_GO receipt and never retries. Three adversarial fake-host tests
cover no-op removal plus eligibility drift for container, network and volume.
Frozen R11-2 QA: **2582 pytest PASS +31 subtests**; Ruff lint/format **402**
files, MyPy **89** sources, repo policy and whitespace PASS. This remains
offline-only and is not a valid host cleanup receipt.

## A45-R11-3: concrete rootless host adapter + durable Compose promotion

The standalone, **unwired** `host_boca_cutover_backend.RootlessCutoverBackend`
now implements the complete `CutoverBackend` protocol against the existing
reviewed `host_first_deploy._cutover_*` exact-ID primitives. Unlike a fake-only
state machine, it has concrete host code, but `host_boca_transaction.main()`
still rejects every effectful dispatch and workflow `cutover-a-apply` **does
not exist**. No physical host operation occurred in development.

- Source bundle must include all four exact target SHA256 artifacts:
  `compose.beta.yaml`, `compose.beta.browser.yaml`, seccomp JSON and Option B
  owner-session SQL. The independently reviewed SQL SHA is bound to #321.
  The B stdlib bootstrap imports only from the verified memfd ZIP, not from
  host `/srv` or the ordinary `panel/__init__.py`; absent B profile NO_GO.
- Host first positively observes the installed original ID/revision/image,
  owner/key/data custody, loopback 8443 and rootless Docker identity. The
  isolated stage keeps historical Compose bytes/inode unchanged while it
  verifies all three reviewed files, strict expanded Compose JSON and actual
  per-service `docker compose config --hash` labels. Only then can it pull
  exact two images and create the UID10002 network-none worker. (Docker CLI
  `--hash` semantics: https://docs.docker.com/reference/cli/docker/compose/config/.)
- Park/recovery uses the historical **immutable controller ID**. While old
  controller is positively stopped, the adapter attests that the rootless
  Boca data volume `/data/boca.sqlite3` is attached **only to that same old
  controller**, with exact owner/mode/inode, and calls #321's stdlib-only
  sidecar bootstrap with the *same held canonical lease FD* and reviewed
  session SQL. No legacy SQLite DDL/0008, no copying/backup. Postflight
  rereads old DB identity before candidate activation.
- Acceptance proves candidate exact ID/config hash/health, worker isolation,
  loopback port, and old ID still parked. The **irreversible promotion** is
  then marked by an O_EXCL + fsynced intent under stage BEFORE replacing any
  live Compose file. Base, overlay and seccomp are each installed from exact
  reviewed bytes with private 0600 temporary file, fsync and per-file SHA
  readback. A separate O_EXCL result binds candidate/worker/old IDs and
  artifact hashes. This is **not an atomic multi-file filesystem operation**;
  interruption after the first replacement is explicit terminal NO_GO and
  fix-forward only. It must not revive the old ID into occupied port 8443.
- After a genuine accepted original-ID retirement, the same backend invokes
  mandatory Boca-only rootless Docker cleanup and then removes only the
  positively attested stage files and O_EXCL markers. A compensated failure
  may discard the verified uncommitted stage. Unknown `.part` files, partial
  promotion, labels/IDs drift, negative SQLite proof, cleanup INDETERMINATE,
  lost Docker command receipt, and missing stage marker all retain residue
  quarantined and report NO_GO; no `prune`, cross-project deletion or backup.
- New PR-only GitHub Action invokes focused offline tests and constructs the
  deterministic authenticated ZIP, with a final `if: always()` assertion that
  **no host receipt** appeared. This is not a physical finalizer. A future
  authorized protected host job must launch exactly one memfd transaction
  under one SSH/lease and execute a separate `if: always()` receipt assertion;
  a lost runner/SSH may skip all finalizers and is automatically NO_GO until
  fresh Boca-only read-only inventory. Avoid suggesting `if:always` itself
  guarantees cleanup after a killed process.

Important remaining P0: no protected effectful CLI dispatch or one-job host
workflow exists, no immutable GitHub GO/release manifest verification has been
wired into this adapter, and no Samsung Chrome/Termius physical acceptance has
occurred. The new #328 bot/Chromium lifecycle intent/ACK contract is separate;
the panel must preserve HTTP/Chrome while stopping only simulated bot work,
and cannot claim execution until protected Actions persists exact ACK. These
gates remain outside R11-3 authorization. No real reservation or purchase.

Frozen R11-3 source QA: **2603 pytest PASS +31 subtests**; Ruff lint and
format **404** files, MyPy **90** sources, repository policy and whitespace
PASS. New fault-injection regressions exercise exact stage promotion/cleanup,
foreign root object rejection, lost `os.replace` receipt, Option B failure
compensation, service `config --hash` receipt and single-owner rootless volume
checks. PR-only Actions evidence must still be reconciled to published HEAD.

### Critical correction: lost exact-ID retirement result

Architecture review exposed a **P0** in the initial R11-3 finalizer:
`commit_started=True` with adapter state still `ACCEPTED` can mean Docker
already removed legacy, but the `rm` acknowledgement was lost. Passing only
the now-absent historical ID as the protected set into an *effectful* generic
cleanup would risk targeting the living candidate and worker—the **only**
service occupying loopback 8443. Fixed: whenever irreversible commit has
started and a positive `COMMITTED` receipt has *not* been obtained, finalizer
performs **only a read-only Boca inventory**, never calls a deletion planner,
never restarts legacy and always reports NO_GO. The stage commit-intent stays
quarantined for an independently governed fix-forward operation. A new
fault-injection test explicitly simulates successful old-ID Docker deletion
followed by lost acknowledgement and asserts zero destructive cleanup calls.
The same fail-closed barrier applies **before** commit if exact original-ID
recovery cannot be proven: state PARKED/BOOTSTRAPPED/CANDIDATE without a
positive RECOVERED receipt can leave the old controller stopped while worker
or candidate is live. In this case the finalizer performs read-only inventory
only, not Docker deletion. Effective selective cleanup occurs **only** for
verified state RECOVERED (precommit) or COMMITTED (postretirement), both under
one held lease. Added fake failed-recovery regression to prove this boundary.

Post-P0 freeze: **2605 pytest PASS +31 subtests**; Ruff lint/format 404,
MyPy 90, repository policy and diff whitespace PASS. The initial published
R11-3 SHA must **not** be promoted alone: this correction is a mandatory
follow-on commit; hosted checks apply to the final combined HEAD only.

1. Exact legacy ID/image/commit/Compose, independent new target and two image
   digests, target/overlay/seccomp SHA256, owner and fixed localhost origin are
   rejected before any host call if malformed.
2. One canonical Boca `flock` encloses original attestation, attempt-specific
   staging, worker preparation, exact old-ID park, **Option B session bootstrap
   only after legacy stop**, candidate activation/acceptance and the final
   irreversible retirement of the exact legacy ID.
3. The injected Option B callback must use the existing Boca data volume and
   a new sibling `boca_owner_session.sqlite3`, with independent schema and
   verified stopped-controller evidence borrowing the same lease descriptor.
   **Never run 0008 on the legacy `boca.sqlite3`.** No database/volume is
   opened by this contract or by its deterministic fake-host tests.
4. Pre-commit failures require positive **exact-ID recovery** plus Boca-only
   postflight before a `RECOVERED` receipt. A lost retirement receipt is past
   the irreversible boundary and **must not restart** the old controller into
   occupied `127.0.0.1:8443`; it is terminal `NO_GO`, pending a fresh read-only
   inventory. Postflight runs in `finally` on both paths; only its positive
   `ACCEPT` yields a successful classification. Unknown cleanup remains NO_GO.

This addition is an **orchestration protocol with an offline fake backend**,
not the concrete `HostInstallBackend`, Docker operations, exact durable
intent/result markers, authenticated release/host proof, or a new Actions
dispatch. The actual `boca-first-deploy.yml` is **unchanged** and allows only
`cutover-a-observe` as the new read-only operation; therefore physical Cutover A
remains NO_GO. Before any future wiring, the backend must prove the stage
inode/lease, Compose hash and configuration, exact service labels, rootless
daemon/cgroups/loopback, crash/transport ambiguity, owner-session file
bootstrap, worker/IPC compensation and protected volumes using disposable
runner Docker plus exact-SHA hosted checks. The protected Actions job must
require an **`if: always()` read-only receipt assertion** for both success and
failure. This assertion detects a *missing receipt* as NO_GO; it cannot
guarantee execution of cleanup after SSH/runner/process loss, nor justify a
guessed deletion or automatic retry.

For historical PR #320 SHA `35f6e29942064b0656a879d94215638d58d55ebe`,
four separate PR-only workflows completed successfully: CI `41949228821`,
image release validation `41949228846`, image security `41949228937` and
first-deploy validation `41949228860`. Their success predates this incremental
code and proves **no physical host action**. Regla84 must record new exact-SHA
checks separately after publication of this change.

## A45-R11-4: same-lease terminal attestation and guarded GO boundary

The protected concrete cutover still has **no effectful CLI dispatch** and
`cutover-a-apply` remains **absent** from the GitHub Action's manual operation
choices. The user authorized preparing an eventual single protected operation,
not physically performing it without a separate exact-SHA GO. In particular,
reviewing source or running synthetic host tests must never flip a host gate.

`host_boca_cutover_receipt.TerminalRecord` now binds attempt, historical SHA
and immutable controller ID, target SHA, terminal state, actual cleanup
classification, recovery/irreversibility flags and optional candidate/worker
IDs. A positive `ACCEPTED` record requires both living candidate and worker
exact IDs **distinct from legacy and from each other**, an irreversible commit
and a positive cleanup receipt; a positively `RECOVERED` failure requires the
old ID restored and no commit. An ambiguous `NO_GO` preserves real uncertainty
and must never be converted into acceptance.

`run_cutover_a()` accepts an optional terminal sink and invokes it **after
the unconditional Docker finalizer but before releasing the exact same
canonical protected job lease**. The production-ready sink creates
`/run/user/10001/boca-cutover-a-result-<run>.json` with O_EXCL and no replace,
owner-only mode 0600, fd fsync, directory fsync, exact inode/mode/bytes
readback and SHA256. A duplicate or symlink refuses; a partial/truncated
marker is retained as evidence and never overwritten. No secret is printed.
It is **not wired to any host invocation**: the existing entrypoint returns
`NO_GO transaction_not_wired` for all effectful arguments.

The GitHub PR-only workflow runs this independent five-test receipt suite;
its `if: always()` assertion continues to require **zero host receipts** on PR.
Future host Actions must assert an authenticated terminal record on both
success and failure, under single SSH/memfd/lease and independently verified
historical controller manifest, target controller manifest and same-release
browser manifest, with the bundle SHA256 bound to that exact run. A missing
host record (SSH interruption, killed runner, failed fsync) is **NO_GO**;
Actions' finalizer is not a recovery guarantee or permission to guess cleanup.

Integration drift in consolidated candidate #319 temporarily omitted the
original `host_boca_transaction.py` contract, its matching test file, and a
nine-line `host_boca_attempt.finalize_attempt()` guard that rejects an
unrecorded but attempt-labelled controller on `FAILURE` when the created ID
is unknown. The complete contract and guard must be restored alongside the
tests; deleting the test from CI would mask a real unsafe cleanup condition.
An extra adversarial test now requires that such a labelled unknown controller
forces `AttemptError` with **zero calls to effectful cleanup**. No host
effects, backups, BLACKBOX changes or service/port mutations were performed.

### R11-5 future GO preflight (runner-only, deliberately inactive)

`scripts/check_cutover_a_go.py` adds a **pure runner-side prerequisite**, not
an authorization token or host invocation. It is tested by the existing
`boca-first-deploy.yml` PR-only job. The current workflow still exposes only
`cutover-a-observe`: there is no dispatch input or `case` for effectful apply,
and the bundled host entrypoint continues to hard-stop every effectful mode.

If the owner later issues a separate physical GO, a *new code review* must
wire this prerequisite into the **same** workflow (never a second privileged
workflow). The protected GitHub Environment would then need to provide
`BOCA_CUTOVER_A_GO_BINDING_SHA256` as a distinct approval variable—not as a
`workflow_dispatch` input. It defaults to absent, therefore NO_GO. The value
must be the SHA256 of a canonical, versioned record containing:

- repository, original owner actor, `refs/heads/main`, exact main/source SHA,
  unique immutable GitHub run ID and `run_attempt=1`;
- original legacy controller ID, historical SHA/image/release run, old
  release-manifest bytes digest and historical `compose.beta.yaml` SHA;
- target SHA/controller image/release run, reviewed controller manifest and
  **same release** browser companion manifest bytes digests;
- browser image digest, reviewed base/overlay/seccomp SHA256, authenticated
  Option B-inclusive memfd ZIP SHA256, owner subject hash and fixed
  `http://localhost:8443` origin.

All three manifests are parsed as bounded files with duplicate-key rejection,
validated against distinct historical and target releases, and SHA-bound.
Historical and target Compose/overlay/seccomp files require stable read-only
inode and exact digest. Each artifact path must be absolute; the runner walks
**every parent directory using O_DIRECTORY|O_NOFOLLOW file descriptors** and
opens the final file with O_NOFOLLOW, so an intermediate symlink cannot swap
the artifact being authenticated. The ZIP must pass the strict source allowlist and
contain **both** independent Option B SQLite bootstrap artifacts. An absent
variable, fork/PR/non-main context, rerun, wrong release/manifest, missing B
profile, symlink, changed file or wrong digest yields NO_GO **before any SSH**.
The additional 16 regression cases explicitly cover those failures and
demonstrate the preflight itself touches no Docker, SQLite or network.

**R11-5 FIFO anti-hang correction (architecture review):** The original
`_read_bounded()` called `os.open(O_RDONLY|O_NOFOLLOW)` before it could apply
`fstat(S_ISREG)`. A local FIFO with mode 0600 and no writer could therefore
block the GitHub runner indefinitely **before its own fail-closed file check**;
this was reproduced with an adversarial subprocess timeout. The final-file
open now includes **O_NONBLOCK** (no behavior change for regular files), then
retains the same exact regular-inode/owner/link/mode/readback verification.
A subprocess regression creates a genuine 0600 FIFO and requires prompt
`NO_GO host=untouched` within a bounded timeout. This resolves the local
availability flaw without claiming a physical GO or modifying the controller.

This preflight deliberately **does not** independently query GitHub to prove
that an Actions run succeeded, authenticate the historical Compose API
response, certify live Docker or attest real Chrome/Telegram usability. These
must be separate positive steps in the eventual protected Action, with
single SSH+verified memfd+flock, exact controller+worker IDs, mandatory
postflight and O_EXCL terminal receipt. Physical **NO_GO** until that final
review, an independently recorded owner GO and a successful actual host run.

After Cutover A, lifecycle issue #328 registers idempotent `bot` and
`chromium` START/STOP intents in the legacy audit ledger and shows only
PENDING until a privileged host worker claims and writes verified ACK. It
must stop the **synthetic bot engine**, not the HTTP controller that serves
the Samsung panel; no panel-side Docker socket. Telegram issue #315 requires
owner-only token custody and its own protected activation/negative synthetic
tests, never token entry into chat or logs. Both belong to governed phases of
the same **existing** deployment authority (or its later protected operations),
not extra ports, HTTPS, a second privileged workflow or real ticket purchases.
Thus even a future positive Cutover A receipt **cannot** by itself certify an
integral BETA GREEN: authenticated Chrome persistence, Telegram private
delivery, lifecycle ACKs, no-reservation simulation, Samsung Chrome+Termius
acceptance and selective Docker cleanup still need actual receipts.

### R19 P1: reboot-persistent host-only receipt, with pre-effect O_EXCL intent

Architecture audit detected a durable-evidence defect in R11-4: the terminal
record was written to `/run/user/10001`, a **tmpfs runtime directory**. An
irreversible accepted cutover followed by host reboot could lose that marker,
so neither GitHub's `if:always()` nor a later read-only inspection could
reconcile the original host decision. Calling `fsync` on tmpfs does not fix
reboot persistence. This is a **code-only correction**; no droplet, SSH or
existing mounted data has been modified.

The new marker namespace is a dedicated private subdirectory named
`.boca-socios-cutover-receipts` under the actual `pwd.getpwuid(10001).pw_dir`
of the **host-only** account `boca-deploy`. It is **not** in the controller's
RW `/data`, nor the strict `/srv/boca-socios` Compose root (whose byte-exact
root-entry inventory would be invalidated by an extra marker). It never
moves/duplicates the canonical cooperative lock: that remains exclusively in
`/run/user/10001/boca-socios-protected-job.lock` during the same process.

Before any Docker attestation, pull or irreversible action, `run_cutover_a`
now requires a *paired* terminal-preflight callback whenever it receives a
terminal sink. **Concrete `RootlessCutoverBackend` additionally refuses any
invocation without both callbacks**, even if a future caller mistakenly omits
the sink; fully injected fake backends remain separately testable. The
preflight, under the exact held lease:

1. Verifies account name/UID, absolute private home, no path redirects or
   overlap with `/run`, `/tmp` or `/srv/boca-socios`, UID/GID10001 and 0700.
2. Uses read-only `/proc/self/mountinfo` to require a recognized **disk-backed
   filesystem** for both the home and the actual receipt child directory;
   a nested tmpfs bind over a disk-backed home or ambiguous stacked mounts
   at an **identical** path are also NO_GO. Ordinary nested disk-backed bind
   mounts at **different** parent/child paths remain valid and are tested.
   Storage space
   and inode headroom are checked before effects, not after port 8443 moves.
3. Creates the dedicated 0700 receipt directory only if absent, checks the
   complete bounded allowlist of existing immutable files, symlink/hardlink,
   file modes and owners; a foreign object is never read or deleted.
4. Writes a versioned **O_EXCL intent** containing the exact legacy ID/SHA,
   old image/Compose, target SHA/two images/three reviewed file hashes, run
   ID, fixed localhost origin and hashed owner subject. It fsyncs the file
   and directory and reads back exact bytes. Existing intent/result forbids
   reuse of the same run ID, even after a crashed process or reboot.

After the mandatory backend postflight (including selective cleanup), the
terminal sink runs before release of the *same* lease, authenticates the
original intent and writes the **O_EXCL terminal result** as a second 0600
file with fsync, directory fsync and exact inode/bytes readback. The result
binds to the intent's SHA256. The two records are retained as audit evidence,
not cleared as Docker garbage and not copied as backups. No stage/root
allowlist, controller database, owner-session SQLite, key/Telegram volume,
other service or additional port is touched.

`reconcile_persisted(plan)` can run in a **fresh read-only process after a
reboot**. It returns only `INTENT_ONLY_NO_GO` (missing result, quarantine) or
`RECORD_PRESENT_RUNTIME_UNVERIFIED` (both records intact). Neither return
value authorizes a Docker retry/deletion, physical GO or a claim that the
Chrome endpoint still works after reboot. Missing/unsafe/corrupt files raise
NO_GO. An independent live inventory and separately authorized fix-forward
operation would still be required if the original result is absent.

Adversarial fake-host QA covers a fresh second process, intent-only after a
failed sink, duplicate attempt, bad directory mode, symlinked home, foreign
file, hardlink, tmpfs home, nested tmpfs receipt mount, real backend without
paired callbacks, and refusal to call
backend when preflight is missing/invalid. These tests attest the **code
contract only**. No actual filesystem type, host home path, reboot behavior
or 8443 state on the droplet has been observed; physical Cutover A remains
NO_GO pending protected host read-only checks, separate owner GO and the
single reviewed Action dispatch.

### A45-R21: corrección del cargador Option B y unión del hook host (CODE-ONLY)

Al reconstruir el candidato integral `#319` en `129f789a62f80ea350e55f700a7d6f64ee238ce1`, la revisión encontró un defecto determinista no cubierto por los fakes: `ReviewedCutoverSources.from_verified_zip()` leía cinco archivos del ZIP autenticado (`Compose`, `overlay`, `seccomp`, helper Python Option B y SQL lateral), pero intentaba construir un registro con **cuatro** atributos pasando las cinco entradas. La primera invocación real produciría `TypeError` antes de la atestación. El test reproducible usa un ZIP real y `/proc/self/fd/<memfd>`; se ejecutó RED y luego GREEN al asignar el helper al importador independiente y el SQL al cuarto campo. No hay migración 0008 a SQLite legacy.

`execute_reviewed_cutover(plan)` concentra el futuro enlace **host-only** entre fuentes validadas contra los cuatro digests, `RootlessCutoverBackend`, `run_cutover_a()` con una sola lease, `prepare_destination()` con intención O_EXCL antes de cualquier Docker, `finalize()` selectivo después de éxito/fracaso y `write_once()` con resultado durable antes de soltar la lease. Las pruebas offline usan backend/recibos fake e incluyen rechazo antes del intento ante SQL no revisado. El hook **no está conectado** a `__main__`, al ZIP ejecutable ni al menú de GitHub Actions; no existe `cutover-a-apply`, GO remoto, operación física, modificación de contenedores ni comprobación real de Samsung. El resultado positivo de QA sintético no equivale a disponibilidad operativa.

Para la siguiente revisión de integración se requiere: decisión de invocación memfd en el workflow único y parámetros exactos sin sobres en argv; GO exact-main protegido según `scripts/check_cutover_a_go.py`, atestación física de identidades/Compose/UID/8443/volúmenes, recibo de éxito y fallos accesible aunque se pierda el runner y lectura independiente posterior de ambos marcadores. Ante ambigüedad del estado irreversible, conservar recursos y `NO_GO`; jamás un `prune` general, backup, rollback o modificación de Porota. El autor de la integración central registra el SHA/Actions finales y la prueba física, si alguna ocurre, en issue #45.

### A45-R21.3: CLI memfd host-only preparado, efecto todavía bloqueado

El ZIP reproducible incluye ahora un helper CLI explícito y el validador memfd
actualiza su allowlist exacta; ambos siguen excluyendo los módulos BLACKBOX.
El nuevo selftest `bundle-cutover-selftest` ejecuta de extremo a extremo:
runner arma ZIP → verifica digest y manifest de entradas → exec del **mismo
memfd** → importa los cinco archivos Option B/Compose y declara
`host=untouched`. Detecta, antes de cualquier operación real, fallos de
importación/empaquetado que los fakes in-process no detectaban.

La invocación futura `cutover-a-apply` recibe únicamente coordenadas públicas
opacas y digests en un JSON canónico acotado, codificado como base64url sin
padding. Rechaza duplicados, campos extra, SHA/identidades inválidos,
non-canonical JSON, bundle distinto y GO distinto. **Es deliberadamente
inerte en el `__main__` publicado**: llama al parser sin inyectarle un GO
aprobado independientemente; por tanto, aunque alguien intente invocarlo,
emite `NO_GO receipt=UNVERIFIED runtime=UNVERIFIED` y retorna código 3,
sin ejecutar el adaptador Docker/SQLite. Sólo una modificación posterior
revisada de ese entrypoint bajo el GO específico y el workflow único podría
proveer ese valor desde su preflight protegido; la mera presencia del SHA
dentro del payload NO es autorización.

El camino interno `run_cli(..., approved_go_binding_sha256=...)` se comprueba
con un ejecutor fake para demostrar enlace exacto y semántica terminal. Tras
la ejecución exigiría **igualdad byte a byte** del resultado O_EXCL en disco
con el recibo devuelto, además del intent original: un marcador antiguo
`NO_GO` nunca puede convertirse en `ACCEPTED` sólo porque exista un archivo
de resultado. El recibo de CLI reconoce expresamente `runtime=UNVERIFIED`,
incluso si el estado guardado es `ACCEPTED`; el futuro workflow necesita
atarlo a una observación física independiente y a su postflight/cleanup.
Los tests de camino real del ZIP y dispatch negativo no hacen SSH ni Docker.

**No es un GO para desplegar.** Siguen pendientes wiring del workflow,
atestación física del controlador histórico, aceptación del candidato,
volumen SQLite lateral y sesión Chrome, Telegram y lifecycle de bot/Chromium,
comprobación Samsung Chrome+Termius y limpieza host selectiva con recibos de
éxito o fallo. Los caminos ambiguos no reintentan ni borran recursos; Porota
y las otras aplicaciones permanecen fuera del alcance. Los resultados de
QA y GH Actions se documentan por SHA exacto en #320/#336.

### A45-R22: GO protegido y operación Cutover A conectada al workflow (PR DRAFT; sin ejecución)

La nueva operación manual `cutover-a-apply` tiene un **NO_GO real por defecto**.
El disparador no autoriza nada por sí solo: antes de crear la configuración SSH,
el runner requiere el valor independiente
`vars.BOCA_CUTOVER_A_GO_BINDING_SHA256` en el *GitHub Environment* protegido
`boca-first-deploy`. El contenido debe coincidir byte por byte con el SHA256
del objeto de autorización que construye `scripts/check_cutover_a_go.py` a
partir del **run ID exacto, intento 1, actor y HEAD de main, IDs originales,
dos releases distintos, tres manifests de release (controller viejo y ambos
actuales), Compose histórico recuperado desde su SHA, Compose/overlay/seccomp
revisados, ZIP completo Option B y destino localhost:8443**. El SHA de GO no
es un input de `workflow_dispatch`; vacío, incorrecto, anterior o de otro
run resulta `NO_GO` **antes de SSH**. No se recicla la autorización de la
observación read-only ni se infiere el ID original del nombre Docker.
Se verifica nuevamente el HEAD de main **inmediatamente antes del único SSH**
para evitar una ventana TOCTOU entre el primer preflight y el efecto remoto.

Tras validación, el runner escribe con O_EXCL dos archivos privados (token
canónico de coordenadas + digest de GO) y ejecuta **un solo SSH** cuyo stdin
contiene exactamente el ZIP autenticado. El bootstrap verifica el SHA y la
allowlist antes de ejecutar el mismo memfd. El entrypoint host comprueba
otra vez el digest ZIP y el GO provisto por canal separado del token; recién
entonces usa `execute_reviewed_cutover(plan)` con lease única, intento/result
O_EXCL y finalizador selectivo. No hay `docker image/system prune`, respaldos,
segundo puerto, HTTPS, rollback o acceso a Porota/otros contenedores.

El host puede imprimir aceptación únicamente tras verificar un recibo
terminal persistido, con `attempt`, `target_sha`, `cleanup=ACCEPT` y
`receipt=RECORDED`. Un paso del workflow `if: always()` exige tanto GO como
SSH con outcome positivo y **la línea exacta**, o declara `NO_GO` sin
reintentar ni limpiar a ciegas. Una caída dura del host/runner no demuestra
que el finally haya corrido; el estado queda **indeterminado, preservar e
inspeccionar sólo Boca**. Incluso con recibo positivo, `runtime=UNVERIFIED`
hasta las pruebas físicas de Chrome Samsung/Termius, bot, Telegram y sesiones.

La rama DRAFT sólo habilita el *camino revisable*; ningún workflow effectful
fue ejecutado, no hay GO independiente cargado por este cambio ni deploy al
droplet. El suite sintético comprueba GO ausente/distinto, manipulación de
actor/branch/SHA/release/ID, token canonical, reutilización O_EXCL, memfd,
líneas de recibo fallidas, pérdida de GO/SSH, límites de la operación y
regresión de las funcionalidades de navegador. El candidato #319 y el resto
de los frentes se integran sólo con QA/Actions de SHA exacto y la decisión
explícita del propietario para el **único** deploy.

## A45-R35 / PR DRAFT #384 — historical unlabeled controller image after COMMITTED (CODE_ONLY)

RCA #323 observed by source audit on 05/11/2026 ART, **not a physical
postcommit failure**: the genuine original controller's release
[Actions #41893887078](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41893887078)
was built with OCI `revision` but no `org.opencontainers.image.source`.
After the Cutover A backend removes its original exact CID, generic cleanup
either sees a now-unreferenced Boca GHCR image with unverified provenance,
returns `INDETERMINATE` after `COMMITTED`, and suppresses terminal acceptance,
or its old reference-only filter can fail to enumerate a digest-only image.
This is a deterministic **code contract hazard**, conditional on the physical
image listing; it has not been reproduced on the droplet.

The limited fix forward in DRAFT #384:

1. While the original controller is still parked and recoverable, the
   already-authenticated `_cutover_legacy_record` returns its immutable
   Docker `Image` ID. A narrowly scoped proof checks only that ID's
   `Id`, `RepoTags`, `RepoDigests`, `Config.Labels`: GH historical
   digest and revision must match exactly, and every alias must belong to
   the **controller** repository. No untrusted image's `Config.Env` is read.
2. A same-lease rootless inventory proves that controller ID still points
   to that exact image, target candidate and browser worker IDs are preserved,
   and **no other uncertain Boca residue** exists. A missing digest/label,
   changed ID, foreign alias, foreign container, ambiguous volume/network or
   unavailable inventory causes `NO_GO` before retirement, while the old
   container can still be restored.
3. After successful retirement only, the generic finalizer receives that
   singular attested old-image proof; every probe re-verifies the exact
   historical digest, source and aliases, including when the original GHCR
   reference filter misses digest-only images. Only this old image may be
   classified removable without OCI `source`. All other missing-source
   images remain `INDETERMINATE`, and every deletion still needs zero
   running/stopped container references, `docker image rm` by immutable
   ID without force, and global image-ID disappearance in the final receipt.
4. Historical precommit failure/recovery does **not** authorize old-image
   deletion. Owner/key/data/Telegram volumes, foreign workloads, BLACKBOX,
   Porota, port/HTTPS configuration, and backup remain untouched.

Offline regression selectors are recorded under `RCA-323` in
`docs/quality/rca-lessons.json`. PR #384 requires exact-SHA Actions success
and technical review before integration. No workflow or GO_B schema fields
change, but any source integration changes the reviewed memfd ZIP SHA:
**new main SHA, dual release, PREPARE receipt and independently bound GO_B
are mandatory**. This documentation does not claim any release/host operation,
Docker cleanup or Samsung runtime proof.
