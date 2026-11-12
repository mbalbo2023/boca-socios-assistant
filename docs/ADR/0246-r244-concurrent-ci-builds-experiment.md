# ADR0246 — Concurrent controller/browser CI builds, with a measured promotion gate

Date: 2026-11-12. Issue: #417. Status: **CODE_ONLY / EXPERIMENT**.
Base commit: `032990875feec8cd3715fb9e201277362656dd4a`.

## Critical-path evidence before this candidate

The successful `main` [CI run 43281076127](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43281076127)
completed `image-build` in approximately **254 seconds**. Its sequential
controller/browser Docker builds consumed about **14 + 36 = 50 seconds**;
Trivy scans about **15 + 18 = 33 seconds** and the many remaining runner
probes roughly **171 seconds**. The parallel `quality-and-tests` job took
about 119 seconds; independent image-security jobs were about 33/80 seconds.
These observations do **not** establish any cache speedup or stable p95.

Only the 14-second overlap is available from build concurrency on an ideal
runner. The modeled build-pair critical path is `max(14,36)=36` seconds,
but actual CPU, network, BuildKit disk and APT contention may erase that
benefit or make the job **slower**. No observed after-duration exists yet.

## Decision for a safe experiment

In the existing required `CI / image-build`, replace the two adjacent
sequential build steps with one shell step which launches the **same two**
`docker build` calls concurrently. Controller and browser build different
Dockerfiles and use disjoint tags. Each writes a log in `$RUNNER_TEMP`.
The parent shell waits for both completion statuses, prints the two logs,
reports per-role execution seconds and total wall seconds, and fails if
**either** returned nonzero. Thus later immutable-image alias checks,
Trivy scans, offline Chromium, disposable Docker labs and cleanup still
gate the exact same locally built pair. No third image build or new job is
added; `quality-and-tests` and `image-build` contexts are unchanged.

No `cache-from`, `cache-to`, Buildx GHA cache, artifact, GHCR upload or
other cross-run state is introduced. The branch includes no protected
release/first-deploy/host workflow edits and does not depend on PR artifacts
for main promotion. The manual protected release remains independently
source-bound, re-built and scanned, as required by ADR0239.

## Regression design and evidence limitations

`tests/test_ci_concurrent_image_builds.py` executes the YAML-extracted
**real Bash build body** with a disposable Docker-command fixture:

- A rendezvous requires both builds to start before either can finish,
  detecting accidental sequentialization.
- Separate controller-only, browser-only and dual-failure cases require
  both background processes to finish and a red step, including both logs.
- The exact source/revision label, browser attempt label, role tags and
  all scan/observer aliases must survive unchanged.
- Scanner steps remain after the shared build barrier, without a bypass
  `if: always()` condition; independent existing tests cover both scans,
  alias IDs, role packaging and the no-publish/no-deploy boundary.

This fixture proves shell orchestration only. It cannot prove actual
Docker images build on concurrent GitHub BuildKit, pinned APT packages
resolve in parallel, both Trivy databases scan, Chromium starts or runner
wall time improves. In particular, GitHub-hosted jobs have unobserved
resource contention and ephemeral Docker caches. Local Python tests are
not a substitute for a hosted exact-SHA green CI report.

**Local TDD receipt (2026-11-12):** the five R244 tests first failed because
the combined step was absent, then passed against the changed shell. The
initial full suite caught three existing tests that expected historical
separate step names; their narrow assertions were updated to verify the
single build barrier and exact two-role provenance, without placeholders.
Final two-worker suite: **7345 passed +34 subtests passed**, **one** sandbox
AF_UNIX `EPERM` skip (`test_r177_fixture_probe_transport.py:72`). Ruff,
format, mypy and repository-policy gates passed. YAML parsed with 37
`image-build` steps and exactly two Docker build invocations. No `docker`
binary is available locally, so real concurrent image builds remain
**UNVERIFIED** until Actions; the local socket skip is not permitted to
silently satisfy the hosted RCA gate.

## Promotion decision, to be recorded from routine CI

Keep this candidate CODE_ONLY until one reviewed, final-SHA PR CI run:

1. Reports `BOCA_CI_BUILD` for **both** roles and
   `BOCA_CI_BUILD_PAIR result=PASS` with the same exact SHA.
2. Completes image identity/alias gates, two Trivy scans, all offline
   Chrome and Docker labs, always-run cleanup, full quality/RCA suite,
   without skipped/softened checks.
3. Provides the build-pair elapsed time, full `image-build` job duration,
   CI wall time and runner-use comparison against the documented baseline.
   Separate startup/queue jitter, APT mirror variance and scan timing;
   a single run is indicative, not a p95 guarantee.
4. Is measured against **one pair** of comparable successful existing
   Actions, never against added parallel R240 attestors that cost extra
   runner-seconds without reducing the required CI critical path.

If the hosted build pair is slower or the critical job does not improve,
revert this experiment before merge; do not dress up a nominal 14-second
upper bound as proven acceleration. Do not dispatch redundant CI runs
solely for benchmarking. Review of the change is not authorization to
publish or operate the Boca droplet or any other host workload.
