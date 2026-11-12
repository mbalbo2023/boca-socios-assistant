# R247 Boca Failure Cleanup V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a separate durable, fail-closed, same-lease Boca FAILURE cleanup executor without enabling the successor APPLY.

**Architecture:** A new module validates the existing journal and restored topology, derives an exact candidate allowlist, then passes a wrapped deletion callback to the already-reviewed generic cleanup engine. A distinct O_EXCL/fsynced terminal V2 receipt reports the failed outcome and never authorizes installation.

**Tech Stack:** Python 3.12, stdlib, existing `host_boca_cleanup`/`host_boca_cleanup_v2`, pytest, Ruff/mypy.

**Spec:** `docs/superpowers/specs/2026-11-12-r247-failure-cleanup-v2-design.md`

## Global Constraints

- Boca-only rootless daemon and exact IDs; never global Docker prune, force delete, host mutations or Porota.
- Preserve protected SQLite/key/owner/SITE/Chrome IPC volumes and R108 image.
- `requires_persistent_receipt=False`, no CLI/workflow/host/PR/push.
- Original failure remains NO_GO even when cleanup is complete.

## Review Focus

1. Old restored binding replaced during cleanup: fail closed before additional deletions.
2. A new running candidate: refuse removal even if labels match.
3. Valid-looking but wrong attempt/release journal: reject before effects.
4. A new unknown image appears between probes: never delete it.
5. Private receipt/journal symlink or replay: refuse, retain attempt residue.

---

### Task 1: Journal and no-effect failure receipts

**Files:** Create `src/boca_socios/host_boca_upgrade_failure_cleanup_v2.py`; test `tests/test_host_boca_upgrade_failure_cleanup_v2.py`.

**Interfaces:** `execute_durable_failure_cleanup(plan: PairCoordinates, lease: BocaJobLease, *, restored: bool, receipt_dir: Path, historical_retained: HistoricalRetainedImageProof) -> DurableFailureCleanupReceipt`.

- [x] Write tests for missing/mismatched journal, unsafe directory, replay, R108 failure, and `restored=False` no deletion.
- [x] Run tests and capture RED.
- [x] Implement immutable journal verification, same-lease inventory, canonical FAILURE receipt and exclusive durable write.
- [x] Run focused GREEN tests and static checks.

### Task 2: Restored-pair conservative selective cleanup

**Files:** Same module and tests.

**Interfaces:** Derive an immutable `frozenset[cleanup.Target]` only from an authenticated restored Boca graph; wrap `cleanup.execute(..., delete_exact=...)` with fresh lease, restored-pair, allowed-ID checks.

- [x] Add tests for exact successful cleanup and every Review Focus failure.
- [x] Capture RED.
- [x] Implement conservative allowlist and same-lease before/every-delete/postflight inventory.
- [x] Run focused GREEN, full relevant suite, Ruff/mypy/policy.

### Task 3: Factual RCA and handoff

**Files:** Create `docs/ADR/0252-r247-failure-cleanup-v2.md`; update the two new design/plan files.

- [x] Record original SUCCESS-only topology flaw, candidate behavior, tests, unverified host, no workflow/GO.
- [x] Commit exact scoped branch, report SHA and test evidence to integration owner.

### Task 4: Independent P1 review — resource drift and restored graph

**Files:** Same source, tests, ADR and this design/plan; no workflow or host.

- [x] Reproduce RED: same-name attempt volume and same-ID attempt network
      swap to foreign labels between planner and `delete_exact`; old worker
      appears on the controller private network without rejection.
- [x] Freeze positive target metadata; require same-attempt labels and exact
      unchanged Volume/Network identity immediately before deletion.
- [x] Require explicit live R188 READ_ONLY custody IO for restored deletion:
      rootless identity, old role mounts/worker state, SITE/IPC inode pins,
      egress ID/creator and exact private/egress topology. No IO means NO_GO.
- [x] Add regressions for missing live IO, changed SITE inode, changed egress
      ID; check all reviewed deletions remain absent on unsafe proof.
- [x] Verify full suite (7774 PASS, 1 AF_UNIX sandbox SKIP, 34 subtests),
      Ruff check/format, mypy (188 modules) and repository policy.
- [x] Create scoped incremental commit and hand exact SHA to integration owner.
