# ADR 0054: observe fixed Boca database candidates without opening SQLite

**Status:** Proposed, 2026-10-31 ART. Issue #139.

## Evidence and scope

Protected inspection #92 found Docker executables available, the dedicated
user's docker.service not found and its rootless socket absent. None of these
facts establishes whether a prior Boca database exists. The owner authorized
read-only database metadata discovery before deciding infrastructure changes.

Extend the existing inspect-prerequisites phase with independent receipts
before the socket readiness failure. Existing identity, socket, service,
resource and deployment gates remain unchanged. No workflow input, transport,
new host access route or service operation is added.

## Fixed candidates

The home directory comes only from the UID10001 account record after the
existing dedicated identity validation. It is never included in output.

| Receipt label | Candidate file |
| --- | --- |
| rootless_default | `<dedicated-home>/.local/share/docker/volumes/boca-socios_boca_data/_data/boca.sqlite3` |
| staging_root | `/srv/boca-socios/boca.sqlite3` |
| staging_data | `/srv/boca-socios/data/boca.sqlite3` |

For each candidate, inspect only that exact filename and its `-wal` and
`-shm` companions. The latter two staging locations are bounded hypotheses,
not the current Compose mount. Compose declares `/data/boca.sqlite3` inside
the named `boca-socios_boca_data` volume. Its physical host location remains
unverified; the default rootless directory might differ from an actual
configured Docker data root. No generic host `/data`, shared Docker store,
other account directory or recursive search is included.

Walk from `/` using directory descriptors with Linux O_PATH, O_DIRECTORY,
O_NOFOLLOW and O_CLOEXEC. Every directory component, including the account
home, refuses symlink traversal. Require the dedicated home or Boca staging
anchor to belong to UID10001 and not be writable by group/others. Descendants
may use subordinate UID ownership; no UID remapping is assumed. Stat the
final entry relative to its parent descriptor with follow_symlinks=False.
Close descriptors on success and every exceptional or early-return path.
Do not open the final file, read SQLite headers or data, hash content, import
runtime/database code, list directory entries or invoke a subprocess.

## Meaning and limitations

Receipts contain fixed labels, an allowlisted state and byte size only for
regular files: candidate-present, candidate-absent, inaccessible, unsafe-path,
not-regular or unavailable. Access denied never means absent. Malformed home
metadata suppresses all candidate probes. Output is bounded by three fixed
candidates and nine files; path depth and length are bounded too.

The summary always reports `location=UNVERIFIED scope=fixed_paths_only`.
A regular file at a candidate path does not prove it is SQLite, belongs to
the intended deployment, is current, internally consistent or safe to reuse.
Missing candidates do not prove that no Boca database exists elsewhere.
WAL/SHM observations are point-in-time metadata, not a consistent DB snapshot.
This inspection creates no database, directory, service, container or backup.
It neither enables deployment nor selects a storage architecture.

Regression tests cover metadata-only opens, absent versus inaccessible,
parent/leaf symlinks, a directory changed into a symlink during traversal,
foreign/writable anchors, path escape, fixed candidate limits, redaction,
dedicated identity ordering and emission before an unchanged NO-GO gate.
