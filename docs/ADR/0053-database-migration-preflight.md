# ADR 0053: validate existing SQLite before migration writes

**Status:** Accepted implementation. Issue #137; PR #141 merged as
`07cf424c92384a42e820b73befcaaeeaca87e8d9`. Exact candidate
`1bd018fccdf4430fc075afe4e957fc17fd59e178` passed
[CI 41258685042](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41258685042)
and [image scan 41258685016](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41258685016).
Acceptance covers code and synthetic fixtures, not a migration of real data.

## Reproduced defect

Database.migrate previously enabled WAL and executed migration 0001 before
checking its recorded checksum. A synthetic database with a mismatched
checksum gained Boca tables and changed journal mode before startup raised
an error. Sentinel data survived; the reproduction proves unwanted mutation,
not data loss. The dormant runtime calls this method during startup.

## Decision

An existing regular file must have a readable migration ledger with version 1
and the exact unchanged 0001 checksum. Validate through SQLite mode=ro before
creating directories, running DDL, changing journal mode or changing file
permissions. Reject unversioned, empty, malformed and checksum-mismatched
files; never adopt an unrelated SQLite database or repair its schema.

Open the same path with mode=rw, recheck its device/inode identity and validate
the ledger again before WAL. This catches a checksum changed between the two
opens and detectable path replacements. Known databases do not rerun 0001.
They retain the WAL and private-permission startup policy.

A missing path is initialized with exclusive file creation. If a file appears
first, fail rather than adopt it. On the newly created empty file, apply the
unchanged 0001 statements and ledger row in one transaction. Fresh creation
and repeated startup preserve current tables, constraints, checksums and data.
An interrupted empty creation is rejected on the next startup, requiring an
explicit diagnosis; startup does not silently overwrite it.

## Limits

Read-only SQLite connections can interact with WAL shared-memory sidecars.
Use mode=ro, never immutable=1: ignoring a live WAL could validate an obsolete
checksum. This change guarantees rejection before application DDL, journal
mode changes and chmod; it does not promise zero filesystem effects for every
SQLite WAL/recovery situation. Tests assert byte and mode preservation only
for their closed, non-WAL rejection fixtures.

Identity checks are defense in depth, not exclusion against arbitrary local
processes replacing paths or writing between checks. Trusted startup ownership
of the database directory remains required. The ledger validates migration
identity, not every schema object or every data page; this is not a full
integrity audit or a new database discovery mechanism.

## Verification and scope

Regression tests reproduce the original checksum failure before the fix and
cover unknown/empty/corrupt input, fresh creation, repeated and concurrent
known-database startup, live WAL checksum visibility, changed checksum between
opens, path replacement and symlinks. Fixtures are synthetic temporary files.

No SQL migration file, business rule, runtime mode, deployment workflow or
existing real database is changed by this PR. It does not authorize applying
migrations, installation, release, backup or live access. PR #130 remains a
separate inactive candidate.

