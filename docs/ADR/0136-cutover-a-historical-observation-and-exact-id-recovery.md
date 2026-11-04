# ADR 0136 — Cutover A: historical observation and exact-ID compensation (code-only)

Date: 2026-11-04 (ART)  
Status: **DRAFT / physical NO_GO**  
Scope: `#227`, existing BETA singleton to future browser IPC candidate; supplements ADR 0130.

## Decision and owner instructions

The deployed, working 127.0.0.1:8443 controller remains **RUNNING**. Tincho has
already authenticated in Samsung Chrome via the Termius tunnel. In response to
his current priorities, independent fronts may evolve Telegram, global
simulation-only controls and official event sources. The current permission
does **not** authorize real Boca login/queue/booking/purchasing, multi-session,
key rotation, deletion or backup. No Porota, other droplet service, host port,
web server or container may be modified.

**One new protected workflow operation, `cutover-a-observe`, is read-only.** Its
GH Actions job authenticates two distinct image/release histories:

1. `source_sha`, `image_ref`, `browser_image_ref`, `release_run_id` must match
   **current main** and one controller + browser release manifest pair from the
   **same target release run**. The browser digest alone is not authorization.
2. `legacy_source_sha`, `legacy_image_ref`, `legacy_release_run_id` must match
   an **independent older, successful controller release manifest**, plus the
   exact historical `compose.beta.yaml` SHA from GitHub at that legacy commit.
3. `legacy_controller_id` is an optional previously observed 64-hex ID. When
   supplied, the host must match exactly. When omitted, the read-only receipt
   reports the actual ID for a subsequent reviewed handoff; no ID is guessed.
4. The dedicated rootless host must independently prove one running legacy
   controller, pinned OCI revision/digest, healthy HTTP localhost listener,
   user/cgroup/mounts, exact owner/key/data volumes, private network, no
   worker, and no changed staging files.
5. The host receipt is strictly bounded and parsed on the runner. It claims
   `original=RUNNING worker=absent effects=none`. Nothing stops, pulls,
   creates, renames, stages, removes or restarts any host resource.

Current canonical evidence before physical observation: issue #45 comment
`6640165355` reports original source
`cabce9f1e452e63ded115f447559a358dc0f4d1b`, image digest
`ghcr.io/mbalbo2023/boca-socios-assistant@sha256:cf6e4266cfcfea0c07fa31301d59c7aaa3b9c2fefb9f6843baddd208cacd3b59`,
install run `41896871289`, acceptance `41897278258`, start `41897569928`,
and controller RUNNING. This ADR does **not** claim that the new operation was
dispatched or that a host observation was obtained.

## Future cutover algorithm (NOT enabled)

The host helper now has standalone **unreachable-from-workflow** primitives
for worker and candidate `docker create` argv plus `_cutover_park_original`
and `_cutover_restore_original`. Unit tests fake Docker, not the droplet.
No `docker compose up` is permitted while the original controller exists:
Compose can reconcile an existing service with the same project/service label
and inadvertently replace it.

| Stage | Future invariant (requires additional code, runner simulation and explicit GO) |
| --- | --- |
| Observe | Independently authenticating original exact ID, historical image/release, data/key/owner, localhost, rootless daemon. |
| Worker ready | Stage exact target Compose overlay/seccomp without overwriting legacy base; pull target images; provision only attempt-labeled IPC; `docker create` worker with `network=none`, no ports, no restart; `docker start` exact ID; verify healthy cgroup/seccomp/UID and strictly synthetic IPC. Legacy continues serving Chrome. |
| Park legacy | Verify worker + original IDs, stop original exact ID; re-inspect; rename exact original to `boca-socios-controller-legacy-<run>`, keep stopped for recovery; ensure localhost port free. Candidate has not been created. |
| Candidate healthy | `docker create` candidate under exact original name, 127.0.0.1:8443, no restart, reviewed volume mounts and IPC RO; start exact ID; verify health and synthetic acceptance; preserve old ID stopped. |
| Accept or recover | Only after positive acceptance retire exact parked original; on any earlier failure stop/remove **only** target attempt resources, rename back the exact original ID and restart; no volume/key/owner removal. If recovery is uncertain: NO_GO INDETERMINADO and no automatic retry. |

The park primitive has tested compensation for (a) `docker rename` fails before
any name change; (b) rename succeeds but a later check fails; (c) recovery
itself fails, which is reported as indeterminate. It never acts by a mutable
Compose service name. Candidate/worker builders specify `--restart no` and a
single reviewed Boca service/volume namespace.

## Open physical NO_GO gates (do not mark done)

1. **Legacy staging conflict.** `browser-stage` and
   `host_browser_file_stage.py` explicitly require an empty new-only
   `/srv/boca-socios`; the installed singleton has `compose.beta.yaml`.
   Implement a separate atomic staging + attempt marker for in-place cutover
   that records original inode/hash, supports interrupted transfer/recovery,
   and never overwrites active original files before the authorized park.
2. **No live execution path.** `cutover-a-observe` is intentionally the sole
   new dispatch option. A reviewed protected `cutover-a-apply` with complete
   worker start, candidate inspection, positive-ID compensating cleanup and
   postflight has **not** been implemented or enabled.
3. **Compose-created vs `docker create` identity.** Exercise both services
   on disposable Actions runner: `docker compose ps -q` must select only the
   exact candidate/worker after original retirement. During the bounded
   transition two objects may have `service=controller`, so service lookup
   alone is forbidden. Inspect exact healthcheck, effective seccomp and all
   labels. Fake-Docker unit tests do not prove this compatibility.
4. **Legacy restart policy.** The installed original has `unless-stopped`,
   while the candidate must use `no`. A daemon restart mid-cutover could
   revive the parked original and collide with localhost:8443. Design and
   verify a temporary exact-ID `docker update --restart=no` under transition
   ownership, restoring `unless-stopped` on original recovery. No change to
   original policy is made by this PR.
5. **No installed browser image/worker receipt.** The historical browser
   image digest was published, not deployed. The next target main SHA and
   paired release manifests must exist after reviewed PR integration; a
   draft SHA and unrelated old release run cannot authorize a cutover.
6. **No physical recovery evidence.** Before a future GO, runner simulations
   need stop→rename failure, candidate start and health failure, SSH timeout,
   rootless daemon restart and strict selective-cleanup postconditions. The
   exact original controller must return healthy on localhost after failure;
   unknown state demands manual Boca-only read-only diagnosis, no blind retry.
7. **Resource and leakage checks.** A prepared worker needs 768 MiB/1 CPU/
   128 PIDs and zero IP egress; candidate 256 MiB/0.5 CPU/64 PIDs. Only
   postdeploy measurements can establish host headroom, but cgroups and
   exclusive namespace are hard invariants. Never touch Porota or other
   services. Only delete an exact attempt-created, positively labeled
   container/IPC volume; no generalized `docker prune`, backup or rollback
   of persistent data.

## Reproducible code-only evidence

- `tests/test_host_cutover_adapter.py` uses mocked Docker records and
  validates immutable historical/target coordinates, read-only receipt,
  exact-ID park/compensation, rejected drift and isolated argv builders.
- Existing `tests/test_browser_ipc_workflow.py` still verifies legacy/new-only
  branch guards, now accounting for the separately authenticated read-only
  cutover option. `pr-validation` includes the new tests.
- This stage is **not a deployment**. No Action was dispatched and the original
  host BETA remains the only known installed service as reported in the
  canonical checkpoint.

Next: maintain the living #227 issue checkpoint with this ADR and concrete
test results; do not merge/deploy until the physical NO_GO gates are closed.
