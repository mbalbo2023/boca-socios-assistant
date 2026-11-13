# ADR 0261 — R252 exact SUCCESS cleanup bridge, never owner acceptance

**Date:** 13-NOV-2026 UTC. **Issue:** #417. **State:** CODE_ONLY / NO_GO.

## RCA

`PhysicalSuccessorIntegrations.bind_backend()` required
`backend.integrations is self`, but the reviewed SUCCESS finalizer
`PostflightGatedSuccessorBackend.finalize()` independently required
`backend.integrations` to be exactly `OneShotFinalCleanupBridge`.
Consequently the future official V2 SUCCESS cleanup adapter could not be
assembled with the dynamic 2/3/4-container physical graph: neither of the
two type-identity requirements could be satisfied simultaneously.

The technical-only health/SQLite/SITE_URL/CREATED-worker receipt introduced
under ADR0257 cannot replace the owner's passkey/Chrome and authenticated
monitor acceptance. Any such substitution would incorrectly make an ordinary
`/healthz` HTTP 200 count as a real login and present a stopped monitor as
proof of live tokens.

## Decision

`PhysicalSuccessorIntegrations.bind_backend()` now accepts either its original
direct backend or **exactly one** `OneShotFinalCleanupBridge` whose private
delegate is the *same* physical integrations object. It rejects a wrapper
whose delegate is any different adapter, repeated binding, or an unrecognized
backend. No class-level effect guard changes.

`prepare_success_cleanup(preflight, durable)` builds the physical adapter,
official `ProductionFinalCleanupCoordinatesReader` and one-shot SUCCESS V2
final cleanup delegate under the exact existing `SuccessorPairJournal`. It
rejects injected observation, pair, binding, and control-inode readers; source
SHA changes; and mismatched release or historical R188 resource pins. It
does not read the host or acquire a lease while assembling. It uses the
same-base-only source bytes with digest equality; the separate ADR0258
physical on-disk Compose comparison remains a prerequisite before any stage.

The returned backend has `gate=None` and
`requires_persistent_receipt=False`, so `run_pair_upgrade` still refuses
before the protected lease and Docker. A second typed check,
`verify_technical_completion`, can consume only the existing
`OneShotFinalCleanupBridge.completed_final_cleanup(plan, lease)` result,
verify its official canonical SUCCESS V2 receipt and a distinct canonical
schema-2 technical postflight record bound to the same plan. It returns
`CompletedSuccessEvidence` carrying **both** exact digests but with
`apply_authorized=False`, `terminal_accept_authorized=False`, and
`beta_deploy=NO_GO` as immutable properties.
The protected Boca lease is explicitly revalidated before consuming the
official completion and again after the technical verifier; a lease lost
between those observations is a fixed-category NO_GO, never an attestation.

This evidence is code-level correlation, **not** a claim of a durable
postflight write, physical owner login or provider monitor. A future bridge
must produce the technical bytes with reviewed physical readers, write them
O_EXCL/fsync/readback under the same live lease, and complete independent
owner passkey/monitor acceptance before any accepted terminal receipt.
The R186 original mutation and historical NO_GO must never be repeated or
rewritten.

## Verification and boundary

TDD initially failed import because the bridge module did not exist. Focal
tests now check exact object identity, official cleanup-reader binding,
wrong provenance/reader/mutated source refusal, no lease or Docker during
assembly, backend type-level rejection and canonical SUCCESS/technical proof
validation with explicit NO_GO. Synthetic fixtures do not establish droplet
state; a dedicated regression makes the second lease check fail and verifies
that no completion evidence is returned.
No real droplet workflow, image, port, Docker container, external site,
credential or database is modified by this CODE_ONLY change. The current installation
remains the historical pair until a fresh physical Action proves otherwise.
