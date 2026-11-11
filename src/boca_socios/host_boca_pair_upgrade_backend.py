"""R179 guarded host actor: one Boca rootless dual-pair replacement.

Only the dedicated user 10001 daemon and its two exact historical Boca CIDs
are eligible for mutation.  The old SQLite/key/owner/IPC volumes are NEVER
deleted/recreated; the historical worker EXIT1 is parked, not restarted.
Target worker is CREATED/PID0 and uses the reviewed ipc_server + Boca egress
bridge. No real seat/ticket operation or browser navigation occurs here.

This backend is entered only from the main-only authenticated Actions memfd
dispatcher. Source/release pins from that runner are rechecked locally, and
the O_EXCL/fsync journal retains intent, commit and terminal under a single
Boca rootless lease. Failed/unknown acknowledgements remain NO_GO.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_observe as pair_observer
from boca_socios import host_boca_pair_stage as pair_stage
from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios import host_boca_pair_upgrade_plan as inert_plan
from boca_socios import host_boca_sqlite_identity as sqlite
from boca_socios import host_cutover_stage as stage
from boca_socios import host_first_deploy as host
from boca_socios import host_on_demand_replace as binding
from boca_socios import host_on_demand_service as service
from boca_socios.host_boca_cleanup import BocaJobLease
from boca_socios.host_lifecycle_rootless_adapter import (
    ProductionRootlessDockerIO,
    ReviewedInstalledPair,
)
from boca_socios.host_on_demand_lifecycle import OnDemandInstallation

if TYPE_CHECKING:
    from boca_socios.host_boca_sqlite_identity import SqliteIdentity

_HISTORICAL_SHA = "03df9a14bdd78cf768386a865876fed9d5656911"
_HISTORICAL_ATTEMPT = "42806447101"
_OBSERVATION_RUN = "43066120206"  # Genuine R177 capture; reobserve live state under new lease.
_HISTORICAL_COMPOSE_SHA = "b9e9465d6ec8e484b615d7bd65aab5a3c150d34a9893ad181167d2099893d811"
_HEX = re.compile(r"[a-f0-9]{64}\Z")
_BASE_ORIGIN = "http://localhost:8443"
_ORIGINAL_CONTROLLER = "boca-socios-controller-1"
_ORIGINAL_WORKER = "boca-socios-browser-worker-1"
_ROOTLESS_DB = Path("/home/boca-deploy/.local/share/docker")
_JOURNAL_PREFIX = ".boca-pair-upgrade-"


class PairHostNoGo(ValueError):
    """Fixed-category error, never Docker output, path or member data."""


def _fail() -> PairHostNoGo:
    return PairHostNoGo("Boca dual replacement host evidence unavailable")


def _read_runner_sources() -> pair_stage.PairSources:
    """Read only the authenticated source files from a pinned memfd ZIP."""
    # The legacy Cutover helper rejects archives above 512 kB and imports an
    # unrelated, effectful dispatcher. This upgrade has an independent,
    # narrowly bounded protected variant; bootstrap already verifies its SHA.
    if re.fullmatch(r"/proc/self/fd/[1-9][0-9]*", sys.argv[0]) is None:
        raise _fail()
    try:
        with open(sys.argv[0], "rb") as stream:
            archive = stream.read(480_001)
        if not 0 < len(archive) <= 480_000:
            raise _fail()
        with zipfile.ZipFile(io.BytesIO(archive), "r") as bundle:
            items = (
                bundle.read("compose.beta.yaml"),
                bundle.read("compose.beta.browser.yaml"),
                bundle.read("docker/seccomp_profile.json"),
            )
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise _fail() from exc
    sources = pair_stage.PairSources(
        base=items[0],
        overlay=items[1],
        seccomp=items[2],
        original_compose_sha=_HISTORICAL_COMPOSE_SHA,
        base_sha=hashlib.sha256(items[0]).hexdigest(),
        overlay_sha=hashlib.sha256(items[1]).hexdigest(),
        seccomp_sha=hashlib.sha256(items[2]).hexdigest(),
    )
    sources.validate()
    if hashlib.sha256(sources.base).hexdigest() != _HISTORICAL_COMPOSE_SHA:
        # The reviewed first migration does not secretly replace the live
        # historical controller Compose profile. This is a one-off dual fix.
        raise _fail()
    return sources


def _observed_coordinates(
    run: str, target_sha: str, controller_ref: str, worker_ref: str, release_run: str
) -> transaction.PairCoordinates:
    release = inert_plan.CandidateRelease(target_sha, release_run, controller_ref, worker_ref)
    release.validate()
    # The old IDs are *read* from current strict two-CID observer; never
    # supplied as arbitrary workflow inputs or inferred from broad names.
    observed = pair_observer.observe(_OBSERVATION_RUN)
    raw_plan = inert_plan.prepare(
        observed,
        observation_run_id=_OBSERVATION_RUN,
        attempt_id=run,
        release=release,
    )
    plan = transaction.PairCoordinates.from_inert_plan(raw_plan, run)
    if plan.old_attempt_id != _HISTORICAL_ATTEMPT or plan.old_source_sha != _HISTORICAL_SHA:
        raise _fail()
    return plan


def _reviewed_owner(controller_id: str) -> str:
    """Consume just one installed controller variable without printing Env."""
    record = host._browser_inspect_record(controller_id)
    config = record.get("Config")
    values = config.get("Env") if isinstance(config, dict) else None
    if not isinstance(values, list) or any(type(item) is not str for item in values):
        raise _fail()
    found = [entry.split("=", 1)[1] for entry in values if entry.startswith("BOCA_OWNER_SUBJECT=")]
    if len(found) != 1:
        raise _fail()
    owner = found[0]
    if type(owner) is not str:
        raise _fail()
    host._validate_owner_context(_BASE_ORIGIN, owner)
    return owner


def _full_old_record(
    plan: transaction.PairCoordinates,
    cid: str,
    *,
    role: str,
    name: str,
    running: bool | None = None,
) -> dict[str, object]:
    """Exact old CID/OCI config, regardless of reversible temporary name."""
    record = host._browser_inspect_record(cid)
    config = record.get("Config")
    state = record.get("State")
    image_id = plan.old_controller_image_id if role == "controller" else plan.old_worker_image_id
    if (
        record.get("Id") != cid
        or record.get("Image") != image_id
        or record.get("Name") != "/" + name
        or not isinstance(config, dict)
        or not isinstance(state, dict)
        or type(state.get("Running")) is not bool
        or running is not None
        and state["Running"] is not running
    ):
        raise _fail()
    labels = config.get("Labels")
    if (
        not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != host.PROJECT
        or labels.get("com.docker.compose.service") != role
        or labels.get(host.BROWSER_ATTEMPT_LABEL) != plan.old_attempt_id
        or labels.get("org.opencontainers.image.revision") != plan.old_source_sha
    ):
        raise _fail()
    return record


def _candidate_exact(
    plan: transaction.PairCoordinates,
    cid: str,
    *,
    role: str,
    name: str,
    expected_hash: str,
) -> None:
    record = host._browser_inspect_record(cid)
    config = record.get("Config")
    if not isinstance(config, dict):
        raise _fail()
    labels = config.get("Labels")
    if (
        record.get("Id") != cid
        or record.get("Name") != "/" + name
        or config.get("Image") != (plan.controller_ref if role == "controller" else plan.worker_ref)
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != host.PROJECT
        or labels.get("com.docker.compose.service") != role
        or labels.get(host.BROWSER_ATTEMPT_LABEL) != plan.attempt_id
        or labels.get("org.opencontainers.image.revision") != plan.new_source_sha
        or labels.get("com.docker.compose.config-hash") != expected_hash
    ):
        raise _fail()


@dataclass
class PairUpgradeJournal:
    """Three O_EXCL/fsync files: intent, irreversible commit, terminal."""

    def _write(self, plan: transaction.PairCoordinates, step: str, payload: bytes) -> None:
        if self._lease is None:
            raise _fail()
        cleanup.verify_protected_boca_job_lease(self._lease, plan.attempt_id)
        if step not in ("intent", "commit", "terminal") or len(payload) > 1024:
            raise _fail()
        fd = stage._root_fd()
        try:
            stage._create_exclusive(fd, f"{_JOURNAL_PREFIX}{plan.attempt_id}.{step}", payload)
        finally:
            os.close(fd)

    def __init__(self) -> None:
        self._lease: BocaJobLease | None = None
        self._intent: bytes | None = None

    def intent(self, plan: transaction.PairCoordinates, lease: BocaJobLease) -> None:
        self._lease = lease
        self._intent = json.dumps(
            {
                "attempt": plan.attempt_id,
                "old_controller": plan.old_controller_id,
                "old_worker": plan.old_worker_id,
                "old_source": plan.old_source_sha,
                "new_source": plan.new_source_sha,
                "release": plan.release_run_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        self._write(plan, "intent", self._intent)

    def commit(self, plan: transaction.PairCoordinates, lease: BocaJobLease) -> None:
        if lease is not self._lease or self._intent is None:
            raise _fail()
        self._write(plan, "commit", hashlib.sha256(self._intent).hexdigest().encode("ascii"))

    def terminal(
        self,
        plan: transaction.PairCoordinates,
        receipt: transaction.PairUpgradeReceipt,
        lease: BocaJobLease,
    ) -> None:
        from boca_socios.host_boca_pair_upgrade_cli import encode_upgrade

        if lease is not self._lease or self._intent is None:
            raise _fail()
        self._write(plan, "terminal", encode_upgrade(receipt))


class RootlessPairUpgradeBackend:
    """One-shot actor with every mutating boundary restricted to two Boca IDs."""

    requires_persistent_receipt = True

    def __init__(self, sources: pair_stage.PairSources) -> None:
        sources.validate()
        self.sources = sources
        self.state = "NEW"
        self.old: OnDemandInstallation | None = None
        self.new: OnDemandInstallation | None = None
        self.old_pair_receipt: bytes | None = None
        self.owner = ""
        self.root: Path | None = None
        self.sqlite_identity: SqliteIdentity | None = None
        self.stage_dir: Path | None = None
        self.worker_hash = ""
        self.controller_hash = ""
        self.worker_id: str | None = None
        self.controller_id: str | None = None
        self.binding_park_started = False

    def _guard(self, plan: transaction.PairCoordinates, lease: BocaJobLease, state: str) -> None:
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        if self.state != state:
            raise _fail()

    def _sqlite(self) -> None:
        if (
            self.root != _ROOTLESS_DB
            or self.sqlite_identity is None
            or sqlite.capture_sqlite_identity(self.root) != self.sqlite_identity
        ):
            raise _fail()

    def _old_exact(self, plan: transaction.PairCoordinates, *, parked: bool) -> None:
        if self.old is None:
            raise _fail()
        names = (
            f"boca-socios-controller-legacy-{plan.attempt_id}" if parked else _ORIGINAL_CONTROLLER,
            f"boca-socios-browser-worker-legacy-{plan.attempt_id}" if parked else _ORIGINAL_WORKER,
        )
        controller = _full_old_record(
            plan, plan.old_controller_id, role="controller", name=names[0], running=not parked
        )
        worker = _full_old_record(
            plan, plan.old_worker_id, role="browser-worker", name=names[1], running=False
        )
        state = controller["State"]
        stopped = worker["State"]
        if not isinstance(state, dict) or not isinstance(stopped, dict):
            raise _fail()
        controller_host = controller.get("HostConfig")
        worker_host = worker.get("HostConfig")
        if not isinstance(controller_host, dict) or not isinstance(worker_host, dict):
            raise _fail()
        restart = controller_host.get("RestartPolicy")
        worker_restart = worker_host.get("RestartPolicy")
        if (
            not isinstance(restart, dict)
            or restart.get("Name") != ("no" if parked else "unless-stopped")
            or not isinstance(worker_restart, dict)
            or worker_restart.get("Name") != "no"
        ):
            raise _fail()
        if parked and (state.get("Pid") != 0 or state.get("Status") != "exited"):
            raise _fail()
        if (
            stopped.get("Pid") != 0
            or stopped.get("Status") != "exited"
            or stopped.get("ExitCode") != 1
        ):
            raise _fail()

    def attest(self, plan: transaction.PairCoordinates, lease: BocaJobLease) -> None:
        self._guard(plan, lease, "NEW")
        host._require_dedicated_identity()
        if not host._rootless_socket_secure():
            raise _fail()
        observed = pair_observer.observe(plan.attempt_id)
        pair_observer.verify(observed, plan.attempt_id)
        raw = json.loads(observed.removeprefix(b"BOCA_INSTALLED_PAIR "))
        controller, worker = raw["services"]
        if (
            raw["source_sha"] != plan.old_source_sha
            or raw["attempt_id"] != plan.old_attempt_id
            or controller["container_id"] != plan.old_controller_id
            or worker["container_id"] != plan.old_worker_id
            or controller["image_id"] != plan.old_controller_image_id
            or worker["image_id"] != plan.old_worker_image_id
            or controller["running"] is not True
            or controller["health"] != "healthy"
            or worker["status"] != "exited"
            or worker["exit_code"] != 1
            or worker["pid"] != 0
        ):
            raise _fail()
        old = service.read_installed_binding(lease)
        if (
            old.installation_run_id != plan.old_attempt_id
            or old.source_sha != plan.old_source_sha
            or old.controller_id != plan.old_controller_id
            or old.worker_id != plan.old_worker_id
            or old.controller_image != controller["image_ref"]
            or old.worker_image != worker["image_ref"]
            or old.pair.sender_id
        ):
            raise _fail()
        self.old = old
        self._old_exact(plan, parked=False)
        self.owner = _reviewed_owner(plan.old_controller_id)
        host._browser_validate_ipc_volume(plan.old_attempt_id)
        host._validate_data_volume()
        self.root = host._checked_docker_storage_dir()
        if (
            self.root != _ROOTLESS_DB
            or sqlite.observe_sqlite_identity(self.root) != "VERIFIED_STABLE"
        ):
            raise _fail()
        self.sqlite_identity = sqlite.capture_sqlite_identity(self.root)
        engine = ProductionRootlessDockerIO().engine_request(plan.old_controller_id, "status")
        if engine.state != "STOPPED" or engine.changed or engine.pid <= 0:
            raise _fail()
        self.old_pair_receipt = observed
        self.state = "ATTESTED"

    def _compose_hash(self, plan: transaction.PairCoordinates, role: str) -> str:
        if self.stage_dir is None or role not in ("controller", "browser-worker"):
            raise _fail()
        base = self.stage_dir / "compose.beta.yaml"
        overlay = self.stage_dir / "compose.beta.browser.yaml"
        seccomp = self.stage_dir / "seccomp_profile.json"
        env = host._browser_compose_env(
            plan.controller_ref,
            _BASE_ORIGIN,
            self.owner,
            plan.worker_ref,
            plan.attempt_id,
            seccomp_file=seccomp,
            control_directory=service.control_directory(),
        )
        output = host._run(
            *host._browser_compose_args(
                "config", "--hash", role, base_file=base, overlay_file=overlay
            ),
            env=env,
        )
        match = re.fullmatch(rf"(?:{re.escape(role)}[ \t]+)?([0-9a-f]{{64}})", output)
        if match is None or not _HEX.fullmatch(match.group(1)):
            raise _fail()
        return match.group(1)

    def stage(self, plan: transaction.PairCoordinates, lease: BocaJobLease) -> None:
        self._guard(plan, lease, "ATTESTED")
        self._sqlite()
        self.stage_dir = pair_stage.prepare(plan.attempt_id, self.sources)
        host._browser_compose_model(
            plan.controller_ref,
            _BASE_ORIGIN,
            self.owner,
            plan.worker_ref,
            plan.attempt_id,
            base_file=self.stage_dir / "compose.beta.yaml",
            overlay_file=self.stage_dir / "compose.beta.browser.yaml",
            seccomp_file=self.stage_dir / "seccomp_profile.json",
            control_directory=service.control_directory(),
        )
        self.worker_hash = self._compose_hash(plan, "browser-worker")
        self.controller_hash = self._compose_hash(plan, "controller")
        if self.worker_hash == self.controller_hash:
            raise _fail()
        host._browser_pull_both(plan.controller_ref, plan.worker_ref, plan.new_source_sha)
        # Only new attempt-scoped Boca resources. The old IPC volume stays on
        # its historical attempt label and is NEVER created/deleted here.
        host._cutover_create_browser_egress(plan.attempt_id)
        host._browser_create_site_config_volume(plan.worker_ref, plan.attempt_id)
        self._sqlite()
        self.state = "STAGED"

    def park(self, plan: transaction.PairCoordinates, lease: BocaJobLease) -> None:
        self._guard(plan, lease, "STAGED")
        if self.old is None or self.stage_dir is None:
            raise _fail()
        self._sqlite()
        self._old_exact(plan, parked=False)
        self.binding_park_started = True
        binding.park_binding(self.old, plan.attempt_id, lease)
        # The socket is quiesced. Stop the exact historical controller and
        # disable restart only on its attested original ID, never globally.
        if (
            host._run("docker", "update", "--restart=no", plan.old_controller_id, timeout=20)
            != plan.old_controller_id
        ):
            raise _fail()
        if (
            host._run("docker", "stop", "-t", "8", plan.old_controller_id, timeout=30)
            != plan.old_controller_id
        ):
            raise _fail()
        worker_name = f"boca-socios-browser-worker-legacy-{plan.attempt_id}"
        controller_name = f"boca-socios-controller-legacy-{plan.attempt_id}"
        host._run("docker", "rename", plan.old_worker_id, worker_name, timeout=20)
        host._run("docker", "rename", plan.old_controller_id, controller_name, timeout=20)
        self._old_exact(plan, parked=True)
        if host._browser_docker_ids() != {plan.old_controller_id, plan.old_worker_id}:
            raise _fail()
        self._sqlite()
        self.state = "PARKED"

    def create_worker(self, plan: transaction.PairCoordinates, lease: BocaJobLease) -> str:
        self._guard(plan, lease, "PARKED")
        pair_stage.verify(plan.attempt_id, self.sources)
        worker = host._run(
            *host._cutover_worker_create_argv(
                plan.worker_ref,
                plan.new_source_sha,
                plan.attempt_id,
                self.worker_hash,
                on_demand=True,
            ),
            timeout=40,
        )
        if not _HEX.fullmatch(worker) or worker in (plan.old_controller_id, plan.old_worker_id):
            raise _fail()
        self.worker_id = worker
        _candidate_exact(
            plan,
            worker,
            role="browser-worker",
            name=_ORIGINAL_WORKER,
            expected_hash=self.worker_hash,
        )
        host._cutover_idle_worker(
            worker,
            plan.worker_ref,
            plan.new_source_sha,
            plan.attempt_id,
            self.sources.seccomp_sha,
            self.sources.seccomp,
            self.worker_hash,
        )
        self.state = "WORKER"
        return worker

    def create_controller(
        self, plan: transaction.PairCoordinates, worker_id: str, lease: BocaJobLease
    ) -> str:
        self._guard(plan, lease, "WORKER")
        if self.worker_id != worker_id:
            raise _fail()
        # Rootless 8443 forwarding can linger briefly after the precisely
        # identified historical controller has stopped and been parked.
        host._browser_port_free(after_candidate_removal=True)
        if service.prepare_control_directory(plan.attempt_id, lease) != service.control_directory():
            raise _fail()
        controller = host._run(
            *host._cutover_candidate_create_argv(
                plan.controller_ref,
                plan.new_source_sha,
                plan.attempt_id,
                _BASE_ORIGIN,
                self.owner,
                self.controller_hash,
                control_directory=service.control_directory(),
            ),
            timeout=40,
        )
        if not _HEX.fullmatch(controller) or controller in (
            worker_id,
            plan.old_controller_id,
            plan.old_worker_id,
        ):
            raise _fail()
        self.controller_id = controller
        _candidate_exact(
            plan,
            controller,
            role="controller",
            name=_ORIGINAL_CONTROLLER,
            expected_hash=self.controller_hash,
        )
        if host._run("docker", "start", controller, timeout=30) != controller:
            raise _fail()
        host._browser_wait_healthy(controller)
        self._candidate_cold(plan, controller, worker_id)
        self.state = "CONTROLLER"
        return controller

    def _candidate_cold(
        self, plan: transaction.PairCoordinates, controller_id: str, worker_id: str
    ) -> None:
        if self.controller_id != controller_id or self.worker_id != worker_id:
            raise _fail()
        if not host._cutover_candidate_postflight(
            controller_id,
            plan.controller_ref,
            plan.new_source_sha,
            plan.attempt_id,
            _BASE_ORIGIN,
            self.owner,
            self.controller_hash,
            control_directory=service.control_directory(),
        ):
            raise _fail()
        host._cutover_idle_worker(
            worker_id,
            plan.worker_ref,
            plan.new_source_sha,
            plan.attempt_id,
            self.sources.seccomp_sha,
            self.sources.seccomp,
            self.worker_hash,
        )
        host._beta_loopback_health(controller_id, _BASE_ORIGIN)
        engine = ProductionRootlessDockerIO().engine_request(controller_id, "status")
        if engine.state != "STOPPED" or engine.changed or engine.pid <= 0:
            raise _fail()
        # The existing on-demand `ready` subcommand opens SQLite READ_ONLY,
        # does not migrate schema, and must confirm the persisted owner ledger
        # on BOTH first health and the one cold panel restart.
        if (
            host._run(
                "docker",
                "exec",
                "--user",
                "10001:10001",
                controller_id,
                "/app/.venv/bin/python",
                "-I",
                "-B",
                "-m",
                "boca_socios.host_on_demand_lifecycle",
                "ready",
                timeout=8,
            )
            != "BOCA_LEDGER_READY"
        ):
            raise _fail()
        self._sqlite()

    def accept(
        self,
        plan: transaction.PairCoordinates,
        controller_id: str,
        worker_id: str,
        lease: BocaJobLease,
    ) -> None:
        self._guard(plan, lease, "CONTROLLER")
        if host._browser_docker_ids() != {
            plan.old_controller_id,
            plan.old_worker_id,
            controller_id,
            worker_id,
        }:
            raise _fail()
        self._old_exact(plan, parked=True)
        self._candidate_cold(plan, controller_id, worker_id)
        self.state = "ACCEPTED_COLD"

    def replace_binding(
        self,
        plan: transaction.PairCoordinates,
        controller_id: str,
        worker_id: str,
        lease: BocaJobLease,
    ) -> None:
        self._guard(plan, lease, "ACCEPTED_COLD")
        if self.old is None:
            raise _fail()
        self.new = OnDemandInstallation(
            installation_run_id=plan.attempt_id,
            source_sha=plan.new_source_sha,
            controller_id=controller_id,
            controller_image=plan.controller_ref,
            worker_id=worker_id,
            worker_image=plan.worker_ref,
            database_path=self.old.database_path,
            pair=ReviewedInstalledPair(plan.attempt_id, self.controller_hash, self.worker_hash),
        )
        service.install_control(self.new, lease)
        self._candidate_cold(plan, controller_id, worker_id)
        # Exercise exactly one idle-controller restart before irreversible
        # acceptance; worker must remain unstarted and historical pair parked.
        if host._run("docker", "stop", "-t", "8", controller_id, timeout=30) != controller_id:
            raise _fail()
        if host._run("docker", "start", controller_id, timeout=30) != controller_id:
            raise _fail()
        host._browser_wait_healthy(controller_id)
        self._candidate_cold(plan, controller_id, worker_id)
        service.verify_control(self.new, lease)
        self._old_exact(plan, parked=True)
        self.state = "BOUND"

    def retire_old(
        self,
        plan: transaction.PairCoordinates,
        controller_id: str,
        worker_id: str,
        lease: BocaJobLease,
    ) -> None:
        self._guard(plan, lease, "BOUND")
        if self.old is None or self.new is None:
            raise _fail()
        self._old_exact(plan, parked=True)
        self._candidate_cold(plan, controller_id, worker_id)
        for cid in (plan.old_worker_id, plan.old_controller_id):
            if host._run("docker", "rm", cid, timeout=30) != cid:
                raise _fail()
            if cid in host._browser_docker_ids():
                raise _fail()
        if host._browser_docker_ids() != {controller_id, worker_id}:
            raise _fail()
        binding.commit_binding(self.old, self.new, plan.attempt_id, lease)
        self.state = "RETIRED"

    def _remove_candidate(self, plan: transaction.PairCoordinates, role: str) -> None:
        """An uncertain create ACK is reconciled by exact name, then full pins."""
        if role == "controller":
            cid = host._cutover_candidate_name_id()
            expected = self.controller_id
            ref = plan.controller_ref
            config_hash = self.controller_hash
            name = _ORIGINAL_CONTROLLER
        else:
            cid = host._cutover_worker_name_id()
            expected = self.worker_id
            ref = plan.worker_ref
            config_hash = self.worker_hash
            name = _ORIGINAL_WORKER
        if cid is None:
            if expected is not None:
                raise _fail()
            return
        if expected is not None and cid != expected:
            raise _fail()
        if cid in (plan.old_controller_id, plan.old_worker_id):
            # A partially parked old container still holds the canonical
            # name. This is NOT the new candidate and must never be removed.
            return
        _candidate_exact(plan, cid, role=role, name=name, expected_hash=config_hash)
        if role == "controller":
            record = host._browser_inspect_record(cid)
            state = record.get("State")
            if not isinstance(state, dict) or type(state.get("Running")) is not bool:
                raise _fail()
            if state["Running"] and host._run("docker", "stop", "-t", "8", cid, timeout=30) != cid:
                raise _fail()
        else:
            host._cutover_idle_worker(
                cid,
                ref,
                plan.new_source_sha,
                plan.attempt_id,
                self.sources.seccomp_sha,
                self.sources.seccomp,
                config_hash,
            )
        if host._run("docker", "rm", cid, timeout=30) != cid:
            raise _fail()
        if cid in host._browser_docker_ids():
            raise _fail()

    def _restore_name(self, plan: transaction.PairCoordinates, *, role: str) -> None:
        if role == "controller":
            cid, canonical = plan.old_controller_id, _ORIGINAL_CONTROLLER
        else:
            cid, canonical = plan.old_worker_id, _ORIGINAL_WORKER
        record = host._browser_inspect_record(cid)
        current = record.get("Name")
        parked = f"/{canonical.removesuffix('-1')}-legacy-{plan.attempt_id}"
        if current == parked:
            host._run("docker", "rename", cid, canonical, timeout=20)
        elif current != "/" + canonical:
            raise _fail()
        _full_old_record(plan, cid, role=role, name=canonical)

    def restore_old(self, plan: transaction.PairCoordinates, lease: BocaJobLease) -> bool:
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        if self.old is None:
            return False
        try:
            # Reverse order of creation. Never use worker compensation that
            # deletes the historical IPC volume or stops arbitrary names.
            self._remove_candidate(plan, "controller")
            self._remove_candidate(plan, "browser-worker")
            if host._browser_docker_ids() != {plan.old_controller_id, plan.old_worker_id}:
                return False
            if self.binding_park_started:
                binding.restore_binding(self.old, plan.attempt_id, lease)
            else:
                if service.read_installed_binding(lease) != self.old:
                    return False
            self._restore_name(plan, role="controller")
            self._restore_name(plan, role="browser-worker")
            record = host._browser_inspect_record(plan.old_controller_id)
            state = record.get("State")
            if not isinstance(state, dict) or type(state.get("Running")) is not bool:
                return False
            if not state["Running"]:
                if (
                    host._run("docker", "start", plan.old_controller_id, timeout=30)
                    != plan.old_controller_id
                ):
                    return False
                host._browser_wait_healthy(plan.old_controller_id)
            if (
                host._run(
                    "docker",
                    "update",
                    "--restart=unless-stopped",
                    plan.old_controller_id,
                    timeout=20,
                )
                != plan.old_controller_id
            ):
                return False
            self._old_exact(plan, parked=False)
            self._sqlite()
            self._reclaim_stage_resources(plan)
            self.state = "RESTORED"
            return True
        except Exception:
            return False

    def _reclaim_stage_resources(self, plan: transaction.PairCoordinates) -> None:
        # Every deletion is restricted to newly created attempt-owned Boca
        # site/egress with independent empty/label/inode checks. Do not remove
        # IPC/data/key/owner or historic Docker images/containers.
        host._cutover_compensate_site_config_volume(plan.attempt_id)
        host._cutover_compensate_browser_egress(plan.attempt_id)

    def finalize(
        self,
        plan: transaction.PairCoordinates,
        *,
        commit_started: bool,
        controller_id: str | None,
        worker_id: str | None,
        lease: BocaJobLease,
    ) -> str:
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        try:
            self._sqlite()
            if commit_started:
                if self.state != "RETIRED" or self.new is None:
                    return "INDETERMINATE"
                binding._new_pair_only(self.new)
                if service.read_installed_binding(lease) != self.new:
                    return "INDETERMINATE"
                host._browser_validate_ipc_volume(plan.old_attempt_id)
                host._browser_validate_site_config_volume(plan.attempt_id)
                return "ACCEPT"
            if self.state == "RESTORED" and self.old is not None:
                if service.read_installed_binding(lease) != self.old:
                    return "NO_GO"
                observed = pair_observer.observe(plan.attempt_id)
                pair_observer.verify(observed, plan.attempt_id)
                state = json.loads(observed.removeprefix(b"BOCA_INSTALLED_PAIR "))
                if (
                    state.get("source_sha") != plan.old_source_sha
                    or state.get("attempt_id") != plan.old_attempt_id
                    or [item.get("container_id") for item in state.get("services", [])]
                    != [plan.old_controller_id, plan.old_worker_id]
                ):
                    return "NO_GO"
                return "ACCEPT"
        except Exception:
            return "INDETERMINATE"
        return "INDETERMINATE"


def apply(
    run_id: str,
    target_sha: str,
    controller_ref: str,
    worker_ref: str,
    release_run_id: str,
) -> transaction.PairUpgradeReceipt:
    """Authenticated Actions code calls this once; no callers choose old IDs."""
    sources = _read_runner_sources()
    coordinates = _observed_coordinates(
        run_id, target_sha, controller_ref, worker_ref, release_run_id
    )
    journal = PairUpgradeJournal()
    return transaction.run_pair_upgrade(
        coordinates,
        backend=RootlessPairUpgradeBackend(sources),
        terminal_preflight=journal.intent,
        commit_marker=journal.commit,
        terminal_sink=journal.terminal,
    )
