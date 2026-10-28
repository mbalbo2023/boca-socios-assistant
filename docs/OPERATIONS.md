# Safe operations — no active deployment yet

## Current state

Repository foundation only. All existing hosts and workloads must be left
untouched. No GitHub workflow in this release has remote-host credentials,
and CI never deploys.

## Proposed isolated deployment layout

| Item | Boca project | Unrelated workloads |
| --- | --- | --- |
| Repository | mbalbo2023/boca-socios-assistant | Existing repos, untouched |
| Compose project | boca-socios | Unknown existing names, never inspect destructively |
| Directory | Assigned only in a separately approved deployment | No shared subtree |
| Database | Boca-only named volume | No shared database |
| Network | Boca-only bridge | No shared network |
| Secrets | Boca-only source and file | No copied/reused keys |
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

