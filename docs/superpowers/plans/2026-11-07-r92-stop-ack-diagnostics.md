# R92 STOP ACK diagnostics implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Distinguish bounded STOP stdout mismatch shapes without weakening the one-shot fail-closed cleanup.

**Architecture:** Keep the existing `stop_failure_cause` fifth receipt token and single `_cleanup_exact` transaction. Extend its fixed enum with sanitized stdout shapes, preserve the previously observed Docker `--time` CLI compatibility, and update the runner's exact NO_GO parser. Never infer STOP success from a later inspect.

**Tech Stack:** Python 3.12, pytest, Bash/GitHub Actions, frozen uv; no host or external effects.

**Spec:** `docs/ADR/0201-r92-worker-stop-ack-evidence.md`.

## Global Constraints

- Only Boca rootless UID10001, exact 64-hex CID, one `docker stop`, zero `rm` on unexpected ACK; no retry.
- No raw Docker stdout/stderr or secret/foreign IDs in receipts.
- PASS receipt byte-identical; failures remain `NO_GO/UNVERIFIED` runner claims.
- Source and archive caps, ZIP mode isolation and Cutover gate unchanged.

## Review Focus

- Empty ACK after success: categorized, never removed.
- Short expected CID, exact Boca name, wrong full CID, multiline and opaque text: each distinct bounded category, never removed.
- Proper full CID ACK: existing success cleanup still runs once; historical CLI flag unchanged.
- Shell verifier rejects any unlisted cause, lowercase/extra token/secret.
- Timeout/nonzero/OSError and primary+cleanup failures retain old categories and no raw output.

### Task 1: STOP output contract

**Files:** `tests/test_r92_stop_ack_evidence.py`, `scripts/host_cutover_worker_preflight.py`.

**Interfaces:** `_classify_stop_ack(ack: str, expected_cid: str, expected_name: str) -> str` produces only reviewed literals; `PreflightFailure.stop_failure_cause` carries the literal on `STOP`.

- [x] Add literal-output synthetic tests of `_cleanup_exact` through `execute`, including count/ordering and no `rm` on mismatch.
- [x] Run tests RED for missing shape classification (8 RED including an initially considered flag change).
- [x] Implement minimal classifier, preserving historical CLI flag and other branches.
- [x] Run tests GREEN plus R88 and R83 cleanup tests (60 PASS).

### Task 2: Runner + Rule84 continuity

**Files:** `.github/workflows/boca-first-deploy.yml`, `tests/test_r92_preflight_receipt.py`, `docs/ADR/0201-r92-worker-stop-ack-evidence.md`, `README.md`, `docs/OPERATIONS.md`, `docs/BETA_INTEGRATION_STATUS.md`, `docs/ROADMAP.md`.

**Interfaces:** unchanged NO_GO single ASCII line; fifth token receives new enum alternatives; always() verifier emits only fixed claim.

- [x] Add actual Bash parser RED tests for each new category and malicious text (5 RED).
- [x] Add exact alternatives to verifier regex; no other workflow operation change.
- [x] Run GREEN, targeted legacy tests, static lint/type/bundle caps, whole pytest suite (5161 PASS +34 subtests).
- [x] Reconcile factual CODE_ONLY documentation; commit only after verification.

**Verified output:** 12 R92 STOP synthetic PASS, 11 R92 Bash parser PASS,
162 selected legacy/new tests PASS, Ruff/format/mypy/policy GREEN.
The preflight archive remains 7 entries, 469767 source bytes / 101162 ZIP
bytes (limits 480000/128000). R92 deliberately keeps `docker stop --time 5`
because the historically observed CLI can execute it but a separate
`Client.Version` has not been attested; no new Docker operation was added.
