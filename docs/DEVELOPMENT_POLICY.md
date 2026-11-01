# Development and merge policy

## Why this exists

Past incident classes include accidental deploy on documentation changes,
overlapping writers and deployment leases, status gates being skipped,
SQLite writer contention, excessive disk/memory pressure and the danger
of mistaking a green CI unit test for a verified live deployment.
The reviewed manual Boca Actions workflow is the sole remote operation path.
Read-only inspection has executed; this does not establish that installation
prerequisites or runtime are ready. Infrastructure and business-logic choices
outside an already approved scope require concrete options, a recommendation
and owner approval before changes.
Earlier blanket autonomy statements do not authorize a new operation. The
current scoped approvals and verified state are recorded in issue #45.

## Approved delivery and maintenance

[ADR0056](ADR/0056-approved-simulation-beta-delivery.md) and
[BETA_DELIVERY_PLAN](BETA_DELIVERY_PLAN.md) record the approved next stage,
including private enrollment and synthetic E2E/restart/one-ticket acceptance.
Do not ask again for routine development/tests within that scope. Identity and
private-access activation decisions and final release/install candidate gates
remain explicit. Evidence of code approval is not evidence of a created DB.

Module writers update their contract/ADR, changed behavior, limits and exact
checks in the same PR. The central documentation owner coordinates plan/status
and the root owner updates #45/#113 on integration. Rule84 does not require
concurrent writers to duplicate identical global summaries; it requires their
facts to remain consistent and the assigned update to complete before closure.
Parallel checks may continue while independent source work advances.

Efficiency work measures queue/execution/build/scan/test and end-to-end latency
on exact candidates. Consolidate changes before publishing, parallelize
independent jobs and serialize final integration/host operations. Do not omit
required checks, substitute old evidence, relax gates or promote untrusted PR
artifacts to privileged release merely to reduce elapsed time.

## Branch protection contract

- Default branch: main; no direct pushes, branch deletion or force-pushes.
- Require a PR and a recorded agent technical review; no human approving
  review or code-owner approval is required by the ruleset. This does not
  replace owner approval of infrastructure/business scope. Resolve conversations.
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
   owner must have approved that concrete operation scope. Approval of code
   tests or a read-only diagnosis does not authorize release or installation.
7. On any unexpected condition, stop/fail closed, record NO_GO and fix forward.
8. If staged `first-install` or `beta-install` fails, the same protected Boca
   Actions job must immediately attempt a positive-identity stop and selective
   cleanup of disposable Boca artifacts. Inventory disk/inodes before and
   after, keep the original failure red, preserve owner/key/data volumes and
   uncertain resources, and never use host-wide prune. Runner/SSH/daemon loss
   may prevent cleanup: report NO_GO, require new Boca-only inventory and
   never silently retry. Other protected host phases retain their own
   non-destructive failure/stop and preservation contracts.
9. Diagnose source failures through Actions before deciding on code changes.
   Report source health as a timestamped semaphore. A source outage cannot
   turn a safe dormant-controller deploy into NO_GO or justify redeployment;
   a demonstrated code defect can justify a new PR and deploy.

## No parallel deployment paths

There must remain **exactly one** controlled deploy workflow. Never add
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

## Rule 84 — factual documentation in the delivery contract

[ADR 0055](ADR/0055-factual-documentation-and-scoped-approval.md) records the owner instruction and the historical
autonomy clauses it supersedes.

Every PR updates the documentation affected by its final behavior, evidence,
authorization and limitations. Distinguish configuration from observed state,
main from an unmerged candidate, synthetic tests from host/site evidence, and
local results from provider confirmation. Exact SHA/run references identify
what was actually checked; a successful old run is never current evidence.

Before task closure, the assigned writer reconciles the relevant README,
operations guide, roadmap, integration status and continuity checkpoint. State
what remains pending and what decision is required. Label historical snapshots
explicitly instead of mixing their instructions with the current contract.
Do not close while a required update is unrecorded. This rule does not add an
automatic documentation updater, a periodic schedule or approval authority.

## Acceptance criteria per PR

Explicit requirement, tests, redacted evidence, doc/ADR updates, security
impact, resource budget, failure mode, idempotency and handoff. A screenshot
or agent narrative alone never replaces a test report.

## RCA lessons enforced by CI

For a reproduced code or deployment-contract defect, preserve the failing
case as a deterministic regression before the fix. Once reviewed and merged,
record the issue, fixing PR, cause, prevention and test selectors in
`docs/quality/rca-lessons.json`. The quality job reads the pytest report
from its single full-suite run; a listed test that did not execute and pass,
or a removed accepted lesson/test, fails the gate. A changed finding needs
another reviewed PR with new evidence. No automated finding edits code,
merges a PR or dispatches deployment. See ADR 0044.

