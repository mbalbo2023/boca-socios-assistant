# ADR 0090: immediate and bounded BETA deploy failure cleanup

**Status:** code integrated by PR #220 / #219 in main commit
`0c2646a4eb91520498f5284783d1572c7fde9761` after technical review and
four successful PR workflows, 2026-11-01 ART. No host cleanup, BETA
install or Docker operation was dispatched from this work.

## RCA and decision

The existing protected `beta-install` failure step calls `beta-rollback` to
stop its positively identified controller. Unlike `first-install` (#97,
ADR 0039), it then retains the staged Compose file, stopped container, private
network and pulled image even if they are disposable. The next new-only BETA
preflight refuses that existing namespace. This is a delivery-recovery gap,
not evidence that a host deploy failed; the BETA has never been installed.

Keep one manual protected Boca workflow and add a **same-job failure hook**
immediately after bounded controller stop. It runs only for `beta-install`,
only after the protected preflight/main recheck and positive staging marker,
with the same immutable image digest, source SHA and Compose hash. No push,
pull request, source failure or diagnostic starts host cleanup. The original
deploy remains failed, and no automatic retry follows.

Reuse the standalone standard-library cleanup helper and its UID10001,
dedicated rootless Docker socket, checked storage backend/path, no rootful
access, exact image revision and before/after free-byte/inode measurements.
The BETA branch additionally requires an exact private regular
`compose.beta.yaml` file or its absence; no other files in the staging
directory; a single exact Boca controller or none in the **entire** dedicated
daemon; validated Compose labels, image/source, UID, three expected
persistent volume mounts and private network; only the expected owner/key/data
volume names; and an exact Boca bridge network with no foreign attachments.

Only after checking this complete boundary may the hook stop an exact running
controller, verify its stopped state, remove that container **without**
`--volumes` or `--force`, remove the now-unused exact private network, remove
an untagged/unshared exact digest image without pruning, and unlink the exact
staged Compose file after a second hash check. It verifies their absence and
the unchanged persistent-volume inventory afterward. It never removes
`boca-socios_boca_owner`, `boca-socios_boca_key`,
`boca-socios_boca_data`, their contents, another image, a foreign workload,
host-level resources or an unknown artifact. A preserved data/key volume is
**intentional state**, not garbage; further recovery requires its own review.

The sanitized receipt reports `CLEANED` or `ALREADY_CLEAN`, per-artifact
removed/absent fields, `volumes=preserved`, logical image size, filesystem
comparison and free bytes/inodes before and after. It does not promise that
free-space deltas were caused by a specific deletion. A rejection before any
mutation is NO_GO; if a mutation may have started and a later step fails, the
only outcome is `NO_GO INDETERMINADO`. Remote stdout/stderr is discarded
unless one small allowlisted receipt matches exactly. Either outcome leaves
the original deploy red and blocks retries pending a new Boca-only inventory.

## Limits and verification

GitHub Actions process cancellation, runner termination, SSH outage or
unreachable rootless daemon can prevent the post-failure hook from completing.
Therefore no system can honestly guarantee **zero** remains after every
possible failure. The selected response is immediate best-effort safe cleanup,
an explicit uncertain-state receipt and no blind retry. It does not add a
second deploy workflow, host cron, broad `docker prune`, volume removal,
backup, unrelated service operation or new security identity.

The tests introduced before implementation failed on the missing BETA cleanup
function and workflow hook. Offline regressions exercise exact and foreign
container identities, running/stopped controller, persistent mounts, network
peers, untrusted Compose/symlink, partial failures, volume preservation,
idempotence, CLI selection, workflow ordering and redacted SSH receipts. Local
results and exact hosted Actions/review evidence belong in PR #220 and the
Rule 84 checkpoint; these tests are not evidence of droplet cleanup.
