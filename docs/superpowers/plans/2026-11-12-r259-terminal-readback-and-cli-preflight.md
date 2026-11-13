# R259 Successor Terminal Readback and Preflight Classification Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement the two independent TDD tasks below. Steps use checkbox syntax to track executable evidence.

**Goal:** Reject a corrupted successor journal terminal before returning from the same lease, and classify a failed pre-lease CLI preflight truthfully without pretending the commit marker ran.

**Architecture:** Reuse the existing O_EXCL/fsync writer and no-follow SHA/inode reader in `host_cutover_stage`; do not create another journal or deployment entrypoint. The existing `apply` CLI must remain hard NO_GO before lease/effects, with the historical R186 actor unreachable.

**Tech stack:** Python 3.12, pytest, Ruff, mypy, existing immutable Boca stage helpers.

**Spec:** #417 A45-R257 and owner-approved R258 continuation; `docs/ADR/0273-r255-inert-single-lease-actor-plumbing.md`.

## Global constraints

- No production host shell, Docker or Actions mutation; no replay R186; no Porota or foreign workload.
- No real Boca navigation, queue bypass, TLS relaxation or actual ticket reservation.
- Keep `requires_persistent_receipt=False` and CLI APPLY exit 3; CODE_ONLY, DEPLOY NO_GO.
- Protected bundle uncompressed cap 1,400,000 bytes; measure exact combined tree after code.

## Review focus

- Terminal bytes altered after fsync: fail closed and retain quarantine residue.
- Terminal inode/mode swapped after write: strict no-follow readback must refuse.
- Factory `KeyboardInterrupt` under the held lease: persist a genuine NO_GO terminal, never ACCEPT.
- Unexpected pre-lease verifier exception: classify `ATTEST`, `commit_started=False`.
- R186 historical engine remains unreachable and no lease or Docker is acquired by CLI.

### Task 1: Same-lease terminal readback

**Files:** `src/boca_socios/host_boca_repeatable_journal.py`, `tests/test_host_boca_repeatable_journal.py`.

**Interfaces:** Override `SuccessorPairJournal.terminal(plan, receipt, lease) -> None`, preserving inherited exclusive write and adding same-lease reread of canonical bytes under stage root.

- [x] Write failing test: real journal intent + factory exception + terminal writer corrupted after fsync must raise, while exact terminal residue remains.
- [x] Run focal pytest and see the expected missing-readback failure.
- [x] Add minimal exact-byte/hash no-follow terminal readback; convert any ambiguity to fixed-category NO_GO.
- [x] Run focal tests and existing journal/transaction regressions; ensure raw PASS only on unaltered receipt.

### Task 2: Accurate pre-lease failure receipt

**Files:** `src/boca_socios/host_boca_pair_upgrade_cli.py`, `tests/test_host_boca_pair_upgrade_cli.py`.

**Interfaces:** Preserve `main(["apply", ...]) -> 3` on preflight exceptions; produce canonical `NO_GO/INDETERMINATE`, `failed_phase=ATTEST`, `commit_started=False` because the lease and marker are not reached.

- [x] Write failing test: inject unexpected preflight exception and assert no lease/actor, canonical pre-effect receipt.
- [x] Run focal pytest and observe prior false `COMMIT_MARKER` classification.
- [x] Implement minimal classification without altering terminal parsing or postmarker engine uncertainty.
- [x] Run focal tests and full repository suite, Ruff/mypy/policy/bundle measurement.

## Completion

- [x] Review source diff, report exact local SHA, all checks and non-release limitations to the integration owner; no remote PR or host dispatch from this isolated branch.
