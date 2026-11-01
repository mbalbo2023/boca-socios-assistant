# ADR 0087: protected check of Boca's host-loopback 8443

**Status:** accepted on integration of issue #211. No host port observation is
implied by the code or its runner tests; the protected manual operation needs
its own exact-main Actions receipt.

## Decision and scope

The owner chose the already defined private panel port 8443, not a new host
port. `compose.beta.yaml` publishes only `127.0.0.1:8443:8443/tcp`; this
configuration is not proof that the port is free on the droplet or reachable
from a tablet. The preexisting rootless daemon's last observed state was
`ALREADY_STOPPED` in run 41282301501, not a current network inventory.

Add a `port-check` choice to the existing `boca-first-deploy` manual workflow,
using its owner, first-attempt, exact-current-main, protected environment,
pinned SSH, service, budget and Boca-only concurrency gates. The read-only
readiness marker suffices; image, release and envelopes must be blank. The
host helper requires the dedicated `boca-deploy` UID before opening a socket.
It makes one IPv4 TCP socket, binds only `127.0.0.1:8443` without listening,
connecting, reusing the address or enumerating host processes, then closes it.
The allowlisted receipt is `FREE`, `BUSY` or `ERROR` with `reserved=no`;
the latter two fail the Action without revealing a service identity, exception
detail or other port. No Docker daemon, Boca application, SQLite, key, volume,
Site, Telegram or unrelated workload is started, read or modified.

The same helper is called after the exact-main recheck and immediately before
the `beta-install` app/key effects. The port remains unreserved, so a FREE
receipt is only an observation at that instant. It cannot replace the later
Docker publish, loopback TLS/health and tablet acceptance gates; a race or
network namespace mismatch remains possible and must fail closed at install.
An SSH forward on a tablet needs its own stable trusted HTTPS origin and owner
identity decision (#209). The manual workflow itself explicitly clears SSH
forwarding and does not create a tablet tunnel.

## Verification and limitations

Focused tests assert fixed IPv4 address, UID before socket, no Docker,
listener or connection, close on every path, redacted busy/error, blank image
contract and workflow ordering/gate. PR/CI/checkpoint record exact candidate
and result after review. A disposable runner test has no authority over the
droplet port; only an actual protected `port-check` dispatch can observe it.
No real Boca login, queue, reservation or purchase is enabled.
