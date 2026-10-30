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

The workflow first validates dispatch inputs and the successful manual image
release run for the same current `main` SHA. It validates the resolved Compose
contract on the runner, reads aggregate host capacity and Boca-only resource
names, stages and hashes one Compose file, then validates the host-resolved
model before pulling the exact digest. The current draft's host-side key file
is not proven readable under rootless UID mapping; #81 must replace that
custody path before any host install. A startup failure stops only the Boca
service, preserves the key and volume, and requires separate
diagnosis before another attempt. An existing Boca key, container, volume,
network or staged file blocks a fresh installation; this flow is not a
recovery or upgrade procedure. The CPU snapshot is an estimate; #91 adds
separate measurement of staging and rootless image storage. #79, #81, #89,
#91, #97 and the strict postflight remain pending gates. An external source
failure is reported by Actions as an alert, not a deploy blocker for the
simulation-only controller.

## Proposed isolated deployment layout

| Item | Boca project | Unrelated workloads |
| --- | --- | --- |
| Repository | mbalbo2023/boca-socios-assistant | Existing repos, untouched |
| Compose project | boca-socios | Unknown existing names, never inspect destructively |
| Directory | Dedicated Boca-owned path after gated Actions preflight | No shared subtree |
| Database | Boca-only named volume | No shared database |
| Network | Boca-only bridge | No shared network |
| Secrets | Boca-only source and file | No copied/reused keys |
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
   image/container/network/staging remnants with before/after measurements.
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

