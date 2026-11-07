# R85 Cutover Observation Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Report only bounded fixed-code failure categories for future `cutover-a-observe` attempts, while retaining NO_GO on every failure.

**Architecture:** One runner-side classifier reuses the existing safe file reader; the existing workflow changes capture/reporting, not host command or protected bundles. A new test executes the real workflow shell with a fake SSH.

**Tech Stack:** Python 3.12 stdlib, Bash/GitHub Actions, pytest, Ruff, mypy, uv.

**Spec:** `docs/superpowers/specs/2026-11-07-r85-cutover-observe-provenance-design.md`

## Global Constraints

- Only Boca repository; no host shell, foreign Docker or new workflow. All physical actions exclusively through reviewed GitHub Actions.
- No owner BLACKBOX access or real Boca navigation; no secrets, raw SSH stderr, private paths or tokens in output.
- Existing `cutover-a-observe` SSH argv and successful READY fields unchanged; all failures NO_GO, no blind retries.
- Full, preflight and recovery ZIP byte-identical to R84. PR0 before release and Cutover.

## Review Focus

1. Unknown or dynamic host exception must never leak text; assert generic NO_GO and secret absent.
2. Exit=1 with nonempty/forged stdout cannot claim host-validity; assert UNVERIFIED.
3. Exit=0 with nonempty stderr or any non-710-byte stdout is refused before READY, with no raw output; 710 has a deterministic field-format derivation.
4. Special files, symlink/hardlink and replacing runner captures must be rejected by reused reader.
5. Excess or simultaneous SSH stream output cannot create unbounded disk writes; test child file-size limit and one dispatch.

---

### Task 1: Redacted classifier and live shell seam

**Files:**
- Create: `tests/test_r85_cutover_observe_provenance.py`
- Create: `scripts/check_cutover_observe_diagnostic.py`
- Modify: `.github/workflows/boca-first-deploy.yml` (only Cutover observe step)

**Interfaces:**
- Consumes `scripts.check_infrastructure_diagnostic._read_bounded(Path) -> bytes` with LIMIT=1024 and strict inode/owner checks.
- Produces `classify(code: int, stdout: bytes, stderr: bytes) -> tuple[int,str]` and `main(argv: list[str] | None = None) -> int`; CLI args `EXIT_CODE STDOUT_PATH STDERR_PATH`. Return zero and no print only for admissible rc=0; return nonzero and one fixed NO_GO line otherwise.

- [x] **Step 1: Write failing tests** for rc 1/124/137/255/other, exact literal allowlist, malformed/private data, zero-exit boundaries, symlink/hardlink/oversize and Bash fake SSH. Assert actual exit status and bounded step summary without testing mere source-text presence.
- [x] **Step 2: Verify RED** with `uv run pytest tests/test_r85_cutover_observe_provenance.py -q`; expected missing classifier/script and failure of existing Bash behavior. Subsequent RED also reproduced a forged `READY` under `PYTHONOPTIMIZE=1`, unbounded SSH if `ulimit` fails and overwrite through a preplanted symlink.
- [x] **Step 3: Implement minimum classifier** using the approved exact bytes table and reused strict reader; no regex over arbitrary error text and no raw print.
- [x] **Step 4: Update existing workflow step** with bounded private captures, exit-code parsing and summary, shorter bounded READY read, cleanup trap; do not change the SSH command/flags/timeout/args. The reviewed private directory uses `mktemp -d` and both captures are removed.
- [x] **Step 5: Verify GREEN** with the focused pytest command; review every mocked SSH action boundary and secure deletion of runner-only temporary stderr. **61/61 PASS** and four independent code reviews GO.

### Task 2: Documentation and whole-branch certification

**Files:**
- Create: `docs/ADR/0194-r85-cutover-observer-failure-provenance.md`
- Modify: `README.md`, `docs/quality/rca-lessons.json`
- Test: `tests/test_r85_cutover_observe_provenance.py` plus repository gates.

**Interfaces:**
- Consumes actual verified classifier and workflow behavior from Task 1. Produces factual Rule84 and RCA status, with test selector recorded for the reproduced loss of diagnostic information.

- [x] **Step 1:** Prove R84 ZIP SHA baseline versus modified tree and caps via existing `tests/test_r83_bundle_caps.py` and bundle build comparisons; any deviation fails the plan. All three ZIP digests remain unchanged.
- [x] **Step 2:** Update ADR, README and RCA prevention with precise code-only/host statuses; append new accepted lesson only after test runs and unique selector are known. RCA-417 extends existing 8/8 selectors while preserving the immutable historical fix_pr=426.
- [x] **Step 3:** Run `uv sync --frozen`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`, `uv run pytest -q` and `uv run python scripts/check_repo_policy.py`, and compare all results. CI-equivalent parallel suite: **4,885 passed, 34 subtests passed**; RCA gate: **45 lessons, 154 exercised selectors, 11 owner-attested blackbox selectors**. Specialized protected job: **1,191 passed**. No new skips or xfails.
- [ ] **Step 4:** Consolidate changes in one commit, review independently with Architecture/QA/Infra/DevOps, then one PR and exact final SHA Actions; no separate host operation until merged/main PR0 and new release.
