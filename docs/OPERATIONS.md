# Safe operations — verified evidence and gated procedures

## Current state

The default runtime remains dormant and CI never deploys. The dedicated rootless service
was prepared in #120 and stopped in #156/41272785626; the BETA application
remains not installed/NO_GO. The protected [image release 41312460820](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41312460820)
published `ghcr.io/mbalbo2023/boca-socios-assistant@sha256:67d8f59487632f117ec8c22d307481c1a9ba340502212d9bafe582309624301f`
with manifest 13086161844 for the pre-change #214 main
`8fdbec97262a525821eb87f3fbc27f1841a5d2ec`. This was registry-only,
with no droplet pull/install. Earlier releases 41301618285/#208 and
41302342233/`3ef7aff8...` are historical. The HEAD after this code change
requires a matching new release, tracked in [issue #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).
The [stop-test #198](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41282301501) observed `ALREADY_STOPPED
containers=not_queried data=preserved` at 03:48 ART; it did not inventory
stopped containers and future daemon state must be rechecked.
[Read-only preflight #124](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41268626135)
on `main` `213be4903669c6e88122a536ad8fee6785c997ac`, attempt 1, passed
at 2026-11-01 00:18 ART: UID10001, rootless boundary, empty namespace,
853288 KiB available memory, 8009560064 free bytes, 2902623 free inodes
and 1.60 CPU headroom. It tested the existing 0.5 CPU/256 MiB controller
contract and performed no install. It does not establish capacity for a
functional BETA with Chromium, public HTTPS access or Telegram.
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
[current BETA authorization](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6552258326)
extends the previously approved preparation to a connected private Site,
Telegram and a validated simulation BETA through the protected workflow.
Concrete identity, release and installation still require reviewed exact
candidate evidence and security gates, but the owner has already authorized
this scoped delivery. No reservation, purchase, Boca account mutation,
unreviewed migration of existing data, backup or unrelated infrastructure
operation is implied. Neither prior inspection nor first-time preparation is
a retry recipe.
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

Before final publication/installation, record the concrete reviewed candidate
with exact SHA, immutable images/manifests, access, schema/data handling,
capacity, stop plan and synthetic acceptance results. All recorded gates
precede the serial Actions operation under the current authorization. Then run the real
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

## Integrated stop-test for mandatory shutdown — issue #157

PR #165 integrated `stop-test` in
`1441d55a632d4a545b21ee7f6f2b0a4140ab2320` into the existing protected manual
workflow. It uses the same owner/main/environment/SSH/mutex gates, blank
image/release inputs and an immediate main recheck. Its reviewed helper checks
the dedicated unit/config and inventories all containers of the private
rootless daemon. Unknown containers prevent any stop; recognized Boca test
containers are stopped by exact ID, then the dedicated user unit is stopped.
Success requires no running Boca container, inactive unit, PID zero and absent
private Docker socket. The operation is idempotent when already stopped. It
preserves data/key volumes and enablement; a later reboot may start the daemon
again. CI 41269572935, scan 41269572802 and review 5726252792
cover its exact candidate. The protected manual
[run #156 / 41272785626](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41272785626)
on main `c1ecf8ae230bd8d02beef9f4e0d3dbf0c9aa5163` emitted
`BOCA_STOP_TEST state=STOPPED ... containers=0 data=preserved` after the
immediate main check. It stopped the dedicated daemon after preparation tests;
no BETA application had been installed. Reinspect after any reboot because
enablement was preserved.
See ADR0067.

## Protected Site custody phases — integrated, not dispatched

[PR #181](https://github.com/mbalbo2023/boca-socios-assistant/pull/181)
integrated `site-prepare`, `site-install` and `site-verify` into the same
protected manual workflow at
`9e923af56e76a04069bfad6f8ca9c68db0edd890`. Candidate
`4c8158d79a49924738b2a52573dc37cc91eccc1a` passed CI 41273068810,
scan 41273068858, disposable sealed owner-volume smoke/deploy validation
41273068811, release PR validation 41273068906 and review 5726437610. The
host job was skipped. These operations accept a reviewed release digest for
the exact main SHA; install accepts only a bounded, canonical sealed envelope
as ciphertext. They do not create the application DB/key, stage BETA Compose,
start a service or enable the Site bridge. See ADR0074.

The prior environment inspection found `BOCA_RELEASE_ENV_READY` absent.
It was subsequently set to `ready` only in `boca-image-release` without
changing its main-only branch rule. [Release #198](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41298346638) succeeded and
published the digest above for the then-current main SHA; verify a matching
release for any later HEAD. No Site custody phase was dispatched. Its real
recipient key and the Site bypass/HMAC material have not been installed on
the host. The dedicated daemon was observed ALREADY_STOPPED in protected
stop-test 41282301501; recheck its state before any future use.
A successful runner smoke cannot satisfy these host gates.

PR #196 integrated the Site custody global-inventory RCA in
`2768d23dd2e9e58563a13aa80d8b76885448d020`. Candidate
`2676bd9f0cb91e4da0785b0cd149e2d33fd5810a` passed CI 41276268828,
scan 41276268931, release/deploy validation 41276268935/41276268997 and
review 5726595915. It checks the entire dedicated rootless daemon before
and after each Site effect; the test injected a foreign container at five
boundaries. No Site host phase was dispatched. See ADR0082.

## Protected served BETA and acceptance — code only

**Newer candidate #223 / ADR0091:** the selected droplet/tunnel origin is
`http://localhost:8443`, without a device TLS certificate or CA. The
`beta-install` package still publishes **only** host `127.0.0.1:8443` from
the dedicated Boca rootless container. It must not configure, restart, proxy,
or modify any host web server, other application or port. An occupied or
unavailable 8443 is a fail-closed **STOP**, not a reason to stop the occupant.
The historical TLS code/release receipts below document earlier candidates;
neither they nor synthetic acceptance mean an installed panel. The one-use
Chrome registration link is still unimplemented and is an activation blocker.

PR #189 integrated image-side `check-beta-owner/config` without listener in
`63965b087fbd6d7a68308302bb8baf2e08975674` (candidate `b2b34a17`, CI
41274671069, scan 41274671077, release/deploy 41274671053/41274671118,
review 5726527799). These are file/identity/TLS preflights, not owner
enrollment or host configuration. See ADR0079.

PR #191 integrated a separate protected `beta-install` in
`161043f15befd5b612b71e036c9c1dead21581ce` (candidate `5265546`, CI
41275510437, scan 41275510471, release/deploy 41275510497/41275510438,
review 5726574754). It gates exact current main and successful protected
image digest, `BOCA_BETA_ENV_READY`, owner subject/origin, empty dedicated
daemon, owner-only files, key, new-only data volume, host-loopback TLS and
positive-identity rollback. Disposable runner smoke exercised both no-listener
preflights before data init. The host/publish jobs were skipped. See ADR0075.

PR #190 integrated the synthetic container TLS probe in
`64746289363741c4d85df79fa4e133b07f261efa`; PR #200 integrated protected
`beta-acceptance` in `f21b55f8cc79f9906b8ce1eff3fa1e6c152e896e`.
The latter candidate `8d629841` passed CI 41277081359, scan 41277081440,
release/deploy 41277081383/41277081431 and review 5726623269. Its PR
smoke ran the probe inside a capped disposable controller. A manual host run
would validate installed identity before/after the probe, then attempt
`stop-test` in the same job even on probe failure or main drift; success
requires a positive STOPPED receipt. No host BETA install/acceptance run has
occurred. Container-loopback tests do not prove owner tablet, Site or Telegram.
See ADR0076 and ADR0081.

PR #208 integrated `owner-prepare/install/verify` for the dedicated owner
volume, with purpose-bound ciphertext holding the physical passkey's **public**
credential and matching TLS/health material. ADR0086 defines the isolated
runner/host contract and the nonsecret receipt. Each owner phase temporarily
starts only the previously prepared, stopped Boca rootless daemon after its
unit/config/inventory proof, then requires `stop-test` in the same job even
after a failed phase; an uncertain stop remains NO-GO. This is code only:
no real owner passkey, origin, certificate, private tablet route or host
custody operation has been verified. The 41301618285 protected release is
SUCCESS for the historical #208 integration main `58f57822e95da9574c0a9d5122607616da4a024a`;
the later #214 release and the requirement for a new exact HEAD are recorded
above. Issue #209 holds
the private tablet route and first-owner ceremony. Do not set the BETA marker
or run `beta-install` from a synthetic fixture.

The earlier 2026-11-01 GitHub environment inspection found no
`BOCA_RELEASE_ENV_READY`; this release marker was then enabled and release
#198 succeeded for the source SHA above. The deploy environment still lacks
`BOCA_BETA_ENV_READY`, both Telegram readiness markers, protected bot/chat
assertions, owner origin/subject and real passkey/TLS files. There is a
protected image release/digest for the source SHA above, but no host install
or private tablet route. The dedicated Boca daemon was observed ALREADY_STOPPED
in stop-test 41282301501, without a stopped-container inventory; recheck
before another operation. Do not
dispatch `beta-install`, Site phases or `beta-acceptance` until their exact
gates are satisfied. No `prepare-rootless` retry over the existing unit.

## Telegram opt-in package — no host provisioning

PR #188 integrated a separate default-off worker in
`1bdc80b7f50021227cd798e655844b157198ea93`; #194 integrated exact
Telegram container recognition for `stop-test` in
`451e40bf08e271f7fdf9dbb975ec5a1ed45bc298`; #199 integrated sealed
bot/destination custody helper in
`a808a6455e624eea7e1eeb7bedd10f3ab63f9a7c`. #203 integrated protected
post-install schema0007 and sealed custody phases in
`487995ca57282e2947d977333e72bd10775fbb98`. #204 integrated a protected
one-shot Bot API identity/send test in `5cb8ce17715f571979a2ea3bb092da9b470f362d`.
Exact local/hosted evidence and reviews are in
[the integration status](BETA_INTEGRATION_STATUS.md).
No bot,
destination, schema0007 migration, private volume, worker or send has been
provisioned on the droplet. The new stop-test code itself has not run on the
host. See ADR0078/0080/0083/0084/0085 and issue #168.

## Implemented first-install contract — not executed

The integrated `boca-first-deploy.yml` provides a manual, environment-gated
installation path. Its read-only inspection has run; first-install has not.
`pull_request` only runs tests and the isolation policy, with no host credentials. A manual dispatch is allowed only from
the exact current `main` commit by the repository owner after agent technical
review, green exact-SHA checks and a recorded gate receipt for the commit,
complete GHCR digest, successful release run, `controller` and resource
budget. The protected `boca-first-deploy` GitHub environment must restrict
deployment to `main` and contain only Boca-specific credentials/variables.
The current owner authorization in #45 includes this simulation BETA delivery;
the ruleset still requires the candidate review and exact checks. Readiness
alone does not prove environment protection or operational success.
The manual job uses separate fail-closed environment variables: only
`BOCA_HOST_READONLY_ENV_READY=ready` can enable `inspect-prerequisites`,
`port-check` or `preflight`, while `BOCA_DEPLOY_ENV_READY=ready` is required for prepare-rootless,
first-install, diagnostic or `stop-test`. READONLY was set before #66; DEPLOY was added only
to the protected environment for #120, without changing secrets/protections.
RELEASE was not enabled by that preparation. Revalidate scope/values before
another operation; a readiness marker does not itself authorize it. Read-only
choices and prepare-rootless require blank image/release inputs; first-install
and diagnostic require both. See ADR0046 and ADR0058.

`port-check` probes only the Boca host's fixed IPv4 `127.0.0.1:8443` with a
dedicated-UID bind and immediate close. It returns an allowlisted FREE/BUSY/
ERROR receipt, does not enumerate or connect to a process, and runs without
the rootless daemon. The BETA install workflow repeats this check just before
app/key effects. A FREE result is instantaneous and does not reserve the port;
the later Docker binding/local-HTTP probe and real tablet access have separate gates.
See ADR0087 and issue #211.

The later protected [run 41310958281](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41310958281)
on exact `main=3ec1096fb5dce8a01af5c8060f0be056bf44fb9d`, attempt 1,
passed `BOCA_PORT_CHECK state=FREE address=127.0.0.1 port=8443 reserved=no`.
This supersedes only the preceding absence of a host port observation; it did
not start Boca. The owner selected a private local tablet forward and kept
Site decommission pending. ADR0088's old candidate origin
`https://localhost:8443` is superseded for the SSH-only BETA by
`http://localhost:8443` in ADR0091, without device certificates or CA.
Do not dispatch owner custody or BETA install until the physical tablet route,
one-time enrollment authorization and real passkey are verified. The present single owner
credential needs separate Android/iOS interoperability proof. No terminal
operation by the owner replaces the gated Actions host workflow.

## First-owner registration on Chrome — new host link still pending

The old #215/ADR0089 one-use **device-local** Python/TLS emitter is retained
for historical audit only; **do not ask the owner to run it**. Per #223/ADR0091,
the planned Chrome flow must be served by a temporary Boca-only registration
service on the *same* droplet host loopback 8443 through Termius SSH. The
owner wants one private URL with a short-lived 256-bit one-use key. No such
URL/endpoint exists yet. The design must prevent token exposure in publicly
accessible GitHub Actions logs, workflow dispatch history, PRs or screenshots;
authorization must be consumed atomically before creating a discoverable
WebAuthn passkey, and the physical create→get ceremony must verify the user.
Only the public credential ID/ES256 key may persist in Boca owner custody.
The private passkey stays in the chosen Android credential manager; it is not
a permanent browser cookie. The panel session cookie remains HttpOnly/Secure/
SameSite=Strict, with 15-minute idle and 8-hour absolute expiration and
revocation on process restart. Real Chrome localhost Secure-cookie acceptance,
Google Password Manager persistence and iOS compatibility remain physical
gates. SSH encrypts the remote path, **not** an app-to-localhost connection
inside Android; do not claim general HTTPS-equivalent protection.

The current sequence is **NO-GO for host operations**: review a private token
handoff, implement the single-use host enrollment phase, verify the real Chrome
flow and forwarding, then perform the separate protected owner and BETA phases
with exact HEAD/release/port/isolation gates. Do not touch a shared web server,
create a public listener, add a new host port, or run another workload's Docker
command. Failed Boca BETA staging still invokes the immediate selective cleanup
of ADR0090, preserving all persistent and uncertain volumes.

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

**Failed served BETA install — #219/PR #220 integrated in code, no host run:**
the same protected Actions workflow adds a bounded cleanup step immediately
after the existing `beta-rollback` failure step. Only after the BETA staging
marker does it check exact Docker rootless identity, SHA/digest/Compose hash,
entire dedicated-daemon container inventory, controller UID/labels/mounts,
private network attachments and named owner/key/data volumes. It may stop
and discard only that exact failed BETA controller (without removing volumes),
its unused private network, its unshared digest image and its exact staged
`compose.beta.yaml`; it confirms each removal and unchanged volume inventory.
The protected owner/key/data volumes remain deliberately, even when freshly
created, because their contents cannot be assumed disposable. The original
deploy still fails. A changed/unknown artifact, unreachable daemon or
mid-cleanup failure yields `NO_GO INDETERMINADO`, an inventory gate and no
automatic retry. Cancelling/losing the Actions runner can prevent the hook;
no unconditional zero-residue guarantee is claimed. See
[ADR 0090](ADR/0090-immediate-failed-beta-deploy-cleanup.md). No host cleanup
was performed merely by adding this code.

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

## Implemented read-only host preflight — executed in #124

Before an image release or first install, the same protected manual workflow
can check the Boca rootless socket, cgroup delegation, dedicated identity,
empty Boca namespace and aggregate capacity with `operation=preflight`. Its
image and release-run fields must be blank. This operation has no stage,
pull, key, volume, container or site effect and is unavailable on PRs. It
requires the protected environment and pinned SSH identity. Prerequisite
inspection ran before #120. The stricter daemon preflight subsequently passed
in #124/41268626135 with the existing controller budget. Its success does not
validate a different Compose budget or the final functional candidate. See
[ADR 0035](ADR/0035-readonly-host-preflight.md).

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
That initial verification enabled only `BOCA_HOST_READONLY_ENV_READY` for the first
inspection, scoped to the protected `boca-first-deploy` environment after
checking no repository-level variable of that name exists; the shell cannot
prove variable scope. That read-only authorization did not permit setting
`BOCA_DEPLOY_ENV_READY` or `BOCA_RELEASE_ENV_READY`. Subsequently, the separately
approved preparation scope enabled `BOCA_DEPLOY_ENV_READY=ready` in that
protected environment for run #120. `BOCA_RELEASE_ENV_READY` was enabled later for release #198; the deployment
marker does not itself approve application installation.
A successful metadata inspection
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
4. Confirm Compose project is boca-socios; no host mounts, Docker socket,
   broad privileges or common secrets/volumes/networks. The dormant package
   publishes no port; the approved served BETA binds only reviewed
   `127.0.0.1:8443`, never a wildcard or public interface.
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


