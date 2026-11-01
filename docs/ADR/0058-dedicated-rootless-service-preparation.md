# ADR 0058: prepare only the dedicated Boca rootless user service

**Status:** Proposed implementation for issue #145. 2026-10-31 ART.
The owner approved beginning the recommended plan in issue #45 and delegated
the storage-location choice. This PR prepares the mechanism; no host dispatch,
Docker installation, application release or first installation has occurred.

## Decision and storage

Keep `/data/boca.sqlite3` in Compose volume `boca_data`, physically named
`boca-socios_boca_data`, with the separate `boca-socios_boca_key` key volume.
This selects the future application mount. It neither locates an existing
database nor creates, opens, migrates or replaces one. The latest inspected
candidate locations were absent only within ADR0054's fixed-path scope;
global location remains UNVERIFIED. Any positively identified existing data
requires a separate compatibility/reuse decision, never automatic replacement.

Prepare a dedicated Docker user service using already available system
binaries and the reviewed existing wrapper. Keep the default dedicated data
root at `<boca-home>/.local/share/docker`, consistent with the candidate path
already documented. A missing or empty directory can be used; a nonempty or
inaccessible data root is retained and blocks this first-time procedure.
An existing user unit, drop-in, enablement link or daemon configuration is
also retained. A separate SQLite file in staging is not a reason to reject
an independent daemon setup; this helper never opens or inventories staging.

## Exact Actions sequence

Add `prepare-rootless` to the existing manual Boca workflow. Use the existing
`BOCA_DEPLOY_ENV_READY=ready` mutation gate, blank image/release inputs, fixed
controller/budget coordinates, owner/main restriction and existing host mutex.
No new readiness variable or parallel host-operation channel is introduced.
After pinned SSH and current-main validation, run helper `check`; recheck
current main immediately before helper `apply`. Apply repeats prerequisite
checks. Root coordinates the one authorized host dispatch after exact-SHA
review/CI and confirmation of the concrete plan and diff.

Check validates UID/eUID/GIDs/name; private home/runtime, owned user sockets
and no write access to the conventional rootful socket; cpu/memory/pids
delegation; existing root-owned, non-writable executable metadata; dedicated
subuid/subgid ranges; user namespaces; and the dedicated account's linger.
No other account or service is queried. The two subordinate-ID allocation
files are bounded public system metadata, not application data: only matching
Boca rows are parsed and no file contents or other account names are emitted.
Their final entries must be nonfollowing regular root-owned files, not writable
by other users. `/etc` and kernel pseudo-filesystem ancestors are trusted OS
paths; the full descriptor traversal protections below apply to Boca paths.

There is no `kernel.unprivileged_userns_clone` requirement: its absence is
valid on some kernels. The decisive namespace smoke runs in apply, before
persistent configuration writes, as fixed `rootlesskit --net=none /usr/bin/true`.
It creates a transient namespace/process and RootlessKit temporary state,
then exits; it is not a metadata-only probe. It is never bypassed by `--force`.
Failure is reported without changing host kernel/AppArmor policy or packages.

Capacity receipts before/after report free bytes/inodes on the actual existing
ancestor of the dedicated data root. They are informative. Application
768-MiB/4-GiB/50,000-inode/load gates are not copied onto daemon preparation;
the existing predeploy capacity contract remains separate. Allocation failure
is NO_GO and may leave only the explicitly reported partial Boca files.

## Effectful scope and safety

All Boca directory components are opened relative to directory descriptors,
with no symlink following and owner/mode checks. Create missing private
directories with mode 0700. Create daemon.json and docker.service exclusively
with O_EXCL/O_NOFOLLOW and mode 0600, then sync. No file is overwritten.
The daemon configuration pins the private Unix socket, execution state and
data root. Classic overlay2 with the containerd snapshotter disabled matches
the existing storage/capacity verifier; the installed dockerd must first
accept this exact configuration through `--validate`, without starting a daemon.
Unsupported installed versions fail closed; no package is upgraded.

The fixed user unit launches the existing wrapper through `/usr/bin/env -i`
with only dedicated identity/home/runtime/bus and trusted system PATH. No CLI
context is created or selected. It uses Delegate=yes, KillMode=mixed and
Restart=no. It orders after the existing user D-Bus socket but does not request
activation of another unit. Reload only the dedicated user's manager, then
verify the effective fragment and empty DropInPaths before starting only its
docker.service. This avoids inheriting unexpected system/user overrides.

Wait a bounded 15 seconds for the dedicated socket. Require active/running
user service and Docker info on the explicit private endpoint: rootless mode,
cgroup v2/systemd, classic overlay2, exact private data root and zero containers.
Require an empty Boca volume/network namespace without accessing the shared
daemon. This does not prove container limits; a later authorized isolated
application installation still needs its effective cgroup/mount/health checks.
After postflight passes, create only the exclusive user enablement symlink.
The already-enabled linger prerequisite allows the user manager to survive
SSH logout and start this enabled service on a future boot.

The rootless daemon necessarily creates its own Docker bookkeeping under its
private data root. It does not create Boca's SQLite or key/data volumes, pull
an image, run a container, start application code or generate a key. No global
systemd operation, sudo, package install, rootful Docker, host network/policy
change, backup or unrelated project operation is included.

## Failure and evidence

Preflight failure has no persistent setup effect. A failure after configuration
creation preserves configuration and all data and is reported as partial/
unverified. If start was attempted, stop only this newly created user service;
failure to stop has a separate UNVERIFIED receipt. Do not delete or recreate
data to make a retry pass. If enablement creation/sync fails or the process
crashes after it, the link may remain: enablement is partial/unverified even
if the stop succeeds. Inspect that exact Boca state before any retry/reboot.

The service-ready receipt certifies only this daemon boundary. It does not
authorize image release/install, certify application capacity or assert DB
existence. Fixed commands have timeouts; stdout is captured then rejected
above 64 KiB, so this is a receipt-size cap, not a streaming RAM bound. Errors
and logs never expose raw command output, paths, credentials or member data.

If linger, UID mapping, trusted binaries or host policy require administrator
privileges, report the concrete prerequisite and stop. Alternatives are an
explicitly scoped host-operator repair for the dedicated account or a separately
approved dedicated host. Never substitute the shared Docker daemon or add sudo.

Primary references: [Docker rootless setup](https://docs.docker.com/engine/security/rootless/),
[rootless daemon lifecycle](https://docs.docker.com/engine/security/rootless/tips/),
[Moby setup tool](https://github.com/moby/moby/blob/master/contrib/dockerd-rootless-setuptool.sh),
[dockerd configuration validation](https://docs.docker.com/reference/cli/dockerd/).
The upstream setup tool also enables a service and changes CLI contexts;
its force mode can ignore a failed RootlessKit smoke. Those broader effects
are deliberately not invoked by this bounded preparation.
