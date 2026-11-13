# R252: separate, non-promoting technical postflight proof

## Context and RCA

R245's `TECHNICAL_ACCEPT` receipt still mandates `LOGIN_HTTP_200` in
`_validate_snapshot`, although the real, mutation-free local panel witness only
probes `GET http://127.0.0.1:8443/healthz` and returns `HEALTH_HTTP_200`.
R247 correctly leaves owner login and authenticated monitor producers absent:
`/ingresar` creates a WebAuthn challenge and the monitor endpoint may renew an
owner cookie. Production postflight therefore cannot complete using the real
safe sources. Synthesizing login or authenticated monitor results would turn a
missing proof into a false positive.

## Contract

- Keep the original schema-1 `BOCA_PAIR_POSTFLIGHT`/`capture_postflight`/
  `verify_postflight` contract unchanged: it still requires the independently
  proven `LOGIN_HTTP_200` and a monitor producer.
- Add an explicit technical-only capture and offline verifier, using schema 2
  and a distinct `BOCA_PAIR_POSTFLIGHT_TECHNICAL_V2` prefix. The technical
  producer requires real `HEALTH_HTTP_200`, *not* owner login; it does not
  access the authenticated monitor. Its `NOT_CONNECTED`/zero observations mean
  **no monitor evidence was acquired**, not a claim that live tokens are zero.
- Preserve structural guards: authenticated pinned release, exact R177 pair and
  healthy controller, CREATED/PID0/Exit0 worker, persisted SITE_URL and mirror
  digests, rootless identity, stable inode/mount custody, retained graph, and
  durable cleanup V2 receipt readback under one held lease. Capture two fresh
  snapshots and require equality with lease checks around both.
- Technical receipt must explicitly say `TECHNICAL_PROOF_ONLY`, owner passkey
  `NOT_ATTESTED`, monitor `NOT_ATTESTED`, `beta_deploy=NO_GO`, no observer
  writes, and no foreign resource access. Cross-version replays fail closed.
- Never enable APPLY, acquire a lease, run a browser, expose credentials,
  contact Boca's public service, book tickets, or claim production installation.

## Scope and deployment caveat

Only the three postflight source/runtime/receipt modules and their focused tests
are changed. No protected ZIP, workflow, operator host or GitHub mutation is
in scope. Therefore this change is a **CODE_ONLY candidate**, not a physical
same-lease acceptance or installed release. A future reviewed protected runner
must explicitly call the new capture path, persist/fsync/readback its bytes
before releasing the lease, and independently attest owner Chrome/passkey and
monitor only after installation. BETA remains NO_GO until those physical steps.

## Rejection tests

Wrong health response, no volume attestor, missing durable readback, drifted
SITE_URL/worker, changed second snapshot, lost lease, forged/not-cleaned pair,
noncanonical/duplicate fields, technical/legacy cross-verification and any
attempt to promote passkey, monitor or beta state all refuse without effects.
