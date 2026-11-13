# Boca Successor APPLY and RCA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing protected Boca dual-pair successor entrypoint capable of returning authentic transaction outcomes, without relabeling post-effect uncertainty as a pre-effect rejection; document the observed deployment-version confusion.

**Architecture:** The protected memfd preflight remains read-only and rejects invalid provenance before lease acquisition. Only a typed, complete preflight can enter the existing reviewed same-lease successor engine; its receipt is emitted verbatim after canonical verification. Exceptions raised after the engine is entered produce only a bounded, noncanonical `INDETERMINATE` error line and a nonzero exit code, never a made-up `commit_started=false` receipt; GitHub Actions treats it as NO_GO and forbids automatic retry. This is a CODE_ONLY change until independent review, full exact-SHA CI/security, dual release and one authorized protected host Action.

**Tech Stack:** Python 3, pytest, GitHub Actions, Docker rootless and existing Boca-owned protected memfd ZIP.

**Spec:** `docs/ADR/0280-r259-one-held-lease-guarded-technical-backend-code-only.md`; `docs/ADR/0206-single-dispatch-cutover-v3.md`; `docs/DEVELOPMENT_POLICY.md`.

## Global Constraints

- Never repeat historical R186; no external provider traffic, reservations, or unrelated services.
- No new deployment workflow, public endpoint, image-pinning exception, privileged shell or direct server operation.
- Keep owner `SITE_URL` absent until configured, worker parked, all owner/session volumes intact.
- `TECHNICAL_ACCEPTED_OWNER_PENDING` is not passkey attestation nor BETA GO.
- Do not reveal host paths, secrets, full Docker output or session contents in runner summaries.
- Only one exact-SHA release/install after reviewed CI and protected GitHub Action readiness.

## Review Focus

- Preflight failure: no engine entry, canonical `NO_GO/ATTEST` from pre-effect path.
- Engine returns `NO_GO` with `commit_started=true`: preserve marker and CIDs in canonical receipt.
- Engine raises after effects: bounded `INDETERMINATE`, never false pre-effect canonical receipt.
- Engine returns `ACCEPTED` without durable readback: fail closed with no success claim.
- Reused, wrong-type or absent protected ZIP preflight: no host actor or lease.

---

### Task 1: Preserve exact outcome through protected CLI

**Files:**
- Modify: `src/boca_socios/host_boca_pair_upgrade_cli.py:191-465`
- Test: `tests/test_host_boca_pair_upgrade_cli.py`

**Interfaces:**
- Consumes: `_successor_preflight(...) -> BoundSuccessorPreflight` and `_execute_reviewed_successor(preflight) -> PairUpgradeReceipt`.
- Produces: `main(["apply", run, source, controller, worker, release_run, observation_run, retained_run]) -> int`, canonical verified `BOCA_PAIR_UPGRADE` receipt when engine returned, and one fixed bounded `INDETERMINATE` line if engine raised ambiguously.

- [ ] **Step 1: RED tests** for accepted engine return, postmarker `NO_GO` preservation, post-engine exception without forged `commit_started=false`, invalid preflight pre-effect rejection, historical R179 never invoked.
- [ ] **Step 2: Reproduce RED** using existing Python environment with `python -m pytest -q tests/test_host_boca_pair_upgrade_cli.py`.
- [ ] **Step 3: Implement** preflight-only exception guard, exact typed successor dispatch, independent post-entry exception boundary, canonical receipt output, and redacted fixed error; no backend/lease redesign.
- [ ] **Step 4: GREEN** using `python -m pytest -q tests/test_host_boca_pair_upgrade_cli.py tests/test_host_boca_guarded_successor_backend_v4.py tests/test_host_boca_pair_upgrade.py`.
- [ ] **Step 5: Commit** only reviewed code/tests and current ADR documentation.

### Task 2: Durable RCA and anti-repeat ownership

**Files:**
- Create: `docs/ADR/0292-r273-deployment-state-evidence-and-uncertain-cli.md`
- Modify: `README.md` (short current-state note)
- Test: `tests/test_host_boca_pair_upgrade_cli.py` (same regression as Task 1)

**Interfaces:**
- Consumes: physical Actions #43455012469, #43455761226, historical R186 #43237528968 and incident #43217075287.
- Produces: a three-state vocabulary: `INSTALLED_SHA`, `REPO_HEAD_SHA`, `BETA_OWNER_ACCEPTED` with distinct evidence and no implicit transitions.

- [ ] **Step 1: Record RCA**: confusion between existing installed pair `b61ca3` and newer `main e1b35fc`, redundant READ_ONLY confirmation, the deliberate CLI hard NO_GO and false post-effect classification danger.
- [ ] **Step 2: Document lessons**: unique physical proof per SHA/operation, no repeat R186, `Created` is expected idle worker, no claim newer installed until host binding exact SHA/manifest.
- [ ] **Step 3: Verify ADR and README** clearly say CODE_ONLY pending protected host release, and post technical acceptance owner passkey remains separate.
- [ ] **Step 4: Commit** documentation with Task 1 regression.

### Task 3: Review, protected release, physical acceptance

**Files:**
- Existing: `.github/workflows/boca-first-deploy.yml` (review only unless a deterministic failure proves an edit needed)
- Existing: `docs/quality/rca-lessons.json` (update only with real reviewed fix PR and passing regression ID)

**Interfaces:**
- Consumes: merged exact SHA from Task 1, required GitHub checks, existing protected `boca-pair-upgrade-apply`.
- Produces: host technical receipt and a separate honest owner-acceptance pending state.

- [ ] **Step 1: Independent review** source/ADR/test diffs; run relevant complete CI, strict type and policy checks on candidate exact SHA.
- [ ] **Step 2: PR** from `feature/417-r273-successor-activation`, merge only after green branch protections and zero-open-PR reconciliation.
- [ ] **Step 3: Release** one paired exact-SHA controller/worker image via existing protected workflow; no duplicate builds, no historical release reuse.
- [ ] **Step 4: Deploy** once with protected `boca-pair-upgrade-apply` only if all current-pair/release/retained/lease evidence is positive. On NO_GO stop, no automatic retry.
- [ ] **Step 5: Certify** new host binding SHA, CIDs, health 8443, worker idle, owner/session/keys, SITE_URL state, selective cleanup. A technical receipt never implies successful owner passkey Chrome acceptance.
- [ ] **Step 6: Post** exact SHA and redacted Actions outcomes to issue #417; do not mark BETA GO until owner verification.
