# ADR 0005: One-entry, deterministic offline queue simulator

Status: Proposed for F1 issue #6, 2026-10-28.

## Decision

`boca_socios.queue.OfflineQueueSimulator` is a Python-only, in-memory
single-event simulator. It contains no URLs, credentials, HTTP transport,
browser automation, Queue-it token/pass handling or connection to Boca.
Its synthetic transitions are not evidence of Queue-it's or Boca's actual
policy. It does not authorize queue circumvention or issue tickets.

The explicit request states are `created`, `prequeue`, `waiting`,
`admitted`, `expired`, `cancelled`, `closed` and `error`. Terminal states
cannot be reactivated. Only a waiting request can be admitted, and only
an admitted request can be explicitly finished. Finishing means ending
the simulation, **not** purchasing or reserving a ticket.

The simulator is parameterized by one opaque event ID, aware opening and
closing times, admission TTL, optional maximum waiting duration, integer
lottery seed and prequeue policy:

- `LOTTERY`: entrants in prequeue receive a deterministic SHA-256-derived
  seeded ranking at opening. Registration order has no lottery advantage.
- `FIFO`: prequeue entrants retain their original joining order.
- In **both** configurations, entrants joining after opening append FIFO.
  This is a simulation choice only, not a claim about live queue behavior.

All operations accept a caller-provided aware timestamp and require
nondecreasing time. The opening draw occurs once. Deadline transitions
record their logical instant even if the caller jumps over several
deadlines: waiting expiry precedes sale close only when the waiting
deadline is no later than sale close. Already-admitted entries retain
their own TTL across sale close; they expire at its exact boundary.
Unknown session IDs and attempted reassignment of an alias are rejected
**before advancing** the shared synthetic clock, so malformed requests
cannot expire unrelated entries. A valid, known session operation can
still advance time and reveal a deadline, even if its requested business
transition is subsequently disallowed.

The request key is `(event_id, opaque member_id)`; all logical session IDs
for that member/event are **aliases of one queue request**, never independent
queue positions. The request's ticket quantity is exactly 1. Cancel/error
applies to the one request and every alias; idempotent rejoin never adds
another queue position. Neither several sessions nor a lottery win can
increase authorized ticket quantity.

Identity uniqueness is configurable without weakening that invariant:
`COALESCE` (default) allows many logical session IDs to observe the same
single request; `SINGLE_SESSION` rejects another distinct session ID for
that member/event, while exact registration retries are idempotent. A test
models 1,000 synthetic sessions across 100 members; these are in-memory
records, **not** real browsers or hypothetical independent queue passes.

## Limitations and future work

This is an **importable library for offline tests**, not yet wired into
`boca_socios.runtime` or a running service. Its inclusion alone does not
change runtime operation.

The simulator is process-local and does not persist state, synchronize
across processes, represent a signed admission pass, reserve inventory or
model actual Boca/Queue-it admission rules. The existing DB unique
member/event constraint is still required for any eventual transactional
reservation. Admission capacity is driven explicitly by `admit_next`, not
derived from a real event. No adapter to a live provider is included.

The simulator uses constant-sized state per logical entry/session plus
in-memory ordering lists; it starts no processes, browser workers or
connections. Full frozen lint, format, strict types, tests and isolation
gates and an agent technical review of the exact head must pass before merge.

Deployment and live observation remain unauthorized, separate milestones.
