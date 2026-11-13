# R252 — compose FAILURE V2 with the existing terminal sink

**Issue:** #417 A45-R252. **Status:** CODE_ONLY, apply interlock remains False.

`run_pair_upgrade` already retains the verified `restored` boolean in the
immutable terminal `PairUpgradeReceipt` and invokes the provided terminal
sink **inside** its only Boca lease, after `backend.finalize` and before
returning. Keep the global engine signature and journal unchanged. Do not
inject a second cleanup dispatcher or infer restoration from Docker names.

## Contract

An exact-type, one-shot `OneShotFailureTerminalSink` owns the **same**
`SuccessorPairJournal` that recorded intent/commit. It validates the receipt
and lease, then rereads the *same journal's* on-disk intent and evidence by
bounded hashes before any cleanup effect. On a precommit `state=NO_GO`
**or legitimately restored** `state=RECOVERED` it calls the existing official
`execute_durable_failure_cleanup` once, using the receipt's `old_restored`,
the fixed Boca stage root, the reviewed R108 expectation, and production
retained-resource IO only when restoration was attested. Revalidate the
typed durable FAILURE V2 proof, hashes, `outcome=FAILURE`, `state=NO_GO` and
the unchanged original terminal receipt; only then call journal.terminal.

For a postcommit ambiguous failure, NEVER call FAILURE cleanup/restore; just
persist NO_GO/INDETERMINATE in the same journal. For a successful accepted
transaction, terminalize without any FAILURE cleanup. Any exception after
the one-way FAILURE intent leaves residue, never retry. A cleanup `ACCEPT`
on a restored old pair cannot turn a failed install into `ACCEPTED`.

## Tests first

1. Fake the official executor behind a fixed, canonical FAILURE receipt:
   precommit restoration calls once and terminals once; original NO_GO or
   RECOVERED state is retained. Negative forged digest/type/status never terminals.
2. Unrestored precommit fails closed with no selective delete authority.
3. Commit-started NO_GO/INDETERMINATE calls no FAILURE executor and terminals
   once; accepted SUCCESS also calls no FAILURE executor.
4. Duplicate sink use and physical executor failure never retry; raw
   exception/host paths never printed.
5. Verify no mutation from construction and `main apply` still rejects
   before lease; keep `requires_persistent_receipt=False`.
6. Focused/full QA, independent review, protected ZIP closure/size with
   source-only and genuine release fixture. Integrate with SUCCESS and
   technical postflight only after all are ready.
7. Independent review exposed two P1s: precommit RECOVERED must reach FAILURE
   cleanup; and a foreign/unprimed journal must fail before any cleanup effect.
   RED tests reproduced both, then an on-disk active-intent attestor fixed them.

This is not a deployment attempt. No Porota, real reservations, queue bypass
or TLS relaxation; host access remains exclusively the Boca protected Action.
