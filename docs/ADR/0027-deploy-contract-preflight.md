# ADR 0027: fail closed on the resolved Boca Compose model

**Status:** Proposed contract for issue #58, 2026-10-28. No host access.

The first installation candidate is a simulation-only controller. Require an
explicit immutable `ghcr.io/mbalbo2023/boca-socios-assistant@sha256:<digest>`
image in Compose and remove its local `build` path. Run as UID/GID 10001 with
one Boca volume, bridge network and key mount; retain read-only root, no host
port, no privileges and the existing 0.5 CPU / 256 MiB / 64 PID ceiling.

Validate the **resolved** `docker compose config --format json` model before
any eventual host operation. Fail on additional services, networks, volumes,
secrets, build, ports, host mounts or drift in the isolation contract. A
repository PR CI job resolves with a synthetic image digest and synthetic
absolute secret source; it neither connects to Docker on a production host
nor provides a real key. The CLI reports only the field that failed.

The preflight cannot establish spare host resources, key-file custody, the
actual image manifest, health on the target kernel or lack of interference
with existing workloads. Those require separately reviewed, read-only host
checks in the future **single Boca-only manual Actions deploy workflow** and
explicit authorization of SHA, digest, service and resource window. A green
PR is not permission to deploy. Do not use a local build or a floating tag as
an emergency fallback.

References: [Compose resolved model](https://docs.docker.com/reference/cli/docker/compose/convert/),
[production Compose update](https://docs.docker.com/compose/how-tos/production/),
[deployment environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).
