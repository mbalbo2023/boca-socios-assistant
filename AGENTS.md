# Binding instructions for every coding agent

Read this file, README.md, docs/DEVELOPMENT_POLICY.md and relevant ADRs **in
full** before touching source. This public repository is independent from
every unrelated service, host configuration and application repository.

## Absolute scope boundary

- ONLY modify files under this GitHub repository and its feature branch.
- Never read, alter, restart, deploy, back up, clean up or delete **any other
  workload**, host-level timer, dashboard, data volume, port, container,
  secret, workflow or system service.
- Never run Docker commands against a production host from your own shell.
  In later authorized deployments, use ONLY the dedicated Boca Actions workflow.
- Never change existing host Docker Compose stacks; use project
  name boca-socios and its own image, secrets, volume, bridge and service only.
- Current mode is SIMULATION_ONLY. No real login or actual ticket buying.
- One ticket per member per event is **nonnegotiable**; enforce at domain,
  DB and transaction boundaries. Multiple sessions must never multiply
  authorized ticket quantity.
- Store credentials encrypted in the database. The key MUST be held outside
  it; never paste credentials, queue passes, session cookies or HAR into GitHub,
  code, issues, PRs, logs, test fixtures or screenshots.
- Do not assume multi-session support means independent Queue-it positions.
  No bypasses of Queue-it, WAF, CAPTCHA or rate limits.

## Development protocol

1. Recover exact main HEAD, open PRs, open work items, CI status and current
   project release state **before** starting. Do not duplicate completed work.
2. Claim exactly one narrow issue with one scoped writer. State files/paths
   being modified. Parallelize independent audits and nonoverlapping issues
   whenever possible; never use concurrent writers on the same scope. If
   another agent owns the same scope, stop and coordinate.
3. Create branch feature/<issue>-<slug> from current main HEAD, and open a
   small, reviewable draft PR; no direct push to protected main.
4. Edit only task-relevant files, keep unrelated work intact. Add regression
   tests and ADR updates for architecture, schema or security changes.
5. Run frozen dependency graph, formatting, lint, strict type check, full
   unit tests and isolation policy gate. Any FAIL, ERROR, SKIP or XFAIL
   affecting required gates is NO_GO. Never weaken a guard to make CI green.
6. Provide exact candidate SHA, base SHA, changed paths, test evidence,
   known limitations and explicit go/no-go in PR description.
7. The agent performs and records technical review; exact-SHA green required
   checks precede merge. GitHub does not require a second human approving
   review; that is distinct from the owner approving the task scope. No
   deployment side effects from push or documentation-only changes.
8. Do not choose infrastructure or business-logic changes unilaterally.
   Present the concrete options, recommendation, effects and evidence to the
   owner, then obtain approval for that scope before changing it. Previously
   broad autonomous-operation wording is superseded by this instruction.
   Approval for a diagnosis or code fix is not approval to install, release,
   migrate a real database or enable another feature. Once a scope is approved,
   complete its routine implementation and checks without asking repeatedly.
   All authorized host actions still use only the dedicated manual workflow
   with exact commit/image/service, isolation, capacity and environment gates.
   Serialize host operations; no automatic retry after a failed gate.
9. On failure, record RCA and Boca-only disk/inode inventory. Through Actions,
   remove only positively identified disposable Boca remnants after verifying
   they are unused; preserve key/data volumes and uncertain artifacts. Never
   prune host-wide resources or touch another workload. Fix code defects in a
   new PR; do not redeploy merely because an external source failed.
10. Use YYYY-MM-DD in America/Argentina/Buenos_Aires for user-facing times.

## Approved BETA preparation scope

[ADR 0056](docs/ADR/0056-approved-simulation-beta-delivery.md) and the
[delivery plan](docs/BETA_DELIVERY_PLAN.md) record the owner-approved stage:
private simulation BETA including mandatory **Socios > Agregar socio**,
coordinator/state/stop, durable local notices, restart/idempotency checks and
measured efficiency. The delegated logical destination is `/data/boca.sqlite3`
in `boca-socios_boca_data`, with a separate key; current global existence
remains UNVERIFIED. Preserve and identify any discovered storage. The dedicated
rootless service was prepared by run #120; no application/database was installed
by that operation. Do not rerun first-time preparation over its existing config.

Build on the prepared dedicated rootless service and proceed with approved
implementation/review/tests of an application-served private panel without repeating the
same permission request. Concrete identity/bootstrap/private-access options
still require their documented decision before activation. Final release and
installation use a reviewed concrete candidate under the plan, not this
planning approval alone. No real credentials/login/queue/reservations, existing
real-DB migration, backup or unrelated workload changes are implied.

## Code design principles

- Thin adapters around any external system; Queue-it and Boca are third-party
  contracts, and unverified behavior belongs behind interfaces and feature flags.
- One deterministic state machine per member/event/session; idempotency and
  transaction boundaries on any eventual reservation.
- Small files/modules with type hints and explicit errors. No hidden fallback
  from simulation to live.
- Never store unencrypted third-party secrets; avoid logging personally
  identifiable data. Use stable opaque internal member IDs.
- External I/O must be bounded with explicit timeouts, backoff and stop-on-block;
  simulated tests must not issue public website traffic.
- Check any external-source incident through a dedicated read-only Actions
  diagnostic before proposing a new deploy. Show timestamped green/yellow/red/
  unknown source health in the operation summary. Source outages are alerts,
  not blockers for a safe simulation-only deploy. Code defects and security,
  image or host-resource gates remain blockers. No live behavior is enabled by
  a source-health result.
- Live automation is a separate technical review and controlled milestone;
  the current runtime remains simulation-only with its engine off.

## Rule 84 — documentation must remain factual and current

[ADR 0055](docs/ADR/0055-factual-documentation-and-scoped-approval.md) records the owner instruction and the historical
autonomy clauses it supersedes.

Update affected documentation in the same PR as the change. Separate observed
behavior from configuration, unmerged proposals and future work; never present
a passing candidate or a configured path as a deployed capability. Cite exact
source SHA, PR and run evidence, its scope and its limitations. Preserve prior
cuts only under explicit historical labels.

Before closing a task, reconcile the affected README, operations/status/backlog
documents and the continuity checkpoint with the reviewed result, remaining
work and current authorization. Verify main and relevant checks again; do not
copy an old SHA or test count into a current claim. One assigned writer owns
each document/issue to avoid conflicting updates. If documentation or evidence
is still pending, keep that fact explicit and the task open.

This is a delivery obligation for each authorized task, not a claim that an
automatic robot checks or rewrites all GitHub content. Do not invent schedules
or a freshness date unsupported by a real verification.

## Handoff checklist

- GitHub branch/PR/issue and exact HEAD
- Ownership released/maintained
- Changed files and behavior
- Local and Actions tests (results, not assertions of success)
- Security and resource impact
- Why unrelated resources remain untouched
- Next steps and blockers


