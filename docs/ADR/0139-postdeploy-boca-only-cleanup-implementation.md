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

## Handoff: transaction core remains INCOMPLETE and physical NO_GO

`run_transaction()` code-only now holds one `protected_boca_job_lease`
through pre-effect O_EXCL intent, offline injected install/observe, exact
controller stop on FAILURE, immutable result and unconditional `try/finally`
call to `finalize_attempt()` whenever a verifiable result exists. Missing or
ambiguous host result is NO_GO without guessed deletion. Its **concrete
trusted host backend**, actual protected stage/apply, hosted receipt assertion
`if:always()` and effectful ZIP entrypoint **DO NOT EXIST**. Bundle execution
outside selftest still returns `NO_GO transaction_not_wired`. Offline fake
backend tests are not proof of any physical install/cleanup.

Owner-approved cutover **Option B** (04-Nov ART): Chrome owner session uses
separate `boca_owner_session.sqlite3` under existing Boca data volume with
UID10001, exact attempt identity and canonical Boca lease. DO NOT migrate
legacy `boca.sqlite3` to schema0008: legacy cabce9f1 rejects that ledger and
cannot restart after failed cutover. Auth agent #321 owns separate-DB proof;
orchestration here must not assume this contract until the evidence lands.

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
