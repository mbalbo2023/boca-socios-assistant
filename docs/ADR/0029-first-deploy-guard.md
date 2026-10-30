# ADR 0029: one manual first-deploy path for the Boca controller

**Status:** Reconciliation candidate for issue #62, 2026-10-29. No host operation performed.

The first host installation runs only from a manual GitHub Actions job on
the exact current `main` SHA after agent technical review and exact-SHA CI. It
requires a protected `boca-first-deploy` environment with an explicit
readiness variable and its own SSH identity/known-host key. The owner and
agent must record the dispatch SHA, immutable GHCR digest, release run,
service `controller` and fixed 0.5 CPU / 256 MiB / 64 PID budget against
the proven gates before dispatch. The owner's standing direction permits
the gated operation without another human approval. No push, PR or
documentation change deploys.

Before mutation, validate Compose's resolved model in the runner and check
the host read-only: amd64, dedicated `boca-deploy` UID 10001, Python 3.10+,
Docker/Compose, at least 4 GiB available disk, 768 MiB available memory,
0.5 approximate CPU headroom and 50,000 free inodes, a Boca-owned path and
**no existing Boca container, volume or network**. The Boca directory must
already exist at `/srv/boca-socios`, be owned by UID 10001 with mode 0700,
and have no Compose file or key. Preparing this account, directory,
Docker access and pinned SSH host identity must be proven separately;
this PR never provisions them. Conservative thresholds can reject a constrained host;
that is NO-GO, not a reason to free resources from another workload. The
preflight does not read another workload's data or name.

After that gate, stage only the reviewed Compose file in the Boca directory,
verify its SHA-256, pull only the exact digest and compare its OCI source
revision label to the dispatch SHA. Create a new 32-byte random master key
on the host only when no Boca data exists; this candidate writes it as
base64 with mode 0400 and owner UID 10001. That host UID/mode alone does
not prove readability from a rootless container with an ID mapping. The
key-volume custody correction in #81 is mandatory before any install.
Never log, transfer or rotate the key.
Start only `controller` using Compose `--no-build --no-deps --wait`; on a
startup failure, stop only that service and preserve the key, volume and
image for diagnosis. No automatic retry, broad rollback, prune, restart of
Docker or touch of another project. An unexpected condition is NO-GO.

This PR validates the pure preflight and command boundary offline and starts
the exact Compose service with a synthetic owner-only key on a disposable
GitHub-hosted runner. This tests secret mount compatibility, SQLite migration
and controller health without a production host or third-party traffic; only
synthetic Boca resources on that runner are removed after the test. It cannot
establish the GitHub environment settings, SSH host identity, GHCR access,
rootless Docker isolation, actual droplet capacity or production health.
The rootless boundary (#79), key custody (#81), strict postflight (#71),
release digest binding (#89), current-main checks (#91), and Boca-only
cleanup (#97) are separate gates before a first install. External source
health is reported by Actions with time and reason; an outage does not
block a safe dormant-controller installation. The controller remains
simulation-only and has no real Boca reservation capability.

References: [GitHub deployment environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments),
[OpenSSH host key verification](https://man.openbsd.org/ssh_config.5),
[Compose up wait/no-build](https://docs.docker.com/reference/cli/docker/compose/up/).
