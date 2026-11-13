# ADR0263 — SUCCESS cleanup journal is scoped to an upgrade attempt (R253)

**Date:** 2026-11-13 UTC. **Issue:** #417. **State:** CODE_ONLY,
`requires_persistent_receipt=False`, `DEPLOY NO_GO`.

## RCA

The successor SUCCESS finalizer wrote two hard-coded names in the shared
private Boca stage directory: `boca-final-cleanup-v2.intent` and
`boca-final-cleanup-v2.receipt`. Its first successful invocation placed both
files durably via `O_EXCL`, making every independent *later* B→C/C→D upgrade
fail before cleanup could start, even under a different validated attempt.
Deleting these receipts or overwriting them would erase forensic evidence
and could permit unsafe retries; neither operation is authorized.

## Decision

- Derive **both** filenames exclusively from a validated numeric `attempt_id`:
  `boca-final-cleanup-v2.<attempt>.intent` and
  `boca-final-cleanup-v2.<attempt>.receipt`. The caller cannot provide a path
  component or change the protected directory.
- Continue `O_NOFOLLOW`, mode/UID/inode custody, `O_CREAT|O_EXCL`, fsync,
  readback and same-lease checks. A repeated attempt is refused before any
  engine effect; a *different* attempt may create independent evidence.
- The postflight source reader resolves the exact same attempt-scoped receipt
  name and verifies its bytes and SHA against that attempt's proof. It cannot
  read a previous attempt's global or attempt-specific artifact by mistake.
- Do not delete, rename or trust old global receipt names. Leave any legacy
  residue for a separate, explicitly reviewed forensic decision.

## Evidence and limits

TDD RED on the old global names: the first attempt lacked its own scoped
intent (and a later attempt would encounter the original `O_EXCL` collision).
GREEN: two distinct attempts each produce independent
receipt bytes, and replay of the first fails before cleanup is invoked.
Existing receipt tamper/mode/symlink/partial-effect tests remain in force.

This fixes journal collision only. It does not enable the transaction, connect
FAILURE V2, approve SSH/Actions, prove Chrome passkey or activate any worker.
Source bundle budgets and the full same-lease actor still gate R252/R253.
