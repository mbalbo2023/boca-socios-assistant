# R244 — concurrent local CI image builds (CODE_ONLY)

Date: 2026-11-12. Issue: #417. Base: `main=032990875feec8cd3715fb9e201277362656dd4a`.

## Intent

Reduce the critical path of the existing required `CI / image-build` job
without a third image build, new runner/job, reusable PR artifact, privileged
cache, weakened scan or change to release/deploy workflows. The observed
main run [43281076127](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43281076127)
spent approximately 14 seconds building the controller and 36 seconds
building the browser, sequentially, inside a 254-second image job. These are
one-run measurements, not a predicted speedup.

## Chosen approach

Launch exactly the same two `docker build` commands concurrently in **one**
GitHub-hosted `image-build` shell step. Give each build its own log, preserve
the exact `github.sha` source/revision and existing role-specific aliases,
and wait/reap **both** child processes even when one fails. Concatenate both
complete logs, fail the step if either exits nonzero, and emit monotonic
elapsed-time receipt(s). Every original image, Trivy, offline Chromium,
deployment/lifecycle and cleanup check remains after this blocking step.

Keep one pair in the runner-local Docker daemon. Never push/cache/export it
or consume it in the separate manual privileged release. PR and main must
continue to build and scan the exact final candidate independently of any
untrusted cache or prior SHA. CI required contexts remain unchanged.

## Alternatives rejected for this candidate

- Buildx `type=gha` remote cache: browser layer exports/imports have not been
  timed and can exceed the 36-second existing build; PR/main cache trust and
  size must be validated before adopting any such change.
- Duplicate or split jobs: adds runner setup/artifact transfer and required
  context aggregation; R239 already consolidated eight PR image builds to two.
- Concurrent Docker labs: the owner/site/HTTP/Chrome steps reuse the named
  `boca-socios_boca_owner` volume, and some later tests depend on Compose
  initialization; concurrency needs its own explicit resource graph.
- Parallel Trivy scans: both use a shared temporary vulnerability database
  cache and concurrent execution has unmeasured locking/download tradeoffs.

## Safety and measurement

The unit contract runs the **actual Bash body** against a disposable `docker`
command substitute. A barrier proves both builds were started before either
finishes; independent role failures must still wait for the other child and
produce a red result. Arguments must preserve exact labels and aliases, and
the subsequent existing Trivy steps must remain blocking. The test does not
certify that images build, that the host has enough CPU/RAM or that the
hosted CI wall time improves.

The theoretical savings on a zero-contention runner cannot exceed the
previous 14-second shorter build; resource contention can make it zero or
negative. This remains **CODE_ONLY / EXPERIMENT, not promoted** until an
exact-SHA hosted PR image job proves both builds, scans, labs and cleanup,
and a comparable baseline/candidate cut reports build-pair wall time,
the full image-job duration, runner time and variability. No Actions
dispatch, protected release, deploy or host operation is part of this change.
