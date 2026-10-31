# Safe operations — no active deployment yet

## Current state

The runtime is foundation-only, and CI never deploys. The Boca-only manual
workflow is being integrated behind objective gates; its private environment
already contains the pre-existing SSH identity and an authorized host-key pin.
No host operation has run through it.

## Proposed first installation (issue #62)

The proposed `boca-first-deploy.yml` adds a manual, environment-gated path; it
has not run on the host. `pull_request` only runs tests and the isolation
policy, with no host credentials. A manual dispatch is allowed only from
the exact current `main` commit by the repository owner after agent technical
review, green exact-SHA checks and a recorded gate receipt for the commit,
complete GHCR digest, successful release run, `controller` and resource
budget. The protected `boca-first-deploy` GitHub environment must restrict
deployment to `main` and contain only Boca-specific credentials/variables.
The owner's standing direction requires no additional human approval. The
readiness variable alone is insufficient evidence of environment protection.

The proposed host prerequisite is a dedicated `boca-deploy` identity with UID
10001, dedicated rootless Docker, Python 3.10+, and an already provisioned empty
`/srv/boca-socios` directory owned by that UID with mode 0700. The SSH host
identity must be independently verified and pinned in the environment's
known-hosts secret; the workflow has no `ssh-keyscan` fallback. Host setup is
not part of this PR. Confirm the GHCR package is accessible by the host
without placing registry credentials on it. If any prerequisite is absent,
stop before dispatch and record NO-GO; do not improvise a host change.

**Security correction #78:** Docker access must be to a dedicated rootless
socket at `/run/user/10001/docker.sock`; access to the shared rootful daemon
is NO-GO. The helper checks real/effective UID/GID before private paths, pins
that endpoint, strips inherited context/TLS client settings and rejects
missing rootless/cgroup evidence before any first-install or diagnostic phase.
**Correction #80:** The key is generated inside a separate Boca-only volume
under the container UID map and mounted read-only by the UID 10001 controller.
No host file secret or 0444 permission is used. An isolated rootless trial
must still prove key access, delegated CPU/memory/PID limits, host account
privileges and restart/retention. Do not dispatch merely because the runner
smoke passes. See [ADR 0033](ADR/0033-rootless-daemon-boundary.md) and
[ADR 0034](ADR/0034-rootless-key-custody.md).

The workflow first validates dispatch inputs and the successful manual image
release run for the same current `main` SHA. It downloads that run's immutable
manifest and requires the selected image digest, SHA and run ID to match
before opening SSH; an absent or expired artifact or any rerun attempt blocks
installation. See [ADR 0036](ADR/0036-release-digest-binding.md). It validates
the resolved Compose contract on the runner, reads aggregate host capacity
and Boca-only resource names, stages and hashes one Compose file, then
validates the host-resolved model before pulling the exact digest. It then
creates an owner-only key once inside a separate rootless volume and starts
the simulation-only controller.
Before reporting success, the helper reuses the read-only diagnostic contract
to check the actual container, image, dormant engine, resource limits, both
mounts and key metadata. Startup or postflight failure stops only the Boca
controller and preserves the key and both volumes for separate diagnosis. An
existing Boca key, container, volume, network or staged file blocks a fresh
installation; this flow is not recovery or upgrade. The CPU snapshot is an
estimate; this gate now measures staging and rootless image storage separately,
while #106 still needs post-pull capacity proof. #99 remains pending. An
external source failure is reported by Actions as an alert, not a deploy
blocker for the simulation-only controller.

After a failed first-install, the same Actions job attempts selective cleanup
only if the read-only preflight, current-main recheck and staging marker passed.
It removes an exact unreferenced image without force if no container uses it,
even when key/data volumes remain. It removes the matching staged Compose file
only when no Boca container, volume or network exists; otherwise it retains
that file and all volumes/networks and reports `PARTIAL` or `RETAINED`. The
bounded receipt records staging and rootless Docker data free space/inodes
before and after, plus whether they share a filesystem. Virtual image size
and observed free-space changes are not proof of causal reclamation. Unknown
storage backends or paths stop before deletion. A failed or unverified cleanup
reports `NO_GO INDETERMINADO`: a partial deletion may have occurred, and a
Boca-only inventory is required before any retry. The original install
failure remains failed. See [ADR 0039](ADR/0039-boca-failed-install-cleanup.md).

## Read-only diagnostic under demand (issue #68)

The same protected workflow proposes a manual `diagnostic` choice for a Boca
controller already installed from the exact current `main` SHA. Under the
owner's standing direction, its recorded gates and environment restrictions
must match the exact operation, SHA, digest, service and budget. It checks
only Boca Compose, key **metadata**, immutable image identity, resource
limits, both mounts, health and `BOCA_ENGINE_MODE=off`. A fixed in-container
probe checks key metadata without printing bytes. It never reads the key
value or database rows, starts the motor, visits the site or changes a container.
The run summary contains only bounded status and immutable coordinates. A
mismatch is NO-GO and requires diagnosis; it is not a reason to retry the
first install or alter another workload. The helper checks real/effective
UID/GID before private metadata and pins rootless Docker transport. It must
remain uninvoked until the environment, identity and host prerequisites are
verified under the objective gates. No host diagnostic has run yet.

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
before staging Compose and again immediately before applying the reviewed
image; the host helper refuses a real/effective UID or GID mismatch before
private-path or Docker checks. A queued
run whose source SHA is no longer current fails closed. These controls do
not prove the SSH account has no other privileged route on the host.
The read-only capacity gate checks free bytes and inodes separately on the
Boca staging directory and the dedicated rootless daemon's verified
`DockerRootDir` beneath the private Boca home. Unknown storage location,
ownership or available capacity is NO-GO; a healthy staging filesystem alone
cannot establish that image storage has headroom.

## Proposed isolated deployment layout

| Item | Boca project | Unrelated workloads |
| --- | --- | --- |
| Repository | mbalbo2023/boca-socios-assistant | Existing repos, untouched |
| Compose project | boca-socios | Unknown existing names, never inspect destructively |
| Directory | Dedicated Boca-owned path after gated Actions preflight | No shared subtree |
| Database | Boca-only named volume | No shared database |
| Network | Boca-only bridge | No shared network |
| Secrets | Boca-only key volume, separate from DB | No copied/reused keys |
| Image | Boca-only tag + digest | No reused images |
| Host ports | None initially | None altered |
| CPU/RAM controller | 0.5 vCPU / 256 MiB | Existing capacity protected |
| Deployment lock | Boca-specific | Never invoke another project's deployment lock |

## Gate before any future live Docker deployment

1. Under the owner's standing direction, record the exact current commit SHA,
   immutable image digest for an install, Compose service, CPU/RAM/disk budget
   and operation before autonomous dispatch. A merge never deploys by itself.
2. Controlled GitHub Actions environment, main-only branch restriction,
   dedicated SSH identity and pinned host key; no required human approval.
3. Check spare host disk/inodes/CPU/memory and existing service health using
   non-mutating observations. If capacity is insufficient: NO_GO.
4. Confirm Compose project is boca-socios; no host mounts, published ports,
   Docker socket, broad privileges or common secrets/volumes/networks.
5. Build once in CI, scan and publish image by digest. Deploy exact digest,
   never rebuild on the production host.
6. Serialize deployment with a Boca-only lock, never parallel retry.
7. Record Boca-only pre/post health and disk/inode capacity; never touch or
   stop an existing workload or enumerate unrelated services destructively.
8. On failure: inventory the Boca attempt through the same Actions workflow,
   stop Boca only, then remove positively identified unused disposable Boca
   image/staging remnants with before/after measurements.
   Retain key/data volumes and uncertain resources. No destructive Docker
   prune, blanket compose down, or volume deletion.
9. Diagnose any external-source failure via bounded read-only Actions before
   proposing a new deploy. Report green/yellow/red/unknown with timestamp;
   source failure is an alert, not a NO_GO for the simulation-only controller.
   A demonstrated code defect may be fixed in a new PR. Security, image,
   capacity and isolation gates remain strict.

## Explicitly prohibited

docker system prune, docker volume prune, mass cleanup, restarting Docker
daemon, reboot, host-wide network changes, shared Compose files, altering
other services' ports or workflows, disabling host timers, publishing new
ports without approval and production SSH outside the owner-approved
Actions workflow.

