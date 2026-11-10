"""Rootless Boca Cutover, guarded by one lease and immutable release coordinates.

The authenticated V3 on-demand profile creates and attests a stopped worker
before parking the original. It installs the controller-only activation socket
and retires the original only after exact-ID, engine and loopback acceptance.
Historical releases retain their original running-worker acceptance contract.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import os
import re
import stat
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_cutover_stage as stage
from boca_socios import host_first_deploy as host
from boca_socios.host_boca_cutover import (
    CutoverError,
    CutoverPlan,
    CutoverReceipt,
    run_cutover_a,
)

if TYPE_CHECKING:
    from boca_socios.host_on_demand_lifecycle import OnDemandInstallation

_SQL_SHA = "38c4c97594143340089395c5230a464372acdd058dbe31169ba4206a1fd83d23"
_BUNDLE_FILES = (
    "compose.beta.yaml",
    "compose.beta.browser.yaml",
    "docker/seccomp_profile.json",
    "boca_socios/owner_session_disk_bootstrap.py",
    "boca_socios/panel/owner_session_sql/0001_owner_browser_session.sql",
)
_HEX = re.compile(r"[0-9a-f]{64}\Z")
State = Literal[
    "INIT",
    "ATTESTED",
    "STAGED",
    "WORKER",
    "PARKED",
    "BOOTSTRAPPED",
    "CANDIDATE",
    "ACCEPTED",
    "COMMITTED",
    "RECOVERED",
]
Bootstrap = Callable[..., str]


@dataclass(frozen=True)
class ReviewedCutoverSources:
    base: bytes
    overlay: bytes
    seccomp: bytes
    session_sql: bytes

    @classmethod
    def from_verified_zip(cls) -> ReviewedCutoverSources:
        """Post-memfd verifier, no host file or unauthenticated import fallback."""
        if not sys.argv[0].startswith("/proc/self/fd/"):
            raise CutoverError("cutover source ZIP has no memfd provenance")
        try:
            with zipfile.ZipFile(sys.argv[0], "r") as package:
                base, overlay, seccomp, _bootstrap_source, session_sql = (
                    package.read(name) for name in _BUNDLE_FILES
                )
        except (OSError, KeyError, zipfile.BadZipFile) as exc:
            raise CutoverError("Option B authenticated ZIP source absent") from exc
        # The memfd includes BOTH Option B bootstrap artifacts, but the
        # imported stdlib helper is loaded directly from the verified ZIP;
        # only the SQL bytes belong in this four-field data record.
        return cls(base, overlay, seccomp, session_sql)

    def validate(self, plan: CutoverPlan) -> None:
        if any(not 0 < len(data) <= 32768 for data in self.__dict__.values()) or (
            hashlib.sha256(self.base).hexdigest(),
            hashlib.sha256(self.overlay).hexdigest(),
            hashlib.sha256(self.seccomp).hexdigest(),
            hashlib.sha256(self.session_sql).hexdigest(),
        ) != (
            plan.target_compose_sha,
            plan.overlay_sha,
            plan.seccomp_sha,
            _SQL_SHA,
        ):
            raise CutoverError("cutover reviewed Compose/seccomp/Option B hashes untrusted")


def _stdlib_session_bootstrap() -> Bootstrap:
    """A ZIP-only stdlib module; never import the normal panel/__init__.py."""
    if not sys.argv[0].startswith("/proc/self/fd/"):
        raise CutoverError("owner session bootstrap requires verified memfd")
    module = importlib.import_module("boca_socios.owner_session_disk_bootstrap")
    if getattr(module, "__file__", None) != (
        sys.argv[0] + "/boca_socios/owner_session_disk_bootstrap.py"
    ):
        raise CutoverError("owner session bootstrap import escaped reviewed ZIP")
    func = getattr(module, "bootstrap_attested_session_file", None)
    if not callable(func):
        raise CutoverError("reviewed owner session bootstrap entrypoint unavailable")
    return cast(Bootstrap, func)


def _stage_path(plan: CutoverPlan) -> Path:
    return stage.ROOT / f"cutover-a-{plan.attempt_id}"


def _precommit_legacy_image_cleanup(
    plan: CutoverPlan,
    legacy_record: dict[str, object],
    candidate_id: str,
    worker_id: str,
) -> tuple[cleanup.LegacyImageProof, cleanup.HistoricalRetainedImageProof | None]:
    """Block irreversible commit if old image cleanup would be uncertain.

    The old controller was already checked for exact historical GHCR digest,
    revision, rootless UID, project and persistent mounts. Its immutable
    Docker image ID is independently cross-checked with narrowly inspected
    image fields, before a successful cutover can retire the original CID.
    """
    image_id = legacy_record.get("Image")
    if not isinstance(image_id, str) or not cleanup.HEX_ID.fullmatch(image_id):
        raise CutoverError("cutover historical controller image ID unavailable")
    try:
        proof = cleanup.attest_historical_legacy_image(image_id, plan.legacy_image, plan.legacy_sha)
        inventory = cleanup.capture_inventory(historical_legacy=proof)
        if not any(
            container.ident == plan.legacy_id and container.image_id == proof.ident
            for container in inventory.containers
        ) or not any(
            image.ident == proof.ident and image.historical_legacy_attested
            for image in inventory.images
        ):
            raise cleanup.CleanupError("historical Boca image/container binding drifted")
        retained = (
            cleanup.attest_historical_retained_image(inventory)
            if cleanup.HISTORICAL_RETIRE_TARGET in inventory.global_image_ids
            or any(i.ident == cleanup.HISTORICAL_RETIRE_TARGET for i in inventory.images)
            else None
        )
        planned = cleanup.plan(
            inventory,
            plan.attempt_id,
            preserve_images=frozenset(
                {proof.ident} | ({retained.ident} if retained is not None else set())
            ),
            preserve_containers=frozenset({plan.legacy_id, candidate_id, worker_id}),
            retire_containers=frozenset(),
        )
        if planned.uncertain:
            # A new legacy/foreign orphan discovered after COMMITTED cannot
            # be safely deleted or declared cleaned. Stop while old CID is
            # still recoverable; never weaken generic cleanup classification.
            raise cleanup.CleanupError("Boca cleanup has precommit unknown residue")
        return proof, retained
    except (cleanup.CleanupError, OSError, ValueError) as exc:
        raise CutoverError("cutover precommit exact legacy image cleanup unproven") from exc


def _reviewed_compose_hash(
    plan: CutoverPlan, service: str, *, control_directory: Path | None = None
) -> str:
    """Use Docker Compose's actual canonical per-service hash; no invented label."""
    if service not in ("controller", "browser-worker"):
        raise CutoverError("cutover Compose service outside allowlist")
    directory = stage.verify(plan.attempt_id, plan.legacy_compose_sha)
    if directory != _stage_path(plan):
        raise CutoverError("cutover Compose stage identity changed")
    base = directory / "compose.beta.yaml"
    overlay = directory / "compose.beta.browser.yaml"
    seccomp = directory / "seccomp_profile.json"
    output = host._run(
        *host._browser_compose_args(
            "config", "--hash", service, base_file=base, overlay_file=overlay
        ),
        env=host._browser_compose_env(
            plan.target_image,
            plan.origin,
            plan.owner_subject,
            plan.browser_image,
            plan.attempt_id,
            seccomp_file=seccomp,
            control_directory=control_directory,
        ),
    )
    # Compose v2 versions print either the one hash or SERVICE<space>HASH.
    match = re.fullmatch(rf"(?:{re.escape(service)}[ \t]+)?([0-9a-f]{{64}})", output)
    if match is None:
        raise CutoverError("cutover resolved Compose service hash uncertain")
    return match.group(1)


def _verified_data_volume_path(plan: CutoverPlan) -> Path:
    """The parked original alone references this authenticated rootless volume."""
    host._cutover_legacy_record(
        plan.legacy_id,
        plan.legacy_image,
        plan.legacy_sha,
        name=f"boca-socios-controller-legacy-{plan.attempt_id}",
        running=False,
        restart_policy="no",
    )
    host._validate_docker_boundary()
    host._validate_data_volume()
    root = host._checked_docker_storage_dir()
    path = root / "volumes" / host.DATA_VOLUME / "_data" / "boca.sqlite3"
    if not path.is_absolute() or any(component.is_symlink() for component in path.parents):
        raise CutoverError("Boca legacy DB rootless volume path redirected")
    associated = host._run(
        "docker",
        "ps",
        "-a",
        "--no-trunc",
        "--format",
        "{{.ID}}",
        "--filter",
        f"volume={host.DATA_VOLUME}",
    ).splitlines()
    controllers = host._run(
        "docker",
        "ps",
        "-a",
        "--no-trunc",
        "--format",
        "{{.ID}}",
        "--filter",
        "label=com.docker.compose.project=boca-socios",
        "--filter",
        "label=com.docker.compose.service=controller",
    ).splitlines()
    if associated != [plan.legacy_id] or controllers != [plan.legacy_id]:
        raise CutoverError("Boca legacy SQLite volume is shared/ambiguous")
    return path


def _legacy_disk_identity(plan: CutoverPlan) -> tuple[Path, tuple[int, int]]:
    path = _verified_data_volume_path(plan)
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 10001
        or metadata.st_gid != 10001
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        raise CutoverError("Boca legacy DB inode/owner/mode untrusted")
    return path, (metadata.st_dev, metadata.st_ino)


def _controller_database_identity(controller: str) -> tuple[int, int]:
    # The container UID owns the SQLite file; on the host that UID is subordinate.
    if not _HEX.fullmatch(controller):
        raise CutoverError("controller database CID invalid")
    program = (
        "import os,stat; s=os.lstat('/data/boca.sqlite3'); "
        "assert os.getuid()==os.geteuid()==os.getgid()==os.getegid()==10001; "
        "assert stat.S_ISREG(s.st_mode) and stat.S_IMODE(s.st_mode)==0o600 "
        "and s.st_uid==s.st_gid==10001 and s.st_nlink==1; print(s.st_dev,s.st_ino)"
    )
    identity = host._run(
        "docker",
        "exec",
        "--user",
        "10001:10001",
        controller,
        "/app/.venv/bin/python",
        "-I",
        "-B",
        "-c",
        program,
        timeout=8,
    )
    match = re.fullmatch(r"([0-9]{1,20}) ([1-9][0-9]{0,19})", identity)
    if match is None:
        raise CutoverError("private controller database identity unavailable")
    return int(match[1]), int(match[2])


def _verify_mounted_control(controller: str, directory: Path) -> tuple[int, int]:
    """Match the listening socket's inode across the read-only bind. No frame is sent."""
    path = directory / "control.sock"
    before = path.lstat()
    if (
        not _HEX.fullmatch(controller)
        or not stat.S_ISSOCK(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o666
        or before.st_nlink != 1
        or (before.st_uid, before.st_gid) != (os.geteuid(), os.getegid())
    ):
        raise CutoverError("on-demand mounted socket identity unavailable")
    result = host._run(
        "docker",
        "exec",
        "--user",
        "10001:10001",
        controller,
        "/app/.venv/bin/python",
        "-I",
        "-B",
        "-c",
        "import os,stat; d=os.lstat('/run/boca-bot-control'); "
        "assert os.geteuid()==os.getegid()==10001 and stat.S_ISDIR(d.st_mode) "
        "and stat.S_IMODE(d.st_mode)==0o711; "
        "s=os.lstat('/run/boca-bot-control/control.sock'); "
        "assert stat.S_ISSOCK(s.st_mode) and stat.S_IMODE(s.st_mode)==0o666; "
        "print(s.st_dev,s.st_ino)",
        timeout=8,
    )
    after = path.lstat()
    if (
        not os.path.samestat(before, after)
        or (before.st_mode, before.st_uid, before.st_gid, before.st_nlink)
        != (after.st_mode, after.st_uid, after.st_gid, after.st_nlink)
        or result != f"{before.st_dev} {before.st_ino}"
    ):
        raise CutoverError("on-demand socket bind differs across the controller namespace")
    return before.st_dev, before.st_ino


def _bootstrap_in_data_namespace(plan: CutoverPlan, identity: tuple[int, int]) -> str:
    """Only the parked controller's data volume, as its own namespaced UID."""
    if len(identity) != 2 or any(type(n) is not int or n < 0 for n in identity):
        raise CutoverError("on-demand bootstrap identity invalid")
    return host._browser_named_probe(
        "owner-session",
        plan.attempt_id,
        (
            "docker",
            "run",
            "--rm",
            "--pull",
            "never",
            "--user",
            "10001:10001",
            "--network",
            "none",
            "--log-driver",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            "16",
            "--memory",
            "64m",
            "--cpus",
            "0.25",
            "--mount",
            f"type=volume,source={host.DATA_VOLUME},target=/data,volume-nocopy",
            "--entrypoint",
            "/app/.venv/bin/python",
            plan.target_image,
            "-I",
            "-B",
            "-c",
            "import sys; from boca_socios.panel.owner_session_disk_bootstrap import "
            "bootstrap_mounted_session; print(bootstrap_mounted_session(int(sys.argv[1]), "
            "int(sys.argv[2])))",
            str(identity[0]),
            str(identity[1]),
        ),
    )


class RootlessCutoverBackend:
    """One ephemeral guarded host adapter. Must be passed to run_cutover_a()."""

    # Unlike injected fake backends, effectful rootless Docker can never run
    # without BOTH the early persistent intent and terminal result writer.
    requires_persistent_receipt = True

    def __init__(
        self,
        sources: ReviewedCutoverSources,
        *,
        session_bootstrap: Bootstrap | None = None,
        on_demand: bool = False,
    ) -> None:
        self.sources = sources
        self.session_bootstrap = session_bootstrap
        self.on_demand = on_demand
        self.idle_installed = False
        self.control_directory: Path | None = None
        self.control_prepared = False
        self.installation: OnDemandInstallation | None = None
        self.worker_id: str | None = None
        self.candidate_id: str | None = None
        self.database_identity: tuple[int, int] | None = None
        self.database_path: Path | None = None
        self.state: State = "INIT"
        self.plan: CutoverPlan | None = None
        self.worker_hash: str | None = None
        self.controller_hash: str | None = None
        self.legacy_image_proof: cleanup.LegacyImageProof | None = None
        self.retained_image_proof: cleanup.HistoricalRetainedImageProof | None = None

    def _guard(self, plan: CutoverPlan, lease: cleanup.BocaJobLease, state: State) -> None:
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        if self.state != state or (self.plan is not None and self.plan != plan):
            raise CutoverError("cutover host backend phase/plan reuse forbidden")

    def attest_original(self, plan: CutoverPlan, lease: cleanup.BocaJobLease) -> None:
        self._guard(plan, lease, "INIT")
        plan.validate()
        self.sources.validate(plan)  # No host call for corrupt source bytes.
        host._cutover_observe(
            plan.legacy_image,
            plan.legacy_sha,
            plan.legacy_compose_sha,
            plan.origin,
            plan.owner_subject,
            plan.target_image,
            plan.target_sha,
            plan.browser_image,
            plan.legacy_id,
        )
        self.plan = plan
        self.state = "ATTESTED"

    def stage(self, plan: CutoverPlan, lease: cleanup.BocaJobLease) -> None:
        self._guard(plan, lease, "ATTESTED")
        stage.initialize(
            plan.attempt_id,
            plan.legacy_id,
            plan.legacy_sha,
            plan.legacy_compose_sha,
            plan.target_sha,
            plan.target_image,
            plan.browser_image,
            plan.target_compose_sha,
            plan.overlay_sha,
            plan.seccomp_sha,
        )
        for slot, reviewed, digest in (
            ("base", self.sources.base, plan.target_compose_sha),
            ("overlay", self.sources.overlay, plan.overlay_sha),
            ("seccomp", self.sources.seccomp, plan.seccomp_sha),
        ):
            stage.upload(
                slot, digest, plan.attempt_id, plan.legacy_compose_sha, io.BytesIO(reviewed)
            )
        directory = stage.verify(plan.attempt_id, plan.legacy_compose_sha)
        if directory != _stage_path(plan):
            raise CutoverError("cutover authenticated stage path drifted")
        if self.on_demand:
            from boca_socios.host_on_demand_service import control_directory

            self.control_directory = control_directory()
        host._browser_compose_model(
            plan.target_image,
            plan.origin,
            plan.owner_subject,
            plan.browser_image,
            plan.attempt_id,
            base_file=directory / "compose.beta.yaml",
            overlay_file=directory / "compose.beta.browser.yaml",
            seccomp_file=directory / "seccomp_profile.json",
            control_directory=self.control_directory,
        )
        self.worker_hash = _reviewed_compose_hash(
            plan, "browser-worker", control_directory=self.control_directory
        )
        self.controller_hash = _reviewed_compose_hash(
            plan, "controller", control_directory=self.control_directory
        )
        self.state = "STAGED"

    def prepare_worker(self, plan: CutoverPlan, lease: cleanup.BocaJobLease) -> str:
        from boca_socios.worker_start_receipt import persist_before_cleanup

        self._guard(plan, lease, "STAGED")
        if not self.worker_hash or not self.controller_hash:
            raise CutoverError("cutover Compose service hashes absent")
        primary = "ATTEST"

        def note_phase(phase: str) -> None:
            nonlocal primary
            primary = phase

        try:
            seccomp = stage.read_verified(plan.attempt_id, plan.legacy_compose_sha, "seccomp")
            primary = "STORAGE"
            host._browser_pull_both(
                plan.target_image, plan.browser_image, plan.target_sha, phase_hook=note_phase
            )
            primary = "ATTEST"
            worker = host._cutover_prepare_worker(
                plan.legacy_id,
                plan.legacy_image,
                plan.legacy_sha,
                plan.browser_image,
                plan.target_sha,
                plan.attempt_id,
                self.worker_hash,
                plan.seccomp_sha,
                seccomp,
                lambda cid, result: persist_before_cleanup(plan, lease, cid, result),
                on_demand=self.on_demand,
            )
        except host.CutoverWorkerPhaseError:
            raise
        except (host.PreflightError, OSError, ValueError, KeyError, TypeError):
            # The error's message may contain private Docker details. Only
            # the known executing operation is allowed to cross this boundary.
            raise host.CutoverWorkerPhaseError(primary, "UNVERIFIED") from None
        if not _HEX.fullmatch(worker) or worker == plan.legacy_id:
            raise CutoverError("cutover worker exact ID untrusted")
        self.worker_id = worker
        self.state = "WORKER"
        return worker

    def park_original(self, plan: CutoverPlan, lease: cleanup.BocaJobLease) -> None:
        self._guard(plan, lease, "WORKER")
        if self.on_demand:
            self.database_identity = _controller_database_identity(plan.legacy_id)
        host._cutover_park_original(
            plan.legacy_id, plan.legacy_image, plan.legacy_sha, plan.attempt_id
        )
        self.state = "PARKED"

    def bootstrap_owner_session(self, plan: CutoverPlan, lease: cleanup.BocaJobLease) -> None:
        self._guard(plan, lease, "PARKED")
        if self.on_demand:
            if self.database_identity is None:
                raise CutoverError("on-demand parked database identity missing")
            self.database_path = _verified_data_volume_path(plan)
            result = _bootstrap_in_data_namespace(plan, self.database_identity)
            self._guard(plan, lease, "PARKED")
            if result not in ("APPLIED", "ALREADY_APPLIED") or (
                _verified_data_volume_path(plan) != self.database_path
            ):
                raise CutoverError("private same-volume session bootstrap unverified")
            self.state = "BOOTSTRAPPED"
            return
        path, db_identity = _legacy_disk_identity(plan)
        bootstrap = self.session_bootstrap or _stdlib_session_bootstrap()
        outcome = bootstrap(
            path,
            held_lease_fd=lease.fd,
            expected_db_identity=db_identity,
            session_schema_bytes=self.sources.session_sql,
        )
        if outcome not in ("APPLIED", "ALREADY_APPLIED"):
            raise CutoverError("independent owner session SQLite bootstrap unverified")
        if _legacy_disk_identity(plan) != (path, db_identity):
            raise CutoverError("legacy SQLite inode changed during Option B bootstrap")
        self.state = "BOOTSTRAPPED"

    def activate_candidate(
        self, plan: CutoverPlan, worker_id: str, lease: cleanup.BocaJobLease
    ) -> str:
        self._guard(plan, lease, "BOOTSTRAPPED")
        if not self.controller_hash:
            raise CutoverError("cutover candidate Compose hash absent")
        seccomp = stage.read_verified(plan.attempt_id, plan.legacy_compose_sha, "seccomp")
        if self.on_demand:
            from boca_socios.host_on_demand_service import prepare_control_directory

            if self.control_directory is None or self.worker_id != worker_id:
                raise CutoverError("on-demand binding missing before controller creation")
            self.control_prepared = True
            if prepare_control_directory(plan.attempt_id, lease) != self.control_directory:
                raise CutoverError("on-demand controller socket directory changed")
        candidate = host._cutover_activate_candidate(
            plan.legacy_id,
            plan.legacy_image,
            plan.legacy_sha,
            plan.target_image,
            plan.target_sha,
            plan.browser_image,
            worker_id,
            plan.attempt_id,
            plan.origin,
            plan.owner_subject,
            self.controller_hash,
            plan.seccomp_sha,
            seccomp,
            control_directory=self.control_directory,
            worker_config_hash=self.worker_hash,
        )
        if not _HEX.fullmatch(candidate) or candidate in (plan.legacy_id, worker_id):
            raise CutoverError("cutover candidate exact ID untrusted")
        self.candidate_id = candidate
        self.state = "CANDIDATE"
        return candidate

    def accept_candidate(
        self,
        plan: CutoverPlan,
        candidate_id: str,
        worker_id: str,
        lease: cleanup.BocaJobLease,
    ) -> None:
        from boca_socios.host_cutover_ipc_probe import verify_controller_peer

        self._guard(plan, lease, "CANDIDATE")
        if self.on_demand:
            from boca_socios.host_lifecycle_rootless_adapter import ReviewedInstalledPair
            from boca_socios.host_on_demand_lifecycle import OnDemandInstallation
            from boca_socios.host_on_demand_service import install_control

            if not self.worker_hash or not self.controller_hash or self.database_path is None:
                raise CutoverError("on-demand verified installation coordinates missing")
            self._verify_cold_pair(plan, candidate_id, worker_id)
            host._cutover_compose_pair(
                candidate_id,
                worker_id,
                plan.target_image,
                plan.browser_image,
                plan.origin,
                plan.owner_subject,
                plan.attempt_id,
                _stage_path(plan),
                control_directory=self.control_directory,
                parked_original=plan.legacy_id,
            )
            self.installation = OnDemandInstallation(
                installation_run_id=plan.attempt_id,
                source_sha=plan.target_sha,
                controller_id=candidate_id,
                controller_image=plan.target_image,
                worker_id=worker_id,
                worker_image=plan.browser_image,
                database_path=self.database_path,
                pair=ReviewedInstalledPair(plan.attempt_id, self.controller_hash, self.worker_hash),
            )
            install_control(self.installation, lease)
            self._cycle_idle_panel(plan, candidate_id, worker_id, lease)
        else:
            if not self.controller_hash:
                raise CutoverError("cutover candidate resolved Compose hash missing")
            if not host._cutover_candidate_postflight(
                candidate_id,
                plan.target_image,
                plan.target_sha,
                plan.attempt_id,
                plan.origin,
                plan.owner_subject,
                self.controller_hash,
            ):
                raise CutoverError("cutover candidate not healthy/running by exact ID")
            verify_controller_peer(candidate_id)
            host._browser_worker_postflight(
                worker_id,
                plan.browser_image,
                plan.target_sha,
                plan.attempt_id,
                plan.seccomp_sha,
                staged_seccomp=self.sources.seccomp,
            )
            host._beta_loopback_health(candidate_id, plan.origin)
        legacy_record = host._cutover_legacy_record(
            plan.legacy_id,
            plan.legacy_image,
            plan.legacy_sha,
            name=f"boca-socios-controller-legacy-{plan.attempt_id}",
            running=False,
            restart_policy="no",
        )
        self.legacy_image_proof, self.retained_image_proof = _precommit_legacy_image_cleanup(
            plan, legacy_record, candidate_id, worker_id
        )
        self.state = "ACCEPTED"

    def _verify_cold_pair(self, plan: CutoverPlan, candidate: str, worker: str) -> None:
        from boca_socios.host_lifecycle_rootless_adapter import ProductionRootlessDockerIO

        if (
            candidate != self.candidate_id
            or worker != self.worker_id
            or self.control_directory is None
            or not self.worker_hash
            or not self.controller_hash
            or not host._cutover_candidate_postflight(
                candidate,
                plan.target_image,
                plan.target_sha,
                plan.attempt_id,
                plan.origin,
                plan.owner_subject,
                self.controller_hash,
                control_directory=self.control_directory,
            )
        ):
            raise CutoverError("on-demand controller identity or health unverified")
        host._cutover_idle_worker(
            worker,
            plan.browser_image,
            plan.target_sha,
            plan.attempt_id,
            plan.seccomp_sha,
            self.sources.seccomp,
            self.worker_hash,
        )
        host._beta_loopback_health(candidate, plan.origin)
        engine = ProductionRootlessDockerIO().engine_request(candidate, "status")
        if (
            engine.state != "STOPPED"
            or engine.changed
            or type(engine.pid) is not int
            or engine.pid <= 0
        ):
            raise CutoverError("on-demand controller engine did not confirm STOPPED")

        if _controller_database_identity(candidate) != self.database_identity or (
            host._run(
                "docker",
                "exec",
                "--user",
                "10001:10001",
                candidate,
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
            raise CutoverError("on-demand candidate ledger identity/schema unverified")

    def _cycle_idle_panel(
        self,
        plan: CutoverPlan,
        candidate: str,
        worker: str,
        lease: cleanup.BocaJobLease,
    ) -> None:
        """Exercise one panel cold boot while rollback to the parked original is possible."""
        from boca_socios.host_on_demand_service import verify_control

        self._guard(plan, lease, "CANDIDATE")
        if (
            candidate != self.candidate_id
            or worker != self.worker_id
            or self.control_directory is None
            or self.installation is None
        ):
            raise CutoverError("on-demand panel restart coordinates unavailable")
        socket_identity = _verify_mounted_control(candidate, self.control_directory)
        host._cutover_legacy_record(
            plan.legacy_id,
            plan.legacy_image,
            plan.legacy_sha,
            name=f"boca-socios-controller-legacy-{plan.attempt_id}",
            running=False,
            restart_policy="no",
        )
        if host._run("docker", "stop", "--time", "8", candidate, timeout=30) != candidate:
            raise CutoverError("on-demand panel stop receipt unverified")
        stopped = host._run(
            "docker",
            "inspect",
            "--type",
            "container",
            "--format",
            "{{.Id}} {{.State.Status}} {{.State.Pid}} {{.State.Running}} "
            "{{.State.Restarting}} {{.State.Dead}}",
            candidate,
            timeout=8,
        )
        if stopped != f"{candidate} exited 0 false false false":
            raise CutoverError("on-demand panel did not reach exited with zero processes")
        self._guard(plan, lease, "CANDIDATE")
        if host._run("docker", "start", candidate, timeout=30) != candidate:
            raise CutoverError("on-demand panel restart receipt unverified")
        host._browser_wait_healthy(candidate)
        self._verify_cold_pair(plan, candidate, worker)
        verify_control(self.installation, lease)
        if _verify_mounted_control(candidate, self.control_directory) != socket_identity:
            raise CutoverError("on-demand control socket was replaced during panel restart")

    def _disable_control(self, plan: CutoverPlan, lease: cleanup.BocaJobLease) -> None:
        if self.control_prepared:
            from boca_socios.host_on_demand_service import remove_control

            remove_control(plan.attempt_id, lease)
            self.control_prepared = False

    def retire_original(
        self,
        plan: CutoverPlan,
        candidate_id: str,
        worker_id: str,
        lease: cleanup.BocaJobLease,
    ) -> None:
        self._guard(plan, lease, "ACCEPTED")
        if not self.controller_hash:
            raise CutoverError("cutover retirement Compose hash absent")
        if self.legacy_image_proof is None:
            raise CutoverError("cutover old image identity not attested before commit")
        # Durable, irreversible O_EXCL intent BEFORE replacing legacy Compose;
        # a crash here is fix-forward NO_GO and must never revive old ID.
        stage.promote_accepted(plan.attempt_id, plan.legacy_compose_sha, candidate_id, worker_id)
        host._cutover_retire_accepted_original(
            plan.legacy_id,
            plan.legacy_image,
            plan.legacy_sha,
            candidate_id,
            plan.target_image,
            plan.target_sha,
            worker_id,
            plan.browser_image,
            plan.attempt_id,
            plan.origin,
            plan.owner_subject,
            self.controller_hash,
            plan.seccomp_sha,
            self.sources.seccomp,
            _stage_path(plan),
            control_directory=self.control_directory,
            worker_config_hash=self.worker_hash,
        )
        self.state = "COMMITTED"

    def recover_original(self, plan: CutoverPlan, lease: cleanup.BocaJobLease) -> bool:
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        if self.plan != plan or self.state in ("INIT", "COMMITTED", "ACCEPTED"):
            return False
        self._disable_control(plan, lease)
        if self.on_demand and self.state == "PARKED" and self.database_path is not None:
            _verified_data_volume_path(plan)  # A lost one-shot may still own the data volume.
        # Existing helper compensates candidate before worker, verifies each
        # exact ID and only then revives the original ID if localhost is free.
        # Its own partial rollback may already have restored the original.
        original_name = f"boca-socios-controller-legacy-{plan.attempt_id}"
        record = host._browser_inspect_record(plan.legacy_id)
        if record.get("Name") == "/boca-socios-controller-1":
            host._cutover_legacy_record(
                plan.legacy_id,
                plan.legacy_image,
                plan.legacy_sha,
                name="boca-socios-controller-1",
                running=True,
            )
        elif record.get("Name") == f"/{original_name}":
            if not self.controller_hash:
                raise CutoverError("cutover candidate rollback hash missing")
            host._cutover_compensate_candidate(
                plan.legacy_id,
                plan.legacy_image,
                plan.legacy_sha,
                plan.target_image,
                plan.target_sha,
                plan.attempt_id,
                plan.origin,
                plan.owner_subject,
                self.controller_hash,
                control_directory=self.control_directory,
                expected_candidate=self.candidate_id,
            )
        else:
            raise CutoverError("cutover original exact-ID name drifted during recovery")
        if host._cutover_worker_name_id() is not None:
            host._cutover_compensate_worker(
                plan.browser_image,
                plan.target_sha,
                plan.attempt_id,
                plan.seccomp_sha,
                self.sources.seccomp,
                self.worker_id,
            )
        host._cutover_legacy_record(
            plan.legacy_id,
            plan.legacy_image,
            plan.legacy_sha,
            name="boca-socios-controller-1",
            running=True,
        )
        self.state = "RECOVERED"
        return True

    def finalize(
        self,
        plan: CutoverPlan,
        *,
        commit_started: bool,
        candidate_id: str | None,
        worker_id: str | None,
        lease: cleanup.BocaJobLease,
    ) -> Literal["ACCEPT", "NO_GO", "INDETERMINATE"] | cleanup.CleanupReceipt:
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        if self.plan != plan:
            return "NO_GO"
        try:
            return self._finalize(
                plan,
                commit_started=commit_started,
                candidate_id=candidate_id,
                worker_id=worker_id,
                lease=lease,
            )
        finally:
            if self.on_demand and commit_started and not self.idle_installed:
                self._disable_control(plan, lease)

    def _finalize(
        self,
        plan: CutoverPlan,
        *,
        commit_started: bool,
        candidate_id: str | None,
        worker_id: str | None,
        lease: cleanup.BocaJobLease,
    ) -> Literal["ACCEPT", "NO_GO", "INDETERMINATE"] | cleanup.CleanupReceipt:
        safely_recovered = self.state == "RECOVERED" and not commit_started
        safely_committed = (
            self.state == "COMMITTED"
            and commit_started
            and candidate_id is not None
            and worker_id is not None
        )
        if not (safely_recovered or safely_committed):
            # Symmetric uncertainty barrier. A failed precommit compensation
            # may leave legacy PARKED and worker/candidate alive; a lost
            # irreversible retirement receipt may mean legacy already GONE.
            # In either case deleting *anything* with the generic planner
            # risks the only living service or exact-ID recovery evidence.
            # Read-only inventory under held lease, NO retries or prune.
            cleanup.capture_inventory()
            return "NO_GO"
        # Destructive finalizer only after POSITIVE old-ID recovery or POSITIVE
        # candidate acceptance plus old-ID retirement. Missing IDs never fall
        # back to protecting a guessed/missing legacy identity.
        if safely_recovered:
            preserve: frozenset[str] = frozenset({plan.legacy_id})
        else:
            if candidate_id is None or worker_id is None or self.legacy_image_proof is None:
                return "NO_GO"
            preserve = frozenset({candidate_id, worker_id})
        outcome: Literal["SUCCESS", "FAILURE"] = "FAILURE" if safely_recovered else "SUCCESS"
        retained = self.retained_image_proof
        if safely_recovered and retained is None:
            # No irreversible commit occurred. Freshly attest the same exact
            # preexisting orphan for the failed-attempt cleanup path too.
            observed = cleanup.capture_inventory()
            if cleanup.HISTORICAL_RETIRE_TARGET in observed.global_image_ids or any(
                i.ident == cleanup.HISTORICAL_RETIRE_TARGET for i in observed.images
            ):
                retained = cleanup.attest_historical_retained_image(observed)
        receipt = cleanup.execute_protected(
            outcome,
            plan.attempt_id,
            preserve_images=frozenset(),
            preserve_containers=preserve,
            retire_containers=frozenset(),
            lease=lease,
            historical_legacy=self.legacy_image_proof if safely_committed else None,
            historical_retained=retained,
        )
        if receipt.status != "ACCEPT":
            return receipt
        if self.state == "RECOVERED" and not commit_started:
            stage.discard_recovered(plan.attempt_id, plan.legacy_compose_sha)
        elif self.state == "COMMITTED" and commit_started and candidate_id and worker_id:
            if self.on_demand:
                from boca_socios.host_on_demand_service import verify_control

                if self.installation is None or self.control_directory is None:
                    return "NO_GO"
                self._verify_cold_pair(plan, candidate_id, worker_id)
                verify_control(self.installation, lease)
                _verify_mounted_control(candidate_id, self.control_directory)
            stage.finalize_promoted(
                plan.attempt_id, plan.legacy_compose_sha, candidate_id, worker_id
            )
            self.idle_installed = self.on_demand
        else:
            return "NO_GO"
        # Preserve the SAME attested before/after metrics and exact removed IDs
        # through the terminal Cutover receipt; status-only loses P0 evidence.
        return receipt


def execute_reviewed_cutover(
    plan: CutoverPlan, *, prepare_run_id: str | None = None, dispatch_v3: bool = False
) -> CutoverReceipt:
    """One Boca-only host transaction with optional exact PREPARE consumption.

    The old run-bound path is unchanged. PREPARE is consumed only after exact
    legacy/controller/rootless/data-volume attestation under the *same* lease,
    but before any stage, image pull, stop, SQLite or cleanup. The marker is
    created inside the EXISTING /data volume by the attested legacy controller
    UID10001, avoiding unsafe host/subuid assumptions. A crash after O_EXCL
    quarantines the PREPARE forever; no blind delete or retry.
    """
    import json
    from dataclasses import asdict

    from boca_socios import host_boca_cutover_receipt as terminal

    plan.validate()
    if prepare_run_id is not None and (
        type(prepare_run_id) is not str
        or re.fullmatch(r"[1-9][0-9]{0,19}\Z", prepare_run_id) is None
        or prepare_run_id == plan.attempt_id
    ):
        raise CutoverError("cutover prepared GO identity invalid")
    sources = ReviewedCutoverSources.from_verified_zip()
    sources.validate(plan)
    # Only the authenticated overlay may request this profile. Compose resolves
    # and checks its actual service/environment/bind before any Docker creation.
    on_demand = any(
        line.lstrip().startswith(b"BOCA_BOT_CONTROL:") for line in sources.overlay.splitlines()
    )
    if on_demand and (dispatch_v3 is not True or prepare_run_id is not None):
        raise CutoverError("on-demand installation requires authenticated V3 dispatch")
    backend = RootlessCutoverBackend(sources, on_demand=on_demand)

    def terminal_preflight(prepared_plan: CutoverPlan, lease: cleanup.BocaJobLease) -> None:
        terminal.prepare_destination(prepared_plan, lease)

    def terminal_sink(
        completed_plan: CutoverPlan, result: CutoverReceipt, lease: cleanup.BocaJobLease
    ) -> None:
        record = terminal.TerminalRecord.from_receipt(completed_plan, result)
        terminal.write_once(record, plan=completed_plan, lease=lease)

    # The legacy controller is a Python image. The constant stdlib-only code
    # runs under docker exec in its exact authenticated CID, with network and
    # Docker daemon unchanged. It opens only /data and creates one marker.
    marker_program = r"""
import hashlib
import json
import os
import re
import stat
import sys

raw = sys.stdin.buffer.read(2049)
if not 0 < len(raw) <= 2048:
    raise SystemExit(3)
def unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate prepared GO field")
        out[key] = value
    return out
try:
    record = json.loads(raw.decode("ascii"), object_pairs_hook=unique)
except (ValueError, UnicodeError):
    raise SystemExit(3) from None
if (
    type(record) is not dict
    or set(record) != {"version", "operation", "prepare_run_id", "plan"}
    or record.get("version") != "boca-cutover-prepared-use-v1"
    or record.get("operation") != "cutover-a-apply"
    or type(record.get("plan")) is not dict
    or any(type(v) is not str or len(v) > 256 for v in record["plan"].values())
    or type(record.get("prepare_run_id")) is not str
    or re.fullmatch(r"[1-9][0-9]{0,19}\Z", record["prepare_run_id"]) is None
    or record["prepare_run_id"] != sys.argv[1]
    or json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii") != raw
    or os.getuid() != 10001
    or os.geteuid() != 10001
):
    raise SystemExit(3)
name = ".boca-cutover-prepared-go-" + record["prepare_run_id"] + ".json"
directory = os.open("/data", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
try:
    info = os.fstat(directory)
    free = os.statvfs(directory)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != 10001
        or info.st_gid != 10001
        or stat.S_IMODE(info.st_mode) & 0o022
        or free.f_bavail * free.f_frsize < 8192
        or free.f_favail < 2
    ):
        raise SystemExit(3)
    output = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600, dir_fd=directory,
    )
    try:
        os.fchmod(output, 0o600)
        with os.fdopen(output, "wb", closefd=False) as target:
            target.write(raw)
            target.flush()
            os.fsync(target.fileno())
    finally:
        os.close(output)
    os.fsync(directory)
    marker = os.open(
        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
        dir_fd=directory,
    )
    try:
        identity = os.fstat(marker)
        readback = os.read(marker, 2049)
        after = os.fstat(marker)
        if (
            not stat.S_ISREG(identity.st_mode)
            or identity.st_uid != 10001
            or identity.st_gid != 10001
            or identity.st_nlink != 1
            or stat.S_IMODE(identity.st_mode) != 0o600
            or identity.st_size != len(raw)
            or readback != raw
            or (identity.st_dev, identity.st_ino, identity.st_mtime_ns)
               != (after.st_dev, after.st_ino, after.st_mtime_ns)
        ):
            raise SystemExit(3)
    finally:
        os.close(marker)
finally:
    os.close(directory)
print(
    "BOCA_CUTOVER_PREPARED_GO state=CONSUMED prepare_run_id="
    + record["prepare_run_id"] + " sha256=" + hashlib.sha256(raw).hexdigest()
)
"""

    def consume_prepared(
        prepared_plan: CutoverPlan, approved_prepare_id: str, lease: cleanup.BocaJobLease
    ) -> None:
        cleanup.verify_protected_boca_job_lease(lease, prepared_plan.attempt_id)
        # attest_original() already proved exact running/healthy controller,
        # fixed loopback8443, project, no browser worker and three named mounts.
        # Recheck the immutable rootless Docker endpoint and named /data volume.
        host._validate_docker_boundary()
        host._validate_data_volume()
        public_plan = asdict(prepared_plan)
        public_plan.pop("owner_subject")
        public_plan["owner_subject_sha256"] = hashlib.sha256(
            prepared_plan.owner_subject.encode("ascii")
        ).hexdigest()
        raw = json.dumps(
            {
                "version": "boca-cutover-prepared-use-v1",
                "operation": "cutover-a-apply",
                "prepare_run_id": approved_prepare_id,
                "plan": public_plan,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        if not 0 < len(raw) <= 2048:
            raise CutoverError("cutover prepared marker payload unbounded")
        expected = (
            "BOCA_CUTOVER_PREPARED_GO state=CONSUMED prepare_run_id="
            + approved_prepare_id
            + " sha256="
            + hashlib.sha256(raw.encode("ascii")).hexdigest()
        )
        try:
            observed = host._run(
                "docker",
                "exec",
                "-i",
                "--user",
                "10001:10001",
                prepared_plan.legacy_id,
                "python",
                "-c",
                marker_program,
                approved_prepare_id,
                input_data=raw,
                timeout=20,
            )
            if observed != expected:
                raise CutoverError("cutover durable PREPARE marker receipt differs")
            host._cutover_observe(
                prepared_plan.legacy_image,
                prepared_plan.legacy_sha,
                prepared_plan.legacy_compose_sha,
                prepared_plan.origin,
                prepared_plan.owner_subject,
                prepared_plan.target_image,
                prepared_plan.target_sha,
                prepared_plan.browser_image,
                prepared_plan.legacy_id,
            )
        except (OSError, ValueError) as exc:
            raise CutoverError("cutover PREPARE consumption or reattestation unproven") from exc
        cleanup.verify_protected_boca_job_lease(lease, prepared_plan.attempt_id)

    return run_cutover_a(
        plan,
        backend=backend,
        terminal_preflight=terminal_preflight,
        terminal_sink=terminal_sink,
        prepare_run_id=prepare_run_id,
        prepared_go_consumer=consume_prepared if prepare_run_id is not None else None,
    )
