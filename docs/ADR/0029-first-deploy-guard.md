# ADR 0029: one manual first-deploy path for the Boca controller

**Status:** Proposed for issue #62, 2026-10-28. No host operation performed.

The first host installation, if authorized after independent reviews, runs
only from a manual GitHub Actions job on the exact current `main` SHA. It
requires a protected `boca-first-deploy` environment with an explicit
readiness variable and its own SSH identity/known-host key. The owner and
environment reviewer must compare the dispatch SHA, immutable GHCR digest,
release run, service `controller` and fixed 0.5 CPU / 256 MiB / 64 PID budget
against a separate authorization record. Workflow inputs alone cannot prove
that authorization exists. No push, PR or documentation change deploys.

Before mutation, validate Compose's resolved model in the runner and check
the host read-only: amd64, nonroot dedicated deploy identity, Docker/Compose,
at least 4 GiB available disk, 768 MiB available memory and 50,000 free
inodes, a Boca-owned path and **no existing Boca container, volume or
network**. These conservative thresholds can reject a constrained host;
that is NO-GO, not a reason to free resources from another workload. The
preflight does not read another workload's data or name.

After that gate, stage only the reviewed Compose file in the Boca directory,
verify its SHA-256, pull only the exact digest and compare its OCI source
revision label to the dispatch SHA. Create a new 32-byte random master key
on the host only when no Boca data exists; never log, transfer or rotate it.
Start only `controller` using Compose `--no-build --no-deps --wait`; on a
startup failure, stop only that service and preserve the key, volume and
image for diagnosis. No automatic retry, broad rollback, prune, restart of
Docker or touch of another project. An unexpected condition is NO-GO.

This branch can test the pure preflight and command boundary offline. It
cannot establish GitHub environment reviewer settings, SSH host identity,
GHCR access, actual host capacity, key mount semantics or production health.
Those must be checked under the later specific authorization before running
the workflow. The controller remains simulation-only and has no real Boca
reservation capability.

References: [GitHub deployment environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments),
[OpenSSH host key verification](https://man.openbsd.org/ssh_config.5),
[Compose up wait/no-build](https://docs.docker.com/reference/cli/docker/compose/up/).
