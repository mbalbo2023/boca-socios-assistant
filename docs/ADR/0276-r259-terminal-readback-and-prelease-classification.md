# ADR 0276 — R259 terminal readback and truthful pre-lease refusal

**Fecha:** 12-NOV-2026 ART / 13-NOV UTC. **Issue:** #417. **Estado:** CODE_ONLY;
`DEPLOY NO_GO`, CLI APPLY hard-blocked, successor `requires_persistent_receipt=False`.

## RCA / prueba roja

The successor `SuccessorPairJournal.terminal()` inherited the historical
O_EXCL/fsync writer but never reread its own terminal. Two offline tests
tampered with the **real** 0600 terminal file immediately after the write
(altered bytes or chmod 0644). Both incorrectly returned normally, despite an
untrustworthy durable receipt. The prior #501 factory-BaseException regression
only inspected an in-memory list and could not catch this failure mode.

Separately, unexpected exceptions in CLI `_successor_preflight` were caught
before any protected lease or host effect but fabricated
`commit_started=True, failed_phase=COMMIT_MARKER`. The third red test captured
that semantically incorrect canonical response.

## Minimal decision

`SuccessorPairJournal.terminal` now uses the existing protected stage
`_read_file` on the exact attempt terminal after O_EXCL/fsync, matching the
SHA-256 of canonical encoded bytes and checking inode, UID/GID, mode 0600,
link count and no-follow read stability. It verifies the **same held lease**
again before returning. Any uncertainty raises a fixed-category NO_GO and
retains forensic residue; no delete/rename/retry or backend operation is
triggered.

CLI preflight errors before a lease continue returning exit 3 and
`NO_GO/INDETERMINATE`, now correctly `commit_started=False, ATTEST`; this
does not reinterpret or weaken genuine post-marker uncertainty produced
by the transaction engine. It does not add any effectful APPLY path.

## Verification and constraints

Three TDD assertions initially FAILED for the exact expected reasons, then
PASSED after the two changes. The focal integration group exercised 82 tests
successfully. This same journal module's explanatory prose was condensed
without changing its security logic; the full rationale is retained here.
The protected pair bundle after this isolated change had **78 entries**,
**360725 ZIP bytes**, **1396743 uncompressed bytes** against the fixed
1400000 limit, leaving **3257 bytes** before reconciliation with other branches.
Full local suite: **8018 passed, 34 subtests passed, 1 skipped AF_UNIX** due
to local sandbox EPERM; Ruff check + format (1039 files), mypy (196 files),
repository policy and `git diff --check` all passed. GitHub Actions exact-SHA
is still required; no historical green run may be inherited. The Actions
Linux socket smoke must supply independent AF_UNIX evidence.

Remaining blockers: assemble protected lease/Compose/factory, SUCCESS and
FAILURE V2 with physical postflight, owner passkey and monitor evidence,
exact-main dual release, then one protected Boca-only install and physical
acceptance. Historical R186 remains irreversible NO_GO and never replayed.
No Boca/Queue-it navigation, tickets, Docker or physical host operation
occurred in this change; Porota and every unrelated workload remain untouched.
