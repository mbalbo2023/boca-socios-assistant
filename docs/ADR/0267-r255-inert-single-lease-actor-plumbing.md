# ADR 0267 — R255 inert same-lease actor plumbing

**Date:** 2026-11-13 UTC. **Issue:** #417. **Base:** exact remote main
`786b06d65c54e2b345730b7cd0e909760db86861`. **Status:** CODE_ONLY,
physical APPLY/BETA NO_GO.

## Architecture and decision

The R251 host CLI already authenticates the protected runner's exact
preflight proofs and three stage source blobs, then deliberately exits 3.
R252 adds strict same-base Compose custody, SUCCESS/FAILURE bridge types,
technical-only health and postflight source closure. These components do not
form an executable same-lease physical transaction and none grants authority.

First, retain legacy `run_pair_upgrade(..., backend=...)` and add the exclusive
alternative `backend_factory(plan, held_lease)`. The engine acquires its sole
Boca-only lease, writes the existing durable `terminal_preflight` intent
**before** invoking arbitrary Python factory code, then validates that the
returned concrete backend type has `requires_persistent_receipt is True`.
Factory exceptions/interruption or a disabled result never invoke backend
methods, restoration or finalization. They produce one terminal
`NO_GO/INDETERMINATE` receipt under that same lease. Missing or ambiguous
backend modes reject before lease acquisition. Post-marker compensation and
legacy ordering are unchanged.

The CLI is deliberately unchanged. No new inert-only assembly adapter is
added: a future PR must actually connect custody, physical cleanup and
postflight with a coherent terminal contract before removing the current
`SuccessorPreflightIneligible` guard. Merely constructing a backend with
`gate=None` would add scaffolding but would not resolve that contradiction.

## Alternatives and limits

- A pre-lease factory could read or mutate the old Compose before the durable
  intent. Rejected. A factory callback cannot be proven side-effect-free.
- Enabling successor APPLY merely because technical `/healthz` returns 200
  would confuse schema-2 `TECHNICAL_PROOF_ONLY` with physical Chrome/passkey
  and authenticated monitor acceptance. Rejected.
- Reusing historical R186's first-upgrade path or changing its uncertain
  terminal receipt is prohibited. This work never touches that actor.

## TDD and acceptance

1. RED/GREEN exact engine order `intent -> factory -> attest`, same lease
   object, one factory call, unchanged accepted legacy fixture.
2. RED/GREEN factory failure, `KeyboardInterrupt`, disabled backend class and
   instance flag spoof: canonical terminal NO_GO, no compensating fiction.
3. RED/GREEN missing/duplicate/noncallable backend mode rejects before lease;
   durability failure stops the factory.
4. Existing genuine-typed CLI preflight tests continue to produce NO_GO/3;
   no lease, Docker, historical R186 actor or journal is invoked.
5. Full pytest, Ruff, mypy, repository policy and exact protected bundle
   checks. No `workflow_dispatch`, deploy, PR, push, host or foreign effect.

## Future GO dependencies (not implemented)

The actor still requires one reviewed binding of current-base custody
`intent`, the same SUCCESS/FAILURE journal/physical backend, stored
`storage_before`/SITE_URL/image evidence, exact postflight V2 O_EXCL/fsync,
terminal receipt semantics, no R186 replay and independent owner acceptance.
Until that review, both type-level and CLI APPLY interlocks stay false/NO_GO.
