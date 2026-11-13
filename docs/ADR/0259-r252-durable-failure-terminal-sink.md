# ADR 0259 — R252 same-lease FAILURE V2 terminal sink

**Date:** 13-NOV-2026 UTC. **Issue:** #417, A45-R252.
**Status:** CODE_ONLY, not connected to APPLY; DEPLOY **NO_GO**.

## Root cause and boundaries

The existing `run_pair_upgrade` engine holds exactly one protected Boca lease,
but its original `terminal_sink` only writes a journal receipt. That cannot
certify physical FAILURE V2 cleanup. A new callback must compose the reviewed
durable cleanup executor without inventing a second transaction, retrying a
possibly mutating call, or accepting a textual cleanup result as installation.

Independent review exposed two additional interlocks:

1. An ordinary pre-commit failure can successfully restore the old pair, so
   the engine legitimately emits `RECOVERED` with `old_restored=True` and
   `cleanup=ACCEPT`. Rejecting all non-`NO_GO` receipts would strand that
   recoverable outcome before durable FAILURE reconciliation.
2. Verifying journal identity only in the later `journal.terminal` is too
   late: a different/unprimed journal could allow cleanup side effects before
   refusing the terminal. Verify the *same* live journal and its on-disk
   durable intent/evidence first.

## Decision

`OneShotFailureTerminalSink` binds an exact `PairCoordinates` and exact
`SuccessorPairJournal` instance. It validates the original immutable engine
receipt and lease, then calls `SuccessorPairJournal.attest_active_intent`,
which requires the original **object-identity** lease, validates the encoded
plan coordinates and reopens the dedicated Boca journal `intent` and
`evidence` through bounded O_NOFOLLOW checksum-checked reads. It revalidates
the lease after reading. There is no filesystem or Docker effect at
construction time.

For **precommit** NO_GO or RECOVERED, it calls the existing
`execute_durable_failure_cleanup` only once: attempt and Boca stage root are
fixed, `old_restored` comes exclusively from the engine, and retained-resource
production I/O is available only when the old pair was actually restored.
Its typed receipt, exact bytes and hashes, `outcome=FAILURE`, `state=NO_GO`
and cleanup status are checked with the official V2 verifier before emitting
the unchanged terminal receipt. `RECOVERED` means *old pair restored*, never
successfully installed new release. The FAIL/NO_GO classification of that
cleanup can be retained without changing the engine's original state.

For **postcommit**, FAILURE cleanup or rollback is forbidden; only the
original non-`ACCEPTED` terminal is stored. The `ACCEPTED` state is expressly
**rejected before journaling** until a typed SUCCESS V2 receipt and independent
physical postflight can be composed and validated before the production gate.
The callback marks itself one-way before any possible effect. An interrupted
or ambiguous attempt remains consumed and cannot be retried or overwritten.

## Verification and remaining gates

TDD demonstrated RED failures for missing active journal, RECOVERED handling
and wrong receipt before implementation. Tests cover exact lease/durable
readback, corrupted intent, alternate journal, no replay, malformed proof,
postcommit non-rollback and untouched original receipt. No real Docker,
browser, external site, Porota, TLS bypass or reservation is exercised.

Further gates before a physical deploy: one exact object graph with the
SUCCESS cleanup/postflight bridge; protected ZIP transitive import closure
and audited byte caps; fresh dual release bound to `main`; verified Actions
preflight with installed pair/custody; protected same-lease APPLY; complete
8443/SQLite/SITE_URL/worker/owner passkey and monitor postflight. Preserve
DEPLOY NO_GO until genuine host evidence is available.
