# Architecture v1 — isolated Boca Socios project

> Corte fuente comprobado al iniciar esta etapa: `213be4903669c6e88122a536ad8fee6785c997ac`.
> La autorización operativa de [ADR0062](ADR/0062-operational-beta-and-recovery.md) no prueba funciones nuevas.
> Revalidar #45 y seguir [reanudación](RESUME_PROCEDURE.md); último host comprobado: #120, no STOP final todavía.

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

## Approved functional BETA target, not current runtime wiring

The current runtime remains dormant. PRs128/130/134/148/149 provide adapters
and coordination; PR152 proves their synthetic in-process composition, not a
served application. Run120 prepared the dedicated rootless daemon without any
application/database installation. ADR0062 now authorizes the operational
BETA and connection of the existing private Site, backed by local SQLite.
The selected design uses Site-native owner identity and an outbound HTTPS
bridge with a temporary RSA-OAEP/AES-GCM encrypted mailbox; SQLite on the
droplet remains canonical. It still needs implementation/review and evidence.
The private form **Socios > Agregar socio** is mandatory for BETA acceptance.
Its server boundary reuses MemberEnrollmentService and CredentialVault for
atomic member/credential/audit persistence with an external key. UI/API input,
authentication of the owner, consent context, request authorization, session
protection and response redaction must be tested before access is activated.
A default-deny identity port is a development boundary, not working login.

[The delivery plan](BETA_DELIVERY_PLAN.md) connects enrollment to synthetic
start/stop/status, guard, persisted results and local notices. The browser
never opens SQLite or receives a key; the server accesses the file locally.
A separate database server or API platform is not required by this design.
Automated tests use synthetic member data. Separately authorized real navigation
uses only the designated private testing account without reservation, purchase
or Boca account modification. Local email validation proves neither Boca
identity nor eligibility. Stop every Boca service, bridge and dedicated daemon
after tests; retain data/key and publish only redacted receipts.

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

The delegated logical destination is `/data/boca.sqlite3` on persistent volume
`boca-socios_boca_data`, with the key in a separate Boca-only volume. This is
the future BETA storage decision, not evidence of an existing database. Global
current location remains UNVERIFIED after the fixed-path inventory #98. If
storage is discovered, identify/preserve it and verify compatibility; no
replacement, fallback path or real migration is implied by this choice.

SQLite dedicated WAL file under a **Boca-only** Compose named volume. Use
busy_timeout and explicit transactions; enforce all unique/foreign-key rules
at DB level. Backups and migration rollback design require independent ADRs
before their eventual activation; operational backup/restore remains deferred.
ADR0062 permits designated-account temporary custody without a backup operation.

## Multi-session design (future)

Browser workers are a separate service boundary. Do not run large Chromium
pools on any unbenchmarked shared host. For testing, simulate many
logical sessions without spawning many actual browsers. A member's ticket
quantity remains 1 independently of the number of sessions observed.

## Resource isolation

Compose project name boca-socios, separate volumes boca_data and boca_key,
network boca_private,
the current dormant Compose has no host port, shared mount, Docker socket or
privileged container. The functional private-access candidate must explicitly
review its changed ingress/health contract; these current flags are not proof
that a future panel is already accessible.
Controller is capped at 0.5 vCPU, 256 MiB RAM, 64 PIDs, nonroot and
read-only filesystem. Future workers require separate resource budgets,
load testing and approval.

Compose project isolation is **not a separate host/kernel**; heavy browser
workers may require another independent compute environment.

## Observability

Structured logs: event type, opaque member/event IDs, state transitions and
duration. No usernames/passwords, token values, full redirects, cookies or
authorization headers. Healthcheck reads only migration status.



