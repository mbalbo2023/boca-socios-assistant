# Architecture v1 — isolated Boca Socios project

## Boundaries and flow

~~~mermaid
flowchart TD
  UI["Future owner panel / Telegram"] --> APP["Orchestrator"]
  APP --> DB["Dedicated encrypted-credentials database"]
  APP --> QUEUE["Queue adapter abstraction"]
  QUEUE --> SIM["Built-in simulator (current)"]
  QUEUE -. "review + consent + live gate" .-> LIVE["Future authorized browser adapter"]
  LIVE -. "actual traffic, not enabled" .-> BOCA["Boca Socios / Queue-it"]
~~~

The live adapter MUST NOT be imported or constructed by the current runtime.
Unverified third-party behavior stays behind interfaces.

## Service and data models

- Member: opaque member_id, unique email, consent timestamp.
- Credential: one per member, AES-256-GCM ciphertext, nonce, key_id;
  decryption key outside DB.
- Event: independent ticketing window.
- TicketRequest: one per member + event, CHECK(quantity = 1).
- QueueSession: multiple future observation states may exist for a member and
  event; queue reference stored only as a hash, not raw entry/admission token.
- AuditEvent: metadata only, no secrets or human-readable password data.

## Storage

SQLite dedicated WAL file under a **Boca-only** Compose named volume. Use
busy_timeout and explicit transactions; enforce all unique/foreign-key rules
at DB level. Backups and migration rollback design require independent ADRs
before a live release.

## Multi-session design (future)

Browser workers are a separate service boundary. Do not run large Chromium
pools on any unbenchmarked shared host. For testing, simulate many
logical sessions without spawning many actual browsers. A member's ticket
quantity remains 1 independently of the number of sessions observed.

## Resource isolation

Compose project name boca-socios, separate volumes boca_data and boca_key,
network boca_private,
no host port, no shared mount, no Docker socket, no privileged container.
Controller is capped at 0.5 vCPU, 256 MiB RAM, 64 PIDs, nonroot and
read-only filesystem. Future workers require separate resource budgets,
load testing and approval.

Compose project isolation is **not a separate host/kernel**; heavy browser
workers may require another independent compute environment.

## Observability

Structured logs: event type, opaque member/event IDs, state transitions and
duration. No usernames/passwords, token values, full redirects, cookies or
authorization headers. Healthcheck reads only migration status.

