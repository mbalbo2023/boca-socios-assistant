# R296 — Consolidated BETA integration implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Prepare one reviewed candidate containing the missing automatic Boca authentication and productive Telegram wiring, ready to incorporate owner QA corrections before promotion.

**Architecture:** Continue PR #517 and its existing branch. Reuse the existing observer/session, credential service, lifecycle ledger, private IPC, Telegram custody caller and maintenance container. Independent writers own disjoint files; root integrates shared contracts and publishes one reviewed source increment.

**Tech Stack:** Existing Python 3.12, SQLite, Playwright, Unix sockets, rootless Docker and protected GitHub Actions; no new external package.

**Spec:** [R296 owner decision](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6881603931), [functional inventory](https://github.com/mbalbo2023/boca-socios-assistant/issues/12#issuecomment-6878606098), ADR0301.

## Global Constraints

- Base candidate e8f8395820a720fef3f7d275a490400582adacec; main/installed c5a143541ccfcaf26f29cf252a4cb33fd7c540f7.
- SAME branch feature/417-r295-beta-followups and PR #517; no new PR or replacement implementation.
- No merge, release, deploy, host operation, agent START/STOP, provider navigation or Telegram message while owner QA remains pending.
- Ticket operations SIMULATION_ONLY. No reservations, purchases, queue/WAF/CAPTCHA bypass or multiple queue positions.
- Preserve synthetic.py and ipc_worker.py bytes and main protections; no extra ports, foreign services, Docker prune, deletion of volumes/data/history, secret logs or arbitrary command execution.
- Reuse the certified baseline; run focused delta tests locally, complete required gates only for the consolidated published SHA.
- One writer per file. Root alone stages/commits/publishes and edits shared builders/workflow/docs. User-authorized independent parallel work overrides the skill's default sequential implementation rule.
- Keep current bundle caps/reserves. Runtime/worker dependencies must not leak vault/DB/cryptography into the browser or eager external dependencies into host-only leaves.
- Report code readiness separately from provider success, physical readiness and human acceptance. No flags assumed true.

## Review Focus

1. STOP/revocation/new START races never publish a late authentication result or leave an unbounded child.
2. Multiple members and replay never silently substitute another member's credential.
3. A destination/token alone never authorizes login; active queue/challenge/unknown stays truthful, without extra session.
4. Telegram failures preserve stage nonce/partial custody/history and restore only the exact known controller; uncertainty remains visible.
5. Real archive/image closure and exact rootless identities must support the implemented path, including failure branches; a mocked success is not physical proof.

### Task 1: Worker authentication continuation
**Owner:** worker agent.
**Files:** browser/automatic_observer.py, ipc_protocol.py, ipc_client.py, ipc_server.py; new browser/boca_auth_protocol.py and browser/boca_login_process.py, necessary parser projection extension and task tests. Root owns Dockerfile.browser.
**Interfaces:** BocaAuthReadiness(operation_id, observation, nonce, remaining_seconds) with ready property; BocaAuthRequest(operation_id, nonce, email, password); BocaAuthReply(operation_id, nonce, provider_payload). UnixSyntheticBrowser.prepare_boca_login(operation_id) and login_boca(request); worker matching methods.
- [ ] Add RED tests for the exact same-context happy path, hostile/ambiguous pages, replay, expiry, STOP and malformed private frames.
- [ ] Implement opt-in continuation; default observe_queue remains unchanged. One legitimate target navigation to exact HTTPS portal, visible enabled email/password in same unambiguous login form, no active queue/challenge. Never authorize from target URL alone.
- [ ] Bind first operation to session, issue one 64-hex nonce with 15-second lifetime, consume before awaits, enforce remaining whole deadline. Reject operation/page/context drift, late replies and replay.
- [ ] Private auth-only four-byte framing: max response90112 bytes (base64 envelope), request32768, decoded provider payload65536; exact keys/types, duplicate-key rejection, redacted representations, SO_PEERCRED and inode checks before secrets.
- [ ] Reuse BocaHttpLoginTransport in one supervised subprocess, fixed argv/bootstrap, private bounded stdin/stdout, no secret env/files/argv/stderr. Deadline includes spawn/DNS/TLS/read/close; max15s, exact-PID kill/reap within1s; existing20s worker/25s client outer bounds. Poison when teardown unverified.
- [ ] Run focused observer/IPC/transport tests and real offline child cancellation/import-closure proof; self-review and report. No global suite/commit.

### Task 2: Controller, START and monitor
**Owner:** controller agent.
**Files:** panel/lifecycle_intents.py, panel/private_http.py, panel/private_ui.py, integration/automatic_observation.py, runtime.py; small controller transport adapter if needed; existing private monitor/activity modules and focused tests. No Telegram changes in shared panel files until root integrates them after this task releases ownership.
**Interfaces:** request(..., on_demand=False, auth_member_id=None); auth_member_for_start(start_id)->str|None; an atomic callback/fence for publishing only current APPLIED START/member. Worker types/methods from Task1; no crypto/runtime imports in lifecycle host leaf.
- [ ] RED tests for atomic member selection, replay with changed member, multiple members, credential revocation, restart and STOP race.
- [ ] Persist selection as a typed audit marker in the existing transaction (no schema/new ledger), validate active credential, preserve historical requests without auth selection and reject changing selection under existing activation.
- [ ] Add accessible member selector to START; only active members, visible single-member preselection allowed; observation-only remains explicit. STOP retains existing behavior and is always usable. Preserve origin/passkey/CSRF/one-use semantics; compare selected member on all retry branches.
- [ ] For selected member, loop worker prepare_boca_login through queue waiting; use existing BocaMemberAuthService with monitor=None and a bounded private IPC transport. Publish only after durable current START/member/revocation fence serialized with STOP. One final correlated durable STOP; no historical replay.
- [ ] Inject one PrivateBocaAuthMonitor into runtime and panel; report fixed authentication phases/outcomes with no secret material. Keep observation-only path compatible; construction remains inert.
- [ ] Run focused ledger/panel/runtime/session tests incl real SQLite stop serialization, same-instance monitor and worker unavailable; self-review/report. No global suite/commit.

### Task 3: Productive Telegram backend and existing sender
**Owner:** Telegram agent.
**Files:** new host_telegram_installed_context.py, host_telegram_backend.py, host_telegram_maintenance.py, telegram_maintenance.py, panel/telegram_recipient.py as needed after checking reuse. Existing host_telegram caller/stage/topology/custody modules, telegram pairing resolver/bootstrap/cutover/one_shot, notify sqlite_outbox/telegram_delivery/telegram_worker and focused tests. Narrow lazy imports in panel/passkey.py and crypto leaves allowed to preserve host stdlib closure. Root owns first_deploy/workflow/build/CLI and shared panel/runtime.
**Interfaces:** prepare_installed_telegram(attempt_id, *, lease, reader=None); activate_installed_telegram(attempt_id, *, lease, reader=None); redacted receipts. read_prepared_recipient(directory, *, expected_source_sha)->RecipientReceipt. Public file telegram_recipient_public_v2.json version2, purpose boca-telegram-prepared-recipient-v2, source_sha, installation_fingerprint and public PREPARED recipient only.
- [ ] RED tests for complete fake-host prepare/stage/activate/custody/restoration transaction and phase failures, binding drift, missing physical access and history-preserving acceptance.
- [ ] Resolve coordinates exclusively from current authenticated installed binding/pair/volumes and same process lease. Attest healthy before stop/after restore; stopped-phase evidence must use correct current profile and actual helper topology.
- [ ] Reuse the existing exact-image network-none maintenance-container mechanism for fixed storage operations under mapped container UID. Narrow injectable storage adapters preserve existing algorithms/local defaults. Bound private binary I/O; no secret argv/env/logs, no persistent new RPC or crypto implementation. Before/after checks and exact-ID cleanup required.
- [ ] Keep host coordination stdlib; canonical crypto/owner verification/decrypt/install run in installed image when necessary. No private key export when helper can perform operation. Verify schema0007; missing schema is explicit prerequisite, no implicit legacy migration.
- [ ] Prepare public recipient idempotently only on coherent custody, publish fixed receipt for UI; activate revalidates owner/stage/current binding and calls existing staged custody once. Consume nonce once, preserve partial state on failure, cleanup helper and restore exact prestate.
- [ ] Wire existing sender to V2 custody/source verification. Extend existing outbox/coordinator with optional exact notice UUID filter; acceptance sends only its own notice while preserving unrelated/history/prepared/ambiguous entries. API acceptance and human receipt separate.
- [ ] Run focused integration/failure/sender tests and self-review/report. Root wires UI/CLI/package only after concrete interfaces are ready. No global suite/commit.

### Task 4: Root integration, review and publication
**Owner:** root.
**Files:** Dockerfile.browser, protected Telegram builder/bootstrap/CLI and existing workflow, public recipient UI hook after Task2 releases files, documentation and necessary packaging tests.
- [ ] Add only reviewed worker stdlib/security leafs to browser image and prove isolated import/runtime closure.
- [ ] Add current installed Telegram prepare/activate entry to existing dedicated protected route and memfd transport after backend works; preserve owner/attempt/source/lease/cleanup checks. Dedicated exact mode source lists may exclude unused diagnostic closure; never raise caps or include Telegram in full cutover merely for convenience.
- [ ] Wire validated public recipient into existing pairing page with no manual hash/key copy; diagnostics show actual prepared/staged/paired/sender/human states.
- [ ] Independently review each task against brief/report/diff, then entire candidate. Fix concrete findings with focal regressions. Check current bundle digest consumer test after affected source edits.
- [ ] Update AGENTS/README/policy/ADR and record reviewed exact files, tests, limitations and physical prerequisites in #417/#12.
- [ ] Publish one consolidated source increment into PR517 after review; wait for required exact-SHA CI. Leave candidate open for owner QA corrections. No merge/release/deploy.

### Task 5: Sender adoption into the installed binding
**Owner:** sender integration agent. Added after code inspection identified the missing binding transition; [canonical decision](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6881863489).
**Files:** new host_telegram_sender.py, narrow compatible update in host_on_demand_service.py, focused tests. Changes to canonical sender constructors/attestors in host_first_deploy.py are serialized after Task3 explicitly releases that file. Root owns packaging/workflow/UI.
**Interface:** activate_installed_sender(context, *, lease, maintenance, expected_source_sha, attempt_id), called after V2 custody commit with controller/worker stopped. Returns a redacted verified sender receipt; updates context installation/binding digest only after successful adoption. Backend restores controller afterwards.
- [ ] Inspect and reuse current sender constructors, one-shot acceptance, V2 identity derivation, on-demand plan/unit helpers and lease checks; no parallel sender registry, PARK or reinstall.
- [ ] Run acceptance for only this attempt's deterministic notice. API acceptance and human receipt remain distinct. Preserve unrelated outbox/history and ambiguous sends.
- [ ] Create/start/attest only the exact current-image sender, using fixed V2 CLI modes and no secret argv. Existing incompatible or unowned objects block instead of being replaced.
- [ ] Under the held lease, compatibly adopt only sender fields into the existing binding and pinned units. Preserve source/controller/worker/images/database/archive. Verify staged bytes, links and service state; compensate exact owned changes on failure and expose uncertainty. Do not describe a multi-file transaction as atomic.
- [ ] Cover adoption/failure/recovery, unexpected object or binding drift, source mismatch, acceptance ambiguity and START/STOP compatibility with focal tests. Report code evidence separately from pending physical certification.

## Execution ledger
The durable source/Actions results and decisions are recorded in #417. Local progress/brief/report files are intermediate review aids, not substitutes for GitHub.

