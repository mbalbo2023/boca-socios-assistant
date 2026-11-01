# ADR 0075: protected served BETA install gate

**Status:** candidate in issue #182. No protected image release or host install has
run from this change. On main `64746289363741c4d85df79fa4e133b07f261efa`,
local `uv run pytest -q` passed 841 tests and 29 subtests; Ruff, mypy,
repository policy and diff checks passed. Exact candidate SHA, hosted checks
and technical review must be appended after the final branch is tested; a
green PR is not host proof.

## Scope and decision

The existing `boca-first-deploy` manual workflow gains `beta-install` for the
separate `compose.beta.yaml` controller. Its protected environment requires
the existing deploy marker and a distinct `BOCA_BETA_ENV_READY=ready` marker;
neither a Site ciphertext envelope nor an arbitrary image tag is accepted.
Private `BOCA_BETA_PANEL_ORIGIN` and `BOCA_BETA_OWNER_SUBJECT` environment
secrets supply the exact model coordinates. The operation retains the fixed
repository/actor/main/attempt-one checks, serialized workflow, pinned host
key, UID 10001, rootless Docker and 0.5 CPU/256 MiB/64 PID budget. It
verifies a successful matching protected release run, source SHA, manifest and
immutable GHCR digest before SSH. The runner hashes and validates the BETA
Compose model; the host validates the staged hash and resolved model. Main is
rechecked before staging and immediately before key/data/application effects.

Host preflight measures delegated cgroups, memory, CPU headroom, both staging
and rootless Docker disk/inodes, an empty **full dedicated rootless daemon
container inventory**, and an empty Boca app container/network namespace.
After startup it requires exactly the proven controller in that daemon. It
allows **only the existing exact Boca owner volume**, proving
local driver/labels/mountpoint and no attached container. It refuses existing
key/data volumes or a staged app: this is new-only installation, not a
migration or replacement. The owner volume must already contain the real
owner's passkey public ID/P-256 key, private TLS key/cert and health CA under
the reviewed UID/mode custody. This operation does not enroll an owner or
install credentials. The streamed host helper pulls the digest and checks its
revision before image-side no-listener `check-beta-owner` with owner read-only,
UID 10001, network none, no key/data mounts. Only its fixed readiness receipt
allows the Boca key volume to be created and initialized. `check-beta-config`
then reads owner and key read-only with no data mount, listener or network.
Only its fixed receipt allows the new data volume and new-only `init-beta`
one-shot container. Failure at any point preserves all named volumes.

The isolated controller runs simulation with engine off, no Site bridge and no
Telegram worker. Compose publishes **only host 127.0.0.1:8443**, while its
container binds 0.0.0.0:8443 on Boca's bridge. Postflight reads the actual
container ID, image/revision, UID, labels, three mounts, private network
identity/sole peer, cgroup limits, capabilities, read-only root, command,
restart policy, health and HostConfig/NetworkSettings port maps. A host
loopback HTTPS request uses the owner volume's **public** CA through the
container, exact hostname verification/SNI and origin Host header, requiring
HTTP 200 with the exact `BOCA_BETA_READY` body. This proves a local package
socket; it does not prove tablet access, multi-client performance or live Site
operation. The selected private tablet route remains a separate reviewed gate.

On failure after the stage attempt, a final workflow step requires the full
daemon inventory to match the Boca labeled/name inventory, and uses the same
rootless identity to stop only one controller whose Boca project/service/name,
UID, image and source revision are proven. The bounded receipt states STOPPED,
ALREADY_STOPPED or NO_CONTROLLER and current Boca staging/Docker free space
and inodes. Any uncertain inventory or failed stop is NO_GO, preserving the
original failure. Stage/data/key/owner volumes remain for Boca-only recovery;
there is no prune, down or volume deletion. The existing protected `stop-test`
is the separate after-tests stop contract for the current controller-only
inventory. Enabling Telegram or the Site bridge requires a distinct reviewed
stop/lifecycle change before activation.

## Verification and operating gate

Tests cover origin/owner rejection before host probing, owner-only inventory,
no-network image preflight argv, key/data ordering on failed owner/full checks,
actual host port-map rejection for wildcard or IPv6 publishes, full daemon
inventory rejection of unrelated containers, positive
rollback identity, and refusal to stop ambiguous containers. Existing
disposable Compose smoke now exercises the **actual image** owner-only and
full no-listener preflights, followed by synthetic new-only DB, TLS health and
loopback on a runner with a synthetic FQDN and private owner directory mode.
These checks use no real Boca credentials or purchases.

At this candidate stage the protected image release environment lacks
`BOCA_RELEASE_ENV_READY`; no approved release digest exists. The BETA marker,
private owner/TLS files and tablet access designation have not been observed
ready. Protected stop-test run 41272785626 succeeded earlier; its
`containers=0` counts running containers stopped by that run, not all exited
container records. The separate Site custody phases inherited an earlier
Boca-scoped container check; they remain NO-GO for host dispatch until a
separate globally inventoried rootless-daemon gate is reviewed. **Host
`beta-install` remains NO-GO.** No host operation is
dispatched by this PR. The integration owner reconciles README, plan, roadmap,
status and issue #45 after exact review and any later host evidence under
Rule 84.
