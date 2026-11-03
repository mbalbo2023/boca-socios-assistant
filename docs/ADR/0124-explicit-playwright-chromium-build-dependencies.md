# ADR0124 — Explicit Chromium and OS dependency installation in browser image

**Status:** 2026-11-03 ART, code candidate for [issue #294](https://github.com/mbalbo2023/boca-socios-assistant/issues/294); no image, host or browser activation is established by this ADR.

## Owner directive and scope

The owner declared `src/boca_socios/browser/synthetic.py` and
`src/boca_socios/browser/ipc_worker.py` externally validated **BLACKBOX**
modules. Their source content must not be read, interpreted, imported for
agent-side testing, modified or refactored. The owner also reserved all Boca
site navigation. Neither an image build nor its security checks authorize
running those modules or navigating to Boca.

The owner specifically requested `playwright install --with-deps chromium`
for the deployable browser container. The already pinned upstream image
`mcr.microsoft.com/playwright/python:v1.64.1-noble@sha256:330d401…` ships
browser binaries and OS dependencies, but the project now **explicitly runs**
the version-matched CLI during the image build so required dependencies are
provisioned rather than inferred from the base alone. The only target is the
separate optional `Dockerfile.browser` image; the controller's Alpine
`Dockerfile` stays Chromium-free.

## Build-time contract

1. Keep the pinned browser base and the frozen `uv.lock` / Playwright
   `1.64.1` optional dependency group.
2. As root, **after** `uv sync --locked --only-group browser`, but **before**
   the build-only tooling purge or `USER 10002:10002`, run exactly:

   ```sh
   /app/.venv/bin/python -m playwright install --with-deps chromium
   ```

   This is a Docker **build step**, not a runtime startup, UI test or
   invitation to navigate the site. No owner-controlled module is present
   in the image at this point; its fixed source copy occurs only afterward.
3. The installer may call `apt`, so fail the build if the pre-existing
   `libbrotli1=1.1.0-2ubuntu0.1` fix is no longer installed or either
   removed GStreamer Bad package is back. Retain the existing precise
   package removal and full HIGH/CRITICAL Trivy gate; never use ignore lists,
   broad distro upgrades or Chromium `--no-sandbox`.
4. Keep the worker isolated as UID/GID10002, with `network_mode: none`,
   no published ports, its own Unix socket and seccomp/cgroup controls.
   The default controller still uses `BOCA_BROWSER_BACKEND=off`; no browser
   worker is installed by `beta-install`.

## Evidence and limits

- Deterministic regression: `tests/test_browser_image_packaging.py` checks
  the explicit command, order, Chromium-only selection and preserved security
  postconditions. The new test first failed (missing command), then passed.
- The existing image policy tests validate immutable base, pinned fixes,
  nonroot runtime and narrow packaged files, but **do not** prove an actual
  `apt` transaction or Chromium launch.
- This managed scratch environment has **no Docker CLI**, so no local image
  build/Trivy result is claimed. The candidate requires the complete hosted
  image build and security scans for its exact commit. If apt, browser
  provisioning or the strict security postcondition fails, the candidate
  remains NO_GO; do not relax security gates merely to obtain GREEN.
- GitHub Actions remain the sole path to any later Boca-only host operation.
  Issue #275 rootless RCA, exact-image provenance, private controller
  activation and a fresh host receipt remain separate operational gates.

The owner-blackbox rule covers both source content and operational navigation.
The agent's change only supplies packaging dependencies; it does not certify
or execute the protected modules.
