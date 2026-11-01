# ADR 0049: durable outcomes for opt-in local simulation

**Status:** Proposed, 2026-10-31 ART. Issue #127, PR #130.

## Problem

OfflineSimulation fences aliases only inside one instance. Two coordinators
or a restart can execute the synthetic browser twice. The existing durable
reservation guard is disconnected and its provider_ack_reported state must
never be used to describe a simulated success.

## Decision

Add DurableOfflineSimulation as an opt-in coordinator. Reuse OfflineSimulation
admission, identity, quota and per-instance checks through a narrow workflow
hook. The new coordinator explicitly prepares storage before use, records the
single ticket intent, and commits a simulation-kind guard claim before the
synthetic browser. A second in-flight, failed or ambiguous attempt cannot
execute the browser. No retry re-arms a consumed claim.

Migration 0005 transactionally rebuilds the guard table to add attempt_kind
and explicit simulation_completed/simulation_failed states. Existing rows
retain their tokens, timestamps and states as external-kind attempts. The
original migration 0003 and checksum remain unchanged. Default guard.migrate
and the dormant runtime still do not apply 0005; only migrate_simulation does.
Both Python resolution checks and SQL constraints prohibit a simulation claim
from becoming provider_ack_reported or an external claim becoming a simulated
result. Local-status schema validation accepts the reviewed v5 checksum while
continuing to report external_confirmation=not_observed.

After a successful synthetic browser, completion is persisted before notice
enqueue. A later admitted invocation can replay that completed receipt and
the existing deterministic outbox key without executing the browser. This
recovers a notice failure between completion and enqueue. Synthetic failure
or cancellation records simulation_failed when persistence and time checks
succeed. A crash, invalid completion clock, expired claim or unavailable DB
may retain in_flight; it stays consumed and can be marked needs_review by the
existing explicit overdue operation. No failure path creates a provider result.

## Boundaries and verification

The clock is injected and validates finite nonnegative Unix seconds; the guard
retains its deadline and token fencing. Replay still requires an admitted
synthetic queue session for the same member/event. Tests cover independent
coordinator races, restart replay, cancellation/failure, crash after claim,
notice recovery, expired completion, invalid clock, checksum drift, transactional
migration rollback/data preservation, kind fencing and read-only projection.

This does not wire the runtime, expose HTTP, start Chromium, perform an actual
reservation or provide provider reconciliation. The initial runtime remains
engine off, simulation only and migration 0001. The legacy OfflineSimulation
remains available for deterministic component tests. No host, credentials,
backup, network or other project operation is part of this change.
