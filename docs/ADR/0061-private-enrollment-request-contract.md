# ADR 0061: private enrollment form and bounded owner sessions

Status: implementation proposal for the approved synthetic BETA scope, issue #17.
This change supplies request adapters, not an exposed server or deployed login.

## Enrollment inside the application

The application serves `Socios > Agregar socio` on one configured HTTPS origin.
GET `/socios/nuevo` renders visibly labelled alias, email, password and individual
consent controls. POST `/socios` calls the existing MemberEnrollmentService,
which generates the opaque member ID and atomically writes the member, AEAD
ciphertext and metadata-only audit. The caller supplies the server's current
consent timestamp after affirmative consent; this is recorded consent, not
proof of external eligibility. The existing service stores email and alias;
there is no separate Boca username column. Email is not asserted to be the
correct external login or verified membership identity. Do not invent another
field or change the schema. No real login or reservation follows.

No SQLite access occurs in the browser and no separate database server or API
platform is introduced. Database/vault/service instances are supplied by the
future application composition root; this adapter never migrates a database,
chooses a storage location or loads a key from a request. Acceptance uses only
synthetic identities and credentials in disposable test databases.

## Authentication remains an explicit decision

Recommend the owner's platform passkey (WebAuthn) with verified origin/RP ID,
one-use challenge, owner credential allowlist and reviewed bootstrap/recovery.
This avoids copying a token from a terminal or introducing an external SSO
dependency. A reviewed equivalent remains an option. Selection of a library,
dependency lock changes, the real verifier, enrollment of the admin's device,
recovery and TLS deployment are separate concrete decisions before exposure.
Password plus TOTP alone is not asserted to meet ADR 0012's phishing-resistant
requirement. This ADR does not silently approve or implement an auth provider.
The proposed verifier follows the W3C WebAuthn authentication and challenge
requirements: <https://www.w3.org/TR/webauthn-3/#sctn-verifying-assertion> and
<https://www.w3.org/TR/webauthn-3/#sctn-cryptographic-challenges>.

OwnerSessions accepts a server-side authentication verifier and denies by
default. Its authenticate method is not an HTTP route. Only a verified owner
with the explicit members:enroll permission can obtain a fresh opaque random
session. Incoming identity headers never create a session. Store only a hash
of the session token in a bounded process-local store. Cookies are host-only
`__Host-boca_session`, Secure, HttpOnly, Path=/ and SameSite=Strict. Regeneration
on authentication prevents adoption of a supplied session identifier. Revocation
and process restart invalidate sessions. Idle and absolute expiry are explicit,
configurable positive durations; proposed defaults 15 minutes / 8 hours are
not BETA acceptance requirements or a decision about the owner's usability.

Every request verifies the session, permission, configured host and trusted WSGI
HTTPS scheme. Never infer TLS or identity from client forwarding headers. A
future server must enforce TLS, header/connection/time budgets and the same
origin before supplying the environment. Cookies and identity proofs must not
appear in access logs. There is no listener or runtime/Compose wiring here.

## Mutation boundary and retry meaning

Require exact Origin, session CSRF token and a server-issued operation UUID;
reject unknown/duplicate fields, query strings, transfer encoding and bodies
larger than 16 KiB. Accept only URL-encoded UTF-8 form data with bounded field
lengths. Validate identity before reading the body. Render no input value in
an error, including email/alias. Return only fixed messages and an opaque UUID
after success. Responses are no-store, with a restrictive CSP and no framing.

Each GET issues a bounded operation ID retained for that session. Reusing that
ID with identical form bytes returns the recorded result without a second
service call; altered bytes conflict. Retain a keyed request fingerprint, not
plaintext form data. Concurrent in-flight requests do not start another write;
uncertain failures are recorded as unavailable and never blindly retried.
The store and mutation rate are bounded. This is process-local HTTP retry
protection, not durable exactly-once delivery across restarts. Restart destroys
the session and its operations; existing service email uniqueness remains the
database defense. A failed or lost response requires explicit reconciliation,
not automatic submission under a new identity.

## Accessible interaction and limits

Use native labels, email/password input types, an explicit unchecked consent
control, large targets, keyboard order and a text aria-live status. A small
same-origin form submission script preserves alias/email in the displayed form
when authentication expires; it clears the password after a response and never
uses localStorage/sessionStorage, timers to erase a form, or password echoes.
Do not claim voice/tablet acceptance from source inspection: deployed browser
and accessibility checks remain part of the BETA acceptance.

This delivers the narrow add-member flow. Rotation, revocation, complete data
erasure, verified membership identity, real enrollment/key custody, real admin
authentication, command controls and notice projections remain explicit work.
Backup/restore remains deferred. The code does not publish a Site, operate the
droplet, modify other projects, enable a port or establish a deployed BETA.
