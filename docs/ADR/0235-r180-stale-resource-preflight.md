# ADR 0235 — R180 Boca rootless stale-resource preflight (2026-11-11)

## Observed evidence and problem

The simulation-only Boca R179 release at source commit
`db33f9219fba0d7f2838622c99ac69545b0f487f` was published as the
two-image, scanned release in Actions run `43081037636`. The separate
read-only SQLite inode witness run `43080787876` returned `VERIFIED_STABLE`.
The read-only current census run `43082209947` returned one controller, one
browser worker, zero other Boca containers, two stable reads and zero writes.
These observations **do not prove** absence of an unused named Docker network
or volume.

Independent code review of `RootlessPairUpgradeBackend.stage` found that it
prepares staging files and pulls new images before trying to create the
fixed-name egress bridge `boca-socios_boca_browser_egress`, then the fixed-name
SITE_URL volume `boca-socios_boca_site_config`. A stale bridge could make the
stage fail after preparation/pulls. A stale site-config volume could cause a
failure after creation of the new bridge; its historical `attempt` labels
could then block exact-attempt compensation. No such residual resource has
been physically demonstrated as of this decision.

## Decision

1. Keep the existing unique Boca rootless daemon and UID/GID 10001 lease.
   Do not change Docker permissions or any host-wide settings.
2. Extend the existing **read-only** `cutover-a-census` receipt to attest the
   absence of the **two exact Boca names**, with stable double reads. An
   existing resource is `NO_GO` pending separate identity and reference RCA;
   the observer must not mutate or delete it.
3. Inside the physical pair upgrade transaction, check both exact names
   before any stage files, image pulls, or network/volume creation, and check
   again at the beginning of `stage` while holding the same dedicated lease.
   A collision aborts before those effects. Keep all later label/attempt/peer
   validation; the early check is not a substitute for it.
4. A failed or indeterminate APPLY is never blindly retried. Preserve the
   durable intent/commit/terminal journal and any uncertain artifacts;
   perform a new Boca-only forensic read, then a separately reviewed exact
   recovery if required. Never run unscoped Docker cleanup or remove data,
   key, owner or historical IPC volumes.
5. No live reservations, ticket actions, queue interaction, or Telegram
   activation are authorized by this change. The worker's Internet access
   still requires a positive probe from its actual running container after
   the paired physical cutover and owner-initiated sandbox START.

## Acceptance requirements and limits

- Unit regression: stale egress, stale SITE_URL volume and foreign/extra
  occupancy must reject **before** stage/pull/create. Existing clean-state
  path remains accepted.
- READ_ONLY census: the two new absence observations must be stable and
  constrained to the attested Boca rootless inventory. An absent resource may
  be certified without inspecting any foreign resource; a present resource
  must never be silently adopted or removed.
- All relevant Python, workflow, package-size, architecture and isolation
  gates must pass on the *exact new source SHA* before the source is merged.
- Any R180 image release must contain both immutable controller and browser
  image digests for that *same* new SHA. The R179 digests are historical and
  cannot be presented as an R180 physical upgrade.
- A successful Actions workflow is insufficient to call BETA deployed: only
  a host terminal `ACCEPTED`/equivalent pair receipt, fresh pair and binding
  observations, stable storage, private panel, on-demand worker health and
  worker egress witness can establish the respective physical claims.

## Status

R180 proposal under implementation; this ADR records a **code-only decision**.
Until physical evidence arrives, the two named resources, pair upgrade, panel
and worker outbound Internet remain explicitly unverified. Porota and all
other Docker projects remain out of scope.
