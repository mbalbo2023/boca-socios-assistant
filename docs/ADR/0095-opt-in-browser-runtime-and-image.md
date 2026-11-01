# ADR 0095: Opt-in synthetic IPC backend and separate UID10002 browser image

**Status:** local **code-only** candidate for #227, 2026-11-01 ART, rebased
onto exact GitHub main `a14d900b95d45b257b429356469f4cd9cae22144`.
This includes the corrected IPC STOP/post-read fence in PR #236, the
Playwright-only image packaging in #232, command regressions #231 and
protected owner-enrollment #229. This phase changes only its owned files and
passed local frozen pytest (**1172 tests and 31 subtests**), Ruff, mypy and
repository policy after rebase. It must still pass **separate exact-commit
GitHub-hosted PR CI and human review** before merge; no CI result or runtime
installation is inferred from the local tests.
It does **not** authorize or modify Compose, GitHub Actions, host scripts,
droplet containers, Docker networks, volumes, application ports or owner
passkey activation #225.

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
