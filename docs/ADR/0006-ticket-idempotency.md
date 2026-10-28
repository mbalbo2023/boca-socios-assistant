# ADR 0006: One durable logical ticket intent per member and event

Status: Proposed for F1 issue #7, 2026-10-28.

## Decision

Keep the database-level `UNIQUE(member_id, event_id)` constraint and
`CHECK(quantity = 1)`, and make `Database.request_ticket()` idempotent for
retries. An atomic SQLite `INSERT ... ON CONFLICT(member_id, event_id) DO
NOTHING` followed by a read **within the same transaction** returns the
original persisted `request_id` when the tuple already exists. Concurrent
callers cannot create multiple rows because SQLite serializes writers and
enforces uniqueness. Invalid quantity and blank/non-string identities fail
before opening the transaction.

The request ID is a stable opaque identifier **after the first successful
commit**. New requests generate a candidate random UUID but never overwrite
an existing record. No network request, queue token or reservation operation
is performed by this method.

## Semantics and failure cases

- Repeating the same `(member_id, event_id)` returns one request ID rather
  than raising on uniqueness conflict; the original `quantity=1` is kept.
- Distinct members or events produce distinct logical intents.
- Invalid foreign keys, disk errors, unavailable DB and transaction failures
  still fail closed; they are not disguised as idempotent success.
- In an uncommitted failure, a later retry may create a new request ID.
  Clients must treat an ambiguous DB timeout as unresolved until a read
  confirms existence. The method is **not** a distributed exactly-once API.
- `BEGIN IMMEDIATE` is not necessary for this write-first design. The
  `INSERT` acquires a SQLite write transaction; the following `SELECT` reads
  the winner's committed or own-inserted row within that transaction.
- Real reservation/checkout is entirely outside this interface. **Exactly
  one external purchase cannot be guaranteed** from a local SQLite unique
  key without an agreed idempotency contract and reconciliation mechanism
  with Boca. On ambiguous external results, do not auto-retry payment.

## Verification

Tests require 36 attempts coordinated in waves by a thread barrier to produce
the same UUID and exactly one DB row, require a second member to receive a
different UUID, and reject `quantity=True` and `quantity=2`. A deliberately
held `BEGIN IMMEDIATE` lock plus short busy timeout must fail without a row;
after lock release, retry must create and retrieve the same single intent.
An existing queued status/timestamp must not change on retry. FK and SQL
quantity constraints stay in force. Tests perform no network or purchases.

This ADR does not authorize any live Queue-it/Boca adapter, login, checkout
or deployment. Changes require review and passing GitHub Actions checks.

References: [SQLite transaction semantics](https://www.sqlite.org/lang_transaction.html),
[SQLite UPSERT](https://www.sqlite.org/lang_UPSERT.html),
[AWS idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/).
