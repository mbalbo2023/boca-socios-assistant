# R88 Worker Preflight Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn an ambiguous STOP cleanup into bounded, typed evidence without retrying it, and close optimized-Python and runner-capture defects.

**Architecture:** One existing host Python producer, one existing Actions runner consumer, synthetic regression tests; no new host command, image, port, service, credential or deployment path.

**Tech Stack:** Python 3.12, Bash, pytest, GitHub Actions, frozen uv.

**Spec:** [R88 design](../specs/2026-11-07-r88-worker-preflight-telemetry-design.md).

## Global Constraints

- Current base main `b4b72526d144f58d7577e49a32591ed304c1414d` and incident #417; no foreign Docker or protected BLACKBOX access.
- One exact CID STOP, zero removal on ambiguous STOP, no retries, no raw diagnostics.
- Keep PASSED receipt exact and original Cutover/GO_B admission intact; all physical effects only via protected manual GitHub Actions after distinct GO.
- Every updated source is covered by RED/GREEN tests, full quality/security gates and independent 3/3 review; Rule84 documentation and issue #45 checkpoint.

## Review Focus

1. `CalledProcessError`, `TimeoutExpired` and `OSError` wrapped by `PreflightError`: tests distinguish allowed categories without leaking raw exception fields.
2. STOP may take effect but lose ACK: test prevents any `rm` and any retry.
3. Race where worker naturally exits after `Running=true`: test still fails closed.
4. `python -O` removes `assert`: test proves boundary marker cannot be emitted on invalid runtime metadata.
5. SSH stdout symlink, huge output, failed `ulimit`, unknown parser tokens: runner tests must fail closed before any accepted receipt.

---

### Task 1: Host producer STOP evidence and boundary

**Files:** Modify `scripts/host_cutover_worker_preflight.py`; tests in `tests/test_r88_*` and historical `tests/test_r83_primary_phase.py` as needed.

**Interfaces:** Produce unchanged PASS; extended NO_GO with fixed `stop_failure_cause`; preserve operation count and stage; never include exception text.

- [ ] Write synthetic RED tests for all failure classes, ACK loss, no retries and invalid `python -O` boundary.
- [ ] Run focused pytest and verify the expected RED failure on previous behavior.
- [ ] Implement minimal allowlisted subtype inspection and explicit boundary guards.
- [ ] Run focused pytest and verify GREEN, preservation of earlier contracts.
- [ ] Commit host change in isolated architecture worktree.

### Task 2: Runner private capture and strict parser

**Files:** Modify `.github/workflows/boca-first-deploy.yml`; test `tests/test_r88_preflight_capture.py` and compatible existing receipt fixtures.

**Interfaces:** Accept only the 5-token NO_GO variant and unchanged PASS, protect stdout/stderr while SSH streams; make `always()` verifier fail closed on missing/unsafe receipt.

- [ ] Add RED offline Bash tests for oversized output, symlink/permissions and malformed categories.
- [ ] Run targeted suite and verify previous workflow fails tests as expected.
- [ ] Implement private capture/ulimit/noclobber and strict category parser based on already-reviewed R87 pattern.
- [ ] Verify targeted GREEN and preserved manual job routing and mutex.
- [ ] Commit runner change in isolated infrastructure worktree.

### Task 3: Integrate and certify one candidate

**Files:** Integrate scoped commits, `README.md`, `docs/OPERATIONS.md`, `docs/BETA_INTEGRATION_STATUS.md`, `docs/ADR/0197*`, design/plan, issue #417/#45.

- [ ] Cherry-pick exact non-overlapping commits into one isolated integration worktree; reconcile input/output fixtures.
- [ ] Run `uv sync --frozen`, complete `uv run pytest -q`, `ruff check`, `ruff format --check`, `mypy src`, policy and ZIP integrity checks.
- [ ] Obtain independent Architecture, Infra and QA approvals for the **exact tree**, record limitations and STOP RCA uncertainty.
- [ ] Open one reviewable short-lived PR, pass all exact-SHA GitHub Actions; merge and verify postmerge CI/Security and PR0.
- [ ] Decide separately on reviewed dual release and **new** preflight (not retry #819) only from new host gates/GO; accept a new physical result only with canonical receipt and unchanged legacy/foreign isolation.

**No automatic Cutover:** A STOP subtype, code GREEN or cleanup #823 never authorizes PREPARE/GO_B/APPLY by itself.
