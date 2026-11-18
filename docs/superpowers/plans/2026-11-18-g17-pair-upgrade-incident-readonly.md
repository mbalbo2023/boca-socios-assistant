# G17 #1241 forensic observation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Determine whether the historical G17 APPLY #1241 persisted a canonical durable terminal, without repeating the deployment or changing the host.

**Architecture:** Fixed-path Boca-rootless host reader → SHA-authenticated memfd and private SSH pipe → exclusive runner tempfile → canonical runner-side terminal verifier → redacted enum only. Transport choice Option D was unanimously approved in issue #417 follow-up; CLI and effectful host modules remain untouched.

**Tech Stack:** Python stdlib, existing Boca cutover stage helpers, pytest, bounded ZIP + bootstrap, protected GitHub Actions Bash.

**Spec:** `docs/superpowers/specs/2026-11-18-g17-pair-upgrade-incident-readonly-design.md`.

## Global Constraints

- CODE_ONLY worktree from `7f20bf0`; no push/PR/Actions/deploy without 4GO_FINAL. Root owns publication and historical receipt correlation. No Porota, UI, motors or Telegram edits.
- Host target path/attempt/G16/G17/release are constants; no caller-provided coordinates. No lease/Docker/systemd/SQLite/network mutations or sensitive stdout.
- TDD RED must be captured before product code; tests are synthetic, never host-connected.

## Review Focus

- Private bytes cannot escape command logs, step summary, GitHub artifact, stderr, or exceptions. Host stdout is a bounded private frame to exclusive temporary file only.
- Snapshot race, double-read inode/hash, canonical JSON, SHA chain, technical/CID match, and failure-state truthfulness.
- Workflow selector is single-purpose, main-bound, owner-only, timeout 120 seconds, no retry; bootstrap has tiny exact allowlist.

### Task 1: Pin tests for immutable five-marker reader (RED → GREEN)

- [ ] Write synthetic fixtures in `tests/test_host_boca_pair_upgrade_incident_readonly.py` for exact source/release/attempt; canonical ACCEPTED + NO_GO, absent/partial/invalid terminal, symlinks, hardlinks, wrong owner/mode, truncated files, concurrent inode replacement, mismatched source/commit/technical and two-snapshot drift. Prove no filesystem writes or untrusted error text.
- [ ] Run focal pytest and retain an observed RED, then implement `src/boca_socios/host_boca_pair_upgrade_incident_readonly.py` only, using stage read helpers and strict finite categories.
- [ ] Run GREEN focal; inspect source for forbidden effects and ensure `__main__` emits only a bounded private frame.

### Task 2: Canonical runner verification and frame security (RED → GREEN)

- [ ] Extend focal tests: round-trip private frame, exact metadata schema/length/SHA, terminal tampering/overrun/trailing bytes, no raw terminal in public summary, canonical CLI rejects forged receipt, missing → UNKNOWN.
- [ ] Runner verification function receives private frame bytes, calls unchanged existing CLI `verify_upgrade` and matches terminal CIDs to attested markers; output finite redacted enum and digest only. Test both `ACCEPTED` and legitimate `NO_GO`.
- [ ] Run focal pytest, Ruff, mypy for new module.

### Task 3: Isolated memfd variant (RED → GREEN)

- [ ] Write tests for builder/bootstrap exact tiny source closure and ZIP mode, entry bounds, no effectful host actors or unrelated modules, SHA mismatch rejection.
- [ ] Add one explicit `--pair-upgrade-incident-observe-1241` builder mode and bootstrap entry set; preserve existing modes; test standalone isolated archive.

### Task 4: Protected workflow selector (RED → GREEN)

- [ ] Tests require exactly one dispatch option, one main-only step, existing Boca SSH and SHA-current-main checks, owner guard, no input coordinates, no retry, timeout ≤120s, no log/artifact of private bytes, tempfile 0600 with always-cleanup trap.
- [ ] Add scoped conditional and runner script to existing workflow, retaining all other operation contracts. Host reads exclusively through Boca Actions; no direct execution now.
- [ ] Run workflow focused tests plus ZIP test, `ruff`, `mypy`, `git diff --check` and relevant existing regressions. No CI/build/Action dispatch.

### Task 5: Local handoff and review gate

- [ ] Commit exact branch locally with redacted test evidence, commit SHA and diff summary. Request Root + independent Architecture/QA/Ops reviews and 4GO_FINAL before a single PR/CI or host read-only Action. Report any unverified #1242–#1244 CID correlation as explicit PENDING, not assumed.
