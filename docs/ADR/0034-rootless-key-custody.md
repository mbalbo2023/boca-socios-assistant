# ADR 0034: owner-only key in a separate rootless Docker volume

**Status:** Proposed for issue #80, 2026-10-29. No production host operation.

## RCA and decision

The original Compose file secret used a host UID 10001, mode 0400 source.
Rootless Docker maps that host UID to container UID 0, whereas the controller
runs as container UID 10001. Compose file secrets do not remap ownership and
mode for a file source. The original key may therefore be unreadable at the
first start; widening it to 0444 would expose it to other identities.

Create a second Boca-only named volume `boca-socios_boca_key`, separate from
`boca-socios_boca_data`. After image digest and source-revision validation,
the single manual workflow creates the empty, labeled key volume through the
dedicated rootless daemon. Because volume creation can reuse an existing name,
the helper rejects local-driver options (including bind-device options) and
requires the exact key mountpoint under that daemon's DockerRootDir with no
symlink redirect before any key initializer runs. A one-time container from the approved image uses
container UID 0 (mapped to the dedicated nonroot host user), no network,
read-only root, bounded resources and only `CAP_CHOWN`. It sees **only** the
key volume. It rejects a nonempty volume, creates a random 32-byte key with
exclusive, nonfollowing open, writes owner-only mode 0400, changes ownership
to container UID/GID 10001 and syncs it. A second networkless container runs
as UID 10001, mounts that volume read-only and proves that the key can be
decoded, without printing the key. Failure preserves the volume and blocks
first-install retry; no key is passed through Actions or created in the host
directory.

Compose mounts the key volume **read-only** at `/run/secrets`; the controller
remains UID 10001 with `BOCA_ENGINE_MODE=off`. The contract permits exactly
the data and key volumes, and no file-backed secret, bind mount or extra
service. Postflight and diagnostic verify exact volume mounts, image,
resources and key metadata as UID 10001 through a fixed Python command in
the controller. This probe does not read or print key bytes. The controller
loads the key at startup; a healthy response alone would not detect later
permission drift, hence the metadata probe. The old 0444 vault exception is
removed. The CLI inspect-to-run interval is not atomic against another writer
with access to the same rootless daemon; the dedicated identity and serialized
operation remain mandatory, and an isolated rootless trial must verify this
boundary before any host use.
After init, the helper rechecks volume identity before verification. A
failed second init must retain the original key; the disposable runner smoke
checks that behavior without exposing key bytes.

## Limits and gates

The disposable GitHub runner smoke uses its default Docker daemon. It proves
volume creation, 10001 read access and controller startup in that environment;
it does **not** prove the same UID map, cgroup delegation or resource limits
on the rootless droplet. A reviewed isolated rootless trial must verify actual
UID mapping, key access, CPU/memory/PID limits, storage ownership, restart and
retention before host installation. Recovery custody and real credential
enrollment remain deferred until a reliable product exists. The dedicated
SSH identity must not have sudo or another Docker socket. Verified main
protection, exact-SHA agent technical review, protected environment, immutable
digest/SHA/service coordinates and resource preflight remain objective gates
under the owner's standing delegation. No live browser,
login or reservation is enabled by this change.

References: [Docker rootless UID/GID mapping](https://docs.docker.com/engine/security/rootless/uid-gid-mapping/),
[Compose file secret limitations](https://docs.docker.com/reference/compose-file/services/#secrets),
[Docker volume no-copy and read-only mounts](https://docs.docker.com/engine/storage/volumes/),
[Rootless cgroup limits](https://docs.docker.com/engine/security/rootless/tips/#limiting-resources).
