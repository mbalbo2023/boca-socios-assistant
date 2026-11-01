# Safe operations — verified evidence and gated procedures

## Current state

The runtime remains dormant and CI never deploys. The dedicated rootless service
is now prepared, while the BETA application remains not installed/NO_GO.
[Run #120](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41262650418)
(attempt1, job124718888659, source `6be606f83c5a6afe0ba7226abbca6a09276d1ca1`)
executed prepare-rootless successfully after exact-source CI41262581358 and
scan41262581422. The apply receipt at 2026-10-31 22:49:24 ART reported
SERVICE_READY, application_database=not_accessed and application=not_installed.
The reviewed helper verified rootless/cgroup-v2-systemd/overlay2/private data
root, zero containers and an empty Boca namespace before enabling its user unit.
See the [operational receipt](https://github.com/mbalbo2023/boca-socios-assistant/issues/145#issuecomment-6551973756).

Only dedicated daemon configuration, unit, enablement and private Docker
bookkeeping were created. No image was released/pulled, no container, SQLite,
application/key volume or key was created, and no backup ran. Informative
capacity was 8010493952 bytes/2902936 inodes at check, then 8010489856/2902936
before apply effects and 8010072064/2902879 after; application_budget=not_checked.
These readings do not validate BETA resource capacity or causal disk usage.
Global location of any older database remains UNVERIFIED.

The earlier inspection #98 on source5c642b6d8bf5feac14aaf4a7c4df34ca2e91a97e
found the service/socket absent and DB/WAL/SHM candidate-absent only at the three
fixed paths of ADR0054. It remains historical evidence; #120 supersedes the
service state, not the limited meaning of that database inventory. No SQLite
content was opened by either operation. Do not rerun #98 or prepare-rootless:
first-time preparation must now preserve the configuration it created.

The earlier scoped diagnosis/fix work is complete. The
[approved BETA direction](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6551681142)
now authorizes preparation/development of the delivery plan, including private
enrollment, dedicated rootless direction, own-application panel, chosen logical
storage and efficiency measurements. Complete routine approved work without
asking again. Concrete identity/bootstrap/private access and final reviewed
release/install candidate gates remain decisions in the plan. No existing real
DB migration, real credentials or general unrelated infrastructure authority
is implied. Neither prior inspection nor first-time preparation is a retry recipe.
See issue #45 for the current scoped decision and BETA_INTEGRATION_STATUS.md
for the source/integration cut. PR #141 separately fixed the migration function
through synthetic fixtures; merging it did not run Database.migrate on the
droplet or create a service database. ADR0053 states the WAL/concurrency limits.

## Functional BETA preparation and final operation

Follow [BETA_DELIVERY_PLAN](BETA_DELIVERY_PLAN.md). The chosen future database
mount is `/data/boca.sqlite3` on `boca-socios_boca_data`, with a separate key.
The choice does not mean the file exists or authorize replacing storage found
later. First-install's empty-namespace assumption must be checked; an existing
installation needs a compatible reviewed procedure, not deletion by default.

For subsequent approved host work through the sole workflow, verify
service/socket/cgroups/storage capacity and separate the browser budget. Do
not reinstall Docker merely because the user unit was absent. The existing
install/diagnostic code expects the dormant controller with no exposed ports;
it must be reviewed against the functional runtime/private-access candidate.
Completing code here does not itself configure the host or deploy the BETA.

Before final publication/installation, present the concrete reviewed candidate
with exact SHA, immutable images/manifests, access, schema/data handling,
capacity, stop plan and synthetic acceptance results. The final decision and
all recorded gates precede the serial Actions operation. Then run the real
interface acceptance with synthetic enrollment, start/stop/status, local notices
and authorized restart. Preserve data/key on failure; no backup or other project.

## Implemented prepare-rootless contract — executed once in #120

PR #150 adds prepare-rootless to the same protected workflow. It uses the
existing BOCA_DEPLOY_ENV_READY mutation gate, blank image/release inputs and
fixed controller/budget coordinates. Those coordinates do not establish an
application budget for the daemon. The helper check is read-only; Actions
rechecks current main immediately before apply, which repeats prerequisites.
Apply runs an ephemeral isolated namespace smoke before persistent writes,
creates daemon configuration/user unit exclusively, validates configuration
and effective unit provenance, starts only the dedicated user docker.service,
verifies the private rootless daemon, then enables only that unit. No package
installation, shared-daemon access or application/DB/key creation is included.

The procedure refuses existing configuration, enablement, unsafe paths or a
nonempty/inaccessible dedicated data root; it is not repair/upgrade. Capacity
receipts are informative, leaving application preflight separate. Failures
preserve files/data; after an attempted start, only that new service is stopped.
An enablement link may remain after a late failure even if stop succeeds:
report UNVERIFIED and inspect the exact Boca state before retry. Diagnostics
expose only fixed phase/exit/timeout and allowlisted unit Result/ExecMainStatus,
never stderr or journal. See ADR0058 for prerequisites and limits.

## Implemented first-install contract — not executed

The integrated `boca-first-deploy.yml` provides a manual, environment-gated
installation path. Its read-only inspection has run; first-install has not.
`pull_request` only runs tests and the isolation policy, with no host credentials. A manual dispatch is allowed only from
the exact current `main` commit by the repository owner after agent technical
review, green exact-SHA checks and a recorded gate receipt for the commit,
complete GHCR digest, successful release run, `controller` and resource
budget. The protected `boca-first-deploy` GitHub environment must restrict
deployment to `main` and contain only Boca-specific credentials/variables.
The owner must approve the concrete installation scope after options and a
recommendation. The ruleset not requiring a human approving PR review does not
waive that decision. Readiness alone does not prove environment protection.
The manual job uses separate fail-closed environment variables: only
`BOCA_HOST_READONLY_ENV_READY=ready` can enable `inspect-prerequisites` or
`preflight`, while `BOCA_DEPLOY_ENV_READY=ready` is required for prepare-rootless,
first-install or diagnostic. READONLY was set before #66; DEPLOY was added only
to the protected environment for #120, without changing secrets/protections.
RELEASE was not enabled by that preparation. Revalidate scope/values before
another operation; a readiness marker does not itself authorize it. Read-only
choices and prepare-rootless require blank image/release inputs; first-install
and diagnostic require both. See ADR0046 and ADR0058.

The host prerequisite is a dedicated `boca-deploy` identity with UID
10001, dedicated rootless Docker, Python 3.10+, and an already provisioned empty
`/srv/boca-socios` directory owned by that UID with mode 0700. The SSH host
identity must be independently verified and pinned in the environment's
known-hosts secret; the workflow has no `ssh-keyscan` fallback. First-install
does not provision these prerequisites; prepare-rootless is the separate
reviewed operation described above. Confirm the GHCR package is accessible by the host
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

For first-install/diagnostic, the workflow validates dispatch inputs and the
successful manual image
release run for the same current `main` SHA. It downloads that run's immutable
manifest and requires the selected image digest, SHA and run ID to match
before opening SSH; an absent or expired artifact or any rerun attempt blocks
installation. See [ADR 0036](ADR/0036-release-digest-binding.md). It validates
the resolved Compose contract on the runner, reads aggregate host capacity
and Boca-only resource names, stages and hashes one Compose file, then
validates the host-resolved model before pulling the exact digest. It then
rechecks the Compose hash, rootless Docker backend/path/device and free
bytes/inodes on staging and Docker storage **after the pull**, before creating
an owner-only key once inside a separate rootless volume and starting the
simulation-only controller.
Before reporting success, the helper reuses the read-only diagnostic contract
to check the actual container, image, dormant engine, resource limits, both
mounts, network, capabilities, tmpfs, effective cgroup v2 limits and key
metadata. It measures both capacities again before the PASS receipt. Startup
or postflight failure attempts to stop only the Boca controller and preserves
the key and both volumes for separate diagnosis. A failed stop leaves the
controller state unverified: `BOCA_ROLLBACK_UNVERIFIED`, NO-GO and Boca-only
inventory before retry. An
existing Boca key, container, volume, network or staged file blocks a fresh
installation; this flow is not recovery or upgrade. The CPU snapshot remains
an estimate and capacity cannot be reserved against another actor. See
[ADR 0042](ADR/0042-effective-runtime-and-post-pull-capacity.md). An external
source failure is reported by Actions as an alert, not a deploy blocker for
the simulation-only controller.

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

The same protected workflow provides a manual `diagnostic` choice for a Boca
controller already installed from the exact current `main` SHA. With the
concrete operation scope approved, its recorded gates and environment restrictions
must match the exact operation, SHA, digest, service and budget. It checks
only Boca Compose, key **metadata**, immutable image identity, resource
limits, effective cgroup values, one Boca-only network, security flags,
tmpfs, both mounts, health and `BOCA_ENGINE_MODE=off`. Fixed in-container
probes check key metadata and cgroup files without printing key bytes. It
never reads the key value or database rows, starts the motor, visits the site
or changes a container.
The run summary contains only bounded status and immutable coordinates. A
mismatch is NO-GO and requires diagnosis; it is not a reason to retry the
first install or alter another workload. The helper checks real/effective
UID/GID before private metadata and pins rootless Docker transport. It must
remain uninvoked until the environment, identity and host prerequisites are
verified under the objective gates. No operation=diagnostic of an installed
controller has run; prerequisite/file inspections have.

## Implemented read-only host preflight — not executed

Before an image release or first install, the same protected manual workflow
can check the Boca rootless socket, cgroup delegation, dedicated identity,
empty Boca namespace and aggregate capacity with `operation=preflight`. Its
image and release-run fields must be blank. This operation has no stage,
pull, key, volume, container or site effect and is unavailable on PRs. It
requires the protected environment and pinned SSH identity. Prerequisite
inspection has run, but the stricter daemon preflight has not passed. See [ADR 0035](ADR/0035-readonly-host-preflight.md).

## Executed prerequisite inspection and its limits

The same manual workflow provides `operation=inspect-prerequisites`, with blank
image and release-run fields. #140 added fixed-path DB/WAL/SHM metadata receipts
without opening SQLite or file contents; ADR0054 defines their narrow scope. It checks socket and cgroup **metadata as UID
10001**, differentiating `absent` from `unavailable`, without running Docker
or altering the host. A failed job reports unproven prerequisites; a metadata
candidate is not proof that a Docker daemon is rootless or healthy. The
existing `preflight` remains mandatory before any release/install decision.
The environment must first be verified and marked ready as an **environment**
(pinned identity and main-only branch rule), independently
of the daemon's readiness. See [ADR 0037](ADR/0037-host-prerequisite-inspection.md).
That verification may enable only `BOCA_HOST_READONLY_ENV_READY` for the first
inspection, scoped to the protected `boca-first-deploy` environment after
checking no repository-level variable of that name exists; the shell cannot
prove variable scope. It must not set `BOCA_DEPLOY_ENV_READY` or
`BOCA_RELEASE_ENV_READY`. The latter gates remain closed until separate
release and deployment evidence exists. A successful metadata inspection
permits considering the stricter read-only `preflight`; it is not host approval.

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

## Configured isolated deployment layout — not evidence of host resources

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

1. Present infrastructure/business options and a recommendation; obtain owner
   approval for the concrete scope. Record the exact current commit SHA,
   immutable image digest for an install, Compose service, CPU/RAM/disk budget
   and operation before dispatch. A merge never deploys by itself.
2. Controlled GitHub Actions environment, main-only branch restriction,
   dedicated SSH identity and pinned host key. Technical checks do not replace
   the scope approval above.
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


