# R179 Read-Only SITE_URL Observer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or subagent-driven-development. Use test-driven development and review the site/browser boundary before integration.

**Goal:** Add an explicit, off-by-default, single-page HTTP(S) observation of the owner-configured `SITE_URL` using Playwright, with categorical IPC results that can never certify reservations.

**Architecture:** Reuse the installed UID10002 worker's exact socket, STOP and teardown machinery. Add one narrow read-only Playwright observer with a separate `PROBE_SITE` IPC command. Preserve `RUN` as `NO_GO` in observer mode; no browser engine from legacy `synthetic.py` and no host/Compose wiring in this change.

**Tech Stack:** Python 3.12, asyncio, pinned Playwright 1.64.1, pytest, ruff, mypy.

**Spec:** R179 owner GO: one ordinary Chromium context; no Queue-it bypass/stealth, URL/token/cookie contents, form submission, clicks, downloads, arbitrary redirects, real bookings or live provider traffic in tests.

## Global Constraints

- Default runtime and `compose.beta.browser.yaml` do not activate observer.
- IPC frames are fixed constants of at most 64 bytes; no URL, account or token in a frame.
- URL is read only from existing `browser.site_url_runtime` on START.
- One exact GET document request; block subresources, non-GET and redirect destinations.
- Disable JavaScript and service workers; preserve browser default user agent and HTTPS certificate validation.
- Existing on-demand STOP cancels the operation, waits for bounded Chromium cleanup and fails closed on uncertain teardown.
- No host, workflow, panel or Docker change; no site traffic during tests.

## Review Focus

- A normal `REQUEST` accidentally causing navigation: test mode mismatch, no adapter call.
- A browser route trying POST, redirect or third-party fetch: test each is aborted with no second GET.
- A stale positive reply arriving after STOP: test `NO_GO`, cancellation and close.
- Non-2xx responses and failed/timeout navigation: fixed categorical result, never `SUCCESS`.
- A failure to tear down Chromium: poison worker and refuse subsequent work.

## Tasks

### Task 1: Distinct IPC observation contract

**Files:** `src/boca_socios/browser/ipc_protocol.py`, `ipc_client.py`, `ipc_server.py`, `tests/test_r179_site_observer_ipc.py`.

**Interfaces:** `PROBE_SITE`, `SITE_HTTP_OK`, `SITE_HTTP_NON_OK`; `UnixSyntheticBrowser.probe_site_readonly() -> str`; `UnixSyntheticWorker(site_observer=...)` accepts an `observe_site()`/`close()` port.

- [x] Write failing tests: default/fixture reject `PROBE_SITE`; site observer rejects `REQUEST` and `PROBE_FIXTURE`; categories map only to site frames, with STOP and injected timeout.
- [x] Confirm RED with `uv run --frozen pytest -q tests/test_r179_site_observer_ipc.py`.
- [x] Implement fixed frames, worker gating/dispatch, client method and shared teardown.
- [x] Confirm GREEN and run existing IPC tests.

### Task 2: Strict read-only Playwright observer

**Files:** `src/boca_socios/browser/site_observer.py`, `tests/test_r179_site_observer.py`.

**Interfaces:** `SiteReadOnlyExecutor(site_url, pages=..., timeout_seconds=...)`, `observe_site() -> SiteObservationStatus`, `close()`; page factory injected in tests, normal lazy async Playwright in production.

- [x] Write failing tests: one exact GET to SITE_URL; stop/redirect/subresources/POST abort; no cookies/JS/tokens; 2xx vs non-2xx; invalid URL; cancellation; teardown failure.
- [x] Verify RED and implement minimal adapter using existing Playwright lifecycle conventions.
- [x] Verify GREEN without network and test STOP/no late positive result.

### Task 3: Explicit entrypoint opt-in and documentation

**Files:** `src/boca_socios/browser/ipc_server.py`, `tests/test_r179_site_observer_ipc.py`, `docs/handoffs/2026-11-11-r179-site-observer-code-only.md`.

- [x] Write failing mode-selection tests: `BOCA_BROWSER_OBSERVE_MODE=site-readonly`, incompatible factory and unknown mode refused; ordinary mode remains `NO_GO`.
- [x] Wire mode only to existing site URL read. Do not modify Compose/Actions/host.
- [x] Document why legacy `SyntheticBrowserEngine` is not reused, exact R180 host activation needs, physical gaps and no real site acceptance.
- [x] Run full `uv run --frozen pytest -q -n 4`, ruff, mypy, policy check, diff check; commit isolated without push.
