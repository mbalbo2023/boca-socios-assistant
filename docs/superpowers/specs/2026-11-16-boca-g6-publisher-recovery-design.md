# Boca G6 release publisher recovery — design (2026-11-16)

**Authority:** Tincho's explicit one-time exception and 4/4 GO_PRE_CODE in
[#417 comment 6925043732](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6925043732).
**Base:** `main` `362ae571b3d8d53bdd43dd4d9b664f5ab2d7d0f0`.

## Intent and evidence

Release #869 (run `43922790822`) built both images, passed IPC/Chromium smoke,
source checks and both security scans, then failed on the first browser `docker
push` with exit 1 and terminal `unknown blob`. Controller was not pushed and
the run has no manifest artifacts. No specific registry or Docker root cause is
proven. Release #868 on the previous source used the same workflow and runner
successfully. Re-running #869 or dispatching again against its source violates
the intentional first-dispatch/attempt-one contract.

## Approaches

1. **Bounded same-run publication recovery (selected):** one global second push
   only for the exact observed failure, from the already built, scanned and
   unchanged local image. Keeps first-dispatch provenance and does not repeat a
   build inside the run. Adds tightly bounded diagnostic evidence.
2. **Another release with no handling (rejected):** recreates the same failure
   boundary without improving observability; uses the one-time exception.
3. **Change builders/scan policy, retry the failed run, or use old images
   (rejected):** no causal evidence and/or breaks provenance and security gates.

## Contract

- No product/UX, browser Dockerfile, build strategy, runtime, secrets, sender,
  rootless host, GHCR permissions, parsers, manifests or anti-replay changes.
- Record immutable local image IDs and source/revision labels before scans and
  re-verify them before each push. Browser is published and its digest validated
  before controller may start publishing.
- At most one recovery for the **entire release**, within the same job and
  `run_attempt=1`: no more than three push invocations total for a dual success.
  First failure must be exit 1 with a sole exact terminal `unknown blob`, no
  digest or conflicting diagnostic. Retry at most once with same tag and image,
  after a 5-second pause and fresh main/unique-dispatch and identity checks.
- Each push has a 300-second timeout. Ambiguous logs, noneligible errors,
  timeout, failed second push, drift or exhausted global budget fail closed.
- Capture stdout/stderr and exit status per attempt with bounded private files.
  Existing digest parser sees only a full successful attempt. Never coalesce
  failed and successful logs. Report redacted role/attempt/result metadata.
- No `GITHUB_OUTPUT`, release manifest or artifact becomes authoritative until
  both push commands and both existing manifest validators succeed. Failure
  never becomes an apparent SUCCESS through `tee`, logging or a partial digest.
- One reviewed short-lived PR, one new release from its genuine merged SHA,
  exact CI/security and independent 4/4 FINAL, INTEGRATION and OPERATION votes.
  A second failure stops; no automatic further PR, build, Action or host change.

## Acceptance

Offline tests must exercise the production publication code with fake local
Docker/GitHub commands, not merely search strings. Cover success, browser and
controller eligible recoveries, exhausted shared budget, wrong/ambiguous
failure, missing or duplicate digest, stdout/stderr and pipeline failures,
timeout, drift and source/uniqueness changes. Existing gate tests stay green.
No external registry push or real booking is part of local testing.
