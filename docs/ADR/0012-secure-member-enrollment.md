# ADR 0012: Owner-only member enrollment and credential lifecycle

Status: Proposed design; agent technical review is recorded in PR #28,
2026-10-29. PR #31 proposes an internal service only. No endpoint or real
credential enrollment is enabled.

Issue: #17. This proposal does not enable an endpoint, accept a real password,
or change the simulation-only runtime. Review of this design is a prerequisite
to implementing an exposed enrollment interface.

## Decision and trust boundaries

- The owner manages each consenting member through a dedicated Boca-only web
  interface. A member is never enrolled from chat, Telegram, a GitHub issue,
  a workflow input, a repository secret, or an import file in source control.
- The application authenticates the owner and checks authorization on **every**
  read and mutation. A trusted reverse proxy alone is insufficient; neither
  a client-supplied header nor possession of a private URL grants access.
- The future panel is disabled by default. Its deployment requires a dedicated
  TLS origin and the exact-input Boca Actions operation gate in ADR 0038. No
  host port or third-party traffic is added to the current Compose service by
  this ADR.
- Administrator identity bootstrap and recovery are separate reviewed tasks.
  They must use a phishing-resistant authentication factor or an equivalent
  reviewed owner authentication mechanism, with no bootstrap password or
  bearer token placed in GitHub Actions, logs, chat, or the Docker image.
  Until bootstrap and recovery are proven, enrollment remains disabled.

## Future HTTP contract

1. An authenticated owner session has an idle timeout and an absolute expiry.
   Cookies are `Secure`, `HttpOnly`, host scoped, and `SameSite=Strict`;
   regenerate the session identifier on authentication. Reject missing or
   expired authentication before reading or writing any member record.
2. Mutations require a per-session CSRF token and exact trusted `Origin`;
   reject cross-origin requests, including a missing origin where the client
   must send one. Limit request size, input lengths, and request rate. Do not
   log request bodies, URLs with secrets, response bodies, form values, or
   query strings. Set `Cache-Control: no-store` and a restrictive CSP.
3. The form names its fields visibly and programmatically, displays an
   explicit consent statement for each person, and requires an affirmative
   consent action. Controls are operable by keyboard and voice, have large
   targets, a logical focus order and text status messages announced with
   `role=status`/`aria-live`. Errors identify the field without echoing the
   entered password. Do not rely on hover, color or a timed interaction.
4. Enrollment accepts an opaque, server-generated member ID, consent time
   and provenance, membership identifier/eligibility evidence, username and
   password only through the protected request. The owner must verify the
   member's consent and eligibility outside the simulator. Store only the
   minimum evidence required; never mark eligibility verified just because
   a form was submitted. No live login or reservation is triggered.
5. The server seals a nonempty password with the existing `CredentialVault`
   using member-bound AEAD and writes member, credential and metadata in one
   SQLite transaction. No plaintext is returned to the client or retained in
   audit events. If the key cannot be read or a DB write fails, roll back the
   entire enrollment. Do not create an empty member as a success fallback.
6. Separate actions rotate a member password, revoke/deactivate a member,
   and delete data. Password rotation is atomic, uses a fresh nonce and key
   version, and never reveals the prior password to the panel. Deletion must
   define ticket-intent retention and irreversible backups before it is
   enabled; a mere UI removal is not a deletion guarantee.

## Identity and one-ticket invariant

The current `members` table uses an opaque `member_id` and unique email, but
neither proves a unique Boca membership identity. A new email or internal ID
could otherwise represent the same person twice. Before eligible requests,
add a separately reviewed migration with a stable, privacy-conscious unique
membership identity and explicit eligibility state. An HMAC blind index with
a separately held key is one candidate, subject to identity and recovery
review. Keep `(member_id, event_id)` unique and `quantity = 1` at the database
boundary; neither multiple sessions nor duplicate form submissions create
additional intents. No reservation may be scheduled for an unverified member.

## Key rotation and data recovery

The database holds ciphertext, nonce and `key_id`; the master key stays
outside the database, repository, image and GitHub workflows. A key rotation
must stage old and new key versions, rewrite every row transactionally or in
restart-safe batches, verify decryptability after process restart, and only
then retire the old key. A failure leaves the old key available. Backups of
the database and key must be separately protected and tested for recovery;
retention and deletion schedules require a recorded technical policy before
real enrollment.

## Verification required before an exposed endpoint

- Agent technical review of this ADR, identity uniqueness, administrator
  bootstrap, TLS topology, authorization model and access recovery.
- Tests for authentication, authorization, CSRF, origin, timeout, input
  limits, rate limiting and accessibility with keyboard/voice control.
- Transaction tests for duplicate submissions, simultaneous enrollment,
  rollback on encryption/DB failures, ciphertext-only persistence, restart,
  password rotation, key migration, deactivation and deletion.
- A negative audit of all logs, CI artifacts and errors for PII, plaintext
  passwords, cookies and session tokens; no real values in test fixtures.
- A dedicated security review of the deployed reverse proxy, admin identity
  and backup custody before the owner enters any real credential.

## Consequences and current status

The foundation schema and vault alone do not verify identity, authenticate an
administrator, protect HTTP requests, delete personal data or serve an
accessible panel. PR #31 adds an internal transaction boundary but leaves real
enrollment disabled until those gates pass.

### Internal service candidate (PR #31)

The internal `MemberEnrollmentService` can create member, sealed credential
and metadata-only audit in one SQLite `BEGIN IMMEDIATE` transaction. Password
rotation decrypts the prior record first to fail closed on stale/missing keys,
then replaces it with a fresh nonce in one transaction. Credential revocation
deletes ciphertext while retaining the opaque member and ticket requests so
that a later re-enrollment cannot silently reset the per-event local quota.
This is credential revocation, **not** a promise of complete personal-data
erasure. The service has no route, runtime import, live login, verified member
identity or administrative access mechanism. Its tests use only fake values.

Master-key re-encryption, process coordination during key changes, backup
deletion, and external identity uniqueness need separate schema and operations
review; the password-rotation method does not solve those tasks. The reviewed
vault hardening from PR #23 is in `main`, but a real secret mount still requires
the Boca-only host permission and isolation gate before it can be used.
