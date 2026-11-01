# ADR 0081: protected synthetic BETA acceptance and Boca stop

**Status:** candidate in issue #193, based on main
`2768d23dd2e9e58563a13aa80d8b76885448d020` after the BETA install,
Telegram stop-helper and Site custody fixes. The disposable TLS probe is
integrated by PR #190. Local frozen Ruff, format, mypy and policy gates passed;
pytest passed 879 tests and 29 subtests on the local candidate. Hosted checks,
exact technical review, release and host execution remain separate evidence.
No protected BETA image release or installation was observed. This is a code
candidate, not a deployed operation. Authorization is the simulation BETA
scope in issue #45.

## Decision and sequence

Add `beta-acceptance` to the **existing** protected Boca manual workflow only
after the new-only `beta-install` gate integrates, but before the first BETA
release and installation. The release, install, acceptance and stop use one
current-main source SHA and matching immutable GHCR digest. The acceptance
operation is not an upgrade or a way to run a new source script against an old
image. If main advances after install, these exact-source gates fail closed;
recovery needs a separate reviewed plan, not a silently weakened comparison.

The workflow keeps the first-attempt, repository/owner actor, protected
environment, BETA marker, service/controller, fixed 0.5 CPU/256 MiB/64 PID
budget, empty Site envelope, pinned SSH identity, current-main rechecks and
verified release run/manifest/digest gates. It hashes the reviewed
`compose.beta.yaml`, validates the runner model, then checks the staged host
file hash and Compose syntax plus the actual container postflight. No PR or
push event reaches the host. The existing workflow mutex serializes the
install, acceptance and stop operations.

The host helper checks the dedicated UID10001 rootless daemon and capacity,
exactly one installed Boca controller, exact named Boca volumes and the full
network ID matched to the inspected network, staged
Compose hash, actual container image/revision, health, command and engine-off
settings, three mount destinations/read-write modes, no unexpected peers,
host-loopback-only port, cgroup/capability/read-only limits and TLS health
using the public CA. It does not read the owner passkey private material, key
or application database. It invokes the reviewed `host_probe` module only by
`docker exec --user 10001:10001` against the positively identified container
ID and accepts one strictly bounded `BOCA_SYNTHETIC_ACCEPTANCE state=PASS`
receipt. Execution and output are bounded; failure output is redacted. It
checks the same host identity, health and capacity again after the probe.
The installed controller has already consumed part of the preinstall host
reserve, so acceptance requires at least 512 MiB available memory and 0.25
approximate CPU headroom, plus 4 GiB and 50,000 free inodes on both Boca
staging and rootless Docker storage. The actual 0.5 CPU/256 MiB/64 PID cgroup
limits are checked separately. These are conservative host gates, not a
tablet performance claim or Chromium capacity estimate.

The probe uses a new temporary SQLite/key/passkey/certificate under the
container `/tmp` and HTTPS container loopback. Its request count, median/p95,
elapsed time, process CPU/RSS, temporary bytes and one synthetic
member/intent/notice are evidence of that disposable journey only. The
installed owner session, data and private tablet path remain untested by it.
The receipt cannot establish real Boca access, reservations or purchases,
Site connectivity or Telegram delivery.

After the test attempt, a final step uses the existing `stop-test` helper to
inventory the dedicated Boca-only daemon and stop only positively identified
Boca containers, then verify its daemon is stopped. The workflow must require
both acceptance PASS and a bounded `BOCA_STOP_TEST state=STOPPED` receipt for
green; failure or uncertain inventory is NO-GO and never authorizes a broad
cleanup. The key, data, owner volumes and staged file remain intact. A stop
failure leaves the state explicitly unverified and requires Boca-only review;
there is no automatic retry or host-wide prune. The precise final-step
ordering will be verified in workflow tests and review before dispatch.
The final step is armed only after protected identity, release, current-main
and SSH gates mark an accepted host attempt. It rechecks main before stopping;
if main advances during the probe, that drift is recorded as NO-GO while the
previously authorized Boca-only positive-identity stop still runs. Main drift
cannot authorize another probe, install or Site effect, and a verified stop
does not turn the drifted acceptance green.

## Evidence required before claiming operational BETA

Offline tests cover gate inputs, exact digest/release/main, staged Compose,
positive and negative container inventory, cgroups/network/mounts/TLS,
malformed/oversize/ambiguous receipts, timeout, postflight drift and stop
failure. PR runtime smoke invokes the same disposable probe inside the actual
runner controller under 0.5 CPU/256 MiB/16 MiB tmpfs, with a strictly parsed
receipt before Boca-only runner cleanup. That synthetic runner check is not a
droplet measurement or proof of owner access. Frozen lint, format, mypy, full
pytest, isolation policy, exact-SHA
Actions and technical review precede merge. A host run must record the
source SHA/digest, acceptance metrics, capacity and verified stop receipt.
Physical owner passkey/private tablet access, Site HMAC bridge and Telegram
receipt have separate gates. Until the release, owner/TLS material, markers,
host install, acceptance and stop receipts exist, this operation is **NO-GO**
for a claim of deployed functional BETA. Rule 84 central status and issue #45
are reconciled by their assigned writers after integration and host evidence.
