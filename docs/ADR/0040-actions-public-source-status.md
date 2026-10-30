# ADR 0040: manual Actions semaphore for the anonymous public source

**Status:** Proposed for issue #94, 2026-10-29. No live source check dispatched.

## Decision

A separate `workflow_dispatch` in the Boca repository checks the fixed public
`/auth/login` path from one GitHub-hosted runner. Only the repository owner can
run it on exact `main`. A standard-library client issues one anonymous HTTPS
GET with an eight-second timeout, certificate verification and no redirect
following. It sends no cookie, authorization header, account value or request
body. It never reads or emits the response body or headers. The script has no
URL or account input and uses no Docker, SSH, secrets or production host.

The output is a bounded JSON record and Actions summary with UTC timestamp,
fixed target, HTTP status when available, and a semaphore:

- `GREEN`: HTTP 200 from the fixed endpoint. The page content, login form and
  actual Boca workflow remain **unverified**.
- `YELLOW`: redirect, client refusal/rate limit or unexpected HTTP status.
  Redirect locations are not read or followed.
- `RED`: server error, timeout, TLS or transport failure. Exception text is
  discarded and must not reveal URLs, headers or environment information.

External-source failures produce an alert and a successful Actions job; a
script, contract or workflow error still fails the job. A source outage alone
does not trigger a new image or block an otherwise isolated simulation-only
controller deployment. Code defects require a separate fix and exact CI. Image,
release digest, host isolation, resource and credential gates remain required.
The controller's operational health is a separate local signal; no live
reservation readiness is inferred from this public status observation.

## Execution boundary and limits

No PR, push or scheduled event runs this check, and its tests use only fakes.
The workflow must be integrated into default `main` before manual dispatch.
A green HTTP response can be a challenge or placeholder. A runner's public
network view does not establish the droplet's reachability or a logged-in
member's reservation path. This observer does not cross a challenge, queue,
login or checkout and has no connection to the dormant runtime. Repeated
testing must stay manual and bounded; never use it as load or admission probe.
