# Boca Physical Worker Probe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Physically boot and classify corrected worker image #810 once on the Boca rootless droplet, with exact-CID cleanup and zero Cutover.

**Architecture:** A new dispatch-only operation in the established protected `boca-first-deploy.yml` authenticates immutable release provenance and sends one SHA-verified host-only bundle through the existing SSH/memfd channel. The host creates a disposable networkless worker with isolated IPC and the real Python entrypoint, captures its startup before START, then removes only its exact CID and verifies the original Boca pair unchanged.

**Tech Stack:** Python 3.12 stdlib, GitHub Actions, Docker Engine rootless CLI/Unix attach, pytest, mypy, ruff.

**Spec:** `docs/superpowers/specs/2026-11-10-worker-physical-probe-design.md`

## Global Constraints

- Rootless Docker UID/GID10001, exclusive socket `/run/user/10001/docker.sock`; SSH user `boca-deploy`, no sudo.
- Image source run `42847341532`, source SHA `31cc6987c30d705113d0323b0700c156fec97eb5`, reviewed browser digest `sha256:0f181b5eab2954453d2054866682efa94c8dbad577ec2adfa3774e68222070cb` and controller digest `sha256:822e88ca0ff617b94baa180c51261fcc0a40fb9d463bf6aeb61ed5c05ce46fad`.
- New Action run itself must be owner/main/PR0/attempt1, independently distinct from image source.
- Never import, open, edit or synthetic-test `synthetic.py` or `ipc_worker.py` in the runner. Never navigate a real site.
- No Cutover, controller restart, installed worker upgrade, host-wide cleanup or foreign Docker access.

## Review Focus

1. Host Docker socket/UID differs: fail before create; no fallback to rootful.
2. Worker image/caps/seccomp/IPC do not match: fail before START and clean exact container.
3. Lost ACK or signal during START: preserve one-start marker, then exact-CID compensation.
4. Physical error instead of healthy: allowlisted classification and exit/OOM, no raw stderr.
5. Post-cleanup controller/worker identity or engine drift: reject success and preserve NO_GO.

---

### Task 1: Host probe with exact-CID cleanup

**Files:** Create `src/boca_socios/host_worker_physical.py`, `tests/test_host_worker_physical.py`.

**Interfaces:** Host `main(['host', run_id])` accepts one GitHub run id; verifier `main(['verify', run_id])` validates an exact bounded public JSON line. Immutable run/digests are constants; runner and host never accept arbitrary Docker args.

- [ ] Write offline tests for fixed Docker command args, networkless+tmpfs+strict caps, exclusive marker, pre-armed attach, one START, failure classification, stop/remove by CID, controller unchanged, and receipt fail closed.
- [ ] Run tests to verify RED for missing behavior.
- [ ] Implement minimal host code around existing `host_boca_cleanup` lease, installed-binding reader, Docker capture module and positive identity snapshot.
- [ ] Run task tests and type checks GREEN.
- [ ] Commit only Task 1 paths.

### Task 2: Protected workflow route and bootstrap

**Files:** Modify `.github/workflows/boca-first-deploy.yml`, `scripts/build_protected_boca_bundle.py`, `scripts/boca_protected_memfd_bootstrap.py`; add `scripts/check_worker_physical_dispatch.py`, `tests/test_worker_physical_bundle.py`, `tests/test_worker_physical_workflow.py`, `tests/test_worker_physical_dispatch.py`.

**Interfaces:** `--worker-physical` builds an allowlisted host-only archive; bootstrap `worker-physical-once <run_id>` verifies exact ZIP SHA and contents; action verifies GitHub #810 release+PR0+main independently, and sends the bundle over pinned SSH.

- [ ] Write offline RED tests for new option/guard/blank pins, manifest provenance, minimal ZIP allowlist, one-shot SSH operation and receipt verification.
- [ ] Implement minimal mode in builder/bootstrap and protected workflow (with explicit no-Cutover and failure result).
- [ ] Run GREEN tests for route, archive and dispatch.
- [ ] Commit Task 2 paths.

### Task 3: Quality, review and physical witness

**Files:** New ADR/checkpoint in `docs/ADR/` only if architecture changes beyond the design, existing issue #417/#45 canonical receipts.

- [ ] Run exact full applicable test suite, frozen dependency checks, ruff/mypy and repository policy; record failures by name, never bypass BLACKBOX boundary.
- [ ] Conduct independent security/QA code review and address Critical/Important findings with RED→GREEN regression tests.
- [ ] Open one small PR from exact main, verify required checks on exact SHA and resolve before action.
- [ ] Authenticate successful #810 manifests and one reviewed protected worker Action from exact new main; observe live `healthy` or bounded error.
- [ ] Verify cleanup and original controller/worker unchanged; publish genuine host receipt to #417/#45. No Cutover.
