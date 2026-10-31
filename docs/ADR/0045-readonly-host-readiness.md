# ADR 0045: separate readiness for host inspection and installation

**Status:** Proposed, 2026-10-31. Issue #120, PR #122. No host dispatch.

## RCA

The manual Boca workflow checked `BOCA_DEPLOY_ENV_READY=ready` before it
distinguished the two read-only choices from installation. Setting that
variable to observe prerequisite metadata would also satisfy the initial
readiness check of `first-install`. Digest, release and host preflight checks
still existed, but the owner's intent to inspect without opening the general
deployment gate had no separate representation.

## Decision

Retain the single `boca-first-deploy` environment, its main-only branch rule,
owner actor check, pinned SSH identity, exact current SHA and one serialized
manual workflow. The first step selects an operation with an exhaustive shell
`case` before checkout or SSH. `inspect-prerequisites` and `preflight` require
`BOCA_HOST_READONLY_ENV_READY=ready` and empty image/release-run inputs.
`first-install` and `diagnostic` require `BOCA_DEPLOY_ENV_READY=ready` and
nonempty image/release-run inputs; their existing digest and release-manifest
checks remain mandatory. An absent, misspelled or non-`ready` value fails
closed. Unknown operations, reruns and SHA mismatches also fail before SSH.

The separate read-only value is an environment-scoped administrative marker,
not proof of the host. It may be configured only after the environment's
main-only restriction, dedicated Boca SSH identity, independently verified
known-hosts pin and host variable are checked. Keep the deploy value unset
while inspecting. The release environment retains its own independent
`BOCA_RELEASE_ENV_READY` and remains unset. No secret is created or copied by
this code change.

CI executes the actual first-step shell with synthetic variable matrices:
read-only readiness must permit only inspection/preflight, and deploy readiness
must permit only install/diagnostic coordinates. Policy checks preserve both
variables and the pre-SSH gate. Neither synthetic test nor a read-only host
result authorizes publication, key creation, Docker changes or installation.
After a metadata candidate, the separate strict `preflight` still must prove
the rootless daemon, delegated cgroups, empty Boca namespace and capacity.
