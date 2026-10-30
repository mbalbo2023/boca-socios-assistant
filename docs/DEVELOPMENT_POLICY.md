# Development and merge policy

## Why this exists

Past incident classes include accidental deploy on documentation changes,
overlapping writers and deployment leases, status gates being skipped,
SQLite writer contention, excessive disk/memory pressure and the danger
of mistaking a green CI unit test for a verified live deployment.
The current main has no remote deployment workflow. A reviewed, manual Boca
Actions workflow may later run autonomously under the owner's standing
direction after its objective gates are satisfied.

## Branch protection contract

- Default branch: main; no direct pushes, branch deletion or force-pushes.
- Require a PR and a recorded agent technical review; no human approving
  review or code-owner approval is required. Resolve review conversations.
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

1. Each issue has explicit owner and narrow scope; parallelize independent
   issues and read-only checks, with no concurrent overlapping source writers.
   Single candidate SHA per decision.
2. First commit includes tests/contract, implementation follows in small
   increments. A red test triggers root cause analysis, not a weaker guard.
3. CI needs no Boca credentials and does not probe third parties. A separate,
   bounded read-only Actions source diagnostic may check a public endpoint
   when needed; its outage result is advisory, not a required deploy check.
4. Use dependency lock, pinned Actions, no CI jobs on untrusted self-hosted
   runners, no broad GITHUB_TOKEN scopes or unreviewed scripts.
5. Do not merge until the exact SHA is green and has a documented agent
   technical review. Main pushes rerun CI but must **never** deploy.
6. Releases are build-once with immutable image digest and verified source
   provenance. An installation uses the sole manual GitHub Actions workflow,
   exact SHA/digest/service inputs and a Boca-only resource preflight. The
   owner has delegated this gated operation without another human approval.
7. On any unexpected condition, stop/fail closed, record NO_GO and fix forward.
8. If a host operation fails, inventory Boca-only disposable artifacts and
   disk/inodes before and after a narrowly scoped Actions cleanup. Preserve
   key/data volumes and uncertain resources; never use host-wide prune.
9. Diagnose source failures through Actions before deciding on code changes.
   Report source health as a timestamped semaphore. A source outage cannot
   turn a safe dormant-controller deploy into NO_GO or justify redeployment;
   a demonstrated code defect can justify a new PR and deploy.

## No parallel deployment paths

There must be **exactly one** future controlled deploy workflow. Never add
automatic push-based deployment, personal SSH procedures, host cron jobs,
any unrelated deployment integration or Docker cleanup of another project.
If a proposed feature requires any of those, stop for an architecture review.

## Synthetic panel preview artifacts

A manual Actions preview of the owner panel may upload a short-lived HTML
artifact built only from fixed sample states in source. It must not accept a
database, credential, member, event or host input, read runtime data, call
Boca, publish a website or add a service port. The artifact is public-repo
material, so it must contain no actual personal data. A preview checks the
panel's presentation only; it is not an authenticated operating interface or
evidence of a reservation. Real enrollment and status serving retain their
separate security gates.

## Acceptance criteria per PR

Explicit requirement, tests, redacted evidence, doc/ADR updates, security
impact, resource budget, failure mode, idempotency and handoff. A screenshot
or agent narrative alone never replaces a test report.

