# ADR 0021: Measure one offline Chromium worker without loading Boca

Status: Proposed for issue #11, 2026-10-28. Depends on the review-only worker
in PR #43; no deployment or authenticated session is included.

## Decision

Run exactly one Chromium startup/close in a separate CI container with the
same nonroot user, sandbox, seccomp, no-network boundary and 1 CPU / 768 MiB /
128 PID caps from PR #43. Read cgroup v2 `memory.peak`, `pids.peak` and
`cpu.stat:usage_usec`, plus monotonic elapsed time. Fail if `memory.max`,
`pids.max` or `cpu.max` is unreadable, unlimited or above the configured
caps. The smoke already uses `about:blank`; no site or fake ticket UI is
visited. Print only rounded aggregate counters and a fixed mode label.

The measurement includes image startup/Python/Chromium in one ephemeral
container. `pids.peak` counts tasks in the cgroup, not Boca members; CPU
delta is total container CPU during the run. Memory peak is monotonic from
container creation. These figures are a **single CI baseline**, not a p95,
not capacity on the droplet, not a visit to Boca and not evidence of a
reservation. A run with no cgroup v2 support or a missing limit is NO-GO
instead of silently reporting a process-only estimate.

## Next gates

Record the actual Actions run values and investigate any resource headroom
below the container caps. A real public observer visit needs a separate
one-shot network policy and approved nonproduction environment; an
authenticated account and ticket step need further authorization. Measuring
2/4/8 sessions or sending repeated traffic to Boca requires a different
review and specific consent. The shared droplet must not be benchmarked here.

Source: [Linux kernel cgroup v2 interface](https://docs.kernel.org/admin-guide/cgroup-v2.html).
