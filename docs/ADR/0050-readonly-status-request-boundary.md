# ADR 0050: minimal read-only local status request adapter

**Status:** Proposed, 2026-10-31. Issue #126, PR #128.

## Decision

Reuse ADR0045's existing SQLite projection in a small WSGI callable. The
application accepts one fixed GET route, `/api/v1/local-status`. Its database
path is supplied by server configuration; no query, body, SQL or path override
is accepted. A browser cannot directly open the SQLite file inside the Boca
volume; this adapter is the small server boundary needed to return permitted
aggregate facts without moving credentials or database access into the Site.

Identity verification is injected and defaults to denying every request.
An accepted bearer identity must match the configured owner, carry the exact
`local-status:read` permission and have an unexpired timezone-aware expiry.
The verifier is responsible for cryptographic verification, issuer/audience,
revocation and applicable session policy. Request headers never directly set
identity or permission. There is no real provider, token, enrollment or login
implementation in this change.

The caller must arrive through a trusted TLS-serving WSGI gateway; the adapter
requires `wsgi.url_scheme=https` and never interprets forwarded-proto headers.
This value is not TLS proof without the hosting configuration and review.
Cookies, Origin headers, mutation methods and bodies are refused. No CORS
headers or OPTIONS permission are emitted. A direct cross-origin Site remains
unconnected until a reviewed gateway/identity contract exists. Do not place a
long-lived bearer credential in public Site code to work around this limit.

Responses are bounded to 2048 bytes, no-store and JSON-only. Only the existing
local projection leaves SQLite; a recorded local result remains unverified
externally. Authorization and read failures use static errors without paths,
tokens, identities or provider diagnostics. No request body or authorization
logging is added. One read can run at a time, at most once per second per
application instance; the future host must enforce total worker/request limits,
TLS, redacted access auditing and header limits as well.

## Scope and evidence

Tests cover default denial before database creation, owner/permission/expiry,
malformed bearer input, method/path/body/query/Origin restrictions, TLS-header
spoofing, private failures, response redaction and the read rate budget. The
adapter opens no listener on import or construction and performs no migrations.
Default runtime, Compose, ports, image, host and the private Site do not change.
Backup/restore remains deferred. This is tested adapter code, not an operational
API, live identity integration, host readiness or a reservation implementation.
