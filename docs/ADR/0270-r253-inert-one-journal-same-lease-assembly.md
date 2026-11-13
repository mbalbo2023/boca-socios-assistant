# ADR 0270 — R253 inert one-journal successor actor assembly

**Date:** 13-NOV-2026 UTC. **Issue:** #417. **State:** CODE_ONLY / DEPLOY NO_GO.

## Context and RCA

The R252 components have distinct, reviewed responsibilities but remained
independent constructors: `CurrentBaseOnlyStageCustody.intent` checks the
on-disk old root Compose; `SuccessorPairJournal` owns repeatable same-lease
intent/commit/terminal witnesses; `BoundSuccessCleanup` composes the official
one-shot final SUCCESS V2 cleanup; `OneShotFailureTerminalSink` enforces the
FAILURE V2 outcome with retained resources. Independently making these objects
did not prove that all callbacks would share the **same journal instance**
or the same immutable plan coordinates. Accidentally wiring two journals
could strand an O_EXCL intent in one instance while a second sink attempts
terminal cleanup against another.

This was a code-level composition gap, **not** a report of a live droplet
failure. A synthetic fixture is not a physical witness or an owner sign-in.

## Decision

Introduce `host_boca_successor_assembly_v3.prepare_inert_same_lease()` with
exactly one prevalidated `BoundSuccessorPreflight`. Its return is a frozen,
slotted `InertSameLeaseAssembly` holding the exact:

1. `PairCoordinates` object from the bound inputs;
2. new `SuccessorPairJournal` with the official production pair capture;
3. `CurrentBaseOnlyStageCustody` using that preflight and journal;
4. `BoundSuccessCleanup` using that same plan/journal, the official physical
   integrations, `OneShotFinalCleanupBridge` and typed gated backend;
5. `OneShotFailureTerminalSink` using that same plan/journal and production
   retained-resource I/O implementation.

The post-init constructor validates **object identity**, not merely values,
across all actors. It rejects foreign journals, plans or altered reader and
lease-verifier defaults, including the captured current-pair observation,
official final-cleanup coordinates reader, default control-inode observer,
and on-demand installed-binding reader. Inputs are taken from the existing
runner-bound evidence verifier; this module does **not** independently
authenticate GitHub artifacts and cannot turn user-supplied bytes into
authorization.

The graph exposes `apply_authorized=False` and
`terminal_accept_authorized=False` with no `execute` method. The backend has
`successor_postflight_gate=None`; the engine's unchanged class-level
`requires_persistent_receipt=False` interlock rejects `run_pair_upgrade()`
**before acquiring the protected host lease**. Assembly performs no Docker,
host filesystem, external-site or lease operations. It creates no Action,
launch path, CLI route, PR merge, or deployment permission.

## Deferred blockers and explicit no-go

Physical deployment remains **NO_GO**. An authorized future integration must
separately prove a durable same-lease technical postflight receipt, enough
verified Boca-owned volume space, protected Action/bootstrap path, and owner
passkey plus authenticated running-monitor/worker/SQLite acceptance. Existing
R186 first-migration logic remains excluded. No TLS bypass, queue bypass,
real reservation, Porota mutation or unrelated-container cleanup is permitted.

## TDD and verification

The initial focused test run failed collection because the new module was
absent (RED); the first seven TDD cases passed after implementing it. Three
additional altered-reader/lease-verifier tests first failed as expected
(RED), revealing a missing rebind hardening check; they now pass (GREEN)
after validating official production defaults in the immutable graph.
Tests cover exact identity of all four collaborators; refusal of foreign
stage/SUCCESS/FAILURE journal and plan; hostile non-preflight input; default
reader and verifier tampering; zero lease/Docker effects during assembly;
and the engine's pre-lease class-level refusal. Local green checks cannot
replace a genuine GitHub Actions or droplet postflight witness.
