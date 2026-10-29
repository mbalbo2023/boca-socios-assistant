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
not entered `main`; its first host dispatch needs reviewed code, protected
environment and a distinct owner decision. Actions cannot grant host root
privileges to the dedicated Boca SSH account.
