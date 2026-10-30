# ADR 0037: inspect Boca host prerequisites under the dedicated UID

**Status:** Proposed for issue #90, 2026-10-29. No host inspection dispatched.

## Incident

The Termius bootstrap checks in #45 ran as session UID 1000 and tested sockets
inside `/run/user/10001`, owned by UID 10001 and mode 0700. A failed `test -S`
could mean access denied, not absence. The user manager was restarted once on
the strength of that false negative. The subsequent blocks stopped before
setting up rootless Docker. Actual socket state remains unverified.

## Decision

Add `inspect-prerequisites` to the existing manual Boca workflow. It uses
the same pinned SSH identity, protected environment, main SHA, owner and
serialized job. It accepts blank image and release-run inputs and invokes
only the standard-library host helper under `boca-deploy`. That helper checks
its effective UID/name **before** reading the private runtime directory. It
classifies the directory, user-manager socket, D-Bus socket, dedicated Docker
socket, conventional rootful socket access and delegated cgroup controllers.
An inaccessible socket is reported `unavailable`, never `absent`. Output is
bounded metadata without host address, credentials, names of other workloads
or member data. Missing or unsafe prerequisites produce a failed job with a
classification; present metadata is only `METADATA_CANDIDATE`.

No Docker command, package installation, systemd start/restart, container,
third-party request or host write is part of this operation. The existing
`preflight` remains a separate strict check of daemon rootless mode, cgroup
driver, capacity and empty Boca namespace. It is not weakened to let a
prerequisite inspection pass. The workflow is unavailable from PRs and has
not entered `main`; its first host dispatch needs exact-SHA CI and a configured
main-only environment with pinned SSH identity. Actions cannot grant host root
privileges to the dedicated Boca SSH account.

## Security review correction before integration

The manual job now rejects a rerun (`GITHUB_RUN_ATTEMPT` must be 1) so that
an earlier failed operation cannot be retried with the original actor and
commit context. GitHub's dispatch SHA is captured when the run starts; it
is not proof that `main` is still at that SHA when a queued job executes.
Before configuring SSH, the job reads the current `main` ref through the
read-only GitHub API and requires the exact dispatch SHA. `first-install`
rechecks that ref immediately before the effectful apply phase. API failure,
malformed evidence or a moved ref is NO-GO. The host helper checks both real
and effective UID 10001 and the `boca-deploy` account before any socket or
Docker probe. This avoids a setuid process passing a real-UID-only check
while a subprocess has elevated access. The parent directory of the rootless
socket remains required to be owned by UID 10001 and mode 0700; socket mode
alone is not used as an unsupported claim about other users' access.
