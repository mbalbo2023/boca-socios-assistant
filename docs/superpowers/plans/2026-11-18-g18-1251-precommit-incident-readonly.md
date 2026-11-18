# G18 #1251 precommit forensic observation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Inspect #1251 durable precommit markers via one fixed READ_ONLY Boca Action; do not retry failed G18 APPLY.

**Architecture:** Existing stage double-read → fixed variant of #1241 inert observer → private SHA-framed bytes → runner's existing canonical CLI → redacted category. History #1241 remains unchanged.

**Tech Stack:** Python stdlib, pytest, Ruff, mypy, sealed ZIP/bootstrap, protected GitHub Actions shell.

**Spec:** `docs/superpowers/specs/2026-11-18-g18-1251-precommit-incident-readonly-design.md`.

## Global Constraints

- Exact base `dbd3f1c`, CODE_ONLY isolated branch. No push/PR/Action/release/deploy/host/Porota/real tickets.
- New selector uses hardcoded attempt/source/release and five fixed names; no caller-selected paths. No legacy #1241 semantic change.
- Every edit is preceded by a witnessed failing test. Keep status finite and private bytes private.

## Review Focus

- Precommit cases distinguish absence from negative evidence; never assert exclusive root cause.
- Original #1241 historical postcommit remains byte/semantics-compatible and tested.
- Host never receives effectful pair actor/CLI; runner alone imports canonical verifier.
- Protected Action uses main/actor/environment guards, single SSH, no retry, bounded 120s, private ephemeral file and suppressed stderr.

## Task 1 — Bounded observer TDD

- [x] Add #1251 synthetic tests for zero markers, valid evidence/intent/terminal combinations, contradiction, invalid chain, owner/mode/race, framed bytes; run focused RED.
- [x] Reuse existing reader/JSON/frame abstractions with fixed #1251 profile; distinguish coherent precommit markers and canonical terminal only on runner; run GREEN and preserve #1241 tests.

## Task 2 — ZIP/bootstrap and workflow TDD

- [x] Add tests for fixed selector, memfd exact four-entry closure, source/digest caps, no effectful actor, private runner, main-only/actor/budget and no retry; run RED.
- [x] Extend existing builder/bootstrap flags and the existing single protected workflow; run GREEN.

## Task 3 — Verification and handoff

- [x] Run `ruff check`, `ruff format --check`, focused and relevant regressions, `mypy`, `git diff --check`; record exact results.
- [x] Local atomic commit; report changed paths, SHA, GREEN checks and limitations to Root for separate 4GO_FINAL. No push or PR.

## CODE_ONLY local evidence (18 November 2026)

- TDD #1251 observer: 17 new cases initially RED (entrypoints absent), then 46/46 including #1241 GREEN; one additional terminal-error classifier observed RED and then GREEN.
- TDD bundle/selector: 2 new cases RED (variant/selector missing), then 51/51 historical + new GREEN; final focused 52/52 PASS.
- Broader upgrade/builder workflow regressions: 132/132 PASS.
- Entire local pytest suite: **10461 passed, 1 skipped (AF_UNIX EPERM in sandbox), 34 subtests passed** (309.93 seconds). This is local evidence, not an Actions or physical host result.
- `ruff check .`: PASS; `ruff format --check .`: 1246 already formatted; `mypy src`: 240 files PASS; `scripts/check_repo_policy.py`: `POLICY_PASS`; `git diff --check`: PASS.
- #1251 postflight markers remain **UNOBSERVED** until an independent 4GO_FINAL permits a single protected Boca READ_ONLY Action. No inference of exclusive ATTEST cause, no G18 physical install and no BETA certification.
