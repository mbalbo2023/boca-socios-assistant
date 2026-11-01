# ADR 0048: distinguish rootless socket absence from service state

**Status:** Proposed for issue #131, 2026-10-31. No host operation from this PR.

Run #70 reached the reviewed helper as UID10001 and found the private runtime,
user-manager and D-Bus sockets, but not the dedicated Docker socket. That is
not evidence that Docker is uninstalled. It also cannot establish whether a
Boca SQLite file exists in a Docker volume.

Keep inspect-prerequisites read-only and add a separate redacted receipt.
After dedicated identity validation, inspect executable availability for the
Docker client, daemon, rootless wrapper and setup tool in fixed system paths
and the dedicated user's bin directory. Never execute those programs. Report
not_found_in_search_path rather than claiming they are uninstalled.

Only after safe private-runtime and owned user-manager/D-Bus metadata, query
the dedicated user's docker.service through /usr/bin/systemctl --user show.
Pin XDG_RUNTIME_DIR and DBUS_SESSION_BUS_ADDRESS to UID10001 and use a minimal
environment, fixed four properties, no shell, no pager and a five-second
timeout. Read no journal, environment, unit file, command line or other unit.
Accept only exact property keys and allowlisted state values within 1024
characters; malformed, unknown, duplicate or failed output becomes unavailable.
Do not emit stderr or raw output. The receipt distinguishes unit not-found,
inactive, failed and active/running without inferring a recovery action.

Preserve the existing BOCA_HOST_INSPECT receipt and metadata-candidate gate.
The new service receipt neither relaxes the rootless socket requirement nor
proves Docker health, isolation, capacity, data presence or deploy readiness.
No install, start/restart, enable, setup, Docker command, backup or data access
is added. A new exact-SHA Actions inspection after merge supplies actual
evidence; this PR's tests are synthetic and cannot diagnose the host.

Primary references: [Docker rootless setup](https://docs.docker.com/engine/security/rootless/)
and [systemctl show](https://www.freedesktop.org/software/systemd/man/latest/systemctl.html).
