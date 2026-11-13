# R259 Same-Lease Technical Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind the already reviewed successor actor, official SUCCESS V2 cleanup, and durable technical postflight to a single protected lease without asserting owner/BETA acceptance.

**Architecture:** Keep R253's inert actor graph unchanged. A narrowly typed adapter delegates stage/PARK/new container creation/retirement to its existing reusable backend and replaces the old `gate=None` finalization with official V2 cleanup followed by R255 two-phase expected, R253 volume custody, and R257 terminal proof. The CLI remains NO_GO until the new route's current-main, URL-absence, rootless mapping, ZIP budget, and physical preflight contracts are independently validated.

**Tech Stack:** Python 3.12, pytest, Ruff, mypy, Docker rootless Boca-only production adapters, immutable O_EXCL journal.

**Spec:** [ADR0270](../../ADR/0270-r253-inert-one-journal-same-lease-assembly.md), [ADR0271](../../ADR/0271-r255-two-phase-prepark-postflight-expected.md), [ADR0274](../../ADR/0274-r257-technical-terminal-same-lease-code-only.md), R186 no-replay in AGENTS.md.

## Global Constraints

- No Porota, external providers, live bookings, TLS downgrade, queue bypass, extra Docker service/port or credential output.
- Exactly one authenticated BocaJobLease and SuccessorPairJournal; no new lease, no extra Docker cleanup or retries.
- Owner passkey/worker/monitor remain unverified after a technical SUCCESS.
- Missing SITE_URL may only be admitted by a separate schema-2 cold-worker acceptance profile proven both before and after installation; never invent a digest.
- Fail closed before commit when any precommit source/provenance/inode check is incomplete.

## Review Focus

- Foreign lease/object graph: constructor/delegates refuse before host effects; test identity guard.
- Missing/unsafe SITE_URL: no PARK or commit; test attest boundary.
- Duplicate finalize/technical proof: one-way consumed before external calls; test duplicate rejection.
- Postcommit official cleanup failed or uncertain: no technical ACCEPT/no second cleanup; test NO_GO state.
- Terminal ACCEPT without durable proof or wrong new CID: fail; test binding of expected CIDs to engine receipt.

---

### Task 1: Strict actor wrapper (CODE_ONLY)

**Files:**
- Create: `src/boca_socios/host_boca_guarded_successor_backend_v4.py`
- Test: `tests/test_host_boca_guarded_successor_backend_v4.py`

**Interfaces:**
- Consumes: `InertSameLeaseAssembly`, `OneShotTechnicalTerminalBridge`, `BocaJobLease`, `PreParkExpectedSeed`.
- Produces: `GuardedTechnicalSuccessorBackend` matching `PairUpgradeBackend`, with class-level `requires_persistent_receipt=True` but no standalone CLI or host entrypoint.

- [ ] Write RED tests for inert construction, graph/lease antirebind, pre-PARK source capture, exact delegate order and terminal-phase refusal.
- [ ] Run `uv run pytest -q tests/test_host_boca_guarded_successor_backend_v4.py` and record expected import/contract RED.
- [ ] Implement minimum typed wrapper: captured lease, one-way stage/finalize, reviewed underlying actor only, exact same-lease journal, official V2 SUCCESS followed by durable technical proof only.
- [ ] Run focal tests GREEN; verify with existing R253/R255/R257 tests.

### Task 2: Review CLI eligibility without promotion

**Files:**
- Inspect only: `src/boca_socios/host_boca_pair_upgrade_cli.py` and PR #501 backend factory.
- Document: `docs/ADR/0280-r259-protected-technical-backend-activation-gate.md`.

**Interfaces:**
- Future protected CLI must call `_successor_preflight` only from verified memfd; after durable intent create the bound adapter through `backend_factory(plan, held_lease)`. Never call historical R179 `apply`.

- [ ] Verify exact PR501 engine factory contract and blockers (rootless UID map, SITE_URL cold-worker, ZIP allowlist/cap, host physical receipts).
- [ ] If any path remains unverified, leave `main apply` pre-effect NO_GO and document the blocker instead of flipping it.

### Task 3: Full verification and handoff

**Files:** `README.md` and this plan, ADR0280, source/tests owned above.

- [ ] Run `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`, `uv run pytest -q -n 2`, `uv run python scripts/check_repo_policy.py`.
- [ ] Record exact local SHA, test count, ZIP budget impact and inherited/current-main caveats. Commit in isolated worktree only; no GitHub push/host dispatch.
