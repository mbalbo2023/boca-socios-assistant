## What is changing?

- Issue / requirement:
- Scope (paths and components):
- Base SHA and candidate SHA:
- Reason for the change:

## Evidence

- [ ] CI quality-and-tests is GREEN for the exact candidate SHA
- [ ] Tests added or justified if this is documentation-only
- [ ] No failing, skipped, xfailed, or suppressed critical tests
- [ ] Updated ADR, schema and security notes where behavior changes
- [ ] No usernames/passwords, cookies, tokens, HAR or session states in Git/logs
- [ ] One ticket per member per event invariant remains enforced
- [ ] No calls that bypass Queue-it or overload protected third-party systems
- [ ] No unrelated paths, images, services, credentials or timers changed
- [ ] Docker Compose remains a separately named, bounded project

## Deployment

- [ ] This PR DOES NOT deploy or change a production host
- [ ] If runtime deployment is needed: separate written approval + exact SHA/digest
- [ ] Rollout and stop/recovery plan documented

## Human approval

- Reviewer:
- Decision / date:

