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
- No `docker system prune`, `docker image prune`, `docker container prune`,
  cross-project deletion, guessed image identity, host-side backup, or broad
  filesystem purge.

See ADR0138 and [issue #323](https://github.com/mbalbo2023/boca-socios-assistant/issues/323)
for the global owner decision. This ADR describes only the isolated code
contract and open gates.
