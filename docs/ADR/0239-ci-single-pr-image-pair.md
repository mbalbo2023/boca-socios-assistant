# ADR0239 — One unprivileged image pair per CI candidate

Date: 2026-11-12 ART. Scope: #417. Status: proposed, CODE_ONLY.

## Intent and decision

Four independent pull-request workflows currently build the same two Dockerfiles
eight times; public-observer path changes add a conditional ninth browser build.
Co-locate all image-dependent PR checks in `CI / image-build`:
one controller build and one browser build, both labeled with exact source and
revision, then existing CI Docker labs, both Trivy scans, release offline probes
and complete disposable deployment/lifecycle smoke. Every step remains blocking.
Main CI also executes this complete image gate; no docs-only exemption is added.
The former public-source PR isolation check remains PR-only, now in CI against
the same browser. Its network-denial/firewall, sandbox and offline-render probes
are unchanged; it makes zero public connections. Its manually dispatched public
observation stays in `boca-source-status.yml`, with its own build and first-run
restriction. That workflow no longer needs a path-filtered PR trigger.

The same Docker build assigns each role both its CI tag and the scanner's
already-allowlisted release-validation alias. Before either scan, compare the
immutable local Docker image IDs of both aliases against the exercised pair,
reject any substitution, and record source SHA plus both image IDs. These IDs
are not published registry digests. The scanner's allowlist is unchanged.
The browser build also assigns the existing observer tag and per-run/attempt
label. The unchanged observer cleanup removes only that alias and positively
identified disposable probe resources, leaving the pair for subsequent probes.

The coordinator approved co-location instead of cross-workflow artifact transfer
or API-wait wrappers. Reusable workflow calls alone would still duplicate builds;
archives add large transfers and cross-run identity races. There are no new
artifacts, caches, API wrappers, privileges or PR-to-release trust edges.

## Check-context migration

`CI / quality-and-tests` and `CI / image-build` remain unchanged. The former
`image-security-controller-scan`, `image-security-browser-scan`,
`image-security-scan`, `release-image-pr-validation` and
`first-deploy-runtime-smoke` and `public-browser-isolation` PR contexts are
retired, not replaced by green
placeholders. Their actual checks now block `CI / image-build`.
`first-deploy-pr-validation` remains. Before merge, verify actual branch rules
do not require retired contexts, and record the evidence; this document does
not assert a GitHub ruleset was inspected or changed. Main Image security
push/manual scans remain independent. Protected publication remains manual.

## Certification and isolation

The protected release job remains byte-for-byte equivalent: builds its own two
images from current main, checks labels, runs offline Chromium, scans both,
rechecks current main and unique dispatch, then logs in, pushes both and writes
both immutable release manifests. It never downloads PR evidence. Build inputs
include README.md; no path filters are safe by assumption. Dockerfiles, pins,
full tests, RCA coverage, offline/network-none boundaries, synthetic-only runtime
and host isolation are unchanged. No droplet operation is authorized here.

## Risks and evidence

Co-located probes run sequentially and may increase one job's duration while
reducing total builds. Its timeout is explicitly sized for the combined gate;
measure actual GitHub queue/build/scan/probe durations before claiming latency
improvement. Cleanup must run after all image consumers and remain always-run.
Local source checks cannot prove Docker or Chromium behavior on Actions.

## Narrow offline replay compatibility

Coordinator explicitly approved changing only the initial attempt guard in
`run_public_observer_isolated.sh`: attempt 2 is accepted solely for
`--offline-check` with event `pull_request`. All public/manual modes remain
attempt 1 only; attempt 0/3, missing attempts, push/manual attempt 2 and live
mode PR attempts are rejected. No environment identity is rewritten and no
old result is consumed. The namespace/firewall/browser/cleanup script body
is unchanged. This preserves ADR0228's authenticated second PR CI attempt
without relaxing public navigation or protected release/deployment gates.

Regression matrix: exactly two PR build invocations; both labels and scans;
all former probe bodies retained; no publish/deploy on PR or main push;
protected release unchanged; named required checks retained; failing scan or
probe remains blocking; full suite/RCA/format/lint/types/policy; exact-SHA hosted
CI before merge. Release and physical deployment remain independently gated.
