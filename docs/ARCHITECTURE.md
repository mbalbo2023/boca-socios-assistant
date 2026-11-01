# Architecture v1 — isolated Boca Socios project

## Boundaries and flow

~~~mermaid
flowchart TD
  UI["Owner panel code, not deployed"] --> APP["Local BETA runtime"]
  APP --> DB["Dedicated encrypted-credentials database"]
  APP --> QUEUE["Queue adapter abstraction"]
  QUEUE --> SIM["Built-in simulator (current)"]
  QUEUE -. "review + consent + live gate" .-> LIVE["Future authorized browser adapter"]
  LIVE -. "actual traffic, not enabled" .-> BOCA["Boca Socios / Queue-it"]
~~~

The live adapter MUST NOT be imported or constructed by the current runtime.
Unverified third-party behavior stays behind interfaces.

## Functional BETA code and deployment boundary

The default Compose runtime remains dormant. PRs #161/#164 integrate the
persistent local command loop and lifecycle; #163 integrates a same-origin
owner passkey panel; #170 tests disposable HTTP loopback; #173 adds explicit
`init-beta` and `serve-beta` TLS entrypoints. #189 adds no-listener owner/TLS
checks, #191 protected new-only install, #190 a disposable TLS probe and #200
protected acceptance with same-job stop. None has installed a BETA in the
droplet. Run #120 prepared only the dedicated rootless daemon, #124 passed
preflight for the dormant budget and #156 stopped it. The private Site #113 v10 has a
disabled D1 bridge; #178/#179 add sealed custody and outbound client code,
and #181 adds protected host custody, hardened by global inventory RCA #196.
No Site host phase ran; the bridge remains disabled. Telegram #162/#188 is
opt-in code with #194 stop recognition, #199 sealed custody helper, #203
post-install phases and #204 one-shot Bot API gate, still without host
dispatch, bot/destination or a send.
ADR0056 sets a panel served by the Boca application, backed by local SQLite.
The private form **Socios > Agregar socio** is mandatory for BETA acceptance.
Its server boundary reuses MemberEnrollmentService and CredentialVault for
atomic member/credential/audit persistence with an external key. UI/API input,
authentication of the owner, consent context, request authorization, session
protection and response redaction must be tested before access is activated.
The owner passkey verifier and #174 registration proof are code boundaries,
not an enrolled owner, verified tablet route or working host login.

[The delivery plan](BETA_DELIVERY_PLAN.md) connects enrollment to synthetic
start/stop/status, guard, persisted results and local notices. The browser
never opens SQLite or receives a key; the server accesses the file locally.
A separate database server or API platform is not required by this design.
Tests and initial acceptance use synthetic member data; no Boca identity,
consent or eligibility is proven by local email validation.

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
before a live release.

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
The dormant controller is capped at 0.5 vCPU, 256 MiB RAM, 64 PIDs, nonroot and
read-only filesystem. The separate beta Compose #171 passed disposable CI
validation with host-loopback TLS and effective isolation; it is not a host
installation. Future workers require separate resource budgets,
load testing and approval.

Compose project isolation is **not a separate host/kernel**; heavy browser
workers may require another independent compute environment.

## Observability

Structured logs: event type, opaque member/event IDs, state transitions and
duration. No usernames/passwords, token values, full redirects, cookies or
authorization headers. Dormant healthcheck reads migration status; explicit
BETA health #173 verifies local TLS/loop and a fixed synthetic event. Neither
health mode proves Site, Telegram or tablet access.


