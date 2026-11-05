# ADR0140 — Chrome image launch proof without owner BLACKBOX

**Date:** 2026-11-04 ART. **State:** DRAFT, PR-only validation; no merge/deploy.
**Scope:** browser-worker readiness #227. This does not alter the physical cutover.

## Problem and decision

The existing image release PR gate built, pinned, inspected and scanned the
separate browser-worker image. That evidence did **not** prove Playwright's
installed Chromium can actually start under the intended UID10002 and Docker
isolation. The external owner validation of `synthetic.py`/`ipc_worker.py`
must not be replaced with any agent import, execution or inspection of those
modules (ADR0121/ADR0123).

Add exactly one ephemeral, **pull-request-only** validation step to
`release-image.yml`, after the reviewed worker command check and before image
security scans. It launches **only** the independent
`scripts/verify_chromium_worker.py` from the already locally built image.
The script runs Playwright's real Chromium against `about:blank`, checks the
internal JavaScript engine and terminates, without external URLs, Boca,
Queue-it, owner-auth or any BLACKBOX import. A source test checks that boundary.

The runner-created container has no IP networking, published port, secrets,
host volume or host socket, runs as UID/GID 10002, read-only, no-new-privileges,
all capabilities dropped except reviewed `SYS_CHROOT`, reviewed seccomp
profile, private cgroup/IPC namespaces, and the existing 768 MiB/1 CPU/128
PIDs/64 MiB shm/tmpfs caps from the browser Compose model. The ephemeral
container uses `docker run --rm` and a 60-second external timeout; any nonzero
result fails the PR validation. No additional production release step is
introduced, no remote host is contacted and no new deployment workflow exists.

## Proof boundaries and acceptance

- Local static tests: require exactly one PR-only smoke; verify Docker argv
  confinement and command, deny host/privileged execution, guarantee the
  helper contains no HTTP(S) URL or protected module reference and navigates
  only to `about:blank`.
- CI requires the actual disposable GitHub runner Docker container to return
  success; static tests and Docker image build do **not** substitute for that
  result. Diagnose any failed launch without weakening isolation, disabling
  Chromium sandbox or activating owner modules.
- The pinned `Dockerfile.browser` already installs
  `playwright install --with-deps chromium`; this change does not alter its
  image contents or the locked dependency graph.
- This proves **only** an isolated offline Chromium launch. It does not prove
  `ipc_worker.py` behavior, IPC health, the new worker running in the droplet,
  controller cutover, session persistence, Telegram, a public Boca workflow or
  real ticketing. Physical deployment remains NO_GO under #227/#323 until its
  independently governed cutover and selective cleanup complete.

Rule84 evidence: cite exact DRAFT PR SHA, CI run and technical review on
issue #227 after GitHub validation. Do not conflate PR runner with host proof.
