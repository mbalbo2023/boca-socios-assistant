# ADR 0130 — Existing controller to browser transition: inert safety contract

**2026-11-04 (ART), issue #227. Status: DRAFT, design/validation only.**
This candidate does **not** authorize or implement a host cutover, launch a
worker, or assert that the two externally validated owner-only modules work.
The published image is not an installed browser service.

## Observed problem

The physical receipts in [issue #45, checkpoint 6640165355](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6640165355)
establish a controller-only installation under `main=cabce9f1e452e63ded115f447559a358dc0f4d1b`:
install `41896871289`, acceptance `41897278258` and start `41897569928`.
The controller was last observed on `127.0.0.1:8443`, with preserved owner,
key and data and its browser engine off. This is not long-term liveness or
Samsung Chrome proof. The paired browser image was published by release
`41893887078` but the worker was not installed.

The current `beta-browser-install` is explicitly **new-only**. Its preflight
requires no containers, only the owner volume and a free port 8443; the
installed singleton has an occupied port and data/key/controller objects.
Its `beta-browser-start` operation requires an already-installed pair.
Neither is an upgrade operation and neither should be dispatched against the
installed singleton. Repeating `beta-install` is equally wrong.

The overlay changes three immutable Docker container-creation attributes:
`BOCA_BROWSER_BACKEND=ipc`, the Unix IPC volume mount and `restart: no`.
It cannot be applied to the existing controller ID by `docker start` or
`docker update`. A naïve `docker compose up` may recreate that ID, eliminating
the old controller needed for recoverable activation. This must be an
explicitly reviewed architectural decision, not a silent retrofit.

## Code-only safety contract in this candidate

`src/boca_socios/browser_transition_contract.py` provides a pure, inert
preflight of **redacted observations** and a separate fail-closed recovery
decision. It rejects unexpected source SHA, release SHA, digest, controller
ID, project/service, live engine, IP/port, mounted data/key/owner, other
containers/networks/volumes and non-preservation during recovery. The only
optional fourth volume is the existing Boca Telegram volume, which must be
preserved as well. No code in this module talks to Docker, SSH, GitHub, Boca
or Telegram, opens a database or runs Chromium. Its plan explicitly has
`executable=False` and no permitted effects. A caller-supplied observation
is **not proof of the Docker host**; future operation must independently
authenticate raw inventory using already reviewed Boca rootless helpers.

`tests/test_browser_transition_contract.py` tests positive and negative
coordinates, foreign objects, changed mounts, occupied loopback belonging
to another service, preservation and uncertain mid-cutover recovery with
synthetic values only. No owner-controlled modules are opened or imported.

## Effectful transition architecture: owner decision still required

Two choices remain:

1. **Recommended: scoped, staged Boca-only cutover.** Add a *new* explicit
   operation to the sole protected Boca Actions workflow. Authenticate the
   running legacy controller by exact ID/digest/revision/labels/Compose,
   host-loopback binding, rootless user and three persistent volume identities.
   Require both image manifests from one exact-SHA release and fresh free
   disk/inode observation. Prepare only a new Boca IPC volume/worker while
   the old controller stays usable; do not initialize the DB/key/owner.
   After a positively identified worker-ready proof, stop only the old Boca
   controller, create and verify the controller IPC candidate on the **same**
   host loopback 8443, and test the local synthetic pair. Keep an independently
   authenticated original controller recovery path until the pair is accepted.
   Any fault stops and disposes **only** positively identified new-attempt
   containers/IPC remnants; retain DB/WAL/key/owner and every uncertain
   object. If the original ID cannot be preserved across recreation, the
   approved design must explicitly specify how to restore an exact singleton
   from its immutable digest without touching the existing volumes. Revalidate
   the final topology, restart and resource use on the physical host. No
   public traffic or real Boca navigation.
2. Keep the existing controller and published browser image separate. This
   avoids a cutover today but does **not** provide the required integrated
   synthetic IPC BETA. It is a temporary holding state, not acceptance.

The proposed cutover requires an approved concrete host-operation contract,
new negative tests for identity swaps and partial failure, selective-cleanup
proof, reviewed exact-main SHA, strict CI/security and an immutable release
before any physical dispatch. The existing `beta-browser-*` operations remain
unchanged and **must not** be used as a substitute. Owners of central README,
operations, backlog and issue #45 will reconcile them upon integration; this
issue-local ADR makes no claim that central docs are current.

## Owner blackbox and service boundaries

- `src/boca_socios/browser/synthetic.py` and `ipc_worker.py` remain byte-for-byte
  owner-controlled. No agent inspects, imports, executes or changes them.
- ADR0121 explicitly keeps host worker/navigation activation outside agent
  authority; this PR does not waive that boundary.
- No actual Boca/Queue-it navigation, account login, reservation, purchase or
  messages are attempted; existing `SIMULATION_ONLY` restrictions remain.
- No backup, global Docker prune, kernel/network/firewall/service change,
  HTTPS, new port, Porota operation or unrelated workload inspection.
- No action or state transition is complete without physical Actions receipts
  and the owner's Chrome/Telegram evidence. Rule 84 requires labeling this
  as an unmerged, non-executable design until its own PR and gates pass.
