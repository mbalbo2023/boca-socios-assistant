# ADR 0039: bounded cleanup after a failed first Boca installation

**Status:** Proposed for issue #93, 2026-10-29. No host cleanup dispatched.

## Incident class and decision

The proposed first-install path stages a Compose file and pulls an immutable
image before it initializes a separate key volume and starts the simulation
controller. A failure can leave a staged file or downloaded image. The next
first-install correctly refuses an existing Boca namespace, but there is no
bounded storage receipt or route to remove provably disposable remnants.
There is no evidence that a Boca deploy has actually run on the droplet.

Provide a separate standard-library helper and a guarded failure step in the
**same** owner-dispatched Boca Actions workflow. It demands exact GHCR digest,
source SHA and Compose hash, real/effective UID 10001 `boca-deploy`, matching
real/effective GID (no setgid escalation), a private owned runtime directory,
the dedicated rootless socket, no writable rootful socket, and rootless Docker
v2/systemd metadata. Every Docker call
pins the private Unix socket and ignores inherited remote contexts. Its
queries are filtered to Boca resources or the exact digest.

The cleanup candidate refuses **all deletion** if any Boca container exists.
It never deletes a Boca volume or network, including `boca-socios_boca_key`
or `boca-socios_boca_data`. It also refuses an unexpected directory entry,
symlink, changed Compose hash, image with another digest/tag/revision, or
any container referencing the exact image. It removes only an unreferenced
image by its exact digest without force or broad prune, including after the
key volume has been created if **no container** uses that image. It removes
the exact regular staged Compose file after rechecking it **only when no Boca
container, volume or network exists**. With retained key/data or network,
the receipt reports `PARTIAL` or `RETAINED` and never claims a clean install.
A failed image removal leaves the file for diagnosis. Repeated
execution on an already clean Boca namespace is idempotent. It records
free bytes/inodes before and after on both the Boca staging filesystem and
the rootless Docker data filesystem. `same_fs` says whether they share a
device; those figures are correlated and must not be added when they do.
The image size is a logical estimate, not a guarantee of physical space
reclaimed because layers may be shared. A free-space delta is an observation,
not proof that the image deletion caused it. It never prints a Docker
environment, other project name, secret, database row or registry token.

## Explicit limits

The workflow marks the attempt **only after** input, release, current-main,
Compose, pinned SSH and read-only host preflight gates have passed. Its
failure hook runs only for `first-install`, only when that attempt marker
exists, and only after a preceding step has failed. It passes the same exact
digest/SHA/Compose hash and streams this helper over the same pinned SSH
configuration. Unsanitized SSH output is discarded; a single bounded
`BOCA_CLEANUP` receipt or a generic `NO_GO` is added to the step summary.
The cleanup step exits successfully to preserve the **original** workflow
failure as its conclusion. A failure before the attempt marker, including
SSH setup or preflight, never invokes cleanup. An Actions timeout or runner
loss may prevent the hook from running at all; it cannot be a recovery
guarantee.

Once an image or staged-file deletion is attempted, any subsequent error
(including a changed file or unavailable post-cleanup capacity reading)
produces `BOCA_CLEANUP_INDETERMINADO` locally. The Actions summary uses
`NO_GO INDETERMINADO` for every failed or unverified cleanup execution: a
partial deletion may already have occurred, so it never claims that all
artifacts were retained. The original install failure stays failed. A new
Boca-only inventory is required before any retry; no automatic retry runs.

This deliberately cannot clean up a key/data volume, network or container
after creation: those states may contain valuable encrypted data and cannot
be proven disposable from the current host metadata. They need a separate
recovery design and an Actions diagnostic, not deletion by this helper. A partially
copied Compose file with a different hash is also preserved. Space measured
on `/srv/boca-socios` may differ from rootless Docker data. The helper asks
the pinned daemon for `DockerRootDir` and accepts only a real Boca-owned path
under the private UID10001 home with a proven classic storage driver. As in
the preflight contract in ADR 0037, containerd/unknown backends are NO-GO:
image layers could be on another filesystem. A changed data root or device
between measurements makes the outcome INDETERMINADO if deletion began.
No `docker system/image/volume prune`, `compose down`, daemon restart,
automatic retry, volume removal or host-wide cleanup is permitted.

No SSH, host or Docker operation was performed while writing or testing this
candidate. Merging the workflow does not dispatch it to a host.
Actions uses the existing Boca-only serialization lock and rejects a manual
run attempt greater than one. The workflow treats uncertain state or an
unverified disk measurement as NO-GO. If a mutation began, the result is
INDETERMINADO until a fresh Boca-only inventory proves what remains.
