"""Boca-only GHCR/rootless worker preflight; no GO, IPC, port or navigation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from boca_socios import host_first_deploy as host
from boca_socios.host_boca_cleanup import protected_boca_job_lease

ATTEMPT = re.compile(r"[1-9][0-9]{0,19}\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
ID = re.compile(r"[0-9a-f]{64}\Z")
PREFIX = "boca-socios-cutover-preflight-"
LABEL = "boca.socios.cutover-preflight-attempt"
RUNTIME = Path("/run/user/10001")
PHASES = frozenset(
    {
        "ATTEST",
        "GHCR_PULL",
        "SECCOMP_ENTER",
        "WORKER_CREATE",
        "WORKER_START",
        "WORKER_BOUNDARY",
        "CLEANUP",
    }
)
PRIMARY_PHASES = (PHASES - {"CLEANUP"}) | {"NONE", "UNVERIFIED"}
CLEANUP_STAGES = frozenset(
    {
        "NONE",
        "TEMP_SECCOMP",
        "PS",
        "INSPECT",
        "OWNERSHIP",
        "STOP",
        "RM",
        "POST_ID",
        "LEGACY",
        "UNVERIFIED",
    }
)
STOP_FAILURE_CAUSES = frozenset(
    {
        "NONE",
        "TIMEOUT",
        "NONZERO",
        "OSERROR",
        "ACK_MISMATCH",
        "ACK_EMPTY",
        "ACK_SHORT_ID",
        "ACK_NAME",
        "ACK_MULTILINE",
        "ACK_OTHER_ID",
        "UNVERIFIED",
    }
)
BOUNDARY_COMMAND = (
    "import os\n"
    "from pathlib import Path\n"
    "def require(condition):\n"
    "    if not condition:\n"
    "        raise SystemExit(3)\n"
    "require(os.geteuid()==os.getegid()==10002)\n"
    "root=Path('/sys/fs/cgroup')\n"
    "memory=int((root/'memory.max').read_text())\n"
    "pids=int((root/'pids.max').read_text())\n"
    "quota,period=map(int,(root/'cpu.max').read_text().split())\n"
    "require(0<memory<=805306368 and 0<pids<=128 and 0<quota<=period)\n"
    "status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)\n"
    "require(int(status['NoNewPrivs'])==1 and int(status['Seccomp'])==2)\n"
    "require(int(status['Seccomp_filters'])>=1)\n"
    "require(os.listdir('/sys/class/net')==['lo'])\n"
    "print('BOCA_CUTOVER_WORKER_BOUNDARY_PASS')\n"
)


class WorkerPreflightError(ValueError):
    """Fail closed."""


class TempSeccompCleanupError(WorkerPreflightError):
    """Unverified cleanup."""


class CleanupStageError(WorkerPreflightError):
    """Bounded stage classification; no raw Docker output crosses the boundary."""

    def __init__(self, stage: str, *, stop_failure_cause: str = "UNVERIFIED") -> None:
        self.stage = stage if stage in CLEANUP_STAGES else "UNVERIFIED"
        self.stop_failure_cause = "NONE"
        if self.stage == "STOP":
            self.stop_failure_cause = (
                stop_failure_cause
                if stop_failure_cause in STOP_FAILURE_CAUSES - {"NONE"}
                else "UNVERIFIED"
            )
        message = (
            "probe cleanup exact ownership unverified"
            if self.stage == "OWNERSHIP"
            else "probe exact cleanup stage unverified"
        )
        super().__init__(message)


class PreflightFailure(WorkerPreflightError):
    def __init__(
        self,
        phase: str,
        cleanup: str,
        *,
        primary_failed_phase: str = "UNVERIFIED",
        cleanup_failed_stage: str = "UNVERIFIED",
        stop_failure_cause: str = "UNVERIFIED",
    ) -> None:
        super().__init__("bounded pre-Cutover probe failed")
        self.phase = phase if phase in PHASES else "UNVERIFIED"
        self.cleanup = cleanup if cleanup in {"VERIFIED", "INDETERMINATE"} else "UNVERIFIED"
        self.primary_failed_phase = (
            primary_failed_phase if primary_failed_phase in PRIMARY_PHASES else "UNVERIFIED"
        )
        self.cleanup_failed_stage = (
            cleanup_failed_stage if cleanup_failed_stage in CLEANUP_STAGES else "UNVERIFIED"
        )
        self.stop_failure_cause = "NONE"
        if self.cleanup_failed_stage == "STOP":
            self.stop_failure_cause = (
                stop_failure_cause
                if stop_failure_cause in STOP_FAILURE_CAUSES - {"NONE"}
                else "UNVERIFIED"
            )


@dataclass(frozen=True)
class Coordinates:
    attempt: str
    source: str
    controller: str
    browser: str
    legacy_source: str
    legacy_image: str
    legacy_id: str

    def validate(self) -> None:
        if (
            not ATTEMPT.fullmatch(self.attempt)
            or not SHA.fullmatch(self.source)
            or not SHA.fullmatch(self.legacy_source)
            or self.source == self.legacy_source
            or not host.IMAGE_PATTERN.fullmatch(self.controller)
            or not host.BROWSER_IMAGE_PATTERN.fullmatch(self.browser)
            or not host.IMAGE_PATTERN.fullmatch(self.legacy_image)
            or self.controller == self.legacy_image
            or not ID.fullmatch(self.legacy_id)
        ):
            raise WorkerPreflightError("unreviewed preflight coordinates")


def _reviewed_seccomp() -> bytes:
    with zipfile.ZipFile(sys.argv[0], "r") as bundle:
        profile = bundle.read("docker/seccomp_profile.json")
    if not 0 < len(profile) <= 32768 or not isinstance(json.loads(profile), dict):
        raise WorkerPreflightError("reviewed seccomp profile unavailable")
    return profile


@contextmanager
def _temporary_seccomp(attempt: str, profile: bytes) -> Iterator[Path]:
    name = f"{PREFIX}{attempt}-seccomp.json"
    if not host._safe_dir(RUNTIME):
        raise WorkerPreflightError("Boca private runtime directory changed")
    directory = os.open(RUNTIME, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    identity: os.stat_result | None = None
    try:
        try:
            try:
                fd = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory,
                )
            except FileExistsError as exc:
                raise TempSeccompCleanupError("prior temporary seccomp residue") from exc
            try:
                identity = os.fstat(fd)
                if os.write(fd, profile) != len(profile):
                    raise WorkerPreflightError("incomplete temporary seccomp profile")
                os.fsync(fd)
            finally:
                os.close(fd)
            yield RUNTIME / name
        finally:
            if identity is not None:
                try:
                    present = os.stat(name, dir_fd=directory, follow_symlinks=False)
                    if (
                        (present.st_dev, present.st_ino) != (identity.st_dev, identity.st_ino)
                        or not stat.S_ISREG(present.st_mode)
                        or present.st_uid != 10001
                        or stat.S_IMODE(present.st_mode) != 0o600
                    ):
                        raise TempSeccompCleanupError("temporary seccomp inode changed")
                    os.unlink(name, dir_fd=directory)
                except (OSError, TempSeccompCleanupError) as exc:
                    raise TempSeccompCleanupError(
                        "temporary seccomp cleanup indeterminate"
                    ) from exc
    finally:
        os.close(directory)


def _named_id(name: str) -> str | None:
    result = host._run(
        "docker", "ps", "-a", "-q", "--no-trunc", "--filter", f"name=^/{name}$", timeout=15
    ).splitlines()
    if len(result) > 1 or any(not ID.fullmatch(item) for item in result):
        raise WorkerPreflightError("preflight Docker name ambiguous")
    return result[0] if result else None


def _require_clean_namespace(name: str) -> None:
    known = host._run(
        "docker", "ps", "-a", "--format", "{{.Names}}", "--filter", f"name=^/{PREFIX}", timeout=15
    ).splitlines()
    if known or _named_id(name) is not None:
        raise WorkerPreflightError("previous Boca preflight probe residue requires exact inventory")


def _inspect_probe(
    container: str, name: str, pins: Coordinates, profile: bytes, *, running: bool
) -> None:
    observed = host._browser_inspect_record(container)
    config = observed.get("Config")
    settings = observed.get("HostConfig")
    state = observed.get("State")
    networks = observed.get("NetworkSettings")
    if (
        not isinstance(config, dict)
        or not isinstance(settings, dict)
        or not isinstance(state, dict)
        or not isinstance(networks, dict)
    ):
        raise WorkerPreflightError("probe Docker identity incomplete")
    labels = config.get("Labels")
    if (
        observed.get("Name") != f"/{name}"
        or config.get("Image") != pins.browser
        or config.get("User") != "10002:10002"
        or config.get("Cmd") != ["python", "-c", "import time; time.sleep(90)"]
        or not isinstance(labels, dict)
        or labels.get(LABEL) != pins.attempt
        or labels.get("com.docker.compose.project") != host.PROJECT
        or labels.get("org.opencontainers.image.revision") != pins.source
        or state.get("Running") is not running
        or settings.get("NetworkMode") != "none"
        or settings.get("IpcMode") != "private"
        or settings.get("CgroupnsMode") != "private"
        or settings.get("ReadonlyRootfs") is not True
        or settings.get("Privileged") is not False
        or settings.get("Init") is not True
        or settings.get("NanoCpus") != 1_000_000_000
        or settings.get("Memory") != 805_306_368
        or settings.get("PidsLimit") != 128
        or settings.get("CapDrop") != ["ALL"]
        or settings.get("CapAdd") not in (["SYS_CHROOT"], ["CAP_SYS_CHROOT"])
        or settings.get("PortBindings") not in (None, {})
        or observed.get("Mounts") != []
        or networks.get("Ports") not in (None, {})
        or set(networks.get("Networks", {})) != {"none"}
    ):
        raise WorkerPreflightError("Boca ephemeral worker isolation changed")
    host._browser_effective_seccomp_options(
        settings.get("SecurityOpt"), hashlib.sha256(profile).hexdigest(), staged_profile=profile
    )


def _probe_argv(pins: Coordinates, path: Path) -> tuple[str, ...]:
    return (
        "docker",
        "create",
        "--pull",
        "never",
        "--name",
        f"{PREFIX}{pins.attempt}",
        "--label",
        f"com.docker.compose.project={host.PROJECT}",
        "--label",
        f"{LABEL}={pins.attempt}",
        "--user",
        "10002:10002",
        "--restart",
        "no",
        "--init",
        "--network",
        "none",
        "--ipc",
        "private",
        "--cgroupns",
        "private",
        "--read-only",
        "--security-opt",
        "no-new-privileges:true",
        "--security-opt",
        f"seccomp={path}",
        "--cap-drop",
        "ALL",
        "--cap-add",
        "SYS_CHROOT",
        "--pids-limit",
        "128",
        "--memory",
        "768m",
        "--cpus",
        "1.00",
        "--shm-size",
        "64m",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=32m",  # noqa: S108 - isolated container tmpfs
        "--tmpfs",
        "/home/boca-browser:rw,noexec,nosuid,size=16m",
        "--env",
        "BOCA_ENVIRONMENT=staging",
        "--env",
        "BOCA_RUNTIME_MODE=simulation",
        "--env",
        "BOCA_ENGINE_MODE=off",
        "--env",
        "BOCA_OBSERVER_STOP=1",
        pins.browser,
        "python",
        "-c",
        "import time; time.sleep(90)",
    )


def _classify_stop_failure(exc: Exception) -> str:
    """Categorize a lost stop receipt without emitting private Docker diagnostics."""
    cause = exc.__cause__ if isinstance(exc, host.PreflightError) else exc
    if isinstance(cause, subprocess.TimeoutExpired):
        return "TIMEOUT"
    if isinstance(cause, subprocess.CalledProcessError):
        return "NONZERO"
    if isinstance(cause, OSError):
        return "OSERROR"
    return "UNVERIFIED"


def _classify_stop_ack(ack: str, expected_id: str, expected_name: str) -> str:
    """Report only an allowlisted shape, never the Docker stdout bytes."""
    if not ack:
        return "ACK_EMPTY"
    if "\n" in ack or "\r" in ack:
        return "ACK_MULTILINE"
    if ack in {expected_name, f"/{expected_name}"}:
        return "ACK_NAME"
    if 12 <= len(ack) < 64 and expected_id.startswith(ack) and re.fullmatch(r"[0-9a-f]+", ack):
        return "ACK_SHORT_ID"
    if ID.fullmatch(ack):
        return "ACK_OTHER_ID"
    return "ACK_MISMATCH"


def _cleanup_exact(pins: Coordinates, name: str) -> None:
    stage = "PS"
    stop_failure_cause = "UNVERIFIED"
    try:
        container = _named_id(name)
        if container is None:
            return
        stage = "INSPECT"
        observed = host._browser_inspect_record(container)
        stage = "OWNERSHIP"
        config = observed.get("Config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        state = observed.get("State")
        if (
            observed.get("Name") != f"/{name}"
            or not isinstance(config, dict)
            or config.get("Image") != pins.browser
            or not isinstance(labels, dict)
            or labels.get(LABEL) != pins.attempt
            or labels.get("com.docker.compose.project") != host.PROJECT
            or not isinstance(state, dict)
            or type(state.get("Running")) is not bool
        ):
            raise WorkerPreflightError("probe cleanup exact ownership unverified")
        if state["Running"]:
            stage = "STOP"
            try:
                stop_ack = host._run("docker", "stop", "--time", "5", container, timeout=20)
            except (host.PreflightError, OSError) as exc:
                stop_failure_cause = _classify_stop_failure(exc)
                raise
            if stop_ack != container:
                stop_failure_cause = _classify_stop_ack(stop_ack, container, name)
                raise WorkerPreflightError("probe exact container stop unverified")
        stage = "RM"
        if host._run("docker", "rm", container, timeout=20) != container:
            raise WorkerPreflightError("probe exact container removal unverified")
        stage = "POST_ID"
        if _named_id(name) is not None:
            raise WorkerPreflightError("probe container retained after cleanup")
    except (
        host.PreflightError,
        WorkerPreflightError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
    ) as exc:
        raise CleanupStageError(stage, stop_failure_cause=stop_failure_cause) from exc


def execute(pins: Coordinates, profile: bytes) -> tuple[str, str]:
    """Require exact cleanup for PASS."""
    pins.validate()
    phase = "ATTEST"
    cleanup = "VERIFIED"
    name = f"{PREFIX}{pins.attempt}"
    with protected_boca_job_lease(pins.attempt):
        failure: Exception | None = None
        primary_failed_phase = "NONE"
        cleanup_failed_stage = "NONE"
        stop_failure_cause = "NONE"
        try:
            host._cutover_legacy_record(
                pins.legacy_id,
                pins.legacy_image,
                pins.legacy_source,
                name=host.CUTOVER_LEGACY_NAME,
                running=True,
            )
            _require_clean_namespace(name)
            host._browser_engine_version()
            host._storage_snapshot()
            phase = "GHCR_PULL"
            # Reuse the reviewed R50 4 GiB pre-pull/1 GiB post-pull and
            # 50k-inode admission policy. No independent or weaker variant.
            host._browser_pull_both(pins.controller, pins.browser, pins.source)
            phase = "SECCOMP_ENTER"
            with _temporary_seccomp(pins.attempt, profile) as path:
                try:
                    phase = "WORKER_CREATE"
                    candidate = host._run(*_probe_argv(pins, path), timeout=60)
                    if not ID.fullmatch(candidate) or _named_id(name) != candidate:
                        raise WorkerPreflightError("probe create returned ambiguous ID")
                    _inspect_probe(candidate, name, pins, profile, running=False)
                    phase = "WORKER_START"
                    if host._run("docker", "start", candidate, timeout=30) != candidate:
                        raise WorkerPreflightError("probe exact start receipt invalid")
                    _inspect_probe(candidate, name, pins, profile, running=True)
                    phase = "WORKER_BOUNDARY"
                    if (
                        host._run(
                            "docker",
                            "exec",
                            "--user",
                            "10002:10002",
                            candidate,
                            "python",
                            "-c",
                            BOUNDARY_COMMAND,
                            timeout=20,
                        )
                        != "BOCA_CUTOVER_WORKER_BOUNDARY_PASS"
                    ):
                        raise WorkerPreflightError("worker rootless kernel boundary unproven")
                except (
                    host.PreflightError,
                    WorkerPreflightError,
                    OSError,
                    ValueError,
                    TypeError,
                    KeyError,
                ):
                    # Capture before the context manager's __exit__: an inode
                    # cleanup error there must not erase the original phase.
                    primary_failed_phase = phase
                    raise
        except (
            host.PreflightError,
            WorkerPreflightError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
        ) as exc:
            failure = exc
            if isinstance(exc, TempSeccompCleanupError):
                cleanup = "INDETERMINATE"
                cleanup_failed_stage = "TEMP_SECCOMP"
                if phase == "SECCOMP_ENTER":
                    primary_failed_phase = "SECCOMP_ENTER"
            elif primary_failed_phase == "NONE":
                primary_failed_phase = phase
        finally:
            try:
                phase_at_cleanup = phase
                _cleanup_exact(pins, name)
            except (
                host.PreflightError,
                WorkerPreflightError,
                OSError,
                ValueError,
                TypeError,
                KeyError,
            ) as exc:
                cleanup = "INDETERMINATE"
                if cleanup_failed_stage == "NONE":
                    cleanup_failed_stage = (
                        exc.stage if isinstance(exc, CleanupStageError) else "UNVERIFIED"
                    )
                    stop_failure_cause = (
                        exc.stop_failure_cause if isinstance(exc, CleanupStageError) else "NONE"
                    )
            try:
                host._cutover_legacy_record(
                    pins.legacy_id,
                    pins.legacy_image,
                    pins.legacy_source,
                    name=host.CUTOVER_LEGACY_NAME,
                    running=True,
                )
            except (host.PreflightError, OSError, ValueError, TypeError, KeyError):
                cleanup = "INDETERMINATE"
                if cleanup_failed_stage == "NONE":
                    cleanup_failed_stage = "LEGACY"
            if cleanup != "VERIFIED":
                raise PreflightFailure(
                    "CLEANUP",
                    cleanup,
                    primary_failed_phase=primary_failed_phase,
                    cleanup_failed_stage=cleanup_failed_stage,
                    stop_failure_cause=stop_failure_cause,
                ) from None
        if failure is not None:
            raise PreflightFailure(
                phase_at_cleanup,
                cleanup,
                primary_failed_phase=primary_failed_phase,
                cleanup_failed_stage=cleanup_failed_stage,
                stop_failure_cause=stop_failure_cause,
            ) from None
    return phase, cleanup


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 8 or arguments[0] != "host":
        print(
            "BOCA_CUTOVER_WORKER_PREFLIGHT state=NO_GO failed_phase=ATTEST cleanup=UNVERIFIED "
            "primary_failed_phase=ATTEST cleanup_failed_stage=UNVERIFIED stop_failure_cause=NONE",
            flush=True,
        )
        return 3
    pins = Coordinates(*arguments[1:])
    try:
        execute(pins, _reviewed_seccomp())
    except PreflightFailure as exc:
        print(
            f"BOCA_CUTOVER_WORKER_PREFLIGHT state=NO_GO failed_phase={exc.phase} "
            f"cleanup={exc.cleanup} primary_failed_phase={exc.primary_failed_phase} "
            f"cleanup_failed_stage={exc.cleanup_failed_stage} "
            f"stop_failure_cause={exc.stop_failure_cause}",
            flush=True,
        )
        return 3
    except (
        WorkerPreflightError,
        host.PreflightError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        zipfile.BadZipFile,
    ):
        print(
            "BOCA_CUTOVER_WORKER_PREFLIGHT state=NO_GO failed_phase=UNVERIFIED "
            "cleanup=UNVERIFIED primary_failed_phase=UNVERIFIED "
            "cleanup_failed_stage=UNVERIFIED stop_failure_cause=UNVERIFIED",
            flush=True,
        )
        return 3
    print(
        f"BOCA_CUTOVER_WORKER_PREFLIGHT state=PASS source_sha={pins.source} "
        "images=VERIFIED worker_boundary=VERIFIED cleanup=VERIFIED "
        "original=RUNNING port=127.0.0.1:8443 ipc_worker=NOT_TESTED "
        "prepared_go=UNCONSUMED foreign=UNTOUCHED",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
