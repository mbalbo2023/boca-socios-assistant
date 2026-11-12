# R247 Boca failure cleanup V2 — design

**Status:** CODE_ONLY proposal, NO_GO host. **Issue:** #417. **Date:** 2026-11-12 ART.

## Intent and constraints

After a failed Boca successor upgrade, capture durable, same-lease Docker and
disk/inode evidence without invoking the existing SUCCESS-only cleanup executor.
Any removal is limited to positively identified stopped/unused resources from
the failed Boca attempt. Preserve the restored old pair, historical R108
quarantine, SQLite/owner/key/SITE/Chrome IPC volumes, unrelated workloads,
unknown resources, original failure and all immutable upgrade journal files.
Do not wire a workflow, change the type-level upgrade interlock or operate a
live host in this PR. A successful cleanup of a failed upgrade is **not**
permission to accept its installation.

## Considered approaches

1. **Use SUCCESS-only cleanup after restore:** rejected; it protects the new
   pair and can delete residue under the wrong topology.
2. **Read-only receipt for every failure:** maximally conservative, but never
   removes positively identified disposable leftovers.
3. **Separate failure executor (selected):** authenticate the original
   successor journal and still-held lease; prove the restored pair or refuse
   mutation; calculate a narrow deletion allowlist from an exact Boca-only
   inventory; invoke the existing generic cleanup engine only with a
   revalidating delete callback. Persist a distinct O_EXCL/fsync V2 FAILURE
   receipt. This reuses the generic engine's bounded probes without reusing
   its success-only bridge.

## Contract

- `execute_durable_failure_cleanup(plan, lease, *, restored, receipt_dir,
  historical_retained, retained_io=None)` creates a **new** failure intent and
  terminal receipt. A restored failure cannot mutate anything unless the
  caller supplies the separately reviewed R188 READ_ONLY resource reader.
- Journal evidence and intent are immutable, exact-attempt, source/release
  matched and read with no-follow under the protected Boca directory. A
  pre-existing failure intent/receipt rejects replay; a commit marker rules
  out restored-state cleanup.
- An unverified/not-restored state is inventory-only with NO_GO/INDETERMINATE;
  it never deletes Docker resources. For restored state, verify old binding,
  exact container/image IDs, rootless Boca graph, exact old role mounts,
  R188 SITE/IPC inode fingerprints and egress ID/creator against the original
  authenticated journal, and R108 before/after and before every deletion.
- The allowed removable set is initially bounded to stopped successor-attempt
  containers with exact role/source/image, the now-unreferenced candidate
  images, and attempt-owned unused disposable Boca networks/volumes. An
  unexpected item, drift, active new container, or foreign ownership cannot
  be deleted. Recheck the **frozen initial Volume/Network metadata** and
  current attempt-owner labels immediately before deletion; same-name or
  same-ID replacement by another attempt fails closed.
- The canonical counted V2 receipt records `outcome=FAILURE`, exact removals,
  counts and disk/inodes. Even if selective cleanup returns `ACCEPT`, the
  returned installation state is **always NO_GO** and `apply_authorized=False`.

## Non-goals and remaining gates

No host dispatch, CLI/workflow wiring, initial compensation, database migration,
live navigation, real tickets, or postflight acceptance. The parent R246
fail-closed code and this executor must be integrated and reviewed separately
before any future GO; physical same-lease evidence is still mandatory.
