# R247 Protected Current-Pair V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, with TDD and a final independent review.

**Goal:** Add runner-authenticated V2 current-pair and historical R188 receipts to Boca's one existing protected dual-upgrade workflow without creating an extra input, bypass, or host capability.

**Architecture:** The trusted runner obtains the current pair observation from the existing independently protected ZIP, discovers exactly one previous dual-image release run by the observed SHA, verifies its ZIPs and independently authenticates the R188 historical creator artifact. The host receives one eight-member exact allowlist (seven original entries plus V2), but the effectful upgrade remains independently interlocked NO_GO until reviewed same-lease proof.

**Tech Stack:** Python 3.10+, GitHub Actions YAML, GitHub REST, uv/pytest, zipfile, SHA-256, pure offline fixtures.

**Spec:** ADR0249 and issue #417 R246/R247 handoff; ADR0240 inherited three independent authorities; no user login/ticket navigation.

## Global Constraints

- Only Boca rootless project, no Docker cleanup/global commands or Porota touch.
- No 26th `workflow_dispatch` input. Derive previous release by authenticated old SHA; require exactly one qualified release. Any ambiguity, expiry or missing old artifact is NO_GO.
- Keep R188 V1 source/attempt/CIDs immutable as resource-creator history, never current pair authority.
- No GH_TOKEN in host ZIP or host. No new SSH command or protected workflow; no apply-authorized flag, no bypass of `requires_persistent_receipt=False`.
- Runner evidence private O_EXCL/0600/fsync; exact eight-entry bundle and unchanged SHA-pinned memfd bootstrap behavior.

## Review Focus

1. Zero or two candidate previous releases: test both reject without guessing a run.
2. A previous run with correct SHA but failed job or wrong manifests: test deny.
3. An R188 ZIP that is absent, expired, altered, belongs to a different actor/source or is a rerun: test deny.
4. Valid V2 with stale or missing R188 creator pins: test builder/host reject.
5. Missing/extra eighth member and an attempt to replace V2 with a forged checksum: test reject or remain NO_GO, never promote.

---

### Task 1: Runner-authenticated V2 attestation

**Files:** Create `scripts/attest_current_pair_v2.py`; Test `tests/test_r247_runner_current_pair_v2.py`.

**Interfaces:** `attest_runner(main_sha, pair_run, apply_run, target_release_run, retained_run, controller_ref, worker_ref, release_dir, github, release_catalog, now=None)` produces three files `boca-retained-observation.receipt`, `retained-proof.json` (sentinel NO_GO) and `current-pair-v2.receipt` after authenticating all sources. `runner_main` is runner-only, not in ZIP.

- [ ] Write offline fakes and tests: one authentic prior release + R188; stale/ambiguous/no artifacts and corrupted artifact; no host imports/effects.
- [ ] Run tests RED before module exists.
- [ ] Implement bounded source-based unique release discovery; replay-safe GitHub auth and O_EXCL output.
- [ ] Run tests GREEN, typecheck and format.

### Task 2: Deterministic eight-member ZIP

**Files:** Modify `scripts/build_protected_boca_bundle.py`, `scripts/boca_protected_memfd_bootstrap.py`; Test `tests/test_r247_protected_current_pair_bundle.py`.

**Interfaces:** `PAIR_UPGRADE_RELEASE_NAMES` gains only `current-pair-v2.receipt`; new member path `release/current-pair-v2.receipt`. Validate V2 canonical structure, projection consistency with current observation, target manifests and R188 raw; require historic `retained-proof.json` exactly NO_GO sentinel rather than replay old V1 as current identity.

- [ ] Tests RED for eight exact members and reject seven/nine, forged source/creator pin or absent V2.
- [ ] Add strict allowlist + bounded source/archive adjustments only if measured.
- [ ] Test standalone zip import/bootstrap, pair-upgrade remains NO_GO with invalid offline inputs.

### Task 3: Protected one-run workflow & RCA

**Files:** Modify `.github/workflows/boca-first-deploy.yml`; Test `tests/test_r247_protected_current_pair_workflow.py`; Create `docs/ADR/0251-r247-protected-v2-runner-wiring.md`.

- [ ] Tests RED for unchanged 25 inputs, exact current pair+R188+target release provenance and new runner invocation, no extra SSH/host retry.
- [ ] Replace R188 V1 pair-equality adapter with runner V2, preserve existing observation+target release authentication and one SHA-pinned host command.
- [ ] Run focused tests, repository policy, Ruff, mypy, complete suite, independent code review.
- [ ] Commit a single incremental R247 change; no push/PR/dispatch. Report exact SHA and NO_GO.
