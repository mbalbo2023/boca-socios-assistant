# ADR 0245 — Boca R244: image count is not release latency

**Status:** measured baseline; R244 concurrent-build experiment proposed,
not yet promoted on hosted CI. See [ADR0246](0246-r244-concurrent-ci-builds-experiment.md).
**Scope:** Boca-only GitHub Actions and its disposable runner Docker; no droplet effect.

## Evidence (2026-11-12)

- Reference main SHA: `032990875feec8cd3715fb9e201277362656dd4a`.
- `CI` run `43281076127`, job `131402167739` (`image-build`):
  18:33:36–18:37:50 UTC, **254 seconds** wall time.
- `quality-and-tests` completed in 119 seconds and overlapped `image-build`.
- Inside `image-build`, controller image build took **14 s**, browser image
  build **36 s**; Trivy controller **15 s**, browser **18 s**.
- Largest remaining individual steps: panel cold restart **24 s**,
  fixture auto-removal **17 s**, disposable Chrome/owner import **15 s**.
- The separate `Image security` run `43281075946` ran its controller
  (~33 s) and browser (~80 s) jobs **in parallel** with that main CI run.
- The historical protected release `43215180354` took **195 s**, including
  controller build **9 s**, worker build **51 s**, scans **16/24 s** and
  GHCR push **84 s**. This is a different run, not proof of current timings.

The nominal lifecycle constructs **eight** image instances: two in PR CI,
two in main CI, two in separate main image security and two for release.
The first six are disposable; two in release are published. This accounting
is **not eight sequential builds** and does not mean six would run faster.

## R240 safe6 investigation, not admitted

R240 attempted to replace two duplicate post-merge security builds with
exact-main CI/Trivy attestations. Its code and tests live in the isolated
`feature/417-ci-speed-r244` experiment and are **not** part of this R244
consolidated candidate, for three concrete reasons:

1. The push security jobs start alongside CI and end sooner; attestors
   polling CI for ~254 seconds could extend runner occupation and API calls
   without shortening release readiness.
2. Switching security to a `workflow_run` completion trigger would avoid
   that busy wait but fail the existing protected release consumer, which
   requires a **push/main** security workflow run for the exact SHA.
3. Any trigger/provenance redesign must be proved with the actual protected
   release consumer and hosted Actions before it can authorize a deployment.

The omission is deliberate: do not turn source-only green tests into a false
speedup or remove final image scans. Existing Trivy gates remain unchanged.

## Cache and fast-path investigation

- **Python/uv:** `actions/cache` could persist only the locked dependency
  download cache; use exact `uv.lock` and Python/runtime key, no broad
  untrusted PR restore prefix, run `uv sync --frozen` and tests on every hit.
  Quality currently finishes before image-build, so this alone cannot reduce
  the measured critical path. In measured main #43281076127, quality's `uv
  sync --frozen` took ~0.9 s, Docker lab's `uv sync --frozen --no-dev
  --no-install-project` ~0.25 s, while installing the pinned uv executable
  took ~5.9 s. Do not confuse this with a costly dependency download cache.
- **Docker/BuildKit:** enable explicit `buildx` only with a separate,
  provenance-scoped GitHub Actions cache for controller and worker, capacity
  and hit-rate measured, unchanged `--load` semantics for disposable labs and
  fresh Trivy scans. Source edits currently invalidate controller dependency
  installation because its Dockerfile copies `src/` before `uv sync`.
  Moving locked dependency installation before project source is useful
  *only after* cache persistence and `--offline` backend provisioning are
  proved in hosted CI. The measured two builds together cost ~49.6 s of the
  254-second image job, so even **zero-time** builds would save no more than
  19.5% of that job; ~171.7 s of unrelated Docker labs/setup and ~32.7 s
  of required Trivy scans remain. A `type=gha` cold miss may instead add
  large cache export/import traffic. Validate containerd image store versus
  the `docker-container` Buildx driver before proposing `--load` behavior.
- **Labs:** time each offline Docker test before restructuring; some jobs
  share the owner volume and cannot safely run concurrently. The long
  runner Docker lab sequence dominates critical-path time (~171 seconds).
  A fast PR path must still produce the branch-protected `image-build`
  context and cannot skip a release-critical test on unproven path matching.
- **Promotion:** reaching four physical builds (PR pair + release pair)
  requires a reviewed, exact-tree-to-squash-main identity/attestation and
  change to the protected SHA consumer. Reaching two or zero on scoped
  changes requires content-addressed reuse and release re-attestation.
  Neither is authorized by a simple YAML job removal.

## Decision

Preserve the existing eight-build lifecycle accounting and record measurements.
The consolidated R244 candidate includes only an experiment to overlap the
**same two** builds already performed in required `CI / image-build`, without
removing image-security jobs, publishing additional images or enabling a
cross-run cache. A final-SHA hosted CI run must verify both build outcomes,
all scan and offline lab gates, and measured critical-path improvement before
this optimization is promoted to main. If the measured path becomes slower,
remove this experiment before merge. Future build-count/cache redesign still
requires separate reviewed provenance and A/B evidence; do not block functional
Boca BETA on those optional steps.
