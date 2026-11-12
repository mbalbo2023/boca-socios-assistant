# Boca R244 Durable Cleanup V2 Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkboxes for the TDD cycle.

**Goal:** Bind the existing Boca-only same-lease cleanup inventory and canonical V2 receipt to one durable, replay-resistant terminal record.

**Architecture:** One new wrapper module calls the existing `execute_protected_with_inventories` exactly once under the pre-existing Boca job lease. It reserves a fixed-name O_EXCL intent in a private attempt directory before any deletion, verifies the exact active pair/R108/protected volumes against the same-execution before/after inventories, serializes and independently verifies V2, and writes/re-reads an O_EXCL/fsync receipt. This is a CODE_ONLY adapter, not a second cleanup engine or an enabled deploy path.

**Tech Stack:** Python 3.10-compatible host code, `host_boca_cleanup`, `host_boca_cleanup_v2`, pytest, Ruff, mypy.

**Spec:** `docs/ADR/0244-pair-upgrade-release-wiring-ineligible.md` and `docs/ADR/0209-r108-attested-historical-quarantine.md`.

## Global Constraints

- No Docker commands, network calls, host mutation or Actions dispatch in this development session.
- Preserve R108 `sha256:a44453ab30cb17fa42f71723cf64b1097dabdf0e56369186077c47bc8224f90b` only with exact historical proof.
- Preserve data/key/owner/IPC/SITE volumes and the active controller/worker pair.
- NO_GO/INDETERMINATE if the inventory, lease, path, digest or final receipt cannot be proved; do not retry cleanup.
- Keep `ReusablePairUpgradeBackend.requires_persistent_receipt=False`; no CLI or protected workflow wiring.

## Review Focus

1. Duplicate O_EXCL intent must prevent a second cleanup execution.
2. Missing R108 proof, worker/active image drift and lost protected volume must fail closed.
3. Invalid or swapped receipt directory must abort before cleanup.
4. Failed cleanup, V2 mismatch or write/fsync/readback failure must leave an intent but no accepted receipt.
5. Exact V2 receipt and both disk/inode counts must be verifiable independently after write.

---

### Task 1: One-shot private intent

**Files:** Create `src/boca_socios/host_boca_upgrade_cleanup_runtime.py` and `tests/test_host_boca_upgrade_cleanup_runtime.py`.

**Interface:** `execute_durable_final_cleanup(plan, lease, *, controller_id, worker_id, controller_image_id, worker_image_id, receipt_dir, historical_retained)` returns `DurableFinalCleanupReceipt` or raises `FinalCleanupNoGo`.

- [ ] Write and run the failing test for invalid lease / unsafe directory / duplicate intent preventing the underlying engine call.
- [ ] Implement strict pins, private directory fd, O_NOFOLLOW/O_EXCL pre-effect intent with fsync.
- [ ] Run targeted tests green.

### Task 2: Same-execution V2 inventory and preservation

- [ ] Write and run failing success/negative tests using an injected test fixture in place of the existing cleanup engine.
- [ ] Call `execute_protected_with_inventories` only once, with exact protected IDs, immutable R108 proof and empty retire list. Require both physical inventories, five protected owner volumes, exact pair and V2 canonical+independent parse.
- [ ] Run targeted tests green.

### Task 3: Durable terminal and independent readback

- [ ] Write and run failing tests for O_EXCL receipt, altered readback and rejected `INDETERMINATE`.
- [ ] Write 0600 canonical receipt with O_EXCL, fsync file and directory; reopen O_NOFOLLOW, compare bytes and V2 parser, revalidate lease.
- [ ] Run all targeted tests, full repo pytest, Ruff/format, mypy and repository policy.
- [ ] Commit scoped files and report SHA, positive evidence and remaining physical wiring blockers to integration owner.
