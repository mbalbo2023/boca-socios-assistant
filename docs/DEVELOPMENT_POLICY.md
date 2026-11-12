# Development and merge policy

## 2026-11-12 — compatibilidad de formularios móviles en el panel 8443

Por autorización específica del titular para resolver `Origen no autorizado`
en Configuración, el panel privado admite `Referrer-Policy: same-origin` en
sus formularios HTML nativos. No se relajan la autenticación passkey, el
origen exacto exigido en el POST, CSRF, permisos ni la protección anti-replay.
La política evita divulgar el `Referer` a sitios externos. Las páginas
Telegram sin formulario nativo permanecen `no-referrer`. La recepción física
en Chrome requiere evidencia separada de las pruebas offline. ADR 0237.

La solicitud del dueño de acelerar cambios pequeños **no** autoriza por sí
misma saltar los checks requeridos ni modificar el workflow de producción:
se auditará el tiempo real para proponer una ruta selectiva con contexto CI
estable, fuente exacta y promoción manual consolidada.

## 2026-11-12 owner direction — consolidate #12 and #417 without source gates

**R186 operational continuation:** the single physical dual-pair APPLY
occurred in [#43217075287](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43217075287).
It passed its irreversible commit and left `RETIRE_OLD/INDETERMINATE`:
another full upgrade or rollback is forbidden. R185 corrected the stopped
worker Health observer, and three subsequent READ_ONLY runs verified the
new pair, systemd binding and SQLite inode. R186 may add **only** one
postcommit archival finalizer operation inside the existing protected Boca
workflow (same mutex and SSH identity), with new lease, O_EXCL claim,
exact-file retirement and postflight. No separate SSH workflow is permitted.
Its code inclusion is governed by syntax/TDD/CI/PR, independent of Queue-it
and Boca provider availability; installation acceptance still needs a
genuine host receipt and private panel acceptance.

The owner assigned the active agent responsibility for completing the **one**
Boca simulation BETA deployment because the previous #417 chat stalled.
This explicitly supersedes the historical separate-chat ownership boundary;
no parallel writers, merges or host Actions may run against a shared scope.

The accepted #12 code-only candidate (#484) may be merged into the single
release once exact-SHA checks and technical review are satisfied. Unavailable
live Queue-it URL/token validation, a missing genuine Boca login endpoint,
and a missing optional sector-preferences SQLite sidecar **do not block a
controller BETA deployment with included Queue-it and Boca contracts**.
By the owner's later clarification on 2026-11-12, **do not require an
additional live-provider test, separately reviewed endpoint or activation
approval to ship/enable those code paths**: syntax, imports, offline TDD,
ordinary CI and contractual repository checks are the release bar. An
unconfigured producer/transport must report unavailable at runtime, without
turning that fact into a deployment veto or inventing a token or response.
The sector page must be honest about unprovisioned storage. Do not conduct
live URL/token checks while the external services are unavailable; ticket
reservation/navigation stays SIMULATION_ONLY and queue bypass forbidden.

This is **not** a waiver of required protected workflows, final PR/merge
provenance, dual release integrity, positive-identity Boca-only host checks,
passkey/CSRF, one-ticket restriction, cleanup or postflight. The stalled
release with incomplete artifacts is still unusable; create and verify a
fresh single release from the final merged main, then perform one controlled
pair upgrade through the dedicated Action.

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

The owner's [2026-11-02 continuity instruction](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6591142632)
requires continuing agreed work without repeatedly asking permission. Recover
and carry forward that authorization across turns and handoffs. The concrete
public diagnostic described in that record was still blocked by platform
approval review after this reiteration; no new run was created. Its existing
map, budgets and isolation remain binding. Record steps and results immediately in
GitHub. Platform blocks are documented, not bypassed, and do not suspend
independent work or justify asking the same question again.

## Approved delivery and maintenance

**Owner resource-gate correction (2026-11-02):** Numeric pre-release
CPU/RAM/PID buffers without an actual BETA benchmark are now advisory and
cannot veto installation merely for being below a chosen estimate. The
approved engineering correction is tracked in [issue #259](https://github.com/mbalbo2023/boca-socios-assistant/issues/259)
and candidate [ADR0112](ADR/0112-postdeploy-resource-observation.md).
All isolation/cgroup caps, exact image provenance, positive-identity rootless,
loopback port, real storage safety and fail-closed/cleanup requirements remain
binding. Measure actual synthetic BETA resource use **after deployment**;
record metrics before approving any future dimensioning change. This is not
authorization to affect another application or to bypass platform controls.

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

## Agile PR and Actions governance (R68, 2026-11-06 ART)

Keep one source-of-truth integration branch per reviewed release. Before opening
a PR, query all open PRs and compare changed paths/hunks with `main` and active
owner scopes; do not create replacement code where an existing feature is being
reviewed. Default base is `main`. A PR against another feature branch must
state its parent, why that dependency is needed and the planned promotion or
closure; stacked PRs do not independently certify a final release.

Every PR must carry issue/scope owner, current base and head SHAs, status
(ACTIVE/BLOCKED/SUPERSEDED/EXPERIMENT), tests and last evidence. A centralized
backlog review reconciles open drafts with `main` at each release freeze.
Close only an *exactly demonstrated* superseded or abandoned PR, with linked
replacement/merged commits and an explanatory comment; never bulk-close by
age, title similarity or number alone. Dependency bumps must satisfy the
current Python/runtime constraints before being considered mergeable.

Batch logically related file changes into **one atomic commit** before opening
or refreshing a PR; avoid file-by-file commits that trigger four redundant
GitHub Actions waves. All required checks must still complete against the
final reviewed SHA. Avoid workflow-level path filters for required contexts,
which can leave required checks pending; any future docs-only fast path must
retain the named required job with an explicit, tested classification.

Measure queue, uv sync, controller/browser builds, scans, PR wall time,
protected publish, PREPARE, APPLY and postflight separately. GitHub-hosted
runner checks may run in parallel; only Boca's single physical deploy mutex
may mutate the shared host. Reuse caches or immutable artifacts only after
proving provenance and branch-trust separation; never consume an untrusted
PR cache in the protected release without rebuilding/verifying by digest.
Do not confuse remote GO wait, dispatch latency and container startup time.

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
   **Permanent owner rule (2026-11-04): run bounded, positively identified
   Boca-only postflight cleanup after EVERY successful or failed install,
   deploy and update, not only after failure.** The same protected Actions job
   must inventory disk/inodes and exact attempt-owned resources before/after,
   remove only disposable Boca artifacts and obsolete images proven unused by
   every container (never remove the image currently serving), then verify
   exact IDs are absent. Keep owner/key/data volumes and anything uncertain.
   No host-wide prune, force-removal, other Compose project or unrelated
   workload; if cleanup cannot run or prove the result, record
   NO_GO/INDETERMINATE and require a new read-only Boca inventory before retry.
   A successful application start alone does not satisfy final acceptance.

   **Narrow R108 Cutover V3 exception:** the single historical Boca image
   `sha256:a44453ab30cb17fa42f71723cf64b1097dabdf0e56369186077c47bc8224f90b`
   may be quarantined as forensic evidence only when its immutable historical
   release proof, lack of references and fresh same-lease rootless inventories
   match exactly. Report `retained_attested` in canonical cleanup V2;
   this is **not** literal deletion of every obsolete image. All other images,
   known residues and uncertain resources retain the normal acceptance gates.
   The failed historical retirement Action #746 must not be blindly retried.
   See [ADR0209](ADR/0209-r108-attested-historical-quarantine.md).
9. Diagnose source failures through Actions before deciding on code changes.
   Report source health as a timestamped semaphore. A source outage cannot
   turn a safe dormant-controller deploy into NO_GO or justify redeployment;
   a demonstrated code defect can justify a new PR and deploy.

## No parallel deployment paths

### Cutover V3 authority (2026-11-07)

The owner replaced the Cutover-specific manual GO_B and two-dispatch
PREPARE/APPLY process with a single authenticated owner dispatch. The reviewed
`cutover-a-apply` route now resolves source, dual immutable GHCR images and
installed legacy identity automatically; the user must not copy hashes or
PREPARE run IDs. Its generated digest binds the reviewed bytes to this run,
not an independent approval. Environment secrets/main restrictions remain;
no changes to reviewer settings, auto-approval or credential recovery are
part of the implementation. Official-import/lifecycle policies are unchanged.
Source/CI/PR0, single lease, UID10001, protected storage/passkey, localhost8443,
no real navigation/login/tickets and mandatory physical cleanup/ACK still
gate acceptance. See [ADR0206](ADR/0206-single-dispatch-cutover-v3.md).

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

