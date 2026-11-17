# G16 implementation plan — accessible Activity without repeated technical fields

**Source:** [G16 spec](../specs/2026-11-17-boca-g16-compact-activity.md), accepted G15 main `aec2d37d793c96b3b063dab1ed10a030e6c35551`; [canonical issue #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417).
**Branch/worktree:** `feature/g16-compact-session-activity` in the isolated `boca-g16-ux` worktree. Do not alter the G15 local worktree, G14 physical droplet or Porota.

**Owner decisions:** Tincho explicitly ordered the P1 UX defects fixed before any next deploy and authorized a new artifact if required. Root, Architecture, QA, Operations and the UX specialist reached pre-code **GO_DESIGN** for compact session disclosures, duplicate empty-worker copy, explicit refresh labels, and third synthetic landscape viewport. Separate author and independent final reviewers.

**Baseline:** `uv run --no-sync python -m pytest -q tests/test_engine_view.py tests/test_engine_dashboard_ui_offline.py tests/test_worker_live_activity.py tests/test_engine_live_status_ui.py` → **218 PASS** on unchanged G15 `aec2d37...`. G15 screenshot full heights **6341px @800x1280**, **6824px @412x915** with 3 sessions. No G16 code exists at baseline.

## Guardrails for all tasks

- Change only **presentation, its existing JS refresh, tests and the existing synthetic Chromium runner**. The sole workflow exception is **one added PNG path** in the existing `.github/workflows/ci.yml` `engine_ui_upload` path list, required to publish the third viewport, with explicit Root/Architecture/QA/Ops/UX pre-code GO in issue #417 comment #6964005953. No engine/worker code, DB, auth, Telegram sender, network, other Actions change, Dockerfile, package graph, or interface to the host.
- Keep `_SESSION_LABELS` all 20 technical fields, unique session UUIDs, `data-field`, all private inspection URLs, 5s polling, single worker feed, CSP derived from exact scripts, CSRF/Origin/permission/nonces and safe escaped HTML.
- No real Boca/Queue-it navigation, reservations or credentials. GitHub issue/Actions evidence contains synthetic status only.
- Use RED→GREEN before implementation, run tests non-interactively, no duplicate PR/build. Freeze once, independently review exact diff, then one PR and single CI G16. If a test fails in Chromium, diagnose before any additional build.

### Task 1 — SSR compact session rows and truthful evidence

**Product:** `src/boca_socios/panel/engine_view.py`. **Tests:** `tests/test_engine_view.py` and relevant status truth tests.

- [ ] RED: Activity SSR for 0/2 sessions has exactly one stable `li[data-session-id]` per valid UUID, a visible `h4[data-field=title]`, a concise visible `data-summary-field` projection, one native `details` closed by default, all 20 original `dd[data-field]` under details, and an `a[data-field=inspect]` visible even when closed.
- [ ] RED: if a source sample repeats a valid UUID, SSR and polling project that UUID **once** instead of duplicating a session or disclosure (new defect reproduced by author during G16).
- [ ] RED: summary distinguishes historical CLOSED data from current, actual `NO_EVENT_CONFIRMED` from UNKNOWN, queue evidence and auth response from actual login; synthetic URL queries, bearer and credentials absent from summary.
- [ ] GREEN: reuse existing `_session_value`, `_SESSION_LABELS`, `_inspection_label` and safe escaping. Keep motor B's **activation member** at motor heading only, not falsely assigned to every browser.
- [ ] Verify layout CSS native `summary` tap >=52px, focus visible, no forced inner scroll, title and inspector distinct for Voice Access. No duplicate IDs.

### Task 2 — JS polling retains opened details and focus

**Product:** same `engine_view.py`, existing `_SESSION_ROWS_SCRIPT`. **Tests:** `tests/test_engine_view.py`, `tests/test_engine_live_status_ui.py`, offline DOM/Node tests.

- [ ] RED: first poll keeps existing SSR row instances; after opening session 301 details, phase3 adds 302 closed while 301/303 remain identical nodes; `details.open` and focused summary survive multiple polls; same session text updates without duplicating child fields; removed UUID row disappears.
- [ ] GREEN: create detailed/summary DOM once per new UUID, update through existing `fieldValue` for summary and all 20 technical fields; no new endpoint or polling timer. Preserve inspector href and no secret reveal in summary.
- [ ] Verify stale/fetch-failed observations remain historical and `WORKER_RECEIPT_UNVERIFIED` does not become “no event”. JS CSP hash remains valid. Existing POST/GET actions unchanged.

### Task 3 — One empty-worker message; source-specific refresh labels

**Product:** `src/boca_socios/panel/private_ui.py`, possibly the existing label string in `engine_view.py` only. **Tests:** `tests/test_worker_live_activity.py`, `tests/test_engine_live_status_ui.py`, JSON/JS truth tests.

- [ ] RED: zero recorded worker events → exactly one visible `#worker-activity-status` message, no fake `li` in `#worker-events`, `#worker-activity-observed` remains present but hidden, and `#worker-activity-refreshed` remains visible as **query time**.
- [ ] RED: transitions zero→event→fetch failure→recovery (and event→zero) keep event time separate, preserve historical samples on fetch failures, restore observed field visibility when event exists, avoid repetitive aria-live changes and preserve distinct Chromium advisory.
- [ ] GREEN: reuse current `_ACTIVITY_SCRIPT`/worker endpoint and polling, only change messages, `hidden` toggle, labels: `Actualizar registro del worker` vs `Actualizar motores y sesiones`.
- [ ] Verify simple, uniquely labelled 52px Voice Access targets, existing CSRF/ACL/CSP behavior unaffected.

### Task 4 — Chromium offline visual proof and third landscape viewport

**Test runner:** `scripts/run_engine_dashboard_ui_offline_chromium.py`. **Tests:** `tests/test_engine_dashboard_ui_offline.py`; optionally existing guest-nav assertions.

- [ ] RED: accept/verify exactly 3 synthetic viewports in order: **800×1280**, **412×915**, **1536×960**; dynamic `len(VIEWPORTS)` validation, exact filenames/PNG dimensions/hashes, rejection of missing/extra/reordered/corrupted capture. Preserve network none, bounded POST/GET, host_checked=false, external credentials and safety checks.
- [ ] RED: 3 rows keyed/one disclosure each and 3 inspection links visible; details closed initially; opening session exposes exactly 20 fields, keyboard Space/Enter and focus preserved during phase3 poll; newly added row closed, original node attached. Close disclosures before final full-page screenshot, no overflow, tap >=52px.
- [ ] GREEN: initial 3-session full screenshot height **<=3170px @800x1280** and **<=3412px @412x915** (G15 measured 6341/6824, at least 50% shorter). 1536×960 has no horizontal overflow or clipped controls; do **not** label this a Samsung physical/200% zoom test.
- [ ] The existing `engine_ui_upload` step publishes **exactly three named screenshots and report.json**, tested against `VIEWPORTS`; preserve step/id/condition/pinned action/retention `7`/compression `0`, and do not add an upload or build.
- [ ] Keep `_MAX_FIXTURE=170000`, `_MAX_DOCUMENT=100000`, `_MAX_CAPTURE=6000000`, `_MAX_PNG=2000000`, `_MAX_HEIGHT=12000`, global timeout, SHA/CSP, `_PROBE_STEPS` enum and fail-closed handling unchanged except explicit new positive probes. If three PNGs exceed the existing cap, stop and obtain a separate evidence-backed remedy; never silently raise limits or weaken tests.

### Task 5 — Candidate freeze, consensus and one integration

- [ ] Run exact focused UI/owner/guest/token/Telegram/ACL/CSP suites, then `uv run --no-sync python -m pytest -q`/CI inventory, `ruff check`, `ruff format --check`, `mypy src`, policy guards and `git diff --check`; distinguish preexisting local full-suite ordering failures from new regressions with evidence.
- [ ] Independent Architecture, QA, Operations and UX reviews of **exact changed files**, Root GO_CODE_FINAL. No code from reviewers.
- [ ] Publish **one G16 PR** (docs+tests+UI) only after content freeze; use GitHub connector if local git push not authenticated; CI includes one isolated Chromium image-build and 3 screenshot artifact. No G15/G14 redeploy and no Actions host operations yet.
- [ ] Record all CI, screenshot heights, exact PR/head/tree SHA, user-accessibility gaps and lessons learned in #417. If green and approved, merge code; then **separately** plan consolidated **one** Boca-only GitHub Actions release/deploy of G15+G16 with independent 4GO_OPERATION and postflight physical evidence, no real reservations.

**Not accepted as BETA certification:** synthetic screenshots alone, theoretical site events, unverified tokens or authentication, Telegram sender readiness, 200% zoom, Voice Access physical support, or any claim that the droplet has G16 before a verified Boca Action.
