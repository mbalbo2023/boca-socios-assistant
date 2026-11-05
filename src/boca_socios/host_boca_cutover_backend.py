"""Exact-ID rootless host adapter for Cutover A; intentionally NOT wired to CLI.

This is real host-facing code backed by existing well-tested cutover helpers,
not merely a fake protocol. The legacy singleton is observed first, remains
running until a new attempt worker is healthy, and its original container ID
is never inferred from names. Only a separate protected workflow with a GO,
two reviewed release manifests and one SSH process may construct this adapter.
No current GitHub Action does so. All destructive host functions are unreachable
by the authenticated ZIP's public main() until a later acceptance gate lands.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import re
import stat
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_cutover_stage as stage
from boca_socios import host_first_deploy as host
from boca_socios.host_boca_cutover import (
    CutoverError,
    CutoverPlan,
    CutoverReceipt,
    run_cutover_a,
)

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
) -> cleanup.LegacyImageProof:
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
        planned = cleanup.plan(
            inventory,
            plan.attempt_id,
            preserve_images=frozenset({proof.ident}),
            preserve_containers=frozenset({plan.legacy_id, candidate_id, worker_id}),
            retire_containers=frozenset(),
        )
        if planned.uncertain:
            # A new legacy/foreign orphan discovered after COMMITTED cannot
            # be safely deleted or declared cleaned. Stop while old CID is
            # still recoverable; never weaken generic cleanup classification.
            raise cleanup.CleanupError("Boca cleanup has precommit unknown residue")
        return proof
    except (cleanup.CleanupError, OSError, ValueError) as exc:
        raise CutoverError("cutover precommit exact legacy image cleanup unproven") from exc


def _reviewed_compose_hash(plan: CutoverPlan, service: str) -> str:
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
        ),
    )
    # Compose v2 versions print either the one hash or SERVICE<space>HASH.
    match = re.fullmatch(rf"(?:{re.escape(service)}[ \t]+)?([0-9a-f]{{64}})", output)
    if match is None:
        raise CutoverError("cutover resolved Compose service hash uncertain")
    return match.group(1)


def _legacy_disk_identity(plan: CutoverPlan) -> tuple[Path, tuple[int, int]]:
    """Owner-independent, rootless Boca data path; no foreign volume reads."""
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
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 10001
        or metadata.st_gid != 10001
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        raise CutoverError("Boca legacy DB inode/owner/mode untrusted")
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
    return path, (metadata.st_dev, metadata.st_ino)


class RootlessCutoverBackend:
    """One ephemeral guarded host adapter. Must be passed to run_cutover_a()."""

    # Unlike injected fake backends, effectful rootless Docker can never run
    # without BOTH the early persistent intent and terminal result writer.
    requires_persistent_receipt = True

    def __init__(
        self, sources: ReviewedCutoverSources, *, session_bootstrap: Bootstrap | None = None
    ) -> None:
        self.sources = sources
        self.session_bootstrap = session_bootstrap
        self.state: State = "INIT"
        self.plan: CutoverPlan | None = None
        self.worker_hash: str | None = None
        self.controller_hash: str | None = None
        self.legacy_image_proof: cleanup.LegacyImageProof | None = None

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
        host._browser_compose_model(
            plan.target_image,
            plan.origin,
            plan.owner_subject,
            plan.browser_image,
            plan.attempt_id,
            base_file=directory / "compose.beta.yaml",
            overlay_file=directory / "compose.beta.browser.yaml",
            seccomp_file=directory / "seccomp_profile.json",
        )
        self.worker_hash = _reviewed_compose_hash(plan, "browser-worker")
        self.controller_hash = _reviewed_compose_hash(plan, "controller")
        self.state = "STAGED"

    def prepare_worker(self, plan: CutoverPlan, lease: cleanup.BocaJobLease) -> str:
        self._guard(plan, lease, "STAGED")
        if not self.worker_hash or not self.controller_hash:
            raise CutoverError("cutover Compose service hashes absent")
        seccomp = stage.read_verified(plan.attempt_id, plan.legacy_compose_sha, "seccomp")
        host._browser_pull_both(plan.target_image, plan.browser_image, plan.target_sha)
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
        )
        if not _HEX.fullmatch(worker) or worker == plan.legacy_id:
            raise CutoverError("cutover worker exact ID untrusted")
        self.state = "WORKER"
        return worker

    def park_original(self, plan: CutoverPlan, lease: cleanup.BocaJobLease) -> None:
        self._guard(plan, lease, "WORKER")
        host._cutover_park_original(
            plan.legacy_id, plan.legacy_image, plan.legacy_sha, plan.attempt_id
        )
        self.state = "PARKED"

    def bootstrap_owner_session(self, plan: CutoverPlan, lease: cleanup.BocaJobLease) -> None:
        self._guard(plan, lease, "PARKED")
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
        )
        if not _HEX.fullmatch(candidate) or candidate in (plan.legacy_id, worker_id):
            raise CutoverError("cutover candidate exact ID untrusted")
        self.state = "CANDIDATE"
        return candidate

    def accept_candidate(
        self,
        plan: CutoverPlan,
        candidate_id: str,
        worker_id: str,
        lease: cleanup.BocaJobLease,
    ) -> None:
        self._guard(plan, lease, "CANDIDATE")
        if not self.controller_hash:
            raise CutoverError("cutover candidate resolved Compose hash missing")
        seccomp = stage.read_verified(plan.attempt_id, plan.legacy_compose_sha, "seccomp")
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
        host._browser_worker_postflight(
            worker_id,
            plan.browser_image,
            plan.target_sha,
            plan.attempt_id,
            plan.seccomp_sha,
            staged_seccomp=seccomp,
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
        self.legacy_image_proof = _precommit_legacy_image_cleanup(
            plan, legacy_record, candidate_id, worker_id
        )
        self.state = "ACCEPTED"

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
        )
        self.state = "COMMITTED"

    def recover_original(self, plan: CutoverPlan, lease: cleanup.BocaJobLease) -> bool:
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        if self.plan != plan or self.state in ("INIT", "COMMITTED", "ACCEPTED"):
            return False
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
        receipt = cleanup.execute_protected(
            outcome,
            plan.attempt_id,
            preserve_images=frozenset(),
            preserve_containers=preserve,
            retire_containers=frozenset(),
            lease=lease,
            historical_legacy=self.legacy_image_proof if safely_committed else None,
        )
        if receipt.status != "ACCEPT":
            return receipt
        if self.state == "RECOVERED" and not commit_started:
            stage.discard_recovered(plan.attempt_id, plan.legacy_compose_sha)
        elif self.state == "COMMITTED" and commit_started and candidate_id and worker_id:
            stage.finalize_promoted(
                plan.attempt_id, plan.legacy_compose_sha, candidate_id, worker_id
            )
        else:
            return "NO_GO"
        # Preserve the SAME attested before/after metrics and exact removed IDs
        # through the terminal Cutover receipt; status-only loses P0 evidence.
        return receipt


def execute_reviewed_cutover(
    plan: CutoverPlan, *, prepare_run_id: str | None = None
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
    backend = RootlessCutoverBackend(sources)

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
