# R244 Concurrent CI Builds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Launch both exact runner-local CI image builds concurrently without weakening the required image gate.

**Architecture:** Replace two sequential Docker build steps in `CI / image-build` with one Bash step that starts two commands in separate background processes, writes separate logs, waits for both and fails if either failed. Preserve every post-build check, image alias, source label and CI context.

**Tech Stack:** GitHub Actions YAML, Bash, Docker CLI, Python pytest disposable command fixture.

**Spec:** `docs/superpowers/specs/2026-11-12-r244-concurrent-ci-builds-design.md`

## Global Constraints

- Only `.github/workflows/ci.yml` and new R244 performance tests/docs change.
- No change to release, image-security, first-deploy or protected host workflows.
- Exactly two builds, same digest-pinned Dockerfiles, tags, labels, Trivy scans, jobs and contexts.
- No new persistent cache, runner/job, artifact, GHCR push or skipped full-suite check.
- CODE_ONLY until GitHub-hosted comparative timing confirms improvement.

## Review Focus

- First child fails before the second finishes: both must be reaped and logs retained.
- Second child fails: a successful first build cannot greenwash image-build.
- Both children fail: status remains red with both logs.
- Source/tags/labels must match role and exact SHA despite concurrent execution.
- Scans and Docker probes must never run after either build fails.

---

### Task 1: Concurrent Docker build gate

**Files:**
- Create: `tests/test_ci_concurrent_image_builds.py`
- Modify: `.github/workflows/ci.yml` (image job's adjacent build steps only)

**Interfaces:**
- Consumes: `SOURCE_SHA`, `GITHUB_SHA`, `RUNNER_TEMP`, `GITHUB_STEP_SUMMARY`, local Docker daemon.
- Produces: original local tags, aliases and existing exact labels; a red/green step result and wall-time receipts.

- [x] **Step 1: Add fixture-driven tests** that execute the extracted Bash body through a `docker` fixture with a two-build rendezvous, assert exact role/alias/revision arguments, enforce both waits and failure matrix (controller, browser, both), and confirm scanning remains later.
- [x] **Step 2: Run** `uv run pytest -q tests/test_ci_concurrent_image_builds.py` and observe RED because the combined build step does not exist (5 expected failures).
- [x] **Step 3: Replace the two sequential build steps** with one Bash step: run both exact Docker builds concurrently with independent logs; wait both and propagate nonzero; emit source-SHA and elapsed-time receipts; do not change following steps.
- [x] **Step 4: Run** `uv run pytest -q tests/test_ci_concurrent_image_builds.py tests/test_ci_single_image_pair.py tests/test_browser_image_packaging.py` and expect PASS (33 passed). Three legacy step-name expectations were also updated after a RED full-suite run, with the coordinator's narrow ownership approval.
- [x] **Step 5: Run** `bash -n` on the extracted shell, `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src`, repository-policy checker and full pytest suite. Final result: 7345 passed, 34 subtests passed, one AF_UNIX EPERM sandbox skip (not a GitHub-runner success claim).
- [x] **Step 6: Inspect diff**, document CODE_ONLY and baseline/benchmark gates in ADR0246, and commit only task-owned files. No hosted Docker or Actions benchmark was dispatched.
