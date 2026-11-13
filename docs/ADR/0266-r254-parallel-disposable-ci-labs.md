# ADR0266 — Parallelize two independent disposable CI labs

Date: 2026-11-13 ART. Issue: #417. Status: **CODE_ONLY / MEASUREMENT EXPERIMENT**.
Original base: `b58131292d` (`main` at the start of this independent worktree).

## Problem and evidence

The current required `CI / image-build` job executes one controller and one
browser-worker BuildKit build, then serial disposable Docker labs. In the
successful `main` [run 43345541126](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43345541126),
`image-build` took **272 seconds**, while `quality-and-tests` took 133 seconds
in parallel. The two eligible independent labs took **18 seconds** and
**23 seconds**, respectively. The current two-image BuildKit cache, both Trivy
scans and required job contexts are already retained.

ADR0246 tested concurrent image *builds* in hosted CI and rejected that
experiment after a nominal 3-second build-pair saving and no measured
critical-path improvement. This proposal does **not** repeat the build
experiment, reorganize release provenance or revive duplicate PR jobs.

## Narrow design

Within the existing `CI / image-build` job only, after the exact controller
and browser pair are available and frozen runtime dependencies installed:

1. Start `scripts.check_worker_start_capture` with its original `python3 -m`
   entrypoint and a **120-second bounded** subprocess. Its disposable worker
   fixtures use `network none`, unique attempt labels and exact CID cleanup;
   it does not publish a port.
2. Start `scripts.lab_panel_restart_921` using its original
   `uv run --no-sync` entrypoint and a separate **180-second bounded**
   subprocess. Its controller fixture uses the runner's loopback 8443 and
   verifies its exact CID and cold stop/restart. The capture lab never binds
   this port.
3. Wait for **both** processes regardless of the first exit status; retain
   their two complete stdout/stderr streams in separate, mode-0600 temporary
   runner files and print both logs with named sections. A single finite
   summary records both exit codes and wall seconds. Any nonzero code,
   including timeout, is **FAIL**, blocking the remaining image consumers.

No further CI lab runs concurrently with these two. The existing downstream
image alias checks, offline Chromium, both separate Trivy HIGH/CRITICAL scans,
disposable HTTP/SQLite/sender labs and always-run cleanup remain on the same
exact image pair. No third image build, registry access, host connection,
untrusted artifact, elevated token or deployment path is introduced. Both
branch-protected check names remain unchanged.

## Verification and risks

The added TDD test executes the **real extracted workflow Bash**, replacing
only the two Docker-calling external programs with fixed disposable local
executables. A rendezvous proves they overlap. Five cases prove joint success,
capture-only failure, panel-only failure, simultaneous failure and a synthetic
timeout-like exit code; all must finish, retain and print both mode-0600 logs,
and produce a fail-closed status if either fails.
The sixth assertion enforces exactly two BuildKit role builds, two separate
Trivy steps and the barrier ahead of downstream consumers. The test was RED
before the workflow change and GREEN afterward. Local source checks are not
physical Docker or GitHub-hosted performance evidence.

The theoretical saving is **at most 18 seconds** before orchestration and
Docker-daemon contention, **not hours**; a shared two-core runner could save
less or even run slower. Real acceptance requires an ordinary, final-SHA PR
run with both lab logs, `BOCA_CI_PARALLEL_LABS result=PASS`, image scan/lab
and cleanup SUCCESS, and `image-build` wall seconds compared against similar
successful single-pair CI runs. If there is no material critical-path gain,
retire the experiment before merge. A green local test is not authorization
to publish a release or operate the droplet; `DEPLOY NO_GO` continues pending
same-lease physical proof and postflight.
