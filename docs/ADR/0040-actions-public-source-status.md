# ADR 0040: manual Actions semaphore for the anonymous public source

**Status:** Implemented for issue #94 in PR #96, 2026-10-29
(America/Argentina/Buenos_Aires). The first manual dispatch
[40984386263](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40984386263)
completed on 2026-10-30 at 01:12:10 UTC, attempt 1. Its bounded observation
at 01:12:06 UTC reported `GREEN`, HTTP 200, `http_200_unverified` from the
anonymous public login URL. This confirms only that single response from a
GitHub runner; login, queue, eligibility and reservation remain unverified.

## Decision

A separate `workflow_dispatch` in the Boca repository checks the fixed public
`/auth/login` path from one GitHub-hosted runner. Only the repository owner can
run it from the `main` commit selected at dispatch. A standard-library client
issues one anonymous HTTPS GET with an eight-second timeout per socket
operation and a three-minute Actions job limit, certificate
verification and no redirect following. It sends no cookie, authorization
header, account value or request
body. It never reads or emits the response body or headers. The script has no
URL or account input and uses no Docker, SSH, secrets or production host.
The workflow rejects `GITHUB_RUN_ATTEMPT` other than `1` before its GET, so
rerunning the same dispatch cannot silently make another public request.

The output is a bounded JSON record and Actions summary with UTC timestamp,
fixed target, HTTP status when available, and a semaphore:

- `GREEN`: HTTP 200 from the fixed endpoint. The page content, login form and
  actual Boca workflow remain **unverified**.
- `YELLOW`: redirect, client refusal/rate limit or unexpected HTTP status.
  Redirect locations are not read or followed.
- `RED`: server error, timeout, TLS or transport failure. Exception text is
  discarded and must not reveal URLs, headers or environment information.

External-source failures produce an alert and a successful Actions job; a
script, malformed semaphore, contract or workflow error still fails the job.
The operation report must cite the source run, timestamp and color, or show
`UNKNOWN` if the check did not produce a valid report. A source outage alone
does not trigger a new image or block an otherwise isolated simulation-only
controller deployment. Code defects require a separate fix and exact CI. Image,
release digest, host isolation, resource and credential gates remain required.
The controller's operational health is a separate local signal; no live
reservation readiness is inferred from this public status observation.
`UNKNOWN` is the operator's interpretation when there is no valid completed
observation, including a rejected rerun or a failed job. It is not a result
emitted by the script and cannot be presented as a green or red site status.

## Execution boundary and limits

No PR, push or scheduled event runs this check, and its tests use only fakes.
The workflow must be integrated into default `main` before manual dispatch.
A green HTTP response can be a challenge or placeholder. A runner's public
network view does not establish the droplet's reachability or a logged-in
member's reservation path. This observer does not cross a challenge, queue,
login or checkout and has no connection to the dormant runtime. Repeated
testing must stay manual and bounded; never use it as load or admission probe.
