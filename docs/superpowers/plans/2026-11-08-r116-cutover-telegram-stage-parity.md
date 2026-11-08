# R116 Cutover IPC Telegram staging parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the real V3 IPC controller receive and attest the encrypted Telegram staging opt-in already approved in Compose.

**Architecture:** Keep the existing direct Docker create path and existing Config.Env postflight parser. Add one required literal environment value to each; do not create a new workflow, service or data path.

**Tech Stack:** Python 3.12, pytest, Ruff/MyPy, existing Docker inspect model fixtures.

**Spec:** `docs/superpowers/specs/2026-11-08-r116-cutover-telegram-stage-parity-design.md`

## Global Constraints

- SIMULATION_ONLY; controller `BOCA_ENGINE_MODE=off`; only `127.0.0.1:8443`; no Telegram sender activation.
- Keep blackbox `src/boca_socios/browser/synthetic.py` and `src/boca_socios/browser/ipc_worker.py` uninspected, unmodified and unexecuted.
- Use exact existing Cutover V3 route; no host dispatch or Docker production operation.
- No Porota/foreign workloads, host-wide Docker cleanup, backups, schema 0008 or real Boca tickets.
- Maintain `BOCA_TELEGRAM_PAIRING_STAGE_MODE=encrypted-only` only for IPC controller; legacy/off mode stays unchanged.
- TDD first, full applicable quality/isolation gates, one scoped PR and factual issue #354/#45 checkpoint.

## Review Focus

1. Missing opt-in in Docker argv must be caught by the creation-contract test (Task 1).
2. Postflight Config.Env missing the opt-in must fail closed (Task 2).
3. Postflight `off` or alternate value must fail closed (Task 2).
4. Duplicate Config.Env entry must fail closed even with one correct value (Task 2).
5. Staging must remain absent in the legacy Compose and worker container (existing `test_telegram_stage_compose_optin_r27` in Task 2).

---

### Task 1: V3 creates the IPC controller with encrypted stage opt-in

**Files:**
- Modify: `tests/test_host_cutover_adapter.py`
- Modify: `src/boca_socios/host_first_deploy.py` (`_cutover_candidate_create_argv`)

**Interfaces:**
- Consumes: exact literal `BOCA_TELEGRAM_PAIRING_STAGE_MODE=encrypted-only` from `compose.beta.browser.yaml` / ADR0157.
- Produces: `_cutover_candidate_create_argv(...) -> tuple[str, ...]` including `--env` and the literal; no signature change.

- [ ] **Step 1: Write failing test.** Add `test_candidate_argv_enables_only_encrypted_ipc_telegram_stage` that calls the real builder, gathers Docker `--env` arguments and asserts exactly one `BOCA_TELEGRAM_PAIRING_STAGE_MODE=encrypted-only` and no `BOCA_TELEGRAM_TOKEN` or sender env.
- [ ] **Step 2: Verify RED.** Run `uv run pytest -q tests/test_host_cutover_adapter.py::test_candidate_argv_enables_only_encrypted_ipc_telegram_stage`. Expected: FAIL because the opt-in is absent.
- [ ] **Step 3: Implement minimum production change.** Add only the literal `BOCA_TELEGRAM_PAIRING_STAGE_MODE: encrypted-only` to `values` in `_cutover_candidate_create_argv`.
- [ ] **Step 4: Verify GREEN.** Run the same selector. Expected: PASS.
- [ ] **Step 5: Stage task changes for the final atomic PR commit.** No intermediate push or release.

### Task 2: Inspect the effective controller environment and reject drift

**Files:**
- Modify: `tests/test_host_browser_ipc_install.py` (`controller_record` + new negative regressions)
- Modify: `src/boca_socios/host_first_deploy.py` (`_browser_controller_postflight`)

**Interfaces:**
- Consumes: the environment contract produced in Task 1.
- Produces: `_browser_controller_postflight(...) -> None` refusing missing, `off`, alternate and duplicate values; no signature change.

- [ ] **Step 1: Write failing test.** Use the existing complete `controller_record()` fixture, explicitly set the correct opt-in for the valid baseline, then parametrically delete, change to `off`, change to another string, or duplicate the entry. Assert the real postflight raises `PreflightError` for each; keep existing Docker-boundary test. Do not replace the postflight with a mock.
- [ ] **Step 2: Verify RED.** Run `uv run pytest -q tests/test_host_browser_ipc_install.py::test_controller_postflight_requires_encrypted_stage`. Expected: FAIL because missing/wrong values currently pass.
- [ ] **Step 3: Implement minimum production change.** Add the same exact entry to the existing `variables` expectations in `_browser_controller_postflight`, preserving duplicate rejection and all other assertions. Update the complete existing record fixture to reflect the approved opt-in.
- [ ] **Step 4: Verify GREEN and compatibility.** Run `uv run pytest -q tests/test_host_browser_ipc_install.py tests/test_host_browser_runtime_lifecycle.py tests/test_host_cutover_adapter.py tests/test_telegram_stage_compose_optin_r27.py`. Expected: all PASS.
- [ ] **Step 5: Stage changes for the same atomic PR commit.** No workflow changes.

### Task 3: Document RCA, quality and code-only handoff

**Files:**
- Create: `docs/ADR/0212-r116-cutover-ipc-telegram-stage-parity.md`
- Modify: `README.md` (new factual, dated top summary)
- Modify: `tests/test_r82_recovery_bundle.py` (pin determinista nuevo, histórico R114 conservado)
- Modify: `docs/quality/rca-lessons.json` **after PR number exists**, if CI tracker accepts the new entry and exact selector.

**Interfaces:**
- Consumes: exact test results and PR identity from Tasks 1-2.
- Produces: truthful CODE_ONLY integration/worker-outstanding statement and issue #354/#45 evidence.

- [ ] **Step 1: Write ADR and README summary.** Document Compose/argv/postflight mismatch, deterministic RED→GREEN evidence, limits, code-only status and worker ExitCode1 independence.
- [ ] **Step 2: Run full applicable local gates.** `uv sync --frozen`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`, `uv run pytest -q`, `uv run python scripts/check_repo_policy.py`; preserve blackbox exclusions. The first full run is expected to reveal a stale pinned Cutover ZIP digest after source edits; preserve the historical pin, calculate/review the deterministic replacement and add the exact-current pin regression before rerunning. Expected final: all PASS; report any failure, error or excluded tests.
- [ ] **Step 3: Commit scoped code, tests and docs together.** `git status` and `git diff --check` before a single atomic commit to `feature/354-cutover-telegram-stage-parity`.
- [ ] **Step 4: Open one reviewable PR against current exact main, obtain independent architecture/QA review and exact SHA CI.** If `rca-lessons.json` requires a concrete new PR number, add it in a final small follow-up commit and rerun the gates on that exact SHA.
- [ ] **Step 5: Record Rule84 checkpoint in issues #354 and #45.** Include merge/release status; keep physical BETA, Telegram and Cutover as NO_GO until separate physical receipts. Never dispatch host from this task.
