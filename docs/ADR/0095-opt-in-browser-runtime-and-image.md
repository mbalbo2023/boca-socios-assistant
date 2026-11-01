# ADR 0095: Opt-in synthetic IPC backend and separate UID10002 browser image

**Status:** the original #227 code-only runtime/image cut was integrated in
PR #237 on main `46f184fc49747f98246ac82047d9786b65239168` (historical
local base `a14d900b95d45b257b429356469f4cd9cae22144`). It included the
corrected IPC STOP/post-read fence #236, the offline Playwright image #232,
command regressions #231 and owner-enrollment #229. Its local verification
was 1172 pytest cases and 31 subtests; that receipt did **not** demonstrate
browser image security or any deployment. The following #241 security
remediation is rebased onto main
`ef34cb40b150f9cfc891c5d7e0e3e48f151358f9` (including #240 offline
Chromium fixtures), and remains a **separate unmerged, code-only candidate**
until exact-commit hosted CI and review. Neither phase authorizes Compose or host
changes, application ports, Docker cleanup outside Boca or owner passkey
activation #225.

## Decision

The existing served controller remains simulation-only, engine `off`, with
`_LocalSyntheticBrowser` and its **five-second** coordinator deadline by
default. A single explicit, strict environment selector
`BOCA_BROWSER_BACKEND=ipc` is available only to served **staging** BETA at
`http://localhost:8443` (the sole future host publication stays
`127.0.0.1:8443`, behind the existing SSH tunnel). Absent selector means
`off`. Unknown values, live runtime, engine activation, non-staging or other
origin/port fail validation. No HTTP input or member/event can select the
backend; direct synthetic port injection remains a trusted test seam and is
refused if mixed with the IPC selector.

When explicitly selected, `build_beta_server` verifies UID/GID10001 and the
**fixed** `/run/boca-browser-ipc/synthetic.sock` identity through the
reused `ipc_protocol.socket_identity` *before* opening a listener, touching
member storage or constructing a worker client. Missing/unowned/redirected
socket fails closed. It then injects the already reviewed
`UnixSyntheticBrowser` (ADR0094), not a local Playwright instance. The
coordinator command deadline is explicitly **30 seconds** in IPC mode to
cover the IPC client's bounded 25-second budget; all other paths keep five
seconds. Initial database preparation and the dormant controller refuse the
IPC selector instead of hiding an incorrectly enabled browser. The full
`check-beta-config` command also requires this fixed worker socket in IPC
mode; `check-beta-owner` remains a separate owner-custody-only gate. This early
socket check does **not** prove the worker is alive or that host no-egress
and cgroups are enforced; those remain separate acceptance gates.

The separate `Dockerfile.browser` still starts from the pinned Playwright
1.64.1 base digest, installs **only** its locked optional Playwright dependency
group, copies **only** `boca_socios.browser` contracts, the package marker,
the one-ticket `domain.policy` and existing offline smoke scripts (never the
controller, storage, key custody or account modules), retains UID/GID10002
and changes only its default container command to the fixed
`python -m boca_socios.browser.ipc_worker`. The packaged code contains no
user-configurable Boca URL, login, purchase or external reservation adapter.
The worker itself validates its cgroup/UID and network namespace before
binding AF_UNIX; it cannot start successfully without its exact disposable
socket mount. The Playwright factory now asks for **Chromium's sandbox**
explicitly (`chromium_sandbox=True`), matching the existing isolated
`verify_chromium_worker.py` smoke; a failed sandbox launch is NO-GO, never
silently retried with `--no-sandbox`.

The controller image/Dockerfile and locked runtime dependencies are unchanged.
Image publication is a **different, later** deliverable: the browser image
must receive its own scanned immutable digest under
`ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:…`, exact source
revision label and manifest in the existing reviewed release system.
The default Dockerfile command does not publish a port; no Docker daemon,
credential, owner/key/data volume or host path is mounted by this code.

## Remaining gates, not implemented here

An approved later contract must define a separate `browser-ipc-v2` Compose
overlay with `network_mode: none`, UID/GID10002, private cgroups no greater
than 1 CPU/768 MiB/128 PIDs, read-only root, bounded tmpfs/shm, reviewed
seccomp/sandbox and **only** a new Boca-scoped Unix IPC mount. No worker
TCP port or egress, no Docker socket and no access to owner/key/data.
The controller's existing 8443 loopback publication and owner-enrollment
flow must be preserved. The Unix socket must verify `SO_PEERCRED` between
two rootless containers, not merely in same-process mocks; a UID mapping
failure is NO-GO. The host image must be pre-pulled/verified under the sole
protected manual Boca Actions workflow, with sufficient measured disk,
memory/PIDs/CPU reserves and selective cleanup after a failed attempt.

Code tests exercise strict OFF-by-default configuration, invalid backends,
origin restriction, fixed socket and UID startup refusal before DB/listener,
30-versus-5-second durable coordinator composition, packaged worker command
and Chromium sandbox request with offline Playwright doubles. Passing
tests/CI prove none of the actual Docker/host, device or website gates.
The code writer updates README and supplies exact local/CI evidence;
the central writer reconciles operational status and #45 after review.

**Host activation remains NO-GO**, regardless of code/test success, until
the owner approves specific host/Compose scope and later execution based on
fresh inventory and exact-main release/digest/security/cleanup evidence.

## Security remediation after PR #237: issue #241 (candidate)

The separately reviewed release PR #239 (candidate `1b7c354ab4302a4b74ad3d81e86bd3c5c8ef1482`)
failed its real hosted [browser image Trivy gate](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41358385474):
three Ubuntu HIGH findings in the GStreamer Bad package family (CVE-2025-3887)
and ten Python HIGH/CRITICAL findings in six base-image Python packages.
This is a confirmed **security NO-GO**, not a failed simulated reservation
or an incident on the droplet. Ubuntu Noble's official CVE status only
lists a fix under [Ubuntu Pro ESM Apps](https://ubuntu.com/security/notices/USN-7558-1)
for **both** `gstreamer1.0-plugins-bad` and `libgstreamer-plugins-bad1.0-0`,
not an ordinary public package update.

The scoped candidate removes only the GStreamer Bad multimedia plug-in
**and its associated shared library**, which the self-contained fake ticket
DOM does not require; its `dpkg-query` postcondition refuses an image still
reporting either package as installed. No `apt-get autoremove`, alternate browser base, sandbox disable,
Trivy ignore or severity downgrade is allowed. The image's global Python
environment pins the fixed versions from the hosted receipt:
`certifi==2026.10.18`, `filelock==4.2.1`, `msgpack==1.2.3`,
`setuptools==78.1.1`, `urllib3==2.8.0` and `virtualenv==21.14.9`.
The exact Python 3.12 transitive requirements of virtualenv were inspected
from its wheel metadata and are also pinned:
`distlib==0.4.4`, `packaging==26.3`, `platformdirs==4.14.2` and
`python-discovery==1.6.6`. Their wheel metadata requirements were validated
in a temporary Python 3.12 environment with all ten exact pins, where
`uv pip check` reported compatible packages. System pip uses
`--no-deps --only-binary=:all:` and `python -m pip check` must pass, refusing
floating resolution or missing requirements. This temporary environment
check is **not** a Docker build or Trivy receipt. The separate browser
dependency graph remains
`uv sync --locked --only-group browser`, pinned Playwright 1.64.1 and UID10002
with Chromium sandbox, no egress and no new ports.

The **existing** `image-security.yml` PR job gains a second, unchanged
HIGH/CRITICAL OS+library Trivy policy scan for the browser image. PR #239's
separate release workflow retains its own independent browser scan. This
duplicates a browser build and scan per release PR (extra disposable-runner
time/storage) deliberately: #241 can never appear green on controller-only
image security while the unmerged release workflow is not yet present.
The existing `ci.yml` image-build smoke must also launch Chromium under
`--network none`, UID10002, seccomp and cgroup budgets and complete the
synthetic DOM journey **after** optional multimedia removal. Any failure,
including an unfixed or newly found Trivy issue, keeps release/host NO-GO;
local static tests do not substitute for hosted image execution.
