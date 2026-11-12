# R182 Consolidated BETA Owner Transfer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:executing-plans` for this inline plan; each result is recorded against the exact GitHub SHA.

**Goal:** Deliver already-tested #12 contracts together with the existing #417
SIMULATION_ONLY BETA in a single protected install, without waiting for Boca
or Queue-it to be live.

**Spec:** `docs/superpowers/specs/2026-11-12-r182-owner-transfer-consolidated-beta-design.md`

## Task 1 — Policy and factual handoff

- [x] Record owner transfer and nonblocking dormant-source classification in
  `AGENTS.md`, `docs/DEVELOPMENT_POLICY.md`, README and OPERATIONS.
- [x] Verify no changed Docker, Compose, protected workflows or browser
  blackboxes; run policy and whitespace checks.
- [ ] Update PR #484 and issue #417 with the actual candidate SHA, scope,
  exact results and new owner; no deployment claims.

## Task 2 — Code integration

- [x] Complete independent technical review of #484, including policy delta
  and existing #12 TDD; no P0/P1, three P2 documentation notes resolved.
- [x] Run `ruff check`, `ruff format --check`, `mypy src`, `pytest -q`
  and `check_repo_policy.py`; preserve sandbox SKIP evidence. Run
  `uv sync --frozen` before publishing.
- [ ] Publish one amended HEAD to the existing #484 branch and require its
  exact-SHA GitHub checks before protected merge.
- [ ] Merge #484 once, record final main and verify no PR open and postmerge
  CI/security. If protected merge rejects, report reason and stop.

## Task 3 — Protected single release and host observations

- [ ] Verify Actions/Artifact incident recovered with a fresh, bounded check.
- [ ] Dispatch one manual `release-image.yml` from reviewed final main;
  require dual manifest artifacts/digests from the same run, source and SHA.
- [ ] Run `cutover-a-census`, `boca-pair-observe`,
  `boca-binding-observe`, `boca-sqlite-inode-observe` READ_ONLY with fresh
  receipts and no foreign or ambiguous resources.
- [ ] Only after all acceptance gates pass, dispatch exactly one protected
  `boca-pair-upgrade-apply` on Boca rootless with contractual budget and pins.
  No SSH or Docker host command from this workspace, no blind retry.

## Task 4 — Acceptance and closeout

- [ ] Require terminal `state=ACCEPTED`, selective Boca-only cleanup,
  fresh postflight and passkey owner verification of panel and synthetic bot.
- [ ] Verify `SITE_URL` saved/applied after START, worker IPC and PID,
  DNS IPv4/HTTPS egress within Boca rootless, and Telegram sender OFF.
- [ ] Preserve NO_GO for real login/tokens and sidecar until separate honest
  physical evidence; update #417/#12 and release documentation with SHA and
  actual runtime observations, then report completion or exact blocker.

## Review focus

- A CODE_ONLY/CI-success claim must never imply an installed controller.
- Missing token sources must not trigger network requests or fabricate data.
- The prior failed release and stale host observations must never be reused.
- A new PR or active host lease must pause the one protected deploy.
- No external app, Docker project, volume or port may be mutated.
