# ADR 0042: verify actual Boca runtime and storage after image pull

**Status:** Proposed for issues #105 and #106, 2026-10-31. No host operation.

## RCA

The first-install preflight measured free bytes and inodes before an image
pull, then initialized a key volume immediately after checking the image
digest and revision. A pull could consume the remaining storage budget.
The postflight inspected configured CPU/memory/PID limits, but did not prove
the actual cgroup limits or the container's network, capabilities, security
options and tmpfs. A green disposable runner could not establish the
rootless droplet's actual configuration.

## Decision

The apply phase measures both Boca staging and the validated classic rootless
Docker data root before and after pull. Each measurement revalidates the
dedicated socket, rootful inaccessibility, rootless daemon, systemd cgroup v2
and delegated controllers. It compares the socket identity, root path,
classic driver and status, and both directory device/inode identities. It
rejects a changed backend, path, socket, directory, unreadable filesystem or
less than 4 GiB or 50,000 free inodes on either filesystem **before creating
the key**. It also rechecks the staged Compose hash after pull. A failed gate
leaves the exact image and staged file
for the guarded #97 cleanup attempt; unknown or partial state is retained
for Boca-only diagnosis. No prune or automatic retry is introduced.

After the controller starts and passes the existing key, image and health
checks, the same read-only diagnostic now inspects the exact controller ID.
It requires one Boca private network, no network port mapping, the expected
NetworkMode and the attached network's exact ID, Compose labels, bridge
configuration and only the controller as a peer. It requires no added
capabilities, all capabilities dropped, no-new-privileges, the approved /tmp
tmpfs and a private cgroup namespace.
A fixed module in the approved image runs as UID 10001 in that container;
it reads only /proc/self/cgroup and the cgroup v2 cpu.max, memory.max and
pids.max files. It requires the private namespace root and effective
0.5 CPU, 256 MiB and 64 PIDs, returning a small numeric receipt. Missing,
unlimited or unexpected values fail closed. The manual diagnostic reuses the
same contract. A postflight error attempts to stop only the Boca controller
and keeps key/data volumes, image and network for separate diagnosis. If the
stop itself fails, a bounded `BOCA_ROLLBACK_UNVERIFIED` marker is emitted; the
controller state remains unknown and needs Boca-only inventory before retry.

Immediately before `BOCA_DEPLOY_PASS`, the helper measures both filesystems
again and checks the same topology and reserve. The bounded PASS receipt
includes final free bytes/inodes and whether both paths share a device; the
figures are observations, not proof of causality or additive capacity. The
disposable Actions runner smoke probes these properties on its own daemon,
but **does not prove** the host UID mapping, delegation, socket, network or
capacity. Only the dedicated protected Boca Actions workflow can later
establish host evidence. The workflow has not been dispatched to the host.

## Limits

Measurements cannot reserve space against another actor or make separate
Docker metadata reads atomic. The dedicated UID, rootless socket and
serialized workflow remain mandatory. If the daemon uses containerd image
storage or any unproven backend, the existing #91 gate remains NO-GO. This
change does not use real credentials, make site calls, create backups, or
alter other workloads.

Primary references: [Docker rootless cgroup limits](https://docs.docker.com/engine/security/rootless/tips/#limiting-resources),
[cgroup v2 runtime metrics](https://docs.docker.com/engine/containers/runmetrics/#running-docker-on-cgroup-v2),
[Docker inspect](https://docs.docker.com/reference/cli/docker/inspect/).
