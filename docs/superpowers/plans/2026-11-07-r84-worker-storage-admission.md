# R84 Worker Storage Admission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and TDD. Steps use checkbox tracking.

**Goal:** Restore the already-approved ADR0183/R50 disk and inode gate in the Cutover worker preflight, and prevent a second physical dispatch for the same SHA without touching other workloads.

**Architecture:** The sole preflight runner delegates its pair of GHCR pulls to the existing `host_first_deploy._browser_pull_both`. That helper already enforces pre-4GiB and post-1GiB floors, validates the same rootless storage identity and both image revisions, and executes exactly two bounded pulls. A GitHub-only REST check identifies exactly one preflight dispatch for the current SHA before SSH. Cutover full/recovery package content stays unchanged.

**Tech Stack:** Python 3.12, pytest, uv, GitHub Actions; no host interaction during implementation.

**Spec:** [ADR0193](../../ADR/0193-r84-worker-storage-admission.md) and [ADR0183](../../ADR/0183-postpull-boca-beta-emergency-residual.md).

## Global Constraints

- Branch from `main=f709508c64c821a5452224fb4ce7bc23d5c909a7`; one scope/writer, one PR, exact checks and no physical host effects.
- No edits/reads of owner BLACKBOX, `src/boca_socios/host_first_deploy.py`, GO_B, or unrelated Docker/workflows. Only the existing protected workflow may receive an extra pre-SSH gate.
- Preserve two pulls, 120-second timeout, same SHA/digest validation, original controller, lease, rootless boundary and bounded cleanup.
- `#807` primary cause remains unknown; code-only approval cannot attest physical readiness.

## Review Focus

1. Pre-pull stage/Docker free bytes 4GiB−1 → zero pulls (Task 1).
2. Pre-pull stage/Docker inode count 49,999 → zero pulls (Task 1).
3. Post-controller 1GiB−1 or 49,999 inodes → block browser pull (Task 1).
4. Post-browser low capacity or storage identity drift → NO_GO with `primary_failed_phase=GHCR_PULL` (Task 1).
5. Exact boundary valid, no new Docker side effects, Cutover/recovery ZIP unchanged (Task 2).
6. Second same-SHA dispatch, truncation, different actor/repo/ref or open PR → NO_GO without SSH (Task 2).

### Task 1: Single storage admission policy

**Files:** `tests/test_r84_worker_storage_admission.py` (new), `scripts/host_cutover_worker_preflight.py` (modify).

**Interfaces:** `probe.execute(pins: Coordinates, profile: bytes)` calls `host._browser_pull_both(pins.controller, pins.browser, pins.source)` once under existing Boca lease. No new public API.

- [x] Add synthetic tests with `host.StorageSnapshot` values from existing fixtures; inject deterministic `_run` and exact cleanup, without network or host Docker.
- [x] Run focused pytest and observe RED under the old `require_capacity=False` implementation (10 fails as expected).
- [x] Remove duplicate `_pull_observing_capacity`, delegate to `_browser_pull_both` during `GHCR_PULL`.
- [x] Run focused pytest and observe GREEN; check negative phases, cleaning and no unexpected Docker calls.

### Task 2: One-first-dispatch protected gate

**Files:** `tests/test_r84_worker_preflight_dispatch.py` (new), `scripts/check_worker_preflight_dispatch.py` (new), `.github/workflows/boca-first-deploy.yml` (modify).

**Interfaces:** checker consumes two GitHub REST JSON files, exact `GITHUB_SHA` and `GITHUB_RUN_ID` on the runner. It must not call a host, Docker or GH directly. Title marker is source-SHA scoped, not a global irreversible block.

- [x] Add tests for unique first dispatch, two same-SHA runs, incomplete/paginated data, non-first attempts, corrupt files, open PR, foreign source/repo/actor and future FIX-FORWARD SHA.
- [x] Observe RED without the checker/marker; implement bounded, fail-closed parser reusing `check_release_dispatch.load_history`.
- [x] Add one operation-specific step before the worker SSH step; keep PR validation source-only and add both R84 suites to the protected source test matrix.
- [x] Run focused GREEN and inspect YAML semantics so no other operation becomes blocked by the new condition, including 3 fake-gh Bash E2E scenarios.

### Task 3: Quality evidence, documentation and packaging

**Files:** `docs/ADR/0193-r84-worker-storage-admission.md`, this plan; issue #417/#45 comments; RCA lesson with actual PR number required by policy.

- [x] Run full `uv run --frozen pytest -q -p no:cacheprovider`: **4823 PASS +34 subtests**; Ruff, format, MyPy 137, repo isolation/policy and YAML PASS.
- [x] Compare deterministic full and recovery ZIP hashes to R83; verify changed preflight ZIP under 480k/128k (ADR0193 lists exact digests).
- [x] Independent QA, Architecture, Infra and CI review, Critical/Important=0 before merge.
- [ ] Record exact source SHA, changed paths, tests and limitations; create one PR, 4/4 GitHub Actions, merge and verify zero open PRs; await fresh release under its new SHA.
