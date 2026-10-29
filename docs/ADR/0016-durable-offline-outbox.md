# ADR 0016: Durable synthetic notification outbox

Status: Proposed for review, 2026-10-28. Partial issue #16; stacked on PR #30.

## Decision

Add SQLite migration version 2 and a separate `SqliteNotificationOutbox`.
The foundation's `Database.migrate()` remains unchanged. The outbox adapter
applies its additive migration in one immediate transaction, checks a SHA-256
checksum in `schema_migrations`, and uses the existing Boca-only DB path.

Only a UUID, allowlisted notice kind/priority, delivery state, attempts and
Unix-second timing are stored. The caller's `untrusted_payload` is discarded,
including if it contains credentials or a queue reference. Fixed Spanish
message text is derived from the existing allowlist at claim time; no message
body, member ID, email, link, token or exception text is stored or sent.

One `BEGIN IMMEDIATE` writer transaction protects enqueue deduplication,
priority/FIFO claim selection, durable rate slots and lease assignment. A
fresh random lease token and incremented attempt number fence a stale worker
after expiry or restart. At lease expiry, retry backoff starts at the
observed recovery time; retry-after is a delay floor. Max attempts, TTL and
capacity fail closed. Terminal rows remain as dedupe tombstones; no automatic
pruning may quietly permit a repeated logical notice. The table contains no
membership foreign key; safe erasure of historical metadata and retention
policy still require separate review before storing real personal data.

Unlike the in-process outbox's monotonic clock, this adapter requires caller-
supplied Unix seconds so leases persist across process restart. Wall clock
changes and multi-host skew are operational risks; it is not a distributed
exactly-once delivery guarantee. SQLite `busy_timeout` bounds contention.

## Gate and evidence

This is an offline library, not wired into the controller or a network
transport. `accept()` records only local simulated acceptance, not Telegram
API acceptance, user reading or Boca ticket confirmation. The default runtime
stays unchanged. A separate adapter/reconciliation review is required before
external delivery. Tests cover restart, concurrent claim fencing, dedupe,
priority, backpressure, retry-after, TTL, capacity, data minimization and
migration checksum failure. No live sites or credentials are needed.
