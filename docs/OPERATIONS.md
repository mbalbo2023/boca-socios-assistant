# Safe operations — no active deployment yet

## Current state

Repository foundation only. All existing hosts and workloads must be left
untouched. No GitHub workflow in this release has remote-host credentials,
and CI never deploys.

## Proposed first installation (issue #62)

The draft `boca-first-deploy.yml` adds a manual, environment-gated path; it
is not on `main` and has not been run. `pull_request` only runs tests and the
isolation policy, with no host credentials. A manual dispatch is allowed only
from the exact current `main` commit by the repository owner after an
independent review and separate authorization recording the commit, complete
GHCR digest, successful release run, `controller`, resource budget and time
window. The reviewer must verify that the `boca-first-deploy` GitHub
environment has required reviewers, deployment branch restrictions and only
the Boca-specific credentials/variables. The readiness variable alone is
insufficient evidence of environment protection.

The proposed host prerequisite is a dedicated `boca-deploy` identity with UID
10001 and access only to its rootless Docker socket, Python 3.10+, and an already provisioned empty
`/srv/boca-socios` directory owned by that UID with mode 0700. A reviewer
must verify SSH host identity out of band and pin it in the environment's
known-hosts secret; the workflow has no `ssh-keyscan` fallback. Host setup is
not part of this PR. Confirm the GHCR package is accessible by the host
without placing registry credentials on it. If any prerequisite is absent,
stop before dispatch and record NO-GO; do not improvise a host change.

**Security correction #78:** Docker access must be to a dedicated rootless
socket at `/run/user/10001/docker.sock`; access to the shared rootful daemon
is NO-GO. The helper now pins that endpoint and rejects missing rootless/cgroup
evidence before any first-install or diagnostic phase. **Correction #80:**
the proposed key is generated within a Boca-only volume by the approved image
and mounted read-only by the UID 10001 controller. No host file secret or 0444
permission is used. This design still requires an isolated **rootless** trial
to prove actual key access and delegated CPU/memory/PID limits, host account
privileges and restart behavior. Do not dispatch merely because the runner
smoke passes. See [ADR 0033](ADR/0033-rootless-daemon-boundary.md) and
[ADR 0034](ADR/0034-rootless-key-custody.md).

The workflow first validates dispatch inputs and the successful manual image
release run for the same current `main` SHA. It downloads that run's immutable
manifest and requires the selected image digest, SHA and run ID to match
before opening SSH; an absent or expired artifact blocks installation. See
[ADR 0036](ADR/0036-release-digest-binding.md). It validates the resolved Compose
contract on the runner, reads aggregate host capacity and Boca-only resource
names, stages and hashes one Compose file, then validates the host-resolved
model before pulling the exact digest. Only then can it create an owner-only
random key in a separate rootless volume and start the simulation-only controller. Before reporting success,
it reuses the diagnostic contract to verify the actual container,
image, dormant engine, resource limits, volume mounts and key metadata. A startup or
postflight failure stops only that service, preserves the key and both volumes, and
requires separate diagnosis before another attempt. An existing Boca key,
container, either volume, network or staged file blocks a fresh installation; this
flow is not a recovery or upgrade procedure. The CPU snapshot is an estimate,
so a human capacity review is still required before authorization.

## Proposed read-only diagnostic under demand (issue #68)

The same protected workflow offers a manual `diagnostic` choice for a Boca
controller already installed from the exact current `main` SHA. After a
separate authorization and environment review, it checks only Boca Compose,
key **metadata** through a fixed in-container Python probe, immutable image identity, resource limits, health and
`BOCA_ENGINE_MODE=off`. It never reads the key value or database rows, starts
the motor, visits the site or changes a container. The run summary contains
only bounded status and immutable coordinates. A mismatch is NO-GO and
requires a reviewed diagnosis; it is not a reason to retry the first install
or alter another workload. This code has not been dispatched to a host.

## Proposed read-only host preflight (issue #84)

Before an image release or first install, the same protected manual workflow
can check the Boca rootless socket, cgroup delegation, dedicated identity,
empty Boca namespace and aggregate capacity with `operation=preflight`. Its
image and release-run fields must be blank. This operation has no stage,
pull, key, volume, container or site effect and is unavailable on PRs. It
requires the protected environment and pinned SSH identity; no host operation
has been dispatched. See [ADR 0035](ADR/0035-readonly-host-preflight.md).

## Proposed prerequisite inspection after false-negative socket checks (issue #90)

The same manual workflow adds `operation=inspect-prerequisites`, with blank
image and release-run fields. It checks socket and cgroup **metadata as UID
10001**, differentiating `absent` from `unavailable`, without running Docker
or altering the host. A failed job reports unproven prerequisites; a metadata
candidate is not proof that a Docker daemon is rootless or healthy. The
existing `preflight` remains mandatory before any release/install decision.
The environment must first be verified and marked ready as an **environment**
(pinned identity and main-only branch rule), independently
of the daemon's readiness. See [ADR 0037](ADR/0037-host-prerequisite-inspection.md).

The manual host workflow rejects reruns and verifies the current `main` ref
through the GitHub API before SSH. First installation repeats that check
immediately before applying the reviewed image; the host helper refuses a
real/effective UID or GID mismatch before private-path or Docker checks. A queued
run whose source SHA is no longer current fails closed. These controls do
not prove the SSH account has no other privileged route on the host.

## Proposed isolated deployment layout

| Item | Boca project | Unrelated workloads |
| --- | --- | --- |
| Repository | mbalbo2023/boca-socios-assistant | Existing repos, untouched |
| Compose project | boca-socios | Unknown existing names, never inspect destructively |
| Directory | Assigned only in a separately approved deployment | No shared subtree |
| Database | Boca-only named volume | No shared database |
| Network | Boca-only bridge | No shared network |
| Secrets | Boca-only key volume, separate from DB | No copied/reused keys |
| Image | Boca-only tag + digest | No reused images |
| Host ports | None initially | None altered |
| CPU/RAM controller | 0.5 vCPU / 256 MiB | Existing capacity protected |
| Deployment lock | Boca-specific | Never invoke another project's deployment lock |

## Gate before any future live Docker deployment

1. Explicit owner permission for a particular commit SHA, immutable image
   digest, Compose service, expected CPU/RAM/disk and time window.
2. Controlled GitHub Actions environment with required approval.
3. Check spare host disk/inodes/CPU/memory and existing service health using
   non-mutating observations. If capacity is insufficient: NO_GO.
4. Confirm Compose project is boca-socios; no host mounts, published ports,
   Docker socket, broad privileges or common secrets/volumes/networks.
5. Build once in CI, scan and publish image by digest. Deploy exact digest,
   never rebuild on the production host.
6. Serialize deployment with a Boca-only lock, never parallel retry.
7. Record pre/post health for Boca and observed absence of effects on every
   unrelated service; never touch or stop an existing workload.
8. On failure: stop Boca only, retain data, no destructive Docker prune,
   no blanket docker compose down and no deletion of volumes.

## Explicitly prohibited

docker system prune, docker volume prune, mass cleanup, restarting Docker
daemon, reboot, host-wide network changes, shared Compose files, altering
other services' ports or workflows, disabling host timers, publishing new
ports without approval and production SSH outside the owner-approved
Actions workflow.

