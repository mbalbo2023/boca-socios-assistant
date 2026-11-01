## What is changing?

- Issue / requirement:
- Scope (paths and components):
- Base SHA and candidate SHA:
- Reason for the change:

## Evidence

- [ ] CI quality-and-tests is GREEN for the exact candidate SHA
- [ ] GitHub Actions static security audit has no unresolved medium/high-confidence findings
- [ ] Tests added or justified if this is documentation-only
- [ ] No failing, skipped, xfailed, or suppressed critical tests
- [ ] Updated ADR, schema and security notes where behavior changes
- [ ] No usernames/passwords, cookies, tokens, HAR or session states in Git/logs
- [ ] No secrets or privileged runner access is exposed to fork PRs
- [ ] One ticket per member per event invariant remains enforced
- [ ] No calls that bypass Queue-it or overload protected third-party systems
- [ ] No unrelated paths, images, services, credentials or timers changed
- [ ] Docker Compose remains a separately named, bounded project

## Deployment

- [ ] This PR DOES NOT deploy or change a production host
- [ ] If runtime deployment is needed: separate written approval + exact SHA/digest
- [ ] Rollout and stop/recovery plan documented

## Rule 84 — factual documentation review

- [ ] Affected documentation is updated in this PR, or no documentation impact is justified below
- [ ] Main, unmerged proposals, configuration, synthetic tests and observed host/site state are distinguished
- [ ] Exact SHA/run evidence supports current claims; older cuts are explicitly historical
- [ ] Storage code/schema changes are not described as a created DB or a real migration without execution evidence
- [ ] Current authorization and remaining decisions are explicit; no blanket infrastructure/business authority is inferred
- Documentation paths changed / no-impact justification:
- Continuity checkpoint owner and link; update before task closure:

These are review obligations, not a claim of an automated documentation gate.

## Technical review and scope authorization

- Recorded agent reviewer and exact SHA:
- Technical decision and evidence:
- Owner-approved scope (or why no new infrastructure/business decision is involved):
- Options, recommendation and owner decision for any new infrastructure/business scope:
- Decision date (actual, not estimated):


