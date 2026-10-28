# ADR 0009: audit GitHub Actions workflow definitions on each change

**Status:** Proposed until its exact public PR passes CI and is reviewed.

## Context

This repository is public, so untrusted contributors may propose pull
requests. The CI executes source from PRs on GitHub-hosted runners. A
future accidental `pull_request_target`, self-hosted runner, excessive
permissions, unpinned Action reference or template injection could
jeopardize the repository or connected infrastructure.

The existing workflow already follows important rules: full-commit Action
pins, read-only `contents` permission, checkout without persisted credentials,
and no deploy or host connections. However, its local source-pattern policy
is **not** a full GitHub Actions YAML security analyzer.

## Decision

Add [`zizmor`](https://docs.zizmor.sh/) as a pinned Action step within
`quality-and-tests`. Use the upstream [official integration](https://github.com/zizmorcore/zizmor-action)
at immutable commit `53290badfa369cb0bf7ad16342cb62c2fa47ac7b` (v0.8.0)
and pin the analyzer version to `1.31.1`.

Select:

- Offline audits only: `online-audits: false`, no injected GitHub API token.
- `advanced-security: false` to avoid adding `security-events: write` solely
  for the scan; annotate diagnostics in the existing Actions job.
- Regular persona; medium-or-greater severity and high confidence to keep
  policy gates high signal rather than accepting suppressions of every
  possible theoretical finding.
- Preserve read-only `GITHUB_TOKEN`, `persist-credentials: false` and
  GitHub-hosted runner; no new deployment workflow or secrets.
- Track the project's `uv.lock` using Dependabot's officially supported `uv`
  ecosystem, with a seven-day cooldown for ordinary version updates. GitHub
  explicitly states that security updates are **not** held by this cooldown.

This placement uses the future `quality-and-tests` required status context
and avoids introducing an unprotected additional GitHub check name.

## Consequences and limits

- A security finding meeting the configured threshold can fail the existing
  quality job, subject to the analyzer's actual exit-code semantics; verify
  this in a PR run. Explicit changes to this policy require review.
- It scans CI definitions, not Python behavior, Docker runtime isolation,
  malicious dependencies or the actual GitHub ruleset state.
- The pinned Action resolves the upstream distribution of the selected
  `zizmor` version from its upstream source; its entire transitive supply
  chain is **not** independently reproduced by this repository.
- Because `main` branch enforcement awaits GitHub re-verification, this
  source-code check cannot itself prevent a repository administrator from
  pushing directly until the ruleset is actually activated.
- As a defense-in-depth control, retain independent human review and audit
  future changes to GitHub Actions/third-party Action pins.

## Source of truth

- [zizmor official integration](https://docs.zizmor.sh/integrations/)
- [zizmor exit-code semantics](https://docs.zizmor.sh/usage/#exit-codes)
- [GitHub Actions checkout security](https://github.com/actions/checkout#readme)
- [GitHub repository secret scanning](https://docs.github.com/en/code-security/reference/secret-security/secret-scanning-scope)
- [GitHub Dependabot uv support](https://github.blog/changelog/2025-12-16-dependabot-security-updates-now-support-uv/)
- [GitHub Dependabot cooldown reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference#cooldown)
