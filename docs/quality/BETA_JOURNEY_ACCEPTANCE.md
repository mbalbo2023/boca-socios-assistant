# Acceptance of the private enrollment and durable command composition

Issue #151 owns `tests/test_beta_enrollment_journey.py`. It exercises the real
application's enrollment WSGI adapter, `MemberEnrollmentService`, credential
vault, SQLite, `BetaCoordinator`, reservation guard and durable notification
outbox together. Every file and credential in these tests is temporary and
synthetic. The origin is an RFC-reserved test domain; no server listens and no
network request is sent. This is not a replacement Boca website.

## Implemented scenarios

| Scenario | Evidence checked |
| --- | --- |
| Enroll, repeat POST, begin, complete, reconstruct service | One member, sealed credential, one quantity-1 request and one notice; credential remains decryptable; a new command key for the same member/event returns the durable result without another browser call |
| Enroll, begin, stop before execution, reconstruct service | Stop remains effective, no browser call or notice, member/credential and the single request retained |
| Missing authentication | Both form and submission rejected; no member, credential, request or notice persisted |
| Completion followed by notification-write failure | Failure is visible; a new Database/coordinator recovers one missing notice from the committed result without repeating the browser; repeated recovery stays deduplicated |

The journey creates storage only through the coordinator's explicit preparation
on a new temporary path, then injects that **same Database instance** into the
enrollment service and outbox/coordinator. Restart scenarios reconstruct the
Database object from the same path and do not prepare another schema. They
exercise persisted state, not just a surviving process cache.

An async test owns one event loop through `begin`, `wait_idle`, `recover` and
`close`; production composition likewise needs a persistent lifecycle. Calling
`asyncio.run` independently for each HTTP request would cancel background work
and is not the hosting model established by these tests.

## What these tests do not prove

Owner verification and the browser port are deterministic injected doubles.
They do not implement or validate passkeys, a TLS origin, a listener, actual
Chromium interaction, a queue provider, Telegram, or a reservation at Boca.
The WSGI enrollment request is real application code, but the subsequent
command calls are in-process; there are no HTTP command routes yet. The status
adapter from #128 rejects cookies, whereas enrollment uses a private cookie
session. A composed panel must define and test one consistent authorization
boundary before being served. The owner-facing list of enrolled members and
tablet/voice interaction remain part of that hosting/UI acceptance.

These tests are complementary to module fault-injection, schema/integrity,
concurrency, authentication-denial and image checks. Their successful result
does not make a controller with its engine off a functional deployed BETA.
Actual server restart, resource isolation/capacity and the complete tablet
journey still require the reviewed candidate and authorized droplet workflow.

## Reproduction and reporting

Run `uv sync --frozen` and `uv run pytest -q
tests/test_beta_enrollment_journey.py` in the isolated development/CI checkout.
The usual full suite, types, lint, policy and RCA checks still apply; no new
host operation, dependency, workflow or performance threshold is introduced.
Record counts, source SHA and the exact CI run in the PR and continuity #45.
Do not promote an in-process test duration into a browser/deploy latency claim.
