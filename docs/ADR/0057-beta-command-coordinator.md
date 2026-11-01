# ADR 0057: durable on-demand commands for the local BETA

**Status:** Proposed implementation, 2026-10-31 ART. Issue #147. Depends on #130.
Scope approved in continuity #45 comment6551577529. This is code and temporary
test data, not an executed host operation or migration of an operational DB.

## Composition and public contract

The callable service is `boca_socios.integration.beta.BetaCoordinator`.
Construction requires `database: Database`, `outbox: SqliteNotificationOutbox`
and a trusted `browser: SyntheticBrowserPort`; `outbox.database is database`
is required. The outbox still accepts its original Path argument; accepting an
existing Database adds dependency injection without implicit initialization.
The agreed deployment configuration is `/data/boca.sqlite3` in Boca's data
volume. That chosen location is not evidence that a database exists there.

| Call | Contract |
| --- | --- |
| `prepare_storage()` | Explicit opt-in preparation of 0001/0002/0003/0005/0006; never called by construction or commands |
| `await recover()` | Startup-only reconciliation under exclusive lifecycle ownership; schedules safe accepted work afterwards |
| `await begin(command_id, TicketIntent(member_id, event_id))` | Persist and return canonical `CommandSnapshot`; start one on-demand worker |
| `status(command_id, *, member_id)` | Read-only snapshot, or None for unknown/wrong member |
| `await stop(command_id, *, member_id)` | Idempotent stop request/snapshot, or None for unknown/wrong member |
| `await wait_idle()` | Await worker completion without a polling loop; useful for integration tests |
| `await close()` | Stop accepting work, persist active stop if possible, always cancel/join the local task |

Snapshot fields: command_id, request_id, state, created_at, updated_at,
notice_enqueued, mode=`simulation`, external_confirmation=`not_observed`.
Command IDs are canonical nonzero UUID strings. Reusing a key for another
member/event raises CommandConflict. New keys for the same member/event bind
durably to the original command; status/stop accept these aliases. There are
at most 64 keys per command, and a bounded pending capacity (default16, max100).
CommandCapacityError reports either limit. Terminal history is retained;
this change does not introduce deletion or retention policy.

The hosting adapter must authenticate and authorize the principal/member
before calling these methods, redact storage errors, and enforce HTTP request
budgets. Root can construct one Database, inject it into enrollment/outbox and
this service, run explicit preparation/recovery once at the approved lifecycle
boundary, and call begin/status/stop from the private request adapter. The
service itself starts its worker; a second scheduler is not required. No
listener or runtime.py wiring is added here. The existing dormant runtime
remains unchanged until its separately reviewed composition is integrated.

## Durable behavior and recovery

Migration0006 adds beta_commands and its command-key aliases. A transaction
creates the single ticket intent plus command/key binding; request_id remains
unique and quantity stays1. Tickets stay planned: completion here is a local
simulation result, never an external reserved ticket. Version6 is recognized
by the existing read-only status projection; an unknown version still fails.
Preparation is sequential across existing migration components, not one atomic
upgrade of every version; migration0006's DDL and ledger are atomic together.

The worker atomically changes accepted to running before any synthetic call.
Only one running/stop_requested command can be claimed through this store at
a time, including competing service instances. Each call uses a new one-entry
offline queue with explicit synthetic admission, then DurableOfflineSimulation
and its durable guard. It does not invent a Queue-it position or visit Boca.
The configured synthetic timeout defaults to5 seconds and is bounded to30;
the injected port must cooperate with asyncio cancellation, not arbitrary code.

| Persisted evidence | Recovery/result |
| --- | --- |
| accepted, never claimed by worker | Safe to process after startup reconciliation |
| running with no guard or unresolved/in-flight guard | needs_review; no automatic browser replay |
| failed guard | failed, or stopped if a stop was requested; never rearmed |
| completed simulation guard | completed; re-enqueue deterministic local notice key without browser |
| completed command, notice_enqueued false | Recover enqueue/ledger gap idempotently |
| stopped or terminal command | Repeated begin returns its existing result |

Enqueue acknowledgment means durable local storage, not delivery to a person.
The synthetic dispatcher #134 is not wired here. A notice error leaves
completed/notice_enqueued=false and stops the worker; explicit recovery can
repair it. Storage errors stop further claims and expose only `failed=True`.
An active stop cancels the local task; a stop racing completed durable work
retains the completed result. Shutdown guarantees cancellation/join even if
persisting the stop fails; ambiguous durable evidence is not erased.

## Limits and verification

The service owns a single event-loop lifecycle. Recovery is allowed only while
that instance is idle, and the host must ensure no older process remains alive.
There is no cross-process lease proving exclusive startup recovery. Ordinary
competing claims are fenced in SQLite; calling recovery against another live
process is unsupported. Remote-instance stop persists stop_requested but cannot
cancel that process's in-memory task; the single hosting instance is the
supported control path. Timeouts are cooperative, not process isolation.
SQLite calls are synchronous with the existing five-second connection timeout;
the hosting request/shutdown budgets must account for database contention.

Read-only status uses SQLite mode=ro and writes use mode=rw, so absent paths
are not silently created by commands. SQLite WAL/shared-memory limitations
from ADR0053 still apply. Only explicit prepare_storage can initialize schema.
No credential value, browser payload or free-form exception enters the ledger.

Tests exercise begin/status/stop, concurrent aliases and workers, scope denial,
restart at accepted/running/completed stages, deterministic notice recovery,
timeout, pending capacity, schema rollback/checksum rejection, injected database
identity, unknown-schema rejection and shutdown despite storage failure.
All fixtures are synthetic and temporary. Actual host readiness, private
authentication, operational enrollment wiring and end-to-end deployment remain
separate acceptance gates; this PR alone is not a deployed or live BETA.
