# ADR 0021: Measure one offline Chromium worker without loading Boca

Status: Proposed for issue #11, 2026-10-28. Depends on the review-only worker
in PR #43; no deployment or authenticated session is included.

## Decision

Run exactly one Chromium startup/close in a separate CI container with the
same nonroot user, sandbox, seccomp, no-network boundary and 1 CPU / 768 MiB /
128 PID caps from PR #43. Pin a private cgroup namespace so the cgroup root
read inside the worker represents the bounded container, independent of the
Docker daemon default. Read cgroup v2 `memory.peak`, `pids.peak` and
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

Actions [run 40780362578](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40780362578)
passed both jobs on the first candidate. Its one offline startup reported
**185.3 MiB** memory peak, **76** peak cgroup tasks, **921 ms** CPU usage
delta and **1142 ms** elapsed. These are CI runner observations under the
768 MiB/128 PID/1 CPU caps, not a resource budget for a real Boca visit or
another kernel. The final documentation commit must pass its own CI.

A real public observer visit needs a separate one-shot network policy and
controlled nonproduction environment with recorded agent technical review;
the owner does not require a second human approval. An authenticated account
and ticket step need their own reviewed gates. Measuring
2/4/8 sessions or sending repeated traffic to Boca requires a different
review and specific consent. The shared droplet must not be benchmarked here.

Sources: [Linux kernel cgroup v2 interface](https://docs.kernel.org/admin-guide/cgroup-v2.html),
[Docker cgroup namespace flag](https://docs.docker.com/reference/cli/docker/container/run/).
