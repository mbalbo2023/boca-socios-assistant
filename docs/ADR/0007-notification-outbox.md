# ADR 0007: Notification outbox contract, offline only

Status: Proposed for F2 simulation, 2026-10-28.

## Decision

Introduce a typed, in-memory `boca_socios.notify` outbox with no network
dependencies, Telegram SDK, chat ID, bot token, credentials or deployment
configuration. All messages use fixed allowlisted Spanish templates prefixed
**Simulación**. Incoming `untrusted_payload` is deliberately discarded before
record creation; no arbitrary text, member identifier, link, cookie, session
URL, redirect, token or exception string is interpolated into notifications.
The caller supplies a stable opaque UUID as the *notification* idempotency
key, and repeats are deduplicated even after local acceptance. This key is
not a ticket-reservation idempotency contract, and does not change the
one-ticket-per-member-per-event invariant or storage schema.

Priority is fixed per notice kind: `ACTION_REQUIRED` (critical),
`QUEUE_ADMITTED` (high), `STATE_CHANGED` (normal), `HEARTBEAT` (low). Due
messages are claimed by priority, then FIFO within a priority. A rolling
window limits claims; an explicit record budget fails closed when full.
Atomic in-process leases prevent simultaneous duplicate claims and make
unacknowledged attempts eligible for bounded retry after lease expiry. A
claim object is valid only for the issuing outbox instance and its active
lease; a copied or identically valued claim cannot acknowledge another one.

Failures take only a boolean retryability decision and optional nonnegative
`retry_after_seconds`, never an exception or remote response payload. The
retry delay is `max(min(cap, initial * 2 ** (attempts - 1)), retry_after)`;
thus provider-requested longer waits are respected, while the local
exponential component is capped. Exhausted and nonretryable notifications
remain terminal; no unbounded retry loop exists. A stale/expired claim
cannot be acknowledged. Time inputs are caller-supplied monotonic seconds
for reproducible, network-free tests.

`run_dry_run` claims and acknowledges locally, and p95/p99 are nearest-rank
statistics for **local simulated acceptance only**. They are not evidence of
Telegram API acceptance, message delivery, user reading, queue admission,
or successful ticket purchase.

## Deliberate limitations and follow-up gates

- **No durability:** the in-memory outbox and deduplication history vanish on
  process restart. F2 must separately review a persistent outbox store,
  transaction boundaries, recovery and retention policy before claiming
  durable delivery or exactly-once behavior. Do not conflate notification
  deduplication with any ticket/checkout idempotency guarantee.
- **No Telegram integration:** no network traffic occurs. A future owner-
  approved adapter must implement bounded timeouts, API response handling,
  `retry_after`, send limits, authorization, channel lookup and fail-closed
  behavior, and must pass only the static text rendered here. Telegram API
  acceptance is not proof that a human saw the message.
- **No real alert SLA:** synthetic p95/p99 cannot establish the proposed
  production acceptance targets. Measure those only in a separately
  authorized synthetic integration with clear timestamp definitions.
- **No sensitive telemetry:** do not log raw event payloads, exceptions,
  usernames, member emails, authentication material, Queue-it tokens,
  session URLs or third-party redirect links. Logging must use only safe
  event types, counts and bounded timings after its own security review.
- **No real site behavior:** this module cannot initiate Boca/Queue-it
  traffic, alter a queue position, reserve a ticket or notify an owner today.

## Verification

Tests cover strict priority/FIFO, repeat deduplication and conflict, sliding
rate limits, capped exponential retry and larger `retry_after`, exhausted and
nonretryable failures, lease expiration and stale claims, concurrent claims,
finite input bounds, dry-run latency, and synthetic secret-like payloads and
exception messages never appearing in records, rendered text or logs.

This ADR requires review alongside the existing isolation and credential
policy before any live adapter is proposed. The current PR must pass exact-head
CI and an agent technical review before merge. It does not authorize deploy.
