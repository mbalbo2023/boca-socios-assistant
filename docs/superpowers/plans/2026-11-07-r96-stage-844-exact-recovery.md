# R96 Boca #844 Stage Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose a single incident-pinned and auditable Boca staging recovery for #844 without changing the already reviewed host recovery code.

**Architecture:** Extend the existing `boca-first-deploy.yml` with an exact new operation, reusing its existing immutable memfd + single-SSH + postflight verification path and the original `scripts/host_cutover_stage_recovery.py`. Add independent tests for admission and rejection. Build/review/merge, then separately authorize exactly one effectful action from GitHub.

**Tech Stack:** GitHub Actions YAML, bash, Python pytest, rootless Docker Boca UID10001 (host functions already implemented).

**Spec:** `docs/superpowers/specs/2026-11-07-r96-stage-844-exact-recovery-design.md`

## Global Constraints

- Exact incident #844 `42388694186`; immutable PREPARE #843 `42381545964`; witness #845 `42388994569`.
- Original CID `27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793`, loopback8443; foreign apps never touched.
- No retry #844 or replay #843; stage-only cleanup, no Docker writes, no arbitrary IDs, no host shell beyond protected GitHub Actions.
- No modification to `synthetic.py` or `ipc_worker.py`; new operation is not evidence that BETA has been deployed.

## Review Focus

- A non-exact incident or PREPARE must fail validation before SSH (Task 1).
- A non-successful #845 witness, a successful #844, or SHA drift must fail before SSH (Task 1).
- Nonblank image/CID/envelope or an unexpected resource budget must fail before SSH (Task 1).
- A receipt absent, extra, malformed or wrong incident must never count as accepted (Task 2; existing verifier stays unchanged).
- A repeated run, new SHA or new stage residue must not be treated as permission for a second host cleanup (Task 2; unique cross-SHA dispatch and host script both enforce one-shot identity).
- Full paginated GitHub dispatch count and all open PRs must be checked BEFORE the only host connection, using a marker-filtered bounded summary, without Python `assert` disappearing under optimized execution.

---

### Task 1: Exact workflow admission for R96 #844

**Files:**
- Modify: `.github/workflows/boca-first-deploy.yml` (operation options, source/validation allowlists, new explicit incident/witness branch in existing gate)
- Test: `tests/test_r96_stage844_one_shot_workflow.py` (new test module)
- Test: `tests/test_r96_stage844_evidence_gate.py`, `tests/test_r96_stage844_dispatch_gate.py` (optimized Python and global replay)

**Interfaces:**
- Consumes: existing `BOCA_OPERATION`, `BOCA_PROTECTED_ACTION_CONTEXT`, `BOCA_INCIDENT_PREPARE_RUN_ID`, `BOCA_SOURCE_SHA`, `BOCA_BUDGET` and GitHub run metadata.
- Produces: one admitted operation `cutover-a-stage-recover-844` with exactly pinned incident/prepare/witness.

- [x] Write failing tests for operation, exact IDs, immutable source triplet, empty-input rules, PR0, cross-SHA replay, complete GitHub history and Python -O.
- [x] Observe RED (missing operation/evidence gate/dispatch module) before implementation.
- [x] Extend exact allowlist and shared recovery, retaining old stage alias and historical pins without repurposing them.
- [x] Execute 135 focused workflow/GitHub attestations locally after changes, all PASS; regression suite pending full run.
- [ ] Commit the tested admission change.

### Task 2: Reuse hardened physical recovery and assert acceptance

**Files:**
- Modify: `.github/workflows/boca-first-deploy.yml` only if Task 1 did not already include the reused recovery and finalizer conditions.
- Test: `tests/test_r96_stage844_one_shot_workflow.py`, `tests/test_host_cutover_stage_recovery.py`.

**Interfaces:**
- Consumes: preexisting `scripts/host_cutover_stage_recovery.py` and `boca_protected_memfd_bootstrap.py` `cutover-stage-recover` mode.
- Produces: verified canonical receipt, no stage or Docker mutation beyond exact-ID deletion for this one incident.

- [x] Add a failing test for exact host memfd + postflight path and `retry=NO_GO` when ACK missing; use optimized adversarial tests to reject replay/context substitution.
- [x] Observe RED prior to implementing path.
- [x] Wire new alias to the existing build/SSH/ACK path, retaining host script unchanged byte-for-byte.
- [x] Run 135 focused tests; real missing ACK verifier returns NO_GO.
- [ ] Commit the tested physical route wiring.

### Task 3: QA, merge, and separately gated physical recovery

**Files:**
- Documentation in canonical GitHub #45/#417 and project ADR as necessary.

**Interfaces:**
- Consumes: merged main SHA, PR0, successful CI and Security, real #845 read-only JSON, independent QA/Architecture/Infra review.
- Produces: one stage-recovery Action receipt and a subsequent fresh READ_ONLY inventory; not a BETA deployment claim.

- [ ] Run full repo tests, CI checks, and Security with genuine results; record exact SHA/IDs.
- [ ] Obtain 3/3 independent review, merge PR only if checks pass and ownership/PR0 policy allows.
- [ ] Dispatch **one** incident-pinned stage recovery through GitHub Actions under the previously granted user GO, after independent 3/3 and all checks; no direct droplet commands.
- [ ] Verify physical ACK and new READ_ONLY inventory; record outcome in #45/#417 with no open PRs.
- [ ] If any result is absent/ambiguous, stop all effectful actions; no automatic retry.
