# Issue #12: isolated private queue-pass observation contract

## Scope and ownership

The owner requested a complete, copyable observed queue token in the private
dashboard, with multi-session support tied to existing member profiles. This
cut supplies the **offline, in-memory domain projection only**. The other
development chat owns the authenticated HTTP/UI integration, `SITE_URL`, IPC,
worker, container configuration and Cutover. This cut does not modify those
files, open a PR, merge, deploy, contact a site or reserve any ticket.

Existing `OfflineQueueSimulator` already coalesces logical sessions into one
member/event ticket request. No new queue manager is introduced. The member
identity in this contract is the existing `member_id`, not an enrollment form
or second source of membership data.

## Observed, never fabricated

An independent value object records either an unavailable observation or an
opaque token **supplied by a future authorized observer**. There is no token
generator, validator, URL allowlist, network client or browser operation.
The recorded destination is merely observed metadata, not an instruction to
navigate there. A token that was seen is always *unverified*; expiry may
override that state, but presence never implies admission or a reservation.

Represent these distinct outcomes:

1. `NOT_OBSERVED`: no token has been supplied.
2. `OBSERVED_UNVERIFIED`: token supplied, expiry unknown or in the future.
3. `EXPIRED`: token supplied, known expiry reached.
4. `UNKNOWN`: observer could not ascertain the result.

All timestamps are timezone-aware; crossing the expiry boundary is explicit.
The source observer is responsible for its authenticity and retention policy.

## Sensitive-data boundary

Safe projections and `repr()` omit the token and destination entirely.
Complete, unmodified token/destination values are exposed only through an
explicit owner-only projection, with a required authenticated-owner signal.
This signal is an adapter contract **not** an authentication implementation:
the future private panel must use its existing passkey/session and CSRF gates
before calling it. The future HTTP endpoint must be `no-store`, same-origin
and hidden from logs, Actions, public artifacts, screenshots and Telegram.

An authenticated owner may copy the **entire** supplied token byte-for-byte
as a Python string; no truncation, formatting or guessing of its syntax.
No secrets are committed: every test fixture is explicitly fictional.

## Completion criteria

- Offline tests cover exact owner-only copy, unauthorized access, not-seen,
  unknown, expiry, timezones, safe `repr` and metadata projection.
- Strict type, format, lint and repository-policy checks pass.
- New modules only; no overlapping changes to the other chat's working files.
- The branch remains isolated with factual documentation. The dashboard
  integration and droplet proof are separately pending, not declared GREEN.
