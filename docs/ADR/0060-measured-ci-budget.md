# ADR 0060: optimize CI from measured critical-path evidence

**Status:** Proposed for issue #143, 2026-10-31. Measurement and documentation
only; workflows, required checks, runtime and host are unchanged.

## Evidence cut

The owner requested efficient parallel testing without reducing integrity.
The current measured source is
`4922e45b5e2e38242263b6ba10969a8190aa939a`. Times below are rounded step/job
timestamps returned by the GitHub Actions jobs API, except the explicit
BuildKit and Chromium probe measurements taken from their logs. These are
two successful runner observations, not a controlled before/after benchmark
or a latency guarantee. No new host or benchmark dispatch was performed.

| Observation | Current main | Historical PR candidate |
| --- | --- | --- |
| CI source SHA | `4922e45b5e2e38242263b6ba10969a8190aa939a` | `aac9c3b0109880f0c6cc7328d332fae85d3a4e3e` |
| CI run | [41259139901](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41259139901) | [41256992584](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41256992584) |
| Quality job | 16 s, job 124708570514 | 19 s, job 124702163333 |
| Full pytest step | 4 s | 4 s |
| Image job | 41 s, job 124708570366 | 49 s, job 124702163507 |
| Controller build | 8 s | 8 s |
| Chromium build | 28 s | 36 s |
| Offline Chromium startup step | 2 s | 2 s |
| Separate image-security job | 28 s, job 124708570422 | 25 s, job 124702163191 |
| Scan's controller build / scan | 11 s / 10 s | 8 s / 10 s |

The current [security run 41259139886](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41259139886)
is independent of CI. Historical PR-only release validation
[41256992623](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41256992623)
built another controller in 13 s and scanned in 9 s; first-deploy PR smoke
[41256992640](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41256992640)
built in 7 s. Those four independent builds use the same candidate source,
but this does not prove their image bytes/digests are identical. The six
active historical candidate jobs all started 3 s after run creation; this
sample does not show a runner-capacity bottleneck. Publication and host jobs
were correctly excluded from that PR event.

## Decision and alternatives

Retain the current full suite and parallel independent workflows. PR #136
already separates first-deploy PR groups while preserving the manual host
mutex; do not add another concurrency mechanism for the same defect.
Stabilize each candidate before pushing routine formatting/source corrections
and reconcile final integration in order, retaining strict up-to-date checks.
This reduces avoidable repeated work without accepting stale source evidence.

Do not introduce cache/artifact plumbing merely because builds are repeated:

- Pytest sharding can save at most the observed 4 s before extra runner setup,
  dependency installation and report aggregation. It complicates the RCA gate
  that verifies the one complete suite. There is no measured benefit here.
- Splitting the image job into controller/browser jobs removes at most the
  observed 8 s controller build from the critical path. Extra checkout and a
  fail-closed aggregate `image-build` job consume part of that margin. The
  8 s spread between the two browser observations already matches that upper
  bound. Do not claim an improvement without a controlled measurement.
- Current browser BuildKit logs attribute 21.2 s to base-image materialization,
  including 13.2 s extracting one layer. Installing uv took 2.5 s and browser
  dependencies 0.7 s. A dependency cache does not establish that extraction
  will disappear. A layer cache must measure restore/export and extraction,
  not just report a cache hit; cold and warm total times both matter.
- Building one controller artifact and feeding scan/smoke jobs could reduce
  aggregate runner work, but each existing local build costs only 7-13 s in
  this cut. Export/upload/download/import, digest verification and new job
  dependencies have not been timed. Their net latency and storage effect are
  UNKNOWN, so artifact reuse is deferred rather than asserted faster.

If later measurements justify such a change, use an isolated PR experiment
on disposable runners and compare end-to-end completion plus aggregate job
time for the same source/lock/base digest. Cache contents never replace the
current scan or frozen lock. Artifacts must be bound to exact run/SHA and
digest, and consumers must fail on absent, mismatched or incomplete artifacts.
Do not promote a PR artifact into a privileged publication. Manual release
continues to build and scan its reviewed current-main image before publishing
its immutable digest. Preserve the required `image-build` result, complete
test report and accepted RCA selectors; no skipped/failed dependency may
produce a successful aggregate check. No new benchmark is scheduled here.

## Browser capacity scope

Current main's offline probe reported `elapsed_ms=1226`, `cpu_ms=1130`,
`peak_memory_mib=185.0`, `peak_pids=77` under 768 MiB, 1 CPU and 128 PID caps,
with network disabled and an isolated disposable runner. This is one startup,
not a loaded page, session-concurrency test or droplet capacity result. In
particular, its 77 observed PIDs exceed the dormant controller's 64 PID limit;
do not embed Chromium in that controller or infer a safe memory budget from
one peak. A future worker needs its own reviewed budget/isolation and a
separately authorized host preflight. No droplet stress test, browser visit,
host resource increase, database operation or installation follows from this
measurement.

## Delivery boundary

This decision records why an optimization is not yet supported by evidence;
it adds no runtime/source behavior, so implementation regression tests are not
applicable. Existing CI still runs for the document candidate. README,
operations and integration capabilities are unchanged. The coordinator must
link the measurement outcome in the continuity checkpoint before closing
issue #143; no claim that caches or build reuse have been implemented is valid.
