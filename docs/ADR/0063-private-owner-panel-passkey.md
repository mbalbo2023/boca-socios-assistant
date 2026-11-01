# ADR 0063: private same-origin panel with passkey assertion gate

**Status:** accepted; PR #163 integrated into
`ebb5e95399233eec629c8c52d4176092e97c5f34`. This describes code, not a
deployed Boca service. Main baseline at start:
`213be4903669c6e88122a536ad8fee6785c997ac`. The later authorization in
[#45 comment 6552258326](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6552258326)
expands the BETA goal while retaining simulation-only and review/Actions gates.

## Decision and trust boundary

Serve an owner-only WSGI application on one **configured HTTPS origin**, with
an ES256 WebAuthn assertion for an already enrolled owner credential. The
public credential ID and P-256 public key, RP ID, exact origin and owner subject
are server configuration. Authentication requires a fresh random one-use
challenge, exact origin and RP hash, user-presence and user-verification bits,
and a valid signature. Challenges expire after 120 seconds; at most eight are
outstanding and new requests are rate limited. Nonzero signature counters are
checked for progression during the process lifetime. The browser receives no
server secret. The private key remains inside the owner's authenticator.

The passkey verifier does **not** register or bootstrap a credential. A
separately reviewed owner-controlled enrollment/recovery ceremony, actual
credential public key, DNS/TLS origin and protected host configuration are
required before exposure. A test-generated P-256 key is not an owner passkey.
The in-process counter is not durable clone detection; synced passkeys may
report zero. Authentication proof is one-use and sessions are revoked on
process restart.

`OwnerSessions` stores only a hash of each opaque cookie token and its verified
permissions, then issues a `__Host-` Secure/HttpOnly/SameSite=Strict cookie.
All owner pages require this session; operations enforce a scoped permission.
The existing enrollment handler retains its Origin, CSRF, request-size and
operation-id checks. The new command and credential mutation handlers accept
only same-origin, bounded form bodies with CSRF. The app checks the trusted
WSGI HTTPS scheme and exact Host; forwarded headers never establish trust.
The hosting server must actually terminate TLS and set that scheme from its
own configuration, enforce header/connection/time budgets and redact access
logs. Merely setting the WSGI value in a test does not prove TLS.

## Local routes and limits

| Route | Permission | Effect |
| --- | --- | --- |
| `GET /ingresar`, `POST /sesion` | passkey assertion | one owner session; no Boca credentials |
| `GET /socios`, `/socios/{id}` | `members:read` | bounded read-only local member list, masked email, active-credential flag |
| `GET /socios/nuevo`, `POST /socios` | `members:enroll` | existing encrypted atomic enrollment handler |
| `POST /socios/{id}/credencial`, `/revocar` | `members:write` | existing local vault rotation/revocation; no external account change or full erasure |
| `GET /comandos`, `/comandos/{id}` and `POST /comandos`, `/comandos/{id}/detener` | `simulation:write` | read/start/stop local simulation via injected persistent command host |
| `GET /estado` | `local-status:read` | read-only SQLite aggregate, labelled without external confirmation |
| `GET /avisos` | `local-status:read` | read-only local outbox state and explicit Telegram API state, without destination or message text |

Read-only member/command queries open SQLite `mode=ro`, never initialize a DB,
return at most 50 rows and avoid credential material. Display names are HTML
escaped and emails masked. A count over 50 fails visibly; pagination is not
implemented in this candidate. The command form selects only server-configured
synthetic events and active local members. Its operation UUID is issued by the
server; the durable command store binds one member/event and quantity one.
Repeated identical POSTs return the same command link; conflicting reuse
fails. If a command result is uncertain, the page asks the owner to inspect
the durable history, without minting another command ID. A stopped or
completed local result is never a Boca reservation.

The authenticated home names deferred event sources/categories, browser
session controls, master-key rotation/full erasure, backup/restore, live Boca
operations and Site integration as **not enabled**. These are static status
labels without an action button or simulated side effect; they do not claim
the remaining BETA matrix is implemented.

The WSGI app has no listener, migration, credential provisioning, Site
credential bridge or Telegram transport. The notice route reads only the
bounded projection integrated by #162; `api_accepted` means a Bot API response,
never human receipt. The runtime writer owns composition
and persistent event loop; the Site writer owns the separate outbound bridge.
No inbound Site bearer route is added in this candidate. All public Site
material remains free of members and passwords.

## Verification and remaining gates

Synthetic tests exercise passkey origin/UV/signature/replay, authenticated
enrollment→encrypted storage→masked list→local command, and cross-origin,
CSRF, spoofed TLS and missing-session denials. Test credentials and keys are
ephemeral fixtures. Candidate
`4b608b1ae8dedd4ad9fe541ecbd5f45fac42958c` passed
CI 41270060363, scan 41270060350, release/deploy validation
41270060360/41270060361 and preview 41270060364; technical review
5726269111 in PR #163. These checks do not establish the host, tablet or Site.

The exact branch was reviewed and the runtime/notification code was integrated
through #162/#164/#173/#179. Before operational acceptance, provision one real owner credential with a
recoverable process and exact HTTPS origin; configure a Boca-only TLS server
through the protected Actions workflow; test real tablet voice/keyboard
behavior, restart, denial and local notices on the deployed candidate. No
real Boca login, queue, reservation, purchase or existing-data migration is
authorized by this code. Backup/restore remains deferred. Other workloads
remain outside this scope.
