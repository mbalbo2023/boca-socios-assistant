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

1. The protected job must retain a single non-reentrant Boca UID10001 flock
   across its install and finalizer. The cleanup module provides a Boca-only
   cooperative lock under `/run/user/10001`. Older workflows do not yet
   acquire it, so this alone does not establish global exclusivity.
2. Snapshot **all** containers (including stopped foreign/Porota containers),
   images (including duplicate tag IDs), networks and volumes on that dedicated
   rootless engine, plus filesystem free bytes/inodes, before and after. This
   identifies image/volume/network references by **other services** without
   mutating those services.
3. A stale container may be removed only when it is stopped and has exact Boca
   project, Boca name and one immutable attempt label. A temporary volume or
   network requires Boca project + matching attempt and zero known references.
   Owner/data/key/Telegram volumes are **never eligible**.
4. A stale image may be removed by **full image ID**, only if no container
   (running **or stopped**, from any project) references it and the exact Boca
   repository provenance label is present, with no foreign repository tags.
   Multi-tag image IDs are deduplicated in inventory; `docker image rm <ID>`
   without force must succeed. `docker image rm <tag>` alone is insufficient
   evidence because it may merely untag one alias.
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
   `INDETERMINATE` receipt. Known residue or observed drift is `NO_GO`;
   only a complete, exact positive postflight is `ACCEPT`. The receipt
   records outcome, attempt, resource ID list, disk/inodes and reasons, without
   environment variables, credentials, filenames containing secrets or
   unrestricted Docker output.

## Evidence / remaining deployment blocker

- Offline tests cover SUCCESS and FAILURE finalization; image cleanup after
  attempt container release; multi-tag and dangling provenance; unknown
  provenance; protected active image and persistent owner/data/key volumes;
  stopped foreign container retaining a Boca image; exact attempt mismatch;
  lost deletion receipt; unrelated container drift; flock exclusivity.
- Local QA for this exact source increment: **12 focused tests PASS**;
  full suite **2511 passed + 31 subtests passed**; Ruff lint/format (393
  files), Mypy (86 source files), repository policy and whitespace PASS.
- `synthetic.py` and `ipc_worker.py` remain BLACKBOX; no Boca login,
  reservation or purchase and no Docker host operation has been dispatched.
- **Physical NO_GO** until a reviewed, single protected finalizer actually
  runs `if: always()` after every install/update phase (including failed
  phases), authenticates its release/attempt and lease, streams the exact
  reviewed helper into the dedicated rootless SSH identity, records the
  receipt and fails acceptance on `NO_GO`/`INDETERMINATE`. Merely publishing
  this module does not satisfy the operational requirement.
- No `docker system prune`, `docker image prune`, `docker container prune`,
  cross-project deletion, guessed image identity, host-side backup, or broad
  filesystem purge.

See ADR0138 and [issue #323](https://github.com/mbalbo2023/boca-socios-assistant/issues/323)
for the global owner decision. This ADR describes only the isolated code
contract and open gates.
