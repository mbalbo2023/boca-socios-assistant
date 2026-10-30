# Repository settings to configure after bootstrap

Creating CODEOWNERS and CI files is not enough to enforce policy.

**Public repository target, 2026-10-29:** GitHub Free supports enforced
protection of public branches. The owner directs the agent to do and record
technical review without requiring a different human account. Verify each
control's actual state in Settings rather than inferring it from this file.

1. Confirm repository is PUBLIC with a **new sanitized initial history**
   and the default branch is main. Verify branch and job names directly.
2. Settings → Rules → Rulesets → New branch ruleset:
   - Name: protect-main
   - Enforcement: Active; target: default branch (main).
   - Block deletion and force pushes.
   - Require pull requests and conversation resolution; zero required GitHub
     approvals. Record the agent's technical review and exact-SHA CI in the PR.
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
6. Environments for future Boca host operations must restrict deployment to
   main, hold a dedicated SSH identity and pinned host key, and be marked ready
   only after those settings are verified. No required human reviewer.
7. Do not recreate or rotate the existing SSH key secret while reconciling
   settings. A pin configured in GitHub is not evidence of host connectivity.
8. Run and verify CI; then activate required status checks.

## Revalidated state on 2026-10-29

- `protect-main` ruleset 26163295 is active on the default branch. It
  requires a PR, linear history and exact required `quality-and-tests` and
  `image-build` checks; required approving review count is zero.
- `main` still contains only `ci.yml`. The manual Boca host workflow exists
  only in draft PRs, so it cannot be dispatched from the default branch yet.
- The private `boca-first-deploy` environment has the pre-existing SSH key
  secret and separately authorized host/key pin. Its branch restriction is
  main-only; required reviewers are off, administrative bypass is available,
  and its readiness variable remains absent. Host readiness and other
  privileged paths are unverified. Do not call this environment ready yet.

Record any subsequent settings changes as observed facts; neither this
document nor CODEOWNERS enforces GitHub settings by itself.

## Repository access

Only give contributors minimal required repository permissions. The single
owner is mbalbo2023. For every development agent, record issue, branch,
scope, status and handoff. Never grant unrelated infrastructure
access merely because this repository exists.

