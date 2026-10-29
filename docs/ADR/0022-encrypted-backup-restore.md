# ADR 0022: bounded encrypted SQLite backup and offline restore

**Status:** Proposed for issue #46 and human review, 2026-10-28. This is an
internal, opt-in module only. It has no CLI, endpoint, scheduled job, runtime
import, Docker mount or deployment path.

## Decision

Use SQLite's online backup API to capture a consistent WAL snapshot into
memory. Check integrity, foreign keys and the foundation migration checksum
and run `VACUUM` to normalize the WAL header in the memory copy before
encrypting the entire image with AES-256-GCM. SQLite's backup API otherwise
leaves WAL header bytes that cannot be deserialized without a WAL sidecar.
The original database is never vacuumed. The format has a fixed
version marker and fresh 96-bit nonce; the header is authenticated as AAD.
Only the ciphertext is written to a private, 0600 staging file and linked
atomically to a previously absent archive name. Never overwrite an archive.

Restore authenticates the file with the independently held backup key before
parsing SQLite. Repeat the DB checks, restore into a private 0600 staging
database, check it again, and publish only to a previously absent path. An
existing database or symlink destination fails closed. Neither operation
mutates the live database, fetches a key, prints records or visits Boca.

The snapshot limit is **16 MiB**. SQLite progress callbacks stop a growing
or contended copy and the memory-only vacuum after **10 seconds**. The
in-memory image, vacuum and authenticated encryption need extra copies, so an offline rehearsal needs
additional memory beyond the controller's 256 MiB cap. Exceeding the limit
requires a new streaming design and resource review, not an override.

## Custody and recovery gate

The backup key is a distinct 32-byte secret supplied by a separately approved
owner-controlled mechanism; it must not be the credential master key. Keep
both outside GitHub, the image, chat and logs, and do not store them together
with the archive. The SQLite image contains personal data and encrypted
credential rows. Restore does not verify possession of each historical
credential master key; a separate offline rehearsal must verify decryption
after restart, especially around PR #40's key-version migration. The code
checks the foundation checksum and permits later migration versions, which
must be checked by the corresponding runtime before operational use.

Private directories, backup retention, deletion propagation, encrypted
off-host custody, restore coordination and key recovery remain operational
design/review tasks. A backup predating deletion may contain a revoked
credential; restoring it must not silently reactivate a person or reset the
one-ticket quota. Do not wire this module into Actions or a live host until
the complete plan, capacity and exact release are reviewed. No real members,
credentials, reservations or droplet operations are enabled by this PR.
