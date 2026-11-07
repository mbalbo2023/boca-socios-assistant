# R86 Exact Worker #819 READ_ONLY Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or subagent-driven-development. Follow tasks with tests first and independently reviewed final candidate.

**Goal:** Obtain a trusted, no-effects inventory of the temporary #819 Boca worker and installed legacy controller after ambiguous STOP cleanup.

**Architecture:** Reuse the existing protected workflow and `host_cutover_worker_inspect.py` with a third immutable attempt mapping; no new observer service, no Docker writes or new GO. The same receipt schema and parser are retained, and the existing recovery implementation is never extended to #819.

**Tech Stack:** Python 3.12, GitHub Actions YAML, pytest, Ruff, MyPy, package checksum tests.

**Spec:** `docs/superpowers/specs/2026-11-07-r86-worker-819-readonly-design.md`.

## Global Constraints

- Source SHA, run ID, paired browser digest and original CID/source/digest are fixed exactly in the spec; reject arbitrary targets.
- Manual protected Actions only; host rootless Boca UID10001 and Docker metadata reads. No stop/start/rm/pull/exec, no real Boca/Queue-it/Telegram, no foreign workloads.
- No re-dispatch of preflight #819 and no PREPARE, GO_B, APPLY or physical cleanup.
- Preserve historical #795/#807 observer and recovery scopes; keep receipt version v3 and all response limits.
- User has already granted ongoing autonomous scope for read-only diagnosis; security/ownership gates remain mandatory.

## Review Focus

1. Wrong #819 source/browser digest must fail closed and never resolve a probe as owned.
2. A present `RUNNING` or `STOPPED` probe must remain observable without becoming removal authority.
3. `ABSENT` worker with unhealthy/unverified legacy must remain physical NO_GO.
4. The historical #795/#807 inspector and their recovery allowlist must not acquire new effectful targets.
5. SSH/inspect failure or large output must produce bounded `INDETERMINATE`, without retrying or printing secrets.

### Task 1: Regression tests, red first

**Files:** Create `tests/test_r86_exact_worker_819_observer.py`.

**Interfaces:** Consume existing `host_cutover_worker_inspect.observe(attempt, original_id, original_sha, original_image)` and `.verify(raw, attempt, original_id)`; produce no new API.

- [x] Write tests for exact #819 pins, observed running/stopped/absent, foreign/mismatch, seccomp/legacy, old-attempt preservation and workflow `protected_action_context` gate.
- [x] Run `uv run pytest -q tests/test_r86_exact_worker_819_observer.py`; verified 7 expected RED before implementation.

### Task 2: Minimal immutable observer extension

**Files:** Modify `scripts/host_cutover_worker_inspect.py` and `.github/workflows/boca-first-deploy.yml`; no recovery target changes.

**Interfaces:** Extend only the immutable `KNOWN_FAILED_PROBES` mapping and exact workflow case; retain v3 receipt. Add static run-name for the #819 inspector if useful for audit.

- [x] Add pinned attempt/source/browser mapping for #819.
- [x] Allow exactly #819 in the existing workflow `cutover-a-worker-inspect` case; preserve legacy pins, zero source/image inputs, one SSH bounded inspector and `READ_ONLY_NO_GO` summary.
- [x] Run new and historical suites GREEN; recovery ZIP verified 7-entry/40.692 B, new digest documented ADR0195, unchanged recovery targets.

### Task 3: Rule84 documentation and full QA

**Files:** Create `docs/ADR/0195-r86-worker-819-readonly.md`; update top-level `README.md`, `docs/OPERATIONS.md`, `docs/BETA_INTEGRATION_STATUS.md`, relevant RCA ledger only if a confirmed code defect exists.

- [x] Document #819 failure, diagnosis rationale, CODE_ONLY boundary and next physical interpretation; mark prior R85 top block historical rather than current.
- [x] Run Ruff lint/format, MyPy, pytest full, policy gate and focused bundle/host contracts; results recorded in ADR0195; final post-test-refinement full run verifying.
- [x] Independent QA/Infra/Architecture and additional code review completed CODE_ONLY GO, 0 Critical/Important; one atomic candidate commit after final test.

### Task 4: GitHub integration and observation

**Files:** GitHub PR under issue #417 and checkpoint #45, no extra source target.

- [ ] Push one branch/atomic commit, open one PR, verify four named checks on its exact SHA, and merge only after technical review.
- [ ] Verify postmerge `main` CI/security, PR0 and protected workflow inputs; do not infer a new server image installation from code merge.
- [ ] Dispatch only `cutover-a-worker-inspect` for exact #819 in the protected workflow, once, via authenticated GitHub; read typed receipt and issue #45/#417 notes.
- [ ] Preserve physical NO_GO if probe/legacy/cleanup remains ambiguous. Any recovery or new preflight requires a separate reviewed narrow design; no automatic retry.
