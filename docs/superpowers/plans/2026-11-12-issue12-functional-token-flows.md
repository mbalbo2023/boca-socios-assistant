# Issue #12 Functional Token Flows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover committed member-sector/queue contracts and add two isolated private observed-token paths without live site traffic or #417 effects.

**Architecture:** Existing encrypted SQLite is the only member credential source. A pure queue URL parser, read-only member authentication adapter and two bounded in-memory observation channels feed a protected view in the current 8443 WSGI panel; no worker or external HTTP is wired.

**Tech Stack:** Python 3.12, SQLite, CredentialVault AES-GCM, WSGI, pytest, Ruff, Mypy, uv.

**Spec:** `docs/superpowers/specs/2026-11-12-issue12-functional-token-flows-design.md`

**Execution checkpoint (12/11 ART):** Tasks 1–4 have passing focused tests;
Task 5's negative audit, full local pytest (7135 PASS/1 sandbox SKIP), Ruff,
Mypy and repository policy passed. This is a plan checklist retained for
traceability, not an assertion of physical/CI certification. Exact-SHA
GitHub Actions and real providers remain pending; see the handoff under
`docs/handoffs/2026-11-12-issue12-functional-code-only.md`.

## Global Constraints

- `SIMULATION_ONLY`; no live Boca/Queue-it requests, reservations, bypasses or URL/token validity checks.
- No changes to #417, Docker/Compose/Actions, browser blackboxes, legacy navigation or other projects.
- One ticket per member/event remains enforced by existing code.
- Only owner-passkey, same-origin/CSRF/one-use protected pages may reveal secrets.
- Full applicable quality gates and exact-SHA PR checks precede any merge or deploy handoff.

## Review Focus

- Missing or repeated `queueittoken`: reject rather than infer from `queueId`.
- Percent-encoded target URL: preserve entire original string, including query/fragment bytes.
- Missing/revoked SQLite credential or wrong vault key: no network, no secret in error.
- Unauthorized/expired session, bad origin or replayed reveal: no token in HTML.
- `token` without `refreshToken` or vice versa: reject, never manufacture a token.

---

### Task 1: Recover only already-authored contracts

**Files:** recover the exact `sector_preferences.py`, `member_sector_store.py`,
`private_http.py`, `private_ui.py`, tests and design/plan files introduced by
`c86059e`/`d56235c`; recover only the four new queue files of `c1b25cb`.

**Interfaces:** existing `MemberSectorStore.for_database`, `QueuePassObservation`.

- [ ] Compare each commit's changed paths to current main.
- [ ] Apply only its own additions, never old ancestor infrastructure changes.
- [ ] Execute recovered focused tests and report merge conflicts accurately.

### Task 2: Parse observed Queue-it URL, register ephemeral passes

**Files:** Modify `src/boca_socios/queue/pass_observation.py`; create
`src/boca_socios/queue/private_pass_monitor.py`; test
`tests/test_queue_pass_url_contract.py`.

**Interfaces:** `QueuePassObservation.from_observed_url(...)` returns an
unverified observation; `PrivateQueuePassMonitor.observe(...)`,
`list_summaries(at)`, `owner_details(key, at)` expose bounded private state.

- [ ] Write offline tests for one genuine supplied query field, duplicate,
  empty/missing field, exact untouched URL, bounded registry and no secrets.
- [ ] Run tests and witness RED for missing interfaces.
- [ ] Implement minimal parser and registry; run focused tests GREEN.

### Task 3: Read encrypted SQLite credentials and parse auth response

**Files:** Create `src/boca_socios/security/member_auth_contract.py`,
`tests/test_member_auth_contract.py`.

**Interfaces:** `BocaMemberAuthService(database, vault, transport).authenticate(member_id)`
returns `BocaAuthObservation` from a strict provider response; optional
in-memory owner monitor records only successful actual transport responses.

- [ ] Test SQLite roundtrip with real enrollment/vault, revoked/invalid member,
  provider error, malformed/partial JSON and no automatic login.
- [ ] Verify expected RED before implementation.
- [ ] Implement read-only lookup, transport-injected exchange, exact field
  parser and safe metadata/`repr`, then verify GREEN.

### Task 4: Private token-monitor UI and guards

**Files:** Create `src/boca_socios/panel/private_token_view.py`; modify
`src/boca_socios/panel/private_http.py` and `private_ui.py`; add
`tests/test_private_token_monitor.py`.

**Interfaces:** Optional observed-only monitors injected into `PrivatePanelApplication`;
GET `/monitor/tokens` shows safe summaries; POST `/monitor/tokens/revelar`
returns an explicitly requested secret view for one selected flow.

- [ ] Test owner-only access and safe overview, POST CSRF/Origin/op replay,
  exact full-value reveal and copy-button behavior with fictional fixtures.
- [ ] Witness RED, then wire the existing session/permission guards and
  escaped accessible view, keeping default monitor empty and inert.
- [ ] Verify focused panel tests GREEN and no browser/worker activation.

### Task 5: QA, documentation, exclusive PR and handoff

**Files:** Modify `README.md` relevant current-status section and
`docs/OPERATIONS.md` narrowly; add code-only #12 handoff/negative-audit note.

- [ ] Add negative, offline checks for TLS downgrade and queue-skip shortcuts.
- [ ] Run `uv sync --frozen`, Ruff check/format, Mypy, full pytest and repo policy.
- [ ] Self-review changed paths against #417/legacy/blackbox exclusion.
- [ ] Create one atomic candidate commit/feature PR based on current main.
- [ ] Check exact-SHA Actions and document PASS/NO_GO with URLs, remaining
  integration/physical stoppers; hand off to #417 without deploying.
