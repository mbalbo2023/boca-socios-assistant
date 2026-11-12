# ADR 0245 — Boca R244: image count is not release latency

**Status:** measured baseline; R244 concurrent-build experiment tested on
hosted CI #43307951183 and **not promoted** due to absent critical-path gain.
R245 adds a narrow, local-tested **CODE_ONLY** docs-PR fast path, not yet
timed or admitted on hosted Actions. See
[ADR0246](0246-r244-concurrent-ci-builds-experiment.md).
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

## R244 decision (historical; resolved by hosted measurement)

Preserve the existing eight-build lifecycle accounting and record measurements.
The original consolidated R244 candidate included an experiment to overlap the
**same two** builds already performed in required `CI / image-build`, without
removing image-security jobs, publishing additional images or enabling a
cross-run cache. Hosted CI #43307951183 verified its scans/labs but measured
~313 s instead of the ~254 s historical baseline and saved only ~3 s at the
build pair. The experiment was therefore removed before merge. Future
build-count/cache redesign still requires separate reviewed provenance and
A/B evidence; do not block functional Boca BETA on those optional steps.

## R245 — Conservative internal Markdown-only PR fast path (CODE_ONLY)

The original warning about eight physical builds still applies: **there is
no general 8→4, 8→2 or reusable-image achievement.** R245 proposes to
avoid the disposable PR pair **only** when the PR changes exclusively regular
`100644` Markdown files under `docs/ADR/` and `docs/handoffs/`. Both Dockerfiles
copy source, root `README.md`, locks or scripts, but neither copies those
two document directories; the full quality/test/RCA/policy job remains
required even for these documents. This is intentionally narrower than a
general docs-only, panel-only, Python-only or dependency-only shortcut.

The existing `CI / image-build` job and context are still present and
successful when its exact-tree classifier approves the narrow PR. Only its
checkout and classification steps execute in that case; the 37 existing
image-dependent steps, including two builds, two Trivy scans, Chromium/Docker
labs and cleanup, are explicitly gated. The classifier uses a two-commit
checkout of the GitHub synthetic PR
merge, authenticates repository/head repository, `main` base, PR merge ref,
the event's exact source/base/head SHAs and both merge parents, then checks
`git merge-base` and NUL-delimited, rename-disabled `git diff --raw` against
that exact base. Only added, changed or removed **regular-file** Markdown in
the two named directories is admitted. Empty diffs, unknown statuses/modes,
non-UTF-8/control-character paths, symlinks, missing Git history, stale base,
forks, mixed changes and every parsing failure take the complete path.
There is no GitHub API poll, untrusted cache, artifact import or new image.

Every `push` to `main` and `workflow_dispatch` runs both CI builds, both CI
Trivy scans and all offline labs regardless of paths. The independent two
`Image security` jobs on main and the protected dual-image release likewise
remain untouched. A docs-PR still requires the full `quality-and-tests`
context, and a PR with **any** other changed path still runs all original
image checks and cleanup. This fast path is not an image digest re-use or
proof that a doc-only release can omit the protected scans.

**Local TDD and validation:** 26 exact Git fixture cases were RED before the
classifier/guards existed, then 26 GREEN after. They execute the real YAML
shell against disposable Git two-parent merges and cover admitted ADR/handoff
changes, mixed source/README/workflow changes, changed file modes/symlinks,
forged SHA/base/head/ref/repository, empty PRs and nonmerge HEADs. Existing
image alias, Trivy and CI tests remained GREEN (55 focused tests total),
Ruff and repository policy GREEN, and YAML parsed as 39 image job steps,
only two unconditional (checkout/classification), two scanners. These are
local evidence, **not** a hosted PR result, a cache benchmark, or approval
to waive a branch-protected check. The full two-worker local suite reported
**7,715 passed, 34 subtests passed, one AF_UNIX sandbox-EPERM skip** (its
physical runner proof remains mandatory), with Ruff format/check, MyPy 187
and isolation policy PASS. Actual hosted performance and CI evidence are
still required before promotion.

**Promotion gate:** one ordinary exact-SHA internal ADR/handoff-only PR must
show both required contexts terminal SUCCESS, zero Docker builds and zero
Trivy invocations in its image job by **verified classification**, full
quality/RCA pass, and real wall-time/runner-minute measurements. A second
mixed-path/internal PR (or comparable routine full-path run) must show the
classifier selecting `FULL`, both builds, both HIGH/CRITICAL scans, all
offline labs and always-run cleanup. On `main`, CI and Image security must
still execute normally. Do not run extra builds merely to improve a number.
The theoretical docs-only PR critical path would shift toward the ~119 s
quality job instead of the historical ~254 s image job; no hosted R245
latency measurement exists and queue/runner variability may dominate.

**Cache candidate not promoted:** Playwright worker layers are large, and
BuildKit `type=gha` cache import/export costs and branch trust behavior have
not been measured cold/warm on hosted runners. `Dockerfile.browser` already
installs its locked Python dependencies before copying the narrow browser
source; dashboard-only edits do not invalidate that dependency layer.
The controller Dockerfile currently copies `src/` before `uv sync`, so source
changes invalidate that layer, but reordering without a persistent cache,
reproducible image/lock/identity proof and A/B timing does not establish a
cross-run speed improvement. No cache, Dockerfile or protected workflow is
modified in this candidate.
