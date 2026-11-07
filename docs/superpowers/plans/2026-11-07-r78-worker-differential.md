# R78 Exact Worker Differential — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Diagnose the exact failed Boca worker probe (#42329475083) without mutations, secrets, retries or unverified ownership claims.

**Architecture:** Extend the existing single protected `cutover-a-worker-inspect` operation; the host observer executes at most four tightly allowlisted rootless Docker reads. The runner validates a bounded canonical receipt and remains `READ_ONLY_NO_GO` regardless of what is found.

**Tech Stack:** Python 3.12, pytest, uv, GitHub Actions, rootless Docker CLI (isolated CI fixture only).

**Spec:** Issue #45 comment 6701580297, issue #417, `docs/ADR/0187-failed-worker-preflight-readonly-diagnosis.md`.

## Global Constraints

- Do not open, inspect or alter owner-protected `synthetic.py` or `ipc_worker.py`.
- No host mutation, no other app or Docker namespace, no credentials or raw inspect metadata in reports.
- Exactly one failed attempt ID, exact immutable browser image/source and legacy controller pins.
- Preserve four-command/12-second-per-command budget under SSH 75 seconds.
- Do not authorize cleanup or Cutover from an observer result; GitHub Actions only for physical operations.
- One temporary PR, exact-SHA full checks, merge then zero open PRs before eventual release.

## Review Focus

- Absent HEALTHCHECK: the no-health Docker template must remain parseable.
- A foreign/incorrect image digest or revision must never produce `PRESENT_PIN_MATCH`.
- Metadata at/above 65536 bytes: report a size band, not raw JSON or PII.
- One Docker read failing must not suppress the independent legacy read.
- A crafted receipt, noncanonical bytes or command mutation must fail closed.
- Docker `stdout` and `stderr` must be bounded **during** reads, in bytes,
  including progressive streams and multibyte input (QA finding, R78).

### Task 1: Observer and behavioral regression

**Files:** `scripts/host_cutover_worker_inspect.py`, `tests/test_cutover_worker_readonly_inspect.py`.

**Interfaces:** `observe(attempt, original_id, original_sha, original_image) -> dict[str, Any]` and `verify(raw, attempt, original_id) -> dict[str, Any]`; CLI `host|verify` unchanged.

- [x] Add failing tests with exact pinned fixtures covering healthless probe, strict digest, metadata size band, independent original, and four read calls.
- [x] Run focused pytest and record the expected RED due to the missing differential behavior.
- [x] Implement separate `INSPECT_NO_HEALTH` and `INSPECT_FULL_JSON_LENGTH` read-only commands (fixed allowlist); emit v3 bounded receipt.
- [x] Run focused tests GREEN, Ruff format/lint and mypy for the changed code.
- [x] Add QA-requested progressive stdout/stderr and multibyte regressions,
  verify RED before bounded-pipe implementation, then GREEN (27 focused tests).
- [ ] Test allowed commands against an isolated ephemeral Docker daemon/container in CI; never against droplet Docker directly.

### Task 2: Factual docs and full quality

**Files:** `docs/ADR/0187-failed-worker-preflight-readonly-diagnosis.md`, affected status docs only where evidence changes.

- [x] Document query limit, exact coordinates, classifications, limitations and distinct physical versus observer RCA.
- [x] Run `uv sync --frozen`, `uv lock --check`, full pytest, Ruff, MyPy and repo policy/RCA selectors.
- [x] Inspect changed paths; neither owner blackbox is in the diff, and the only
  Docker create/rm fixture is explicitly limited to the disposable CI runner.
- [x] Obtain independent QA, Architecture and Infra technical review; rectify
  the QA Important (unbounded subprocess capture), then all three CODE_ONLY GO
  on the corrected local tree. This does not grant physical GO.

### Task 3: GitHub integration and physical observation

- [ ] Push one reviewed feature branch and open one transient PR for #417, with base/head/tree, QA and limitations.
- [ ] Require all exact-SHA checks GREEN, documented technical consensus and protected main merge.
- [ ] Recheck main, CI/security, zero open PRs and any concurrent owners.
- [ ] Dispatch one protected `cutover-a-worker-inspect` READ_ONLY with exact #795/legacy pins, service controller and resource budget, via GitHub Actions.
- [ ] Inspect sanitized receipt. Never infer physical Cutover success; only design Boca-only cleanup after positive ownership evidence and separate review.
- [ ] Record all observed facts and remaining steps in #417 and #45 (Rule 84).
