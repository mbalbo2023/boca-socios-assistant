# G18 ATTEST Factory Route Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve a distinct future terminal category when the Boca pair-upgrade backend factory fails, without changing the upgrade's behavior, durable journal schema, or historical #1251 RCA.

**Architecture:** The existing `PairUpgradeReceipt.failed_phase` is the only classification carrier. Add the single literal `ATTEST_FACTORY`, assign it only in the current `backend_factory` exception branch, and tighten the existing receipt verifier's coherence check. The same terminal sink, `schema=1`, and O_EXCL receipt remain the sole durable output. No new observer, Action, host effect, image, or deployment is part of this plan.

**Tech Stack:** Python 3.12, pytest, uv (offline lock), Ruff, mypy, existing Boca GitHub CI.

**Spec:** `docs/HANDOFF_G18_2026-11-18.md` §4/§6 and issue #417 D2.2 consensus `https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6993940940`.

## Global Constraints

- Four independent pre-code votes are recorded: Root, Architecture, QA, Operations **GO_PRE_CODE_OBSERVABILITY_ONLY**. The author of implementation must differ from Root/reviewers.
- Current baseline `main@382685c3bee7282001f2bce6ca2846cdc1e08650`; G17 installed, G18 not installed; historical APPLY #1251 `ATTEST_ROUTE_UNDETERMINED` and `exclusive_cause=UNPROVEN` must remain unchanged.
- Never repeat APPLY #1251, incident observer #1255, current-status #1257, or GHCR release #876. No real bookings, no Porota, no host commands outside Boca Actions.
- Allowed implementation: a **single** new `PairPhase` literal `ATTEST_FACTORY` and its assignment only in the factory exception/invalid-backend branch; a narrow schema-1 coherence guard in `_upgrade_fields_ok`, tests and Markdown handoff/checkpoint updates.
- `ATTEST` remains for `backend.attest` and pre-entry CLI failures. Existing historical `BOCA_PAIR_UPGRADE` schema 1 and 8 data fields remain valid. No schema bump, no new persistent file/field, no raw exception, no change to transaction or compensation flow, O_EXCL, Docker, SQLite, SSH, workflow, or release.
- `ATTEST_FACTORY` requires `state=NO_GO`, `cleanup=INDETERMINATE`, `old_restored=false`, `commit_started=false`, and both new CIDs `null`; it **does not mean no host effects** because factory callbacks can be uncertain. No retry authorization.
- TDD RED before production code, GREEN focused then whole suite; independent code review; 4GO_FINAL before merge. PR is a single observability candidate, not deploy approval.

## Review Focus

1. Factory throws `RuntimeError`/`KeyboardInterrupt`: must give `ATTEST_FACTORY` after intent and one terminal, no stage/park/commit.
2. Factory returns an invalid backend (`requires_persistent_receipt` spoofed on instance): must give `ATTEST_FACTORY` with no backend calls.
3. Factory succeeds, but backend `attest` fails: must remain `ATTEST`, with a canonically different receipt from factory failure.
4. Malformed or forged `ATTEST_FACTORY` plus ACCEPT/commit/restore/CIDs: `verify_upgrade` must reject; unknown phase must also reject.
5. Historic `schema=1` `ATTEST` #1251 and CLI pre-actor `ATTEST`: still verify; no attempt to attribute historical cause.

---

### Task 1: Differentiate future factory refusal without new effects

**Files:**

- Modify `src/boca_socios/host_boca_pair_upgrade.py` (`PairPhase`; factory exception receipt only).
- Modify `src/boca_socios/host_boca_pair_upgrade_cli.py` (`_upgrade_fields_ok` coherence only).
- Test `tests/test_host_boca_pair_upgrade.py` (reuse `_local_lease`, `_coordinates`, `Backend` fixtures).
- Test `tests/test_host_boca_pair_upgrade_cli.py` (canonical and malformed receipt cases).
- Update `docs/HANDOFF_G18_2026-11-18.md`, `docs/BETA_INTEGRATION_STATUS.md`, `README.md`, and `AGENTS.md` with one concise consistent checkpoint: #1257 G17 STOPPED/HEALTHY/worker CREATED/PID0, #1251 still unproven, four-role GO for this **prospective** diagnostic fix, no deploy. Do not re-copy completed UX or entire incident logs.

**Interfaces:**

- Consumes: `run_pair_upgrade(plan, backend_factory, terminal_preflight, commit_marker, terminal_sink)`, `PairUpgradeReceipt.failed_phase`, `encode_upgrade` / `verify_upgrade` (schema 1).
- Produces: `failed_phase="ATTEST_FACTORY"` **only** for factory callback exception or invalid backend; `ATTEST` preserved for backend `attest` and historical verifiers.

- [ ] **Step 1: Write RED tests** comparing two `backend_factory` scenarios: callback exception versus valid backend that raises from `attest` with `finalize=INDETERMINATE`. Assert same `NO_GO/INDETERMINATE/no commit/no CIDs`, distinct `ATTEST_FACTORY` vs `ATTEST`, different `encode_upgrade` bytes, and no stage/park/commit; update factory-return-invalid test to assert the new phase. Add tamper and historic `ATTEST` cases through real `verify_upgrade`.
- [ ] **Step 2: Run RED**: `uv run --locked --offline pytest -q tests/test_host_boca_pair_upgrade.py tests/test_host_boca_pair_upgrade_cli.py`. Confirm failure is precisely missing `ATTEST_FACTORY` classification, not an unrelated setup error.
- [ ] **Step 3: Minimal GREEN**: add exactly `ATTEST_FACTORY` to `PairPhase`; change only factory `except BaseException`'s `failed_phase`. Add a branch in `_upgrade_fields_ok` rejecting `ATTEST_FACTORY` unless the six fixed fail-closed conditions hold. Keep all other phases, exception handling and terminal transport unchanged.
- [ ] **Step 4: Run focused GREEN** using the same command, then `uv run --locked --offline pytest -q` for the whole project, `uv run --locked --offline ruff check src/boca_socios/host_boca_pair_upgrade.py src/boca_socios/host_boca_pair_upgrade_cli.py tests/test_host_boca_pair_upgrade.py tests/test_host_boca_pair_upgrade_cli.py`, and available mypy/CI equivalent. Record exact outputs. Do not suppress failures.
- [ ] **Step 5: Update the four existing Markdown checkpoint files**, preserving their statuses and links; distinguish observed G17 physical readiness from retrospective RCA and prospective route instrumentation. No new claims of installed G18.
- [ ] **Step 6: Self-review diff** for only enumerated source/tests/docs; verify no workflow, Docker, journal, host, image or unrelated changes. Commit locally on the isolated branch with a clear `fix(g18): distinguish factory refusal in future ATTEST receipts` message. **Do not push or create PR** until Root's independent review and explicit 4GO_FINAL.
