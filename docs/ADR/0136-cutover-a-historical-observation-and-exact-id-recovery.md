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

The host helper has standalone **unreachable-from-workflow** primitives for
worker and candidate creation, worker preparation, original park/compensation,
candidate activation/failure compensation, and positive-acceptance retirement.
`host_cutover_stage.py` can atomically stage only reviewed public files in
`/srv/boca-socios/cutover-a-<attempt_id>`; it does not replace the installed
`compose.beta.yaml`. Offline tests fake Docker and use disposable local files,
not the droplet. These helpers are **not wired into an orchestrated host phase**.
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

The park primitive has tested compensation for (a) Docker restart-policy
update has no effect or succeeds before a lost CLI receipt; (b) `docker stop`
times out with/without effect; (c) `docker rename` fails before or after
changing the name; (d) a recovery action fails (INDETERMINATE). The **exact
original ID** switches `unless-stopped→no` before stop and back to
`unless-stopped` only upon validated recovery, preventing a daemon restart from
reviving the parked legacy controller during the port handoff. Worker and
candidate builders specify `--restart=no` and a single Boca-only namespace.

Worker preparation now has unreachable code-only compensation for partial
volume init, `docker create` receipt loss, start failure and worker health
failure, with exact worker ID and attempt-labeled IPC volume checks. Candidate
activation independently tests the create/start/health/loopback path and
removes **only** a positively identified attempt candidate before restoring
the old ID; unexpected labels produce INDETERMINATE, never blind deletion.
Retirement of the parked original is a distinct irreversible commit point
guarded by positive candidate and worker health and localhost acceptance, and
it then checks Compose singleton discovery from attempt-scoped files. If the
retirement receipt or discovery is unclear, it does not restart the old ID
over the candidate's bound port or retry a destructive command.

## Open physical NO_GO gates (do not mark done)

1. **Legacy staging conflict.** `browser-stage` and
   `host_browser_file_stage.py` explicitly require an empty new-only
   `/srv/boca-socios`; the installed singleton has `compose.beta.yaml`.
   A **code-only** independent stager now requires the exact live base hash,
   saves its inode/device in an immutable O_EXCL attempt marker, accepts only
   3 reviewed SHA256-bounded files, and quarantines a partial transfer.
   Still **NO_GO** until the future single protected Action streams that
   module to the same dedicated SSH identity and verifies resumed/aborted
   transfer postconditions without leaving untracked stage residues.
2. **No live execution path.** `cutover-a-observe` remains the sole new
   dispatch option. Individual effectful helpers are code-only; no reviewed
   protected `cutover-a-apply`, composed transaction marker/ownership lease,
   verified installer, post-SSH timeout resume or one-shot recovery Action
   exists. Even passing all fake Docker tests does **not** authorize host use.
3. **Compose-created vs `docker create` identity.** Exercise both services
   on disposable Actions runner: `docker compose ps -q` must select only the
   exact candidate/worker after original retirement. During the bounded
   transition two objects may have `service=controller`, so service lookup
   alone is forbidden. Inspect exact healthcheck, effective seccomp and all
   labels. Fake-Docker unit tests do not prove this compatibility.
   **CI RCA A227-F1 (2026-11-04):** PR #320 initial First Deploy runner
   `41932123724` failed at the disposable label-topology probe: manual
   `docker create` objects with project/service/oneoff labels were invisible
   to `docker compose ps -a`. Official Docker Compose `getDefaultFilters`
   also requires the presence of `com.docker.compose.config-hash`. Fix-forward
   requires each argv builder to take a SHA256 reviewed service hash and emit
   that label; runner smoke derives **separate** hashes from `docker compose
   config --hash` for original, candidate and worker. A227-F2 HEAD
   `f872e6de46c489100ecaab02e174e1af6f97cf00` passed exact-SHA hosted
   First Deploy `41933482012`, CI `41933482030`, Image security `41933482088`
   and release PR validation `41933482111`, all SUCCESS on disposable runner,
   **without host action**. Subsequent new cutover helpers still need their
   own hosted runner simulation, including exact effective seccomp and Compose.
4. **Legacy restart policy.** The installed original has `unless-stopped`,
   while the candidate must use `no`. A daemon restart mid-cutover could
   revive the parked original and collide with localhost:8443. The code-only
   park now positively checks a temporary exact-ID `docker update --restart=no`,
   restoring `unless-stopped` during original recovery and preserving `no`
   while parked. Physical daemon-restart and transport-loss simulations remain
   mandatory; no real restart policy was changed.
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
8. **Single governable authority and Telegram V2.** The Telegram custody front
   identified that a second independently dispatchable SSH gate introduces a
   race against the first-deploy singleton. Any future Telegram V2 custody
   operation must integrate in the **same** authenticated `host_first_deploy.py`
   workflow/attempt/identity gate and remain simulation-only until separately
   reviewed; do not introduce a second physical installer. No Telegram token
   is read or transmitted by this cutover code.
9. **Owner session upgrade dependency #321.** The owner's new single persistent
   Chrome-session contract makes schema `0008_owner_browser_session` mandatory
   for the future controller; the installed controller-only legacy is not
   migrated. A future cutover must first verify a *separately reviewed*,
   Boca-only stopped-controller additive migration and prove that the original
   image can still resume against that schema during exact-ID compensation.
   Neither this cutover code nor its Actions option runs that migration; an
   unverified schema or legacy-read compatibility is physical **NO_GO**.

## Reproducible code-only evidence

- `tests/test_host_cutover_adapter.py` uses mocked Docker records and
  validates immutable historical/target coordinates, read-only receipt,
  exact-ID park/compensation, rejected drift and isolated argv builders.
- `tests/test_host_cutover_stage.py` validates isolated private O_EXCL staged
  files, immutable original inode, bounded hashes, interrupted transfer,
  symlink/replacement rejection and direct no-secret seccomp reads. Neither
  tests nor cutover helpers read/execute the protected blackbox modules.
- Existing `tests/test_browser_ipc_workflow.py` still verifies legacy/new-only
  branch guards, now accounting for the separately authenticated read-only
  cutover option. `pr-validation` includes the new tests.
- Local 2026-11-04 ART, source-only cutover candidate: `uv sync --frozen
  --offline` checked 15 packages; 55 focused tests PASS; full suite **2498
  passed +31 subtests passed**; Ruff lint/format (390 files), Mypy (85
  sources), repository policy and `git diff --check` PASS. These results are
  local source/runner mocks, **not** a Docker host transition. Hosted PR checks
  for this increment remain pending until the exact new commit is published.
- This stage is **not a deployment**. No Action was dispatched and the original
  host BETA remains the only known installed service as reported in the
  canonical checkpoint.

Next: maintain the living #227 issue checkpoint with this ADR and concrete
test results; do not merge/deploy until the physical NO_GO gates are closed.
