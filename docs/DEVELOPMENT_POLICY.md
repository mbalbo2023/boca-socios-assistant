# Development and merge policy

## Why this exists

Past incident classes include accidental deploy on documentation changes,
overlapping writers and deployment leases, status gates being skipped,
SQLite writer contention, excessive disk/memory pressure and the danger
of mistaking a green CI unit test for a verified live deployment.
This new repository has deliberately no autonomous production deploy path.

## Branch protection contract

- Default branch: main; no direct pushes, branch deletion or force-pushes.
- Require a PR, 1 approving review and code owner review.
- Dismiss approvals on new commits; require resolution of conversations.
- Required contexts: CI / quality-and-tests and CI / image-build,
  after the first workflow run.
- No merge of draft PRs, skipped tests or unknown candidate SHAs.
- Enable secret scanning, Dependabot and dependency review if supported.
- Require up-to-date CI for the exact merge candidate; avoid stale artifacts.

GitHub rulesets need to be configured in repository Settings; merely
committing this document or CODEOWNERS does **not** enforce them.
The public personal plan supports enforcement, but no agent should claim
main is protected before verifying GitHub's **actual ruleset state**. See
[GITHUB_SETUP.md](GITHUB_SETUP.md) for required administrative checks.

## Work protocol

1. Each issue has explicit owner and narrow scope; no concurrent overlapping
   source writers. Single candidate SHA per decision.
2. First commit includes tests/contract, implementation follows in small
   increments. A red test triggers root cause analysis, not a weaker guard.
3. CI is read-only against third parties and needs no Boca credentials.
4. Use dependency lock, pinned Actions, no CI jobs on untrusted self-hosted
   runners, no broad GITHUB_TOKEN scopes or unreviewed scripts.
5. Do not merge until the exact SHA is green and reviewed. Main pushes rerun
   CI but must **never** deploy.
6. Releases are signed/tagged and build-once with immutable image digest.
   Deployment of digest and tag requires an independent human-approved
   manual GitHub Actions workflow and a Boca-only resource preflight.
7. On any unexpected condition, stop/fail closed, record NO_GO and fix forward.

## No parallel deployment paths

There must be **exactly one** future controlled deploy workflow. Never add
automatic push-based deployment, personal SSH procedures, host cron jobs,
any unrelated deployment integration or Docker cleanup of another project.
If a proposed feature requires any of those, stop for an architecture review.

## Acceptance criteria per PR

Explicit requirement, tests, redacted evidence, doc/ADR updates, security
impact, resource budget, failure mode, idempotency and handoff. A screenshot
or agent narrative alone never replaces a test report.

