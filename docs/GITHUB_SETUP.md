# Repository settings to configure after bootstrap

Creating CODEOWNERS and CI files is not enough to enforce policy.

**Public repository target, 2026-10-28:** GitHub Free supports enforced
protection of public branches. The steps below are **target-state
requirements**, not claims that any setting is already enabled. Document
each actual control's visible state after configuration. A separate
reviewer identity is needed before requiring approvals: authors cannot
approve their own PR.

1. Confirm repository is PUBLIC with a **new sanitized initial history**
   and the default branch is main. Verify branch and job names directly.
2. Settings → Rules → Rulesets → New branch ruleset:
   - Name: protect-main
   - Enforcement: Active; target: default branch (main).
   - Block deletion and force pushes.
   - Require pull requests. Add one independent approval and mandatory
     code-owner review **only after** a distinct reviewer exists.
   - Dismiss stale reviews and require conversation resolution.
   - Require status checks `quality-and-tests` and `image-build`, after
     CI first reports their exact GitHub check context names.
   - Prevent bypass except for a documented break-glass owner decision.
3. Enable Issues and Discussions only if useful; do not permit public
   personal-data issues or unaudited external collaborators.
4. Settings → Actions → General: require actions pinned to complete SHA,
   restrict GITHUB_TOKEN to read-only and disable Actions-created PR
   approval. Never expose secrets to untrusted fork PR workflows.
5. Security → secret scanning, push protection, Dependabot alerts and code
   scanning if plan supports them. Do not substitute unavailable plan features
   with a false claim of enforcement.
6. Environments: add staging and production **only** if deployment is later
   approved. Production must require reviewer approval and run only from main.
7. Do NOT add deployment secrets yet; first review a dedicated deployment
   workflow PR and verify capacity on the intended host.
8. Run and verify CI; then activate required status checks.

Until protection is actually activated and verified in GitHub Settings,
changes must go through PR and exact-SHA CI by policy. Disclose if a rule
is still unenforced. Do not falsely claim that merely adding this document
or CODEOWNERS has locked main.

## Repository access

Only give contributors minimal required repository permissions. The single
owner is mbalbo2023. For every development agent, record issue, branch,
scope, status and handoff. Never grant unrelated infrastructure
access merely because this repository exists.

