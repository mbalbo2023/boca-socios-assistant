# ADR 0052: separate PR validation from the manual host mutex

**Status:** Proposed for issue #135, 2026-10-31. No host operation or image
publication is part of this change.

## Cause

The first-deploy workflow uses both `pull_request` and `workflow_dispatch`.
Its constant concurrency group put every PR's offline validation and runner
smoke test into the same pending slot as manual host operations. PR #128 run
41256473909 was cancelled while unrelated PR validations queued. GitHub's
default concurrency queue allows only one pending run per group and replaces
an older pending run when another arrives. `cancel-in-progress: false`
protects the running operation, not the pending slot.

## Decision

Only a `pull_request` event selects `boca-first-deploy-pr-<PR number>`.
Every other event retains the literal `boca-first-deploy` group. In particular,
all manual inspection, preflight, installation and diagnostic operations
remain serialized together regardless of their input, SHA, ref or run ID.
Running operations continue to have `cancel-in-progress: false`. Distinct
PRs may validate concurrently on disposable GitHub-hosted runners. Newer
runs of the same PR can still replace that PR's older pending validation;
the current exact candidate must pass before merge.

The repository policy requires the complete top-level concurrency block,
including the event discriminator, PR number and literal manual fallback.
Regression tests evaluate the bounded routing expression against unrelated
PRs and manual events and reject policy mutations that share PR groups,
split the manual lock or cancel running work. Existing dispatch, main,
repository, actor and protected-environment gates are unchanged. No push
trigger, new host job, permission or deployment route is introduced.

The image-release workflow already groups by `github.ref`; distinct PRs
use distinct `refs/pull/<number>/merge` refs and cannot replace one another's
pending validation. It is unchanged. This decision does not promise extra
GitHub runner capacity, change the default queue policy, or queue multiple
host operations. Host operations must continue to be dispatched serially.

Reference: [GitHub concurrency semantics](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
