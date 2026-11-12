# CI single image pair implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two Docker builds total per PR without losing any image test.
**Architecture:** Co-locate all image-dependent PR probes on the CI image runner;
keep protected release independent and retain required CI job names.
**Tech Stack:** GitHub Actions YAML, Docker, Python pytest, frozen uv.
**Spec:** docs/ADR/0239-ci-single-pr-image-pair.md

## Global constraints

- No pushes, PRs, merge, dispatch or host operations without coordinator.
- Preserve CI / quality-and-tests and CI / image-build.
- No PR artifact or cache consumption by protected publication.
- No docs fast-path or required workflow path filter.
- Single writer in this isolated worktree from b05da1d9.

## Review focus

- YAML anchor from former release PR job must become a literal publish body.
- Existing CI cleanup cannot delete images before relocated consumers.
- Runtime smoke must use the already-built exact pair, not accidental pulls.
- Release/host privileged source must not change during PR optimization.
- Retired PR contexts require explicit branch-rules evidence before merge.

## Task 1: consolidate without changing certification

Files: five image/deploy/public-source workflows; tests/test_ci_single_image_pair.py;
existing workflow contract tests; ADR0239 and this plan.

- [x] Add tests asserting two total PR builds, all former probe commands retained,
  exact labels/scans/required contexts, release/deploy preservation and cleanup order.
- [x] Run tests RED against unmodified workflows.
- [x] Move release PR probe steps and deployment PR runtime steps to CI image;
  retire superseded PR jobs/triggers and leave protected jobs unchanged.
- [x] Adapt existing probe assertions to their real new execution owner.
- [x] Run targeted tests GREEN, full pytest, lint/format/types/policy/RCA.
- [x] Report diff, observed results, pending hosted runtime/rules evidence.

## Ledger

Plan approved by coordinator's explicit co-location instruction. Baseline source
is origin/main b05da1d9ab8dae4a41b337baa1cebf0589b365fc. No remote effects.

Integration order: R188 observer must merge before this CI fast path. Rebase only
after coordination. Expected overlap is `boca-first-deploy.yml`: retain R188's
new protected observer and PR regression selectors, while removing only the old
`pr-runtime-smoke` job. Do not alter observer/upgrade backend source. Reconcile
ADR numbering against final main (R188 owns ADR0238; this proposal uses ADR0239).

Ruling approved by coordinator: public-observer's path-filtered PR adds a ninth
build. Its offline probe moves to the same CI browser; public manual dispatch
is unchanged. The script's attempt guard alone permits attempt2 for offline PR,
with mode/event/attempt negative tests; no navigation/firewall/cleanup edits.

### Local verification — 2026-11-12, CODE_ONLY

- TDD RED: absent co-location/labels; conditional public ninth build; offline
  PR attempt2 refused; substituted observer alias initially accepted.
- GREEN: 21 new tests; existing probe assertions relocated, none waived.
- Final full CI command: `pytest -q -n 2 --junitxml=...` reports 7201 passed,
  34 subtests passed, 1 skipped, 0 failed in 74.99 seconds. The sole skip is
  unchanged `test_r177_fixture_probe_transport` because sandbox AF_UNIX is EPERM.
- RCA gate was executed and returned `RCA_GATE_FAIL` for that skip. This is
  **not full quality acceptance**: exact-SHA hosted execution must pass with
  no skips before merge. Do not remove this test or relax the RCA gate.
- Frozen dependency sync offline, Ruff, format, mypy (173 sources), isolation
  policy, Bash syntax and whitespace checks passed.
- Parsed YAML equivalence proved protected publish/deploy/quality and public
  HTTP observe jobs unchanged; public manual browser step bodies unchanged;
  all 15 runtime steps identical and 8 release probes equivalent. Script body
  after its initial guards is byte-identical. All PR workflow/job routes sum
  to exactly two Docker build invocations, including observer-sensitive paths.
- Independent review: coordinator reported 0 CRITICAL/MAJOR; the one MINOR
  observer-alias identity gap was fixed with RED→GREEN and is covered by the
  final suite. Coordinator authorized a local-only atomic commit.
- Pending: actual branch-rules evidence, hosted Docker/Trivy/Chromium/netfilter
  execution, exact-SHA checks and coordinator release. No remote operation.

### R188-first rebase verification — 2026-11-12

Fetched and rebased cleanly onto `95591d33134cf055f73f8739d51f9bb742064ee9`
(#490), with no conflicts and no remote write. `boca-first-deploy.yml` against
that base has zero additions and 585 deletions, solely the retired PR runtime
job. The complete protected `deploy:` branch is byte-identical to R188;
`pr-validation` is semantically identical. The new
`boca-retained-resource-observe` selector, source gate, memfd transport and
retained-resource regression selectors remain intact. All R188 backend,
bootstrap, bundle and test files are unchanged.

Focal regressions: 207 passed. Full CI command after rebase: 7253 passed,
34 subtests passed, 1 unchanged AF_UNIX EPERM skip, zero failures in 74.64
seconds. RCA still correctly rejects the skipped report; no guard or exclusion
was altered. Ruff/format, strict mypy (174 sources), repository policy, Bash
syntax, protected-YAML equivalence and whitespace checks passed. No push, PR,
dispatch or host effect; R188 physical RCA retains priority under coordinator.
