# ADR 0033: prove a dedicated Docker boundary before host operations

**Status:** Proposed for issue #78, 2026-10-29. No host operation performed.

## Incident and decision

The first-install helper in #62/#71 checked the Boca namespace and host
capacity but accepted whichever Docker daemon the `boca-deploy` account could
reach. If that account controls the shared rootful Docker socket, a compromised
deployment identity could obtain host root authority despite the script's
Boca-only commands. The actual droplet daemon and SSH permissions have **not**
been observed. This is a conditional threat, not a claim about the host.

All first-install phases and the read-only diagnostic now fail before their
other actions unless the dedicated UID 10001 owns the private runtime
directory and rootless Unix socket, cannot write the conventional rootful
socket, and `docker info` on the **explicit** rootless socket reports
`name=rootless`, cgroup v2 and the systemd driver. The user service's
`cgroup.controllers` must list `cpu`, `memory` and `pids`. Every Docker command
in the helper pins `DOCKER_HOST` to that socket and discards an inherited
Docker context/TLS target. Absent or malformed evidence is NO-GO. The checks
read metadata only; they do not enumerate or change another workload.

## Limits and next review

This guard prevents the proposed helper from intentionally operating the
shared rootful daemon. It does not prove that an SSH identity has no *other*
privileged path (sudo, another socket, group or host policy); an independent
host identity review is still required. Nor does a successful `docker info`
prove that Compose enforces the limits after a container starts. A separate
isolated-host run must inspect actual cgroup limits and health.

**Rootless secret incompatibility:** the current Compose file mounts a host
UID 10001, mode 0400 key as a file and runs the container as UID 10001.
Docker's rootless UID map makes host UID 10001 appear as container UID 0;
container UID 10001 maps to a subordinate host UID. Compose file-backed
secrets do not remap ownership or mode. The controller therefore may not be
able to read the key under rootless Docker. Do not relax mode to 0444, pass the
key through Actions or claim deploy readiness. Design and test a dedicated
rootless-compatible key/volume custody path in a separate reviewed PR before
any dispatch. CPU delegation also needs a real host check, not a fixture.

No merge, image release or droplet operation is authorized by this ADR. The
remaining #10, independent PR/environment reviews, exact digest/SHA/service,
capacity and window gates still apply.

Primary references: [Docker rootless](https://docs.docker.com/engine/security/rootless/),
[rootless cgroup limits](https://docs.docker.com/engine/security/rootless/tips/#limiting-resources),
[UID/GID mapping](https://docs.docker.com/engine/security/rootless/uid-gid-mapping/),
[Compose file secrets](https://docs.docker.com/reference/compose-file/services/#secrets).
