# ADR 0008: Isolated, local-only BrowserContext benchmark

Status: Proposed / instrumentation ready; **no measured host capacity**.
Date: 2026-10-28.

## Question

How many independent Chromium `BrowserContext` instances can a **separate**
test worker accommodate without degrading another workload or relying on a
claim about available RAM? This question is different from how many Queue-it
positions a member receives. The latter is controlled by an external vendor
and cannot be inferred from local browser counts.

## Decision

Provide `scripts/benchmark_browser_contexts.py` as an **optional** experimental
tool that:

1. Starts a temporary HTTP server bound exclusively to `127.0.0.1` with a
   fixed synthetic DOM page, no third-party resources or real member data.
2. Launches one Playwright-managed Chromium process per run, and tests
   isolated contexts in bounded groups of 1, 2, 4 and 8. Each context gets
   its own page, storage and cookies; all routed page requests are restricted
   to that ephemeral localhost port. Chromium's background networking is
   disabled where supported, but router hooks are **not** an OS-level
   outbound firewall.
3. Measures creation and document-ready latency, nearest-rank p50/p95/p99,
   group duration, page failures, cleanup failures, rejected external page
   requests, and sampled cgroup v2 memory, CPU throttle, PIDs and `/dev/shm`.
4. Enforces configurable memory-delta, remaining-cgroup-memory and PID
   headroom stop conditions after launch/context creation/navigation/hold.
   Stops subsequent groups on **any** failure, including an unexpected
   blocked external page request, and closes all contexts and Chromium in
   `finally`.
5. Exports sanitized JSON, with explicit `null` for unavailable counters.
   The metrics describe the **entire current cgroup**, not just Chromium.

Playwright is deliberately **not** a runtime dependency, and no network or
ticket adapter is enabled. Unit tests exercise caps, percentiles, counters,
local-only CLI construction and failure decisions without installing a browser.

## Reproducible manual experiment, on an isolated development workstation

Do not run this benchmark in a shared production droplet. For a strong
no-egress guarantee, first provision a dedicated network namespace/container
with outbound networking disabled; the temporary HTTP server and Chromium
must share its loopback namespace. Install the browser beforehand outside
that isolated execution environment. The following
commands are intended for a **dedicated test environment**, not the host of
any existing service. The Python package version was checked against the
official PyPI release dated 2026-10-22.

```sh
uv run --with playwright==1.64.1 -- python -m playwright install chromium
uv run --with playwright==1.64.1 -- python scripts/benchmark_browser_contexts.py --counts 1,2,4,8 --repeats 2 --output local-browser-benchmark.json
```

The Chromium build is associated with the pinned Playwright package. Browser
installation may download binaries; it is a development workstation operation,
not a runtime start or CI default. Use the project's locked Python environment
for tests and keep benchmark instrumentation separate from the controller.

Supported safety controls include `--counts` (max four ascending values, each
1..8), `--repeats` (max five), `--dom-nodes` (50..2000), `--timeout-ms`,
`--max-delta-mib`, `--min-headroom-mib` and `--min-pid-headroom`. There is
intentionally **no** `--url` option, no login, no client session import, no
bypass flags, no host IPC, no proxy support and no production deployment
workflow.

## Interpretation and decision gate

- `PASS`: all synthetic contexts navigated, were ready and closed, with no
  observed budget breaches. **It does not authorize live browser automation.**
- `NO_GO`: any navigation, launch, memory-budget or teardown failure. It stops
  later groups. Browser capacity is therefore bounded by the highest tested
  successful group, **not** an extrapolated session count.
- `null` resource fields mean that the selected host/kernel did not expose
  those counters. Missing counters are not zero and require supplemental
  measurement before any resource decision.
- Cgroup counters can include unrelated processes if the benchmark is launched
  inside a shared cgroup. Run in a dedicated sandbox to measure attribution.
- Sampled peaks can **underestimate instantaneous actual peaks**; add an
  external resource observer and repeat prolonged runs before a release gate.
- A p95/p99 computed from one to eight samples is descriptive, not a robust
  confidence interval. Increase controlled repetitions in a separate test
  campaign before presenting an SLO.
- `/dev/shm` measured availability is not an instruction to enable
  `--ipc=host`. In Docker, benchmark with container-private `shm_size` and a
  separate resource budget; Docker and Playwright guidance must be balanced
  against isolation policy.

Even a successful 8-context local run does **not** demonstrate support for
eight independent Queue-it positions, eligibility, checkout, or sufficient
capacity on the shared production machine. This tool does not intentionally
request Boca/Queue-it pages; the **strong** no-egress claim requires the
OS-level network isolation described above. No personal data is emitted.

## Deferred work

- Optional isolated CI/manual workflow after confirming runner cost, browser
  download size, container limits, and security policy. Do not add heavyweight
  automatic Playwright installation to every push.
- External cgroup monitor to observe sub-second peaks and forced worker
  termination; instrument file descriptors and Python event-loop lag.
- Resource baseline and safe operating envelope measured *on a dedicated
  test worker* before integration, reviewed with exact-head CI and a technical
  agent review. This optional local experiment is not a host-capacity gate.

References:

- [Playwright BrowserContexts](https://playwright.dev/python/docs/browser-contexts)
- [Playwright Python BrowserContext API](https://playwright.dev/python/docs/api/class-browsercontext)
- [Playwright Docker guide](https://playwright.dev/python/docs/docker)
- [Docker Compose `shm_size`](https://docs.docker.com/reference/compose-file/services/#shm_size)
- [Docker resource constraints](https://docs.docker.com/engine/containers/resource_constraints)
- [Playwright Python v1.64.1 (official PyPI release)](https://pypi.org/project/playwright/1.64.1/)
