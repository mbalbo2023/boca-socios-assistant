# ADR 0027: fail closed on the resolved Boca Compose model

**Status:** Reconciliation candidate for issue #58, 2026-10-30. Static
simulation-only contract; no host access or installation.

The first installation candidate is a simulation-only controller. Require an
explicit immutable `ghcr.io/mbalbo2023/boca-socios-assistant@sha256:<digest>`
image in Compose and remove its local `build` path. Run as UID/GID 10001 with
one Boca volume, bridge network and key mount; retain read-only root, no host
port, no privileges and the existing 0.5 CPU / 256 MiB / 64 PID ceiling.
The `.env.example` file remains a development-only illustration with a local
tag; it is not a deployment input. The manual workflow must supply staging
and the reviewed GHCR digest explicitly, which this validator checks.

Validate the **resolved** `docker compose config --format json` model before
any eventual host operation. Fail on additional services, networks, volumes,
secrets, build, ports, host mounts or drift in the isolation contract. A
repository PR CI job resolves with a synthetic image digest and synthetic
absolute secret source; it neither connects to Docker on a production host
nor provides a real key. The CLI reports only the field that failed.

The Compose file-secret representation here is a historical staging contract.
The resolved model's exact secret path or Docker's 0444 mount compatibility
does **not** establish host-side source ownership, mode, runtime readability
or key custody. In particular, this candidate is **NO-GO for rootless
installation** until #81 atomically reconciles Compose, validator, tests and
key-volume custody with the first-install workflow. The preflight cannot
establish spare host resources, the actual image manifest, health on the
target kernel, egress isolation or lack of interference with existing
workloads. Those require technically reviewed, read-only checks in the sole
Boca manual Actions workflow, followed by exact SHA/digest, SSH pin, protected
environment, rootless and capacity gates under ADR 0038. An external source
failure is a timestamped advisory for a safe simulation-only installation;
it never waives these gates. A green PR is not permission to deploy. Do not
use a local build or a floating tag as an emergency fallback.

References: [Compose resolved model](https://docs.docker.com/reference/cli/docker/compose/convert/),
[production Compose update](https://docs.docker.com/compose/how-tos/production/),
[deployment environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).
