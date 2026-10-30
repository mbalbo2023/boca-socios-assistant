# ADR 0033: prove a dedicated Docker boundary before host operations

**Status:** Proposed for issue #78, 2026-10-29. No host operation performed.

## Incident and decision

The first-install helper in #62/#71 checked the Boca namespace and host
capacity but accepted whichever Docker daemon the `boca-deploy` account could
reach. If that account controls the shared rootful Docker socket, a compromised
deployment identity could obtain host root authority despite the script's
Boca-only commands. The actual droplet daemon and SSH permissions have **not**
been observed. This is a conditional threat, not a claim about the host.

All first-install phases and the read-only diagnostic now check real/effective
UID and GID and the dedicated `boca-deploy` account before reading private
socket or key metadata. They fail before other actions unless UID 10001 owns
the private runtime directory and rootless Unix socket, cannot write the
conventional rootful socket, and `docker info` on the **explicit** rootless
socket reports
`name=rootless`, cgroup v2 and the systemd driver. The user service's
`cgroup.controllers` must list `cpu`, `memory` and `pids`. Every Docker command
in the helper pins `DOCKER_HOST` to that socket and discards inherited
Docker context, client config and TLS variables, including `DOCKER_TLS`.
Absent or malformed evidence is NO-GO. The checks read metadata only; they do
not enumerate or change another workload.

## Limits and next review

This guard prevents the proposed helper from intentionally operating the
shared rootful daemon. It does not prove that an SSH identity has no *other*
privileged path (sudo, another socket, group or host policy); an independent
host identity review is still required. Nor does a successful `docker info`
prove that Compose enforces the limits after a container starts. A separate
isolated-host run must inspect actual cgroup limits and health.

**Original rootless secret incompatibility:** the former Compose file mounted
a host UID 10001, mode 0400 key and ran the controller as container UID 10001.
Rootless Docker maps that host UID to container UID 0, while container UID
10001 maps to a subordinate host UID. Compose file secrets do not remap owner
or mode. ADR 0034 proposes a dedicated key volume instead; do not relax mode
to 0444, pass the key through Actions or claim host readiness from a runner
smoke. CPU delegation and key access need a real isolated rootless check.

This ADR does not authorize a merge, image release or droplet operation. The
owner's standing delegation still requires exact-SHA CI and recorded agent
technical review, verified main/environment restrictions, immutable digest,
service, host identity, capacity and window gates. No additional human
approval is required once those objective gates are proven.

Issue #80 / [ADR 0034](0034-rootless-key-custody.md) uses a separate key
volume for the identified UID mismatch. Its runner smoke is not
evidence of the actual droplet's rootless storage or delegated limits.

Primary references: [Docker rootless](https://docs.docker.com/engine/security/rootless/),
[rootless cgroup limits](https://docs.docker.com/engine/security/rootless/tips/#limiting-resources),
[UID/GID mapping](https://docs.docker.com/engine/security/rootless/uid-gid-mapping/),
[Compose file secrets](https://docs.docker.com/reference/compose-file/services/#secrets).
