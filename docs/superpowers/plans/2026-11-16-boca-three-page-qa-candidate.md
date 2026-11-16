# Boca QA Three-Page Candidate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrar en una sola candidatura la corrección P1, el observador G3b A1c y tres pantallas privadas claras para la QA de Tincho.

**Architecture:** Reusar en W los renderers/endpoints de motores y actividad existentes, conservar los POST y controles de privacidad, reorganizar HTML y JS sin introducir backend nuevo. Recuperar dos patches históricos con identidad exacta antes del delta UX.

**Tech Stack:** Python 3.12, HTML/CSS/JS vanilla con CSP hash, pytest, Ruff, mypy, GitHub Actions Boca.

**Spec:** `docs/superpowers/specs/2026-11-16-boca-three-page-qa-design.md`

## Global Constraints

- SOURCE W `55da98df6713d40ebf1455fb328005544043d091`; single candidate branch, 0 extra PR/builds.
- P1 frozen diff SHA256 `f0607e6dcd2a37b4c5e024df1dfaf2e84f0e7a9f481ff40efd1b1047bc1613b6`, 2 files; G3b frozen diff SHA256 `39e2a100d12f0000a61ceb26c1a71f5cdde5f802ecb61b922b8480473a487300`, 7 files. Verify original hash before alteration; never hand-reinvent.
- Three primary routes Control/Actividad/Configuración; `/monitor/tokens` owner `simulation:write` -> Actividad, status-read-only legacy monitor intact; no ACL broadening.
- Preserve POST engine start/stop exact semantics, session permissions, anti-replay, CSRF/Origin, passkey, static CSP, per-session private reveal and one physical worker.
- No changes to backend, BLACKBOX, runtime/worker, Dockerfiles, secrets, DB, capacity, Telegram custodia/sender, host or other apps. No host Actions until new 4GO_OPERATION later.
- Tests focal RED/GREEN for new UX only, don't rerun historical P1 88 or G3b 49 unchanged selections just to inflate counts. CI/security once on exact integrated SHA after 4GO_FINAL/INTEGRATION.

## Review Focus

1. A user with only `local-status:read` opens `/monitor/tokens` and still gets the authorized legacy monitor; no 403 or permission escalation — Task 2 route test.
2. The member `<select required>` for engine B must remain visible/focusable even when browser count options are collapsed — Task 3 rendering test.
3. Snapshot polling failure must not display stale engine RUNNING/zero sessions as current verified state — Task 3 JS/HTML test.
4. An ACK failure does not cause UI to claim NO_EVENT, absent queue, no tokens or actual SITE_URL visit — Task 3 provenance test.
5. CSP hashes and one-use token reveal work after splitting UI into 2 pages — Task 3 security/view test.

---

### Task 1: Recover exact approved P1 + G3b patches (no rewriting)

**Files:** P1 `src/boca_socios/panel/private_http.py` and its historical focal test; G3b frozen seven files: `src/boca_socios/host_boca_public_recipient_metadata.py`, `scripts/build_protected_boca_bundle.py`, `scripts/boca_protected_memfd_bootstrap.py`, `.github/workflows/boca-first-deploy.yml`, `tests/test_host_boca_public_recipient_metadata.py`, `tests/test_public_recipient_metadata_transport.py`, `tests/test_public_recipient_metadata_bundle.py`.

**Interfaces:** Consumes exact GitHub issue #417 comments P1 `6909265626`, G3b `6910203363`, `6910205896`, `6910208321`. Produces frozen applied code and checksum/evidence; no novel design.

- [ ] **Step 1:** Retrieve full original fenced unified diffs from canonical comments. Reassemble G3b all 3 parts; verify exact original SHA256 fingerprints **before application** and compatibility with base W; reject any incomplete/truncated part.
- [ ] **Step 2:** Apply the original patches unmodified to this candidate, verify `git diff` equality with originals and exact file allowlists. If any hash mismatches, STOP and document discrepancy; do not reconstruct by guess.
- [ ] **Step 3:** Confirm P1 route no longer early-returns to Control; G3b remains metadata-only `engine=UNVERIFIED`, no added host effects. Record hashes and historical 88/88 and 49/49 from issue without rerunning them as new evidence.
- [ ] **Step 4:** Commit frozen originals as one baseline candidate commit only after verification; note no new CI/build.

### Task 2: Simplify navigation and preserve reader ACL

**Files:** Modify `src/boca_socios/panel/private_http.py`, `src/boca_socios/panel/private_ui.py`; test/modify `tests/test_private_engine_controls.py` and targeted navigation/privacy tests only.

**Interfaces:** Consumes existing `PrivatePanelApplication._engine_page`, `_token_monitor_page`, `private_ui._page`; produces `/control` unchanged route, `GET /control/actividad` real activity, `/monitor/tokens` role-safe Activity alias, 3 main nav links plus secondary links.

- [ ] **Step 1 RED:** Write specific route/permission tests for `/`, `/control`, `/control/actividad`, `/monitor/tokens` owner and read-only session, no new operations/no GET mutation; nav has 3 primary targets and secondary links. Run only these cases, ensure failure is expected route/markup.
- [ ] **Step 2 GREEN:** Make minimal handler/nav changes. For owner `/monitor/tokens`, use an authenticated redirect to activity but preserve `local-status:read` legacy monitor and all JSON/reveal routes. Keep `/ingresar` passkey content/no unauthenticated nav leakage.
- [ ] **Step 3:** Run focal route/permission tests to green; inspect CSP and target handlers; commit this independent change.

### Task 3: Split Control from real-time activity (existing endpoints only)

**Files:** Modify `src/boca_socios/panel/engine_view.py`, `src/boca_socios/panel/private_ui.py`, `src/boca_socios/panel/private_http.py`; test/modify `tests/test_engine_view.py`, `tests/test_worker_live_activity.py` and only directly affected engine/session security tests.

**Interfaces:** Consumes `engine_view.page`, `private_ui.worker_activity`, `/control/motores.json`, `/control/actividad.json`, `_request_engine`. Produces Control with two logical-engine cards/START/STOP/reasons and Activity with engine read-only status, sessions, provenance and redacted worker events.

- [ ] **Step 1 RED:** Add tests that fail on existing long Control and short Activity: no session tables on Control, activity has motor A/B and worker timeline, timestamps/unknown/fail provenance, browser/session details, polling/error state and no hidden required member. Test disable reasons for mirror SITE_URL, absent B credential, can_start=false, STOP without activation and last-value historical.
- [ ] **Step 2 GREEN:** Reuse existing renderer helpers without rebuilding engine model. Fold count inputs inside `<details>` in their current forms, keep required socio visible, show reasons. Place session/progress/metadata in Activity and combine the existing redacted worker timeline without injecting secrets. Update JS and static CSP sha256 to handle separate DOMs gracefully, preserve `noscript` manual refresh.
- [ ] **Step 3:** Run only new/affected route/renderer/CSP and token privacy tests RED→GREEN. Verify source has no new provider/host/navigation/DB effects. Commit minimal UX implementation.

### Task 4: Owner documentation + final source review package

**Files:** Modify `AGENTS.md`, `docs/BETA_INTEGRATION_STATUS.md`; keep design and plan; no generic repo churn.

**Interfaces:** References exact candidate SHA/diff, frozen source W, new issue #417 evidence, conditions G3–G7.

- [ ] **Step 1:** Update misleading historical top headlines to current G2 candidate, preserve historical sections as archives, link source/checkpoint/QA/RCA/gates, distinguish CODE_ONLY from physically installed version.
- [ ] **Step 2:** Verify `git diff --check`, Python syntax targeted, impacted Ruff/format/mypy and focal tests only, build-bundle budget **dry measurement** without publishing image, exact checksum allowed paths and status. No entire CI locally repeated.
- [ ] **Step 3:** Commit docs; prepare patch/review package; Root independently verifies diff and requests separate Root/Arquitectura/QA/Operaciones GO_FINAL then GO_INTEGRATION. No push/PR/host before those votes.

### Task 5: Root G3–G7 (AFTER 4GO_FINAL; outside author scope)

**Files:** None without fresh approved scope. Root owns GitHub issue and Actions.

- [ ] **Step 1:** After 4/4 FINAL and 4/4 GO_INTEGRATION on exact candidate SHA, push one branch/create one PR, run CI/security once, address genuine findings with renewed diff review, merge and reconcile main/source-vs-installed.
- [ ] **Step 2:** Get NEW 4/4 GO_OPERATION pinned to W CID/OCI for G3b metadata Action Boca once before replacing W; validate double stat/receipt and leave engine unverified. G5 custody read-only; no admin auto provision.
- [ ] **Step 3:** After approvals and gates, one release+APPLY Boca via protected Actions only, physical controller/worker health+pin/OCI and stopped-state receipt. Any failure STOP/RCA/fix-forward, not blind retries.
- [ ] **Step 4:** G7 controlled SIMULATION_ONLY tablet verification; separate outcome of engine ACK, Site URL, event/queue, tokens, browsers, two independent STOPs, Telegram sender OFF; record PASS/FAIL in #417. Never claim BETA READY without these receipts.
