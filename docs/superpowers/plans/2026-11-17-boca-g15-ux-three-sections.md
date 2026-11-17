# Boca G15 Three-Section UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Boca's repeated navigation and buried motor activity with the approved three-section voice-friendly dashboard, preserving G14 operation contracts.

**Architecture:** Refactor existing private view renderers and reuse their fixed JSON projections/polling. Preserve endpoints/permissions and combine all changes in **one candidate** after independent Architecture/QA/Ops design approval; defer release/deploy until separate operational review.

**Tech Stack:** Python 3.12 HTML renderers, inlined hashed CSS/JS, existing WSGI panel routes, pytest/Ruff/MyPy, existing offline UI checks.

**Spec:** [G15 three-section UX design](../specs/2026-11-17-boca-g15-ux-three-sections.md)

## Global Constraints

- G14 installed main `fc4b482053468b0b29004bdb663a82cfe1da585c`; no repeat release #873/APPLY #1220.
- No mutations of host except subsequently reviewed Boca-only GitHub Actions. No Porota, foreign resources, real bookings or queue bypass.
- Keep `synthetic.py` / `ipc_worker.py` blackbox and all existing auth, CSRF, Origin, operation IDs and scope contracts.
- No new backend/event source; reuse `/control/motores.json`, `/control/actividad.json`, existing 5-second polling and private token inspection.
- Existing `/telegram/configurar` direct POST remains owner-only and sender OFF pending separate install.
- Preserve legacy status-only and guest routes; no manufactured worker/DOM evidence.

## Review Focus

1. Two visible live cards but only one updated: add an A/B polling test in Task 2.
2. CSS `a{display:inline-block}` defeating `hidden`: assert rendered CSS and hidden-state behavior in Task 1.
3. Authenticated `/ingresar` still consuming passkey challenge: add valid/absent/revoked cookie tests in Task 4.
4. A failed poll mislabeling a historical event as live: test stale→recovery separately for motor and worker in Task 3.
5. Accordion or layout hiding B's required member selector or breaking Telegram form: test forms, permissions and mobile constraints in Tasks 2/3/4.

---

### Task 1: Three-tab navigation, scoped layout and `hidden` fix

**Files:** Modify `src/boca_socios/panel/private_ui.py`, `src/boca_socios/panel/enrollment_form.py`; tests `tests/test_private_beta_panel.py`, `tests/test_engine_live_status_ui.py` and relevant CSP/guest suites.

**Interfaces:** `_page(title, content, ..., private_navigation=True) -> bytes` retains signature; new HTML has exactly three `nav[aria-label=Principal] a` paths `/control`, `/control/actividad`, `/configuracion`. Use a dashboard-only body class and CSS. `_guest_page` retains existing restricted view.

- [ ] **Step 1:** Write failing tests for exactly three permanent navigation links, `aria-current`, no second navigation, responsive container, and `[hidden] { display: none !important; }` effective for inspection/other links.
- [ ] **Step 2:** Run the focused tests and confirm a meaningful pre-change failure.
- [ ] **Step 3:** Change only shared page nav/layout CSS and preserve page CSP hashes.
- [ ] **Step 4:** Run focused tests through GREEN, including guest/login/enrollment/Telegram regressions and `ruff check`.
- [ ] **Step 5:** Commit Task 1 changes on the single isolated feature branch.

### Task 2: Control shows both engines and honest live summaries

**Files:** Modify `src/boca_socios/panel/engine_view.py`; tests `tests/test_engine_view.py`, `tests/test_engine_live_status_ui.py`, `tests/test_private_engine_controls.py`, `tests/test_engine_dashboard_ui_offline.py`.

**Interfaces:** Preserve `page(snapshot, csrf, operations, members, *, site_url_ready, engine=None) -> bytes`, POST form names/targets, `engine_view.csp()` and all GETs. Make Control's two motor summaries visible before start/stop form details. A/B state, phases and projected event/queue/tokens/error must refresh for **both** from one existing motor JSON request; worker timeline does not belong on Control. Deep Motor A/B pages remain compatible.

- [ ] **Step 1:** Write failing tests for two distinct initial + live-updated A/B summaries, independent operation forms, full B member selector, correct 25/0/0 receipt explanation, and no phantom token inspection link.
- [ ] **Step 2:** Observe RED for the missing/incorrect Control summary.
- [ ] **Step 3:** Reuse/refactor live projection once (no two independent poll loops), render compact motor panels and keep all existing form names/IDs.
- [ ] **Step 4:** Observe GREEN, prove no secrets or mislabelled `NO_EVENT`, validate CSP script hashes and default 5 s cadence.
- [ ] **Step 5:** Commit Task 2 changes.

### Task 3: Activity first-viewport timeline and contextual engine evidence

**Files:** Modify `src/boca_socios/panel/private_ui.py` and `src/boca_socios/panel/engine_view.py` only if necessary; tests `tests/test_engine_live_status_ui.py`, `tests/test_engine_view.py`, `tests/test_private_ui_truthfulness.py`, `tests/test_engine_dashboard_ui_offline.py`.

**Interfaces:** `worker_activity(snapshot, *, engine_snapshot=None, members=()) -> bytes`, `activity_content(snapshot, members) -> str` keep endpoints and scripts `_ACTIVITY_SCRIPT`, `_SCRIPT`. Worker feed stays **one** shared timeline at top; preserve existing DOM IDs required by polling and session updates. A/B jumps link into this page, not create more global tabs.

- [ ] **Step 1:** Write failing HTML/JS tests for chronology before verbose reports, one shared source-labelled feed, visible A/B anchors, absence of duplicate worker feeds and stale/fetch-fail/recovered cases.
- [ ] **Step 2:** Confirm RED due to existing order/duplication.
- [ ] **Step 3:** Reorder and group existing projections; move verbose explanations/metrics to labelled disclosures without losing IDs and links.
- [ ] **Step 4:** Run GREEN and verify timestamps are real event vs fetch times, session inspector and read-only perms unchanged.
- [ ] **Step 5:** Commit Task 3 changes.

### Task 4: Consolidated Configuration, Telegram discoverability and existing-session login routing

**Files:** Modify `src/boca_socios/panel/private_ui.py`, `src/boca_socios/panel/private_http.py`; tests `tests/test_private_beta_panel.py`, `tests/test_telegram_direct_owner_stage.py`, `tests/test_telegram_admin.py`, owner session/access suites.

**Interfaces:** Preserve `site_url_configuration(csrf, operation_id, site_url) -> bytes`, the SITE_URL POST, `/telegram/configurar` GET/POST, guest GET semantics, and WebAuthn verifier. Add contextual Socios/Telegram/advanced links under Config. GET `/ingresar` with currently valid owner `simulation:write` cookie redirects to `/control`; absent/revoked/limited cookie still uses existing passkey page.

- [ ] **Step 1:** Write failing tests for grouped Config links, direct Telegram form destination and status, and `/ingresar` valid-owner redirect versus missing/revoked/limited owner session.
- [ ] **Step 2:** Verify RED on current owner login behavior and Config discoverability.
- [ ] **Step 3:** Implement the constrained view/routing changes only; no authentication bypass, no new credential path.
- [ ] **Step 4:** Verify GREEN, unchanged POST permissions/CSRF/Origin and Telegram pending behavior, plus no login loop.
- [ ] **Step 5:** Commit Task 4 changes.

### Task 5: Whole-candidate QA and integration

**Files:** Existing tests and these spec/plan docs; changes to product code only for proven regressions.

- [ ] **Step 1:** Run focused UI/auth/CSP/Telegram tests, followed by full `uv run --no-sync pytest -q`, `uv run --no-sync ruff check`, `uv run --no-sync ruff format --check`, `uv run --no-sync mypy src` and existing policy guards; name any expected platform skips accurately.
- [ ] **Step 2:** Run actual offline Chromium DOM/visual smoke where the environment permits; include tablet landscape 1536×960, portrait 800×1280, mobile 412×915, zoom 200% and Voice Access acceptance checklist. If the browser is blocked, report that explicitly and leave visual QA open.
- [ ] **Step 3:** Independent reviewer of exact diff, SHA and regression evidence; remedy critical/important issues. Preserve single candidate and no build dispatch before scope freeze.
- [ ] **Step 4:** Publish **one** GitHub PR with docs and tests, wait for single CI run; do not repeat G14 APPLY or release images. Record outcome, unverified live UX and pending functional gates in issue #417.

## Implementation evidence and bounded follow-ups — 17 November 2026

- A separate code author implemented the G15 UI/auth changes in a single isolated worktree, after independent Architecture/QA/Operations pre-code review. The author froze the 13 changed code/test files; no G14 deployment was repeated.
- The richer Control HTML exposed a **test transport** defect: offline fixture schema v3 repeated the same Control script in five documents and grew to ~224 KB. Architecture, QA, Operations, and root separately approved a **test-only**, lossless schema v4 shared-script representation: no production script compression, unchanged 170,000-byte wire cap (newline included), 100,000-byte expanded-document cap, byte-for-byte reconstruction, SHA-256/CSP validation and negative integrity tests. The new fixture measures ~128 KB; see [issue #417 consensus](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6962806933).
- Author's frozen-tree evidence: 375 focused tests PASS, fixture-specific 118 PASS, Ruff/format/MyPy/policy and diff-check PASS. Root independently reran a five-module regression selection: **190 PASS**.
- Full-suite `-x` yielded **the identical first failure** on untouched G14 and G15: `tests/test_engine_browser_pool.py::test_fifty_isolated_contexts_share_three_processes_and_close_one_engine_only`, at the same assertion, after **1,544 PASS and 10 subtests** in each. The test passes individually on G15. This is an existing full-suite ordering/concurrency problem; its precise underlying mechanism remains unproven and must not be “fixed” by changing unmodified browser engines as part of G15. See [issue #417 evidence](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6963005951).
- **Visual BETA gate remains open:** Chromium offline could not start in the local execution sandbox (`NO_GO_CHROME_START`), so no real screenshot, layout, Voice Access, Telegram sender, event/queue/token discovery or browser-per-member behavior is certified by these local tests. Recheck the UI runner in CI of the **single eventual G15 PR**, then complete Tincho's Android tablet QA and physical observations via **Boca-only GitHub Actions**. No real bookings.
