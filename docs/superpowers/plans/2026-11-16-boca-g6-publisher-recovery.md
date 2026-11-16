# Boca G6 publisher recovery implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover one exact `unknown blob` push inside a verified Boca image-release run without another build in that run or weakening provenance.

**Architecture:** Keep the existing protected manual release job and dual manifests. Extract only the push/recovery mechanics into a focused helper invoked from the same publish step; preserve the browser-first sequencing and current parser and release output contracts. Make it exerciseable offline with fake commands.

**Tech Stack:** GitHub Actions YAML, Bash/Python helper as narrowly appropriate to existing project patterns, pytest with local fake Docker/gh; no new dependency.

**Spec:** `docs/superpowers/specs/2026-11-16-boca-g6-publisher-recovery-design.md`

## Global Constraints

- User's one-time exception and unanimous PRE_CODE contract: issue #417 comment `6925043732`, original G6 RCA `6924597514`.
- Source base exact `362ae571b3d8d53bdd43dd4d9b664f5ab2d7d0f0`; one real PR and subsequent release on new merged main only.
- No change to product, Dockerfiles, existing parsers, manifest schema, OCI source labels, permission scope, scans, smoke, main/unique guards, owner/actor/env/attempt1, host or secrets.
- Maximum **one retry globally** for browser OR controller; maximum three `docker push` invocations total; never rebuild within the release or re-dispatch failed SHA.
- An eligible error is `docker push` exit 1, exact sole terminal `unknown blob`, no digest or contradictory diagnostics. Timeout300s; delay5s; identity/main/unique rechecked before retry; no other recovery.
- Evidence stays redacted and separated by attempt; final paired manifests and artifacts only after two verified pushes; worker remains unstarted and Telegram sender OFF.
- Do not repeat the historical G2 suite; test only new/focal implementation locally and let the exact PR CI run required full gates once.

## Review Focus

1. Browser spends retry and succeeds, then controller fails `unknown blob`: STOP without fourth invocation.
2. Docker exits nonzero but output contains a digest or `tee` exits zero: never treat as successful publication.
3. Main/unique-dispatch or local immutable image identity drifts between pushes: STOP before second attempt.
4. Partial, duplicate, foreign-repository or malformed digest: existing strict parser rejects, no manifests.
5. Timeout, mixed error output or log I/O error: STOP without retry or secrets in public evidence.

---

### Task 1: Bounded paired publisher and offline regression

**Files:**
- Modify: `.github/workflows/release-image.yml` (only local image-ID evidence and publish step; leave all earlier gates intact)
- Create if necessary: `scripts/release_push_guard.py` or a single shell helper with the same narrow responsibility
- Create: `tests/test_release_push_guard.py`
- Modify only when strictly required: `tests/test_browser_image_release_workflow.py`, `tests/test_release_publish_gate.py`
- Update headers, not history: `AGENTS.md` and `docs/BETA_INTEGRATION_STATUS.md` (doc ownership coordinated with Root)

**Interfaces:**
- Consumes: exact tags, source SHA, run ID, current `parse_image_digest.py`, `check_main_ref.py`, `check_release_dispatch.py`, local image IDs and label assertions.
- Produces: verified browser/controller push logs from successful attempts and existing two digest refs; downstream manifest writer/verifier and artifact upload unchanged.

- [ ] **Step 1: Establish the focused RED contract.** Write offline cases for: initial dual success, browser eligible failure then success, controller eligible failure then success, browser consumes retry then controller fails, double `unknown blob`, auth/timeout/mixed/digest-bearing failures, missing/duplicate/foreign digest, local identity and main/unique drift, and bounded logs. Test the actual executable publish path using fake Docker/gh and run the RED cases; record expected failures.
- [ ] **Step 2: Implement the smallest production change.** Add one global recovery budget across browser/controller within the same job. Keep original builds, scans, offline Chromium smoke, label validations, GHCR login, parser/manifests and artifact gates. Separate attempts; inspect immutable IDs, recheck main+unique before eligible recovery; timeout300s, pause5s. No retry after ambiguity or second failed push.
- [ ] **Step 3: GREEN and compatibility.** Run the new focused offline tests, existing release workflow/manifest/anti-replay tests affected by the edit, syntax/style/type checks of changed modules, diff whitespace and source/branch verification. Do not repeat unrelated suites locally; record exact PASS/FAIL/SKIP evidence.
- [ ] **Step 4: Independently review.** Author self-review; Root obtains Architect, QA and Ops independent FINAL votes and gives separate Root FINAL on exact commit/tree. Address any real findings with focal RED/GREEN, then re-review exact diff. Never invent consensus.
- [ ] **Step 5: Integrate once.** Push branch and open one PR, run exact required CI/security once, obtain new 4/4 INTEGRATION approval, squash merge only under protected main rules, verify main SHA/tree and PR0.
- [ ] **Step 6: Release one new SHA after a fresh 4/4 OPERATION_RELEASE.** Dispatch `release-image.yml` once via GitHub UI/Actions, check both scans and dual manifest artifacts, verify published digests. On any ambiguity or fail STOP/RCA; no automatic further build.
- [ ] **Step 7: Physical G6.** Get separate 4/4 OPERATION per protected `boca-pair-observe`, later `boca-current-retained-resource-observe`, then one `boca-pair-upgrade-apply` with exact fresh pins; validate same-lease ACCEPTED postflight and cleanup. Never touch other apps/ports/volumes.
- [ ] **Step 8: G7 handoff.** Only after physical BETA verification, give Tincho Samsung Voice Access SIMULATION_ONLY checklist for three pages/engines/activity and record defects without declaring real provider or Telegram functionality.
