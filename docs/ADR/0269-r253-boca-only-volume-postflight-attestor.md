# ADR 0269 — R253 Boca-only volume and mount custody for postflight

**Date:** 13-NOV-2026 UTC. **Issue:** #417. **State:** CODE_ONLY / PHYSICAL NO_GO.

## RCA

`build_protected_postflight_sources(..., volume_attestor=None)` deliberately
leaves its structural storage reader unbound. A generic successful-looking
callback or recycled preflight inventory must not convert that intentionally
missing production evidence into a postflight pass. The R177 live pair witness
already attests exact CIDs, installed binding and service mounts, but does not
individually prove the *local Docker driver, options, exact storage mountpoint
and no-symlink file-system custody* of the three persistent data/key/owner
volumes. The existing `host_first_deploy._validate_*_volume` has those checks,
but that mutation-capable first-install module is not a suitable postflight
producer or dependency for the protected pair-upgrade transport.

## Decision

The new `ProductionBocaVolumeAttestor(expected, lease)` is an **inert on
construction**, read-only callable for the existing R247 `volume_attestor=`
slot. At call time it:

1. Reattests the **same held Boca lease** and R177's exact live pair,
   installed systemd binding and all pair mounts; checks rootless UID/GID
   `10001:10001`.
2. Uses the reviewed dedicated rootless `cleanup.capture_inventory()`. It
   refuses all foreign containers, networks and volumes before inspecting any
   volume; it also proves DockerRootDir ancestry and disk dev/inode without
   following symlinks.
3. Requires the authentic DockerRootDir to match the R245 postflight root;
   accepts **only** `boca-socios_boca_data`, `_key` and `_owner` from the
   authenticated inventory. For each, narrow exact-name Docker volume inspect
   checks `Name`, `Driver=local`, `Scope=local`, empty `Options`, Docker Compose
   project/volume labels and mountpoint rooted at
   `<DockerRootDir>/volumes/<exact-name>/_data`. This reproduces the already
   reviewed first-install identity predicate without running installer code.
4. Opens every mountpoint ancestor using descriptor-relative `O_NOFOLLOW`
   and `O_DIRECTORY`, compares the Docker root's dev/inode with authenticated
   inventory, and refuses symlinks, directory changes and unsafe group/world
   write permissions. It opens **directories only**, never DB, master key,
   owner session, credential or token files.
5. Reattests the live pair and same lease again. Any absent, changed or
   unparseable proof yields one constant redacted **NO_GO**.

The existing structural storage reader independently invokes this attestor
both **before and after** its fixed read-only inode metadata capture. The
new attestor has no host entry point, no Docker mutation, no HTTP request,
no worker activation and no permission to inspect Porota or another daemon.
It is not an owner-login/monitor callback.

## Physical P1 — rootless subuid ownership must not be waived

`host_boca_upgrade_postflight_runtime.ProductionSiteUrlWitness` explicitly
warns that rootless Docker volume files may be owned by **remapped subordinate
UIDs**. R247's `capture_structural_storage_fingerprints()` currently requires
that each file's host inode UID/GID match the calling effective UID/GID
`10001:10001`. Even a successful R253 volume mount attestation would **not**
prove that the R247 structural file reader succeeds under actual host UID
mapping. The exact files' UID/GID and the remap must be evidenced on the
droplet via a reviewed Boca-only same-lease, **metadata-only** witness. If
R247 rejects valid mapped custody, a separate reviewed fix-forward reader
must bind to the authenticated UID mapping without weakening no-follow,
file-mode, link-count or inode continuity checks. No synthetic fingerprint
may be admitted as a substitute.

## Verification and integration boundary

TDD started RED with an absent module. Synthetic tests prove exact
lease/pair/inventory ordering, strict local volume identity and labels,
foreign inventory refusal **before inspecting any volume**, no-follow
symlink rejection, and rootless UID refusal. They do not prove the droplet.

The new module and its selected tests are CODE_ONLY. A future separately
reviewed protected-transport integration must include the module in the
SHA-pinned pair-upgrade bundle and supply the production callable under
the active protected lease. Do not merge this code in place of that wiring
or physical testing. **DEPLOY NO_GO** remains until one authentic GitHub
Actions invocation finishes preflight, installation, exact SUCCESS cleanup
V2, technical/physical postflight, real owner passkey/SITE_URL/worker/
monitor/SQLite acceptance, and redacted receipts on the actual Boca host.
No real reservations, queue bypass or TLS relaxation are authorized.
