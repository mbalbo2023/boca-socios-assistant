# R295 — Postdeploy followups implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Develop the verified missing status, Boca login and Telegram components while the owner tests the installed R294 BETA.

**Architecture:** Reuse the existing lifecycle ledger, private credential service, monitor, Telegram custody caller and sender. Independent owners edit exclusive files; root integrates shared contracts serially. Code verification and physical acceptance remain separate.

**Tech Stack:** Python 3.12, SQLite, pytest, existing rootless Docker contracts and protected GitHub Actions.

**Spec:** [R295 canonical design and ownership](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6878044872), [R294 physical handoff](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6871954660), and ADR0299.

## Global constraints

- Base main `c5a143541ccfcaf26f29cf252a4cb33fd7c540f7`; certified tree `a3498beafc614f3c59c4bac24a3d5708dcde55c3`.
- SIMULATION_ONLY tickets; no reservations, purchases, queue bypass, WAF/CAPTCHA bypass or agent navigation to Boca/Queue-it.
- No host operations, release, START/STOP or Telegram messages during the owner's Samsung test.
- Preserve `synthetic.py`, `ipc_worker.py`, strict lifecycle authorization, main protections and bundle caps/reserves.
- Reuse the existing isolated worktree. Do not rerun the unchanged certified full baseline locally.
- One source writer per scope. Root owns GitHub publication, shared integration and documentation.
- Explicit user authorization permits independent implementation in parallel without a new routine permission pause.
- A historical provider contract enables offline development; it does not prove current provider behavior.

## Review focus

1. A preserved terminal STOP must not be attributed to the newly installed pair; Task 1 uses a real ledger with two fingerprints.
2. A pending or corrupted lifecycle operation must remain NO_GO; Task 1 tests uncertain states and races.
3. Credentials, cookies and token responses must not reach logs/errors or a redirected origin; Task 2 tests a malicious exchange and bounded output.
4. A stopped on-demand controller must satisfy its exact current mounts/restart policy; Task 3 rejects partial or extra topology.
5. Compatibility changes must not falsely enable a Telegram sender or certify human receipt; Task 3 preserves the activation gate and root documents remaining integration.

## Ownership and interface rulings

| Task | Writer | Exclusive paths | Shared interface ruling |
| --- | --- | --- | --- |
| 1 | status agent | `host_on_demand_status.py`, status tests | Do not change `read_panel_status` or CURRENT_RETAINED authorization. |
| 2 | auth agent | `security/boca_login_transport.py`, its focused tests | Implement the existing `BocaLoginTransport.login(*, email, password) -> bytes`; root owns runtime/IPC/panel wiring. |
| 3 | Telegram agent | `host_telegram_postcutover.py`, its tests | Reuse current on-demand topology; do not remove workflow NO_GO or modify sender in this task. |
| 4 | root | private UI copy, plan/ADR/global documentation, bundle integration | Integrate dependent changes serially and review the entire diff. |

No new producer, sender or ledger duplicates an existing module. If the scope requires another file or a shared interface change, first report the concrete dependency to root and record the ruling.

## Task 1: Current installed status and preserved STOP

**Files:** modify `src/boca_socios/host_on_demand_status.py` and `tests/test_r294_installed_status.py`; extend the existing status tests only for a demonstrated dependency.

**Interfaces:** consume the installed controller's read-only ledger helpers and existing validated `PanelStatus`. Produce a versioned diagnostic receipt separating the currently bound operation from `NOT_BOUND_TO_CURRENT_INSTALLATION`; the shared strict reader remains unchanged.

- [x] Add and run a failing regression using a real migrated SQLite ledger containing a valid STOP/APPLIED bound to fingerprint A, read against fingerprint B.
- [x] Implement a fixed bounded read-only controller program and a strict diagnostic parser. Only an unbound terminal bot STOP/APPLIED with current worker CREATED/PID0 and engine STOPPED may be projected separately.
- [x] Verify same-fingerprint operation, uncertain/corrupt records, binding/physical/intent races and unchanged read-only database content.
- [x] Run the affected status tests; root checks actual bundle closure and independent review before publication.

## Task 2: Boca login transport, using recovered contract

**Files:** create `src/boca_socios/security/boca_login_transport.py` and `tests/test_boca_login_transport.py` after the recorded inventory found no concrete transport.

**Interfaces:** implement `BocaLoginTransport.login(*, email: str, password: str) -> bytes`. Reuse `BocaMemberAuthService`, `BocaAuthObservation` and `PrivateBocaAuthMonitor`; do not duplicate their parser or vault. Inject the HTTP/session boundary for offline tests and later worker integration.

**Evidence:** `pany100/bocasociosv2@f107a88dba195fead329616529fa074df33be083`, `constants.js` blob `7478f8ea47f412578769543f41301fa45d1f937b`, `login.js` blob `adb052e68d416d51b0c501545c0dfac30559b3d4`. POST `https://bocasocios-gw.bocajuniors.com.ar/auth/login/baas`, JSON email/password, response token/refreshToken. Origin/Referer refer to the ordinary portal.

- [x] Add and run a failing offline test for exact method, HTTPS origin/path, JSON fields and one exchange.
- [x] Implement the small transport with verified TLS, finite socket timeout, maximum 65,536-byte response, no redirects or retries and category-only errors.
- [x] Test malformed/oversized replies, failures, secret redaction and same-session cookie restrictions. Construction must perform no I/O.
- [x] Run focused transport and existing auth contract tests. Report the exact adapter interface to root for START/STOP and worker IPC integration design.

No copied `validate(true)`, invented cookies, extra Queue-it session or automatic refresh endpoint. Runtime wiring remains a separate dependent task until its security/lifecycle contract is recorded.

## Task 3: Telegram stopped controller compatibility

**Files:** modify `src/boca_socios/host_telegram_postcutover.py` and `tests/test_host_telegram_postcutover.py`.

**Interfaces:** preserve `observe_telegram_host(...) -> TelegramTopologyWitness`, its lease and exact identity checks. Reuse on-demand controller topology from `host_lifecycle_rootless_adapter`; accept the current approved restart policy/control mount only as one coherent profile.

- [x] Add and run a failing test for the stopped R294 on-demand controller with its exact control bind and restart policy.
- [x] Implement profile-aware validation without accepting mixed old/current or extra mounts, arbitrary restart policies, running/restarting controller or unverified pair.
- [x] Run affected observer/topology/caller tests and verify the activation guard remains NO_GO.
- [x] Report remaining backend, physical attestor, V2 sender and acceptance-history dependencies; do not claim Telegram activation.

## Task 4: Integrate, review and document

**Files:** existing `src/boca_socios/panel/private_ui.py`, this plan and an R295 ADR; update current continuity headers coherently.

- [x] Replace the misleading automatic-stop label with “Detención automática del bot al finalizar el ciclo”; show actual reason through existing Monitor/Activity.
- [ ] Independently review each task, then the whole candidate for scope, privacy, topology and deployment side effects.
- [x] Measure changed bundle closures against the unchanged caps and reserves, and run only necessary dependent checks.
- [ ] Reconcile main/open PRs, consolidate one source commit and publish a reviewed PR with exact-SHA required checks.
- [ ] Record developed/verified versus physically installed states and remaining work in #417 and #12. Do not promote or operate the host while the owner is testing.

## Execution ledger

Publication, exact-SHA Actions results and subsequent acceptance are recorded in
the canonical #417 issue after this source snapshot; do not create another source
commit solely to check these boxes or copy run timings.

- 2026-11-14: inventories completed against the certified R294 tree, canonical decision recorded before files/tests. No duplicate concrete login adapter or productive Telegram backend found.
- 2026-11-14: root reused the isolated worktree and created `feature/417-r295-beta-followups` from current main. Owner test remains independent.
- 2026-11-14: all three task implementations passed focused tests and independent review. Review closed the orphan-current-note and live-worker/sender contradictions with real RED→GREEN regressions. No protected authorization reader changed.
- 2026-11-14: Telegram reader scope extended only to `NetworkSettings.Ports`, with its existing tests. The ZIP reuses AST-selected canonical network nodes and checked comment compaction; exact on-demand checks execute under `python -I -S` without checkout. Source caps remain unchanged. Details and measured bytes are in ADR0300; whole-branch review/publication remain pending below.
