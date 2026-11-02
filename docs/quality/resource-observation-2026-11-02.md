# Resource observations and capacity policy — 2026-11-02

## Latest successful existing-smoke profile

The corrected candidate `3e34717735064cdae7dcbcef120f3b381f6cf7e4` passed
[smoke 41518027065/job125526497976](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41518027065/job/125526497976)
on test-merge `12ea553d7f86a6cbff06b6f0ed4ba5c30c3d7d95`. Its tree
`a32cedf8f68ec6977653da65e528efdfac5fe060` equals integrated main
`32506362be24d350424cfc1911627d038ff8059c`. All ten receipts were OBSERVED
at 2026-11-02 17:21:24–17:22:16 ART; the
[complete sanitized counters](resource-observation-2026-11-02-261-final.json)
retain their original timestamps and provenance.

| Service / phase | Cgroup lifetime peak MiB | Peak tasks |
| --- | ---: | ---: |
| Controller / HTTP acceptance | 47.16 | 9 |
| Browser worker / initial IPC | 188.38 | 79 |
| Browser worker / restart IPC | 188.39 | 79 |
| Offline sender / ready | 40.27 | 8 |

The existing 24-request synthetic HTTP probe passed with median 1.93 ms and
p95 11.78 ms. Real dual-service inspection, kernel IPC, retained-container
restart and isolated sender readiness passed; cleanup steps completed.
These are sequential observations of the existing runner scenarios, with
observer overhead and cumulative peaks. Do not add them into a simultaneous
three-service requirement or extrapolate to host capacity. No Bot API,
public-site request or droplet operation occurred. Container caps and the
numeric host policy remain unchanged.

## Historical failed candidate

The later candidate `7cfc9b60564f8c7bb8a589c86e15153c77bc948d` passed
CI (2081 tests +31 subtests), but its
[Docker smoke 41514375981](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41514375981/job/125514028659)
failed in temporary enrollment before the measured lifecycle phases.
It emitted no replacement lifecycle profile. The ten observations below
remain historical evidence from the earlier candidate, not measurements of
that failed run. RCA #265 and the integration status document the failure
and require a corrected candidate before merge. No host run occurred.

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

## Provenance and limits of the pre-change policy

| Topology | Sum of container caps | Existing pre-start threshold | Added margin |
| --- | --- | --- | --- |
| Controller + browser | 1024 MiB / 1.5 CPU / 192 tasks | 1536 MiB / 1.75 CPU / 256 tasks | 512 MiB / 0.25 CPU / 64 tasks |
| Controller + browser + sender | 1152 MiB / 1.75 CPU / 224 tasks | 1792 MiB / 2 CPU / 288 tasks | 640 MiB / 0.25 CPU / 64 tasks |

PR #247 introduced the pair threshold; PR #253 added the three-service
threshold. They are implementation choices. The source comment reserves
space for Docker and bounded probes; no recorded benchmark establishes those
exact margins as necessary minima. Caps are upper bounds, not actual usage.
The preflight checks values; it does not reserve CPU, RAM or tasks physically.

The pre-change CPU estimate was `max(0, affinity_count - loadavg_1m)`. It is not measured
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

## Observed existing-smoke profile: PR #261

[Docker smoke 41507865954](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41507865954),
job `125491674590`, emitted ten complete `OBSERVED` receipts around
2026-11-02 16:15 ART. The actual checkout and receipt source was test-merge
`07b1b11a73b486142c3528a4896a20d5df59e57c`; its tree
`ebf53c7dfb082d25257acd2ed6f8bebb54e36499` equals candidate
`42eb497e8b597cd86035d08370dc935cba9b0f17` over main `5ddfba5`.
[Sanitized full counters](resource-observation-2026-11-02.json) preserve
current and peak memory/tasks, cumulative CPU and sequential-snapshot deltas.

| Service | Phase | Peak MiB | Peak tasks | Time ms | CPU delta ms | Throttled delta ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| controller | http_acceptance | 47.27 | 9 | 3084 | 1195.53 | 1067.93 |
| controller | startup | 44.71 | 9 | 8457 | — | — |
| browser-worker | startup | 24.32 | 8 | 14232 | — | — |
| controller | startup_ipc | 44.71 | 9 | 1777 | 837.72 | 700.54 |
| browser-worker | startup_ipc | 187.47 | 76 | 1777 | 981.55 | 544.72 |
| controller | restart | 44.80 | 9 | 7971 | — | — |
| browser-worker | restart | 24.12 | 8 | 8133 | — | — |
| controller | restart_ipc | 44.80 | 9 | 1797 | 814.97 | 692.67 |
| browser-worker | restart_ipc | 187.83 | 79 | 1797 | 1014.40 | 589.72 |
| telegram-offline | sender_startup | 40.51 | 8 | 2577 | — | — |

Time means command wall time for HTTP/IPC, age at healthy observation for
startup/restart, and run-to-READY for the sender. These are different
intervals; startup age is not exact startup latency. Peaks are cumulative
within the current cgroup start. CPU deltas include sequential observer
processes; throttled time is not spare host CPU and must not be converted
into a host-utilization percentage. The controller and sender hit their
configured CPU caps during these startup/probe scenarios and still passed
functional checks. No counter was missing in this cut.

The HTTP probe also passed 24 local requests, with median 1.04 ms and p95
5.95 ms, using temporary SQLite, one member/intent/notice and engine off.
Both IPC journeys passed with real isolated kernel peers before and after
same-container restart. Both final cleanup steps passed. The sender ran
only after the pair had stopped, with an empty outbox, synthetic readiness
and network none; its production network container was created but never
started. **Three-service concurrency, real Telegram dispatch, real-site
render demand and droplet performance remain unmeasured.** Do not sum these
peaks into a measured combined requirement or use them to promise capacity.

The final legacy cleanup step tolerates already absent resources with
`|| true`; its green conclusion alone is not an exhaustive final inventory.
The preceding lifecycle cleanup validates the attempt identity and checks
absence of the lifecycle objects it removes. Neither receipt describes a
cleanup on the droplet.

[CI 41507866223](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41507866223)
passed 2000 tests and 31 subtests; security 41507865955 passed. These receipts
belong to the stated code cut. Later code/documentation candidates need their
own required checks; no release or host installation occurred in these PR runs.

## Reviewed CPU correction in the final #261 delta

The original predicate was independently reproduced RED with two CPUs,
load1=64, sufficient memory/tasks and a 2.0 CPU requirement. Linux loadavg
counts runnable and uninterruptible tasks; it is not an idle-CPU measure.
[RCA #259](https://github.com/mbalbo2023/boca-socios-assistant/issues/259)
and ADR0103 record the cause and the exact regression.

The reviewed correction resolves the rootless systemd container branch and
its applicable ancestors, compares finite quotas as exact fractions, and
uses the verified effective/configured CPU masks. A not-yet-materialized
user.slice is read through its effective systemd configuration without
starting a unit or creating a container. Docker's startup CPU count is an
additional conservative bound, not current idle CPU. Missing identity or
required controls fail closed; load1 is separately advisory.

The new receipt names the result `cpu_ceiling`. It is a configured ceiling,
not reserved or currently idle capacity. Requirements remain 1.75 CPU for
the pair and 2 CPU with Telegram, including the existing 0.25 policy margin.
RAM thresholds remain 1536/1792 MiB and task thresholds 256/288; all service
caps are unchanged. The smoke observations do not calibrate those RAM/task
margins. No server resizing, new infrastructure or other workload change
is selected. The final delta passed independent review and 290 focused
tests. Those candidate checks subsequently passed in 41518027202, 41518026922
and 41518027065, as recorded above. The new #266 candidate needs its own
checks; the protected host preflight remains pending. No droplet capacity or
performance is inferred from this fix.

