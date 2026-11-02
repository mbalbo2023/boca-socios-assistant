# ADR 0097: complete the protected browser IPC lifecycle

**Status:** code candidate for issues #250/#251 and PR #253, based on
`032de0ebb923b4f80154e93cee3dfd1b254687ed`. No application installation,
sender activation, passkey ceremony or restart on the droplet is established
by this change.

## Reproduced gaps

The owner enrollment workflow deliberately stops the prepared rootless daemon
after its bounded ceremony. The browser install path previously entered a
Docker preflight without starting that daemon. The standalone stop helper did
not recognize the new `browser-worker` service. The older acceptance and
Telegram contracts also assumed a single controller. Finally, acceptance
stopped the application and no protected operation could resume the existing
two-service topology without attempting a forbidden fresh installation.

The initial lifecycle regression produced two failures: a legitimate
controller/worker pair was rejected by stop-test, and the workflow had no
guarded start before browser preflight. This is a cross-module lifecycle
failure, not grounds to rerun first-time rootless preparation or relax host
isolation gates.

## Decision

Keep one serialized, manually dispatched workflow and the existing dedicated
rootless service. Add a current-main recheck immediately before a guarded
`start-existing` for new browser installation and explicit resume. This starts
only the previously prepared Boca daemon; it never installs or rewrites its
configuration. A failed or cancelled marked attempt requires bounded,
positive-identity stop and the already required selective cleanup.

The protected browser operations are explicit:

| Operation | Purpose and retained boundary |
| --- | --- |
| `beta-browser-install` | New-only reviewed pair; existing staging/cleanup contract remains mandatory. |
| `beta-browser-status` | Inspect the existing pair and optional sender without starting them. |
| `beta-browser-start` | Start the prepared daemon, then resume the same verified container IDs. |
| `beta-browser-restart` | Bounded stop/start of the same verified services; no pull, recreate, data initialization or key generation. |
| `beta-browser-acceptance` | Validate the installed topology and synthetic local journey, then stop known Boca services and daemon. |
| `beta-browser-telegram-start` | Explicitly create the optional verified sender after its recorded Bot API identity test. |
| `beta-browser-telegram-recover` | Clean only the exact failed run's sender and empty egress; never start applications or repeat a send. |

After acceptance, `beta-browser-start` is the separate explicit operation
that makes the private panel available again. `restart: no` remains intact;
there is no automatic restart loop or hidden deployment path. Physical Chrome
create/get, Google Password Manager custody and post-restart reuse remain
separate acceptance evidence.

All browser operations require exact current source, the two images from one
successful release, both manifests and the protected Boca/BETA/browser markers.
The helper resolves the original installation attempt from its private marker
and verifies the source, digests and all three staged file hashes. An `existing`
selector is not permission to ignore these coordinates. The listener remains
only `127.0.0.1:8443`, reached as `http://localhost:8443` through SSH; no HTTPS,
certificate, host proxy or other service changes are introduced.

## Complete inventory before stop

The standalone rootless helper remains usable through `python3 -` over SSH,
with no installed Python package requirement. It inventories the entire
dedicated daemon before the first stop. Presence of the browser worker, an
IPC attempt label, or the private installation marker selects the strict
browser topology for **every controller**, preventing a missing-label fallback
to the older singleton rule.

The new recognition binds exact image IDs/repo digests/revisions, service
names, user, command, attempt labels, namespace, fixed port, caps, seccomp,
resource limits, and the named volume set. The IPC worker receives only its
IPC volume; the controller mounts that volume read-only. The worker cannot
mount owner, key or application data. Private control
files use no-follow/nonblocking descriptor reads, owner/mode/link/size/hash
checks and inode revalidation. Unknown or replaced resources prevent every
stop. Stopped Docker port representations are accepted only when static
HostConfig still binds exactly the approved loopback port.

## Optional sender and explicit aggregate budget

The controller/browser pair retains `1.5cpu-1024m-192pids`. The sender adds
0.25 CPU, 128 MiB and 32 PIDs; its aggregate option is therefore explicitly
`1.75cpu-1152m-224pids`. A sender-enabled lifecycle cannot present the smaller
budget. The host retains its capacity/reserve checks and the sender's own
fixed limits. These values do not claim that the shared droplet has capacity.

The sender requires protected owner readiness and exact bot/chat assertions;
its seven-element command binds the same source and owner assertions used by
the one-shot API test. It has only the data and dedicated Telegram volumes,
no published port and the specific Telegram egress bridge. The private
credentials never become workflow inputs or log output. Worker readiness
does not itself prove a notification was received by the owner.

Before a sender attempt, a read-only phase proves sender and egress absent.
Only after this positive receipt and another main recheck is its attempt
marked. The sender and its new bridge carry both the original browser
installation label and a separate `telegram-runtime-attempt` for the current
GitHub run. Failure/cancellation invokes immediate bounded cleanup for that
attempt before stop-test. It removes only the verified new sender and empty
bridge, preserving all volumes and the installed controller/browser. Unknown
identity, SSH loss or uncertain cleanup is NO_GO INDETERMINADO with no retry.

Once SSH returns, recovery requires the explicit `failed_telegram_run_id` and
the same source, image, owner and resource coordinates. GitHub must prove a
completed failed/cancelled/timed-out first workflow attempt on this repository,
main and owner, including the successful sender-attempt marker. The standalone
`inspect-existing` phase only reads the prepared daemon boundary. An inactive
daemon requires another main recheck and the existing guarded daemon start;
no application start is invoked. Cleanup binds the old runtime label before
any removal and stop-test follows even when cleanup fails. A new run ID never
implicitly claims the old attempt's resources. Retrying the failed run remains
forbidden.

Freeze main throughout release, owner enrollment, installation, Telegram and
any recovery: each operation binds the exact same current SHA and staged
artifacts. Merge documentation before release; record operational evidence in
checkpoint #45 without advancing main during activation. If main has advanced
after an uncertain failure, the current-main gate deliberately blocks this
recovery path. A separately reviewed recovery change is then required; never
substitute a newer SHA or relax the old attempt's identity.

Runner receipt validation accepts exactly two lines for acceptance (the
bounded synthetic measurements plus the lifecycle identity) and exactly two
for sender cleanup (storage before/after plus identity/preservation). Other
lifecycle phases retain their single-line contract. Extra, missing, unrelated
or stale receipt fields are rejected; fixed diagnostic output is not mistaken
for a failed operation.

## Validation limits

Tests execute the real workflow's shell gate with synthetic coordinates and
mock host commands. They cover stale main ordering, two/three-service budgets,
worker identity mutations, controller label fallback, marker/file changes,
FIFO/symlink/hardlink refusal, stopped ports, cancellation cleanup conditions
and the pinned sender command. This is not host evidence. Local Unix-socket
integration tests may be blocked by the executor sandbox; exact-candidate
hosted CI must run them successfully before merge. The source/review and
operational receipts remain recorded separately in checkpoint #45.

The disposable hosted Docker smoke additionally creates the real pair from
the Compose files, validates running and stopped inspections against both
production helpers, and repeats the synthetic IPC journey after restarting
the same IDs. Kernel UID/cgroup/seccomp observations are real. Local images
have no published RepoDigest; a test-only in-memory adapter supplies only that
reference metadata, explicitly without claiming registry or release proof.
The sender runs only in `network=none` with an invented custody and acceptance
ledger. Its production network configuration is created and inspected stopped,
never started. This does not establish a real Bot API acceptance or delivery.
No success is recorded until that hosted smoke actually runs.

The first real pair smoke, run `41483687457`, reached healthy controller and
worker but failed their strict Docker inspection. Bounded diagnostic run
`41485137010` established the exact cause: Compose reports the sole allowed
capability as `["CAP_SYS_CHROOT"]`; the fixture-derived predicate expected
`["SYS_CHROOT"]`. All other worker boundary fields matched. Both runs completed
their selective runner cleanup; the sender test was skipped and is not PASS.
The production and standalone stop predicates now accept only those two
single-item representations of the same capability. Extra, duplicate, mixed,
lowercase or different capabilities remain forbidden. The diagnostic keeps
real observations intact and never serializes credential values, raw commands,
labels or mounts. This is a representation/coverage defect, not permission
to relax seccomp, resource, mount, namespace or network controls.
