# Resource observations and capacity policy — 2026-11-02

## Verified starting point

Main `5ddfba568d0b53168f51c0e5b33c363ba24c505e`, tree
`c8f439a76e0dd3a4513d4dc4d28650bf568211ef`, has passing
[CI 41495122362](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41495122362)
and [security 41495122337](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41495122337).
The real Docker lifecycle smoke on its identical reviewed candidate tree
passed in [41494321017](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41494321017).
That proves the exercised runner scenarios, not deployment on the droplet.

The existing `scripts/measure_browser_budget.py` already measures a single
offline Chromium startup. Its current-main receipt, from
[job 125447926866](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41495122362/job/125447926866)
at 2026-11-02 14:52:46 ART, reports:

| Counter | Observation |
| --- | ---: |
| Cgroup memory peak | 182.1 MiB |
| Cgroup task peak | 77 |
| Container CPU used during the observation | 1072 ms |
| Monotonic elapsed time | 1079 ms |

This is one startup on a disposable GitHub runner under the configured
768 MiB / 1 CPU / 128 task caps. It is not a measurement of the complete
controller/browser/Telegram combination, a loaded public page, the droplet,
multiple sessions, or a necessary minimum. Reuse this receipt; do not run an
extra experiment merely to reproduce it.

## Host observation

[Inspection 41495516709](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41495516709)
at 2026-11-02 14:54:42 ART observed `MemAvailable=1020020 KiB`
(996.11 MiB) and the existing `cpu_headroom=0.27` estimate. The dedicated
daemon was inactive and its private socket absent; delegated free tasks,
effective daemon version and storage were not verified. The inspection
performed no Docker operation and explicitly reported
`capacity_gate=not_evaluated`. It did not execute the BETA.

[Port check 41497093298](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41497093298)
at 2026-11-02 15:04:45 ART found `127.0.0.1:8443` free at that instant,
without reserving it or starting a listener beyond the bounded bind check.

## Provenance and limits of the configured policy

| Topology | Sum of container caps | Existing pre-start threshold | Added margin |
| --- | --- | --- | --- |
| Controller + browser | 1024 MiB / 1.5 CPU / 192 tasks | 1536 MiB / 1.75 CPU / 256 tasks | 512 MiB / 0.25 CPU / 64 tasks |
| Controller + browser + sender | 1152 MiB / 1.75 CPU / 224 tasks | 1792 MiB / 2 CPU / 288 tasks | 640 MiB / 0.25 CPU / 64 tasks |

PR #247 introduced the pair threshold; PR #253 added the three-service
threshold. They are implementation choices. The source comment reserves
space for Docker and bounded probes; no recorded benchmark establishes those
exact margins as necessary minima. Caps are upper bounds, not actual usage.
The preflight checks values; it does not reserve CPU, RAM or tasks physically.

The CPU estimate is `max(0, affinity_count - loadavg_1m)`. It is not measured
idle CPU or the application's demand. With two CPUs in the affinity mask,
the threshold of 2.0 would require the load average to be exactly zero.
This conditional example does not assert the droplet's current affinity.

The host reading did not meet the configured reserves. It does **not** prove
that the BETA cannot run on that server or that new infrastructure is needed.
[Issue #259](https://github.com/mbalbo2023/boca-socios-assistant/issues/259)
corrects that earlier interpretation while preserving the observations.

## Measurement and decision boundary

Extend the existing lifecycle smoke with bounded cgroup observations around
the scenarios it already performs. Keep one context, the same container caps
and network restrictions, and no additional public requests or stress load.
Report each service and lifecycle phase separately, with exact source and
container-start identity. Mark absent counters unknown, account for probe
overhead, and do not add unrelated service peaks or interpret a cumulative
peak as a phase delta.

The runner experiment and a protected host infrastructure preflight answer
different questions. Neither alone demonstrates production performance.
Any proposed capacity-policy correction must cite the resulting evidence,
preserve enforceable container limits, explain its assumptions and pass
independent review. Do not replace an unmeasured reserve with another guessed
number or suppress a failed gate to report success. The measurement work
does not authorize a change to other workloads or the server's size.

Primary interface references:

- [Linux cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)
- [Linux Pressure Stall Information](https://docs.kernel.org/accounting/psi.html)
- [Docker resource constraints](https://docs.docker.com/engine/containers/resource_constraints/)

This report records the verified starting point. Later candidate and host
receipts must be added with their exact scope; missing measurements are not
zero and an unexecuted check is not PASS.
