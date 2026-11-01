"""Bounded first-install host helper, streamed over SSH by the gated workflow.

This file uses only the Python standard library and never reads other projects.
Each invocation is a single phase; a failed phase is not retried automatically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import pwd
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path("/srv/boca-socios")
COMPOSE = ROOT / "compose.yaml"
PROJECT = "boca-socios"
KEY_VOLUME = "boca-socios_boca_key"
ROOTLESS_SOCKET = Path("/run/user/10001/docker.sock")
PRIVATE_MANAGER_SOCKET = Path("/run/user/10001/systemd/private")
USER_BUS_SOCKET = Path("/run/user/10001/bus")
ROOTFUL_SOCKET = Path("/var/run/docker.sock")
CGROUP_CONTROLLERS = Path(
    "/sys/fs/cgroup/user.slice/user-10001.slice/user@10001.service/cgroup.controllers"
)
IMAGE_PATTERN = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class PreflightError(ValueError):
    """First installation cannot proceed without an explicit new review."""


@dataclass(frozen=True)
class HostSnapshot:
    arch: str
    uid: int
    available_memory_kib: int
    available_disk_bytes: int
    available_inodes: int
    docker_disk_bytes: int
    docker_inodes: int
    root_ready: bool
    boca_containers: bool
    boca_volume: bool
    boca_network: bool
    cpu_headroom: float = 1.0


@dataclass(frozen=True)
class StorageSnapshot:
    docker_root: Path
    driver: str
    driver_status: tuple[tuple[str, str], ...]
    stage_device: int
    docker_device: int
    stage_inode: int
    docker_inode: int
    socket_device: int
    socket_inode: int
    stage_free_bytes: int
    stage_inodes: int
    docker_free_bytes: int
    docker_inodes: int


@dataclass(frozen=True)
class DockerBoundarySnapshot:
    socket_secure: bool
    rootful_socket_inaccessible: bool
    daemon_rootless: bool
    cgroup_version: str
    cgroup_driver: str
    controllers: frozenset[str]


@dataclass(frozen=True)
class CgroupLimits:
    cpu_quota: int
    cpu_period: int
    memory_bytes: int
    pids_limit: int


@dataclass(frozen=True)
class DiagnosticSnapshot:
    uid: int
    key_secure: bool
    mounts_secure: bool
    container_id: str
    health: str
    image_ref: str
    revision: str
    project: str
    service: str
    user: str
    runtime_mode: str
    engine_mode: str
    cpu_nano: int
    memory_bytes: int
    pids_limit: int
    read_only: bool
    privileged: bool
    has_ports: bool
    network_mode: str
    networks: frozenset[str]
    network_id: str
    network_ports: bool
    cap_drop: tuple[str, ...]
    cap_add: tuple[str, ...]
    security_opt: tuple[str, ...]
    tmpfs: tuple[tuple[str, str], ...]
    cgroupns_mode: str
    cgroup: CgroupLimits


def validate_diagnostic(snapshot: DiagnosticSnapshot, image: str, source_sha: str) -> None:
    if snapshot.uid != 10001 or not snapshot.key_secure or not snapshot.mounts_secure:
        raise PreflightError("dedicated Boca identity, key or mounts are unsafe")
    if not re.fullmatch(r"[0-9a-f]{64}", snapshot.container_id):
        raise PreflightError("expected exactly one Boca controller ID")
    for actual, expected, field in (
        (snapshot.health, "healthy", "health"),
        (snapshot.image_ref, image, "image"),
        (snapshot.revision, source_sha, "revision"),
        (snapshot.project, PROJECT, "project"),
        (snapshot.service, "controller", "service"),
        (snapshot.user, "10001:10001", "user"),
        (snapshot.runtime_mode, "simulation", "runtime mode"),
        (snapshot.engine_mode, "off", "engine mode"),
    ):
        if actual != expected:
            raise PreflightError(f"Boca diagnostic {field} mismatch")
    for bounded_actual, bounded_expected, bounded_field in (
        (snapshot.cpu_nano, 500_000_000, "CPU"),
        (snapshot.memory_bytes, 268_435_456, "memory"),
        (snapshot.pids_limit, 64, "PIDs"),
        (snapshot.read_only, True, "read-only root"),
        (snapshot.privileged, False, "privileged"),
        (snapshot.has_ports, False, "published ports"),
        (snapshot.network_mode, "boca-socios_boca_private", "network mode"),
        (snapshot.networks, frozenset({"boca-socios_boca_private"}), "networks"),
        (snapshot.network_ports, False, "network ports"),
        (snapshot.cap_drop, ("ALL",), "dropped capabilities"),
        (snapshot.cap_add, (), "added capabilities"),
        (snapshot.security_opt, ("no-new-privileges:true",), "security options"),
        (snapshot.tmpfs, (("/tmp", "rw,noexec,nosuid,size=16m"),), "tmpfs"),  # noqa: S108 - container tmpfs
    ):
        if type(bounded_actual) is not type(bounded_expected) or bounded_actual != bounded_expected:
            raise PreflightError(f"Boca diagnostic {bounded_field} mismatch")
    if type(snapshot.network_id) is not str or not re.fullmatch(
        r"[0-9a-f]{64}", snapshot.network_id
    ):
        raise PreflightError("Boca network identity is unavailable")
    if type(snapshot.cgroupns_mode) is not str or snapshot.cgroupns_mode not in {
        "private",
        "",
    }:
        raise PreflightError("Boca private cgroup namespace is unproven")
    limits = snapshot.cgroup
    if (
        not isinstance(limits, CgroupLimits)
        or any(
            type(value) is not int
            for value in (
                limits.cpu_quota,
                limits.cpu_period,
                limits.memory_bytes,
                limits.pids_limit,
            )
        )
        or not (0 < limits.cpu_period <= 1_000_000)
        or limits.cpu_quota * 2 != limits.cpu_period
        or limits.memory_bytes != 268_435_456
        or limits.pids_limit != 64
    ):
        raise PreflightError("Boca effective cgroup limits are unproven")


def validate_snapshot(snapshot: HostSnapshot) -> None:
    if snapshot.arch != "x86_64":
        raise PreflightError("host architecture must be x86_64")
    if snapshot.uid != 10001:
        raise PreflightError("dedicated deploy identity must have UID 10001")
    if snapshot.available_memory_kib < 768 * 1024:
        raise PreflightError("insufficient available host memory")
    if snapshot.cpu_headroom < 0.5:
        raise PreflightError("insufficient approximate host CPU headroom")
    if (
        min(snapshot.available_disk_bytes, snapshot.docker_disk_bytes) < 4 * 1024**3
        or min(snapshot.available_inodes, snapshot.docker_inodes) < 50_000
    ):
        raise PreflightError("insufficient Boca staging or rootless Docker storage")
    if not snapshot.root_ready:
        raise PreflightError("Boca-owned directory is unavailable or unsafe")
    if snapshot.boca_containers or snapshot.boca_volume or snapshot.boca_network:
        raise PreflightError("existing Boca namespace requires separate recovery review")


def validate_docker_boundary(snapshot: DockerBoundarySnapshot) -> None:
    if snapshot.socket_secure is not True or snapshot.rootful_socket_inaccessible is not True:
        raise PreflightError("dedicated rootless socket or rootful Docker access is unsafe")
    if snapshot.daemon_rootless is not True:
        raise PreflightError("Docker daemon must be rootless for the dedicated Boca identity")
    if snapshot.cgroup_version != "2" or snapshot.cgroup_driver != "systemd":
        raise PreflightError("rootless Docker cannot prove enforceable cgroup limits")
    if not {"cpu", "memory", "pids"} <= snapshot.controllers:
        raise PreflightError("rootless CPU, memory and PID controllers must be delegated")


def _run(*args: str, env: dict[str, str] | None = None) -> str:
    run_env = env
    if args[0] == "docker":
        # SSH environment and Docker CLI context must never redirect host
        # operations to the shared rootful daemon or a remote endpoint.
        run_env = dict(os.environ if env is None else env)
        run_env.pop("DOCKER_CONTEXT", None)
        run_env.pop("DOCKER_CONFIG", None)
        run_env.pop("DOCKER_TLS", None)
        run_env.pop("DOCKER_TLS_VERIFY", None)
        run_env.pop("DOCKER_CERT_PATH", None)
        run_env["DOCKER_HOST"] = f"unix://{ROOTLESS_SOCKET}"
    try:
        result = subprocess.run(  # noqa: S603 - validated coordinates; fixed argv, no shell
            args, check=True, text=True, capture_output=True, timeout=120, env=run_env
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        # Suppress subprocess stderr: it may include paths or registry diagnostics.
        raise PreflightError(f"Boca command failed: {args[0]} {args[1]}") from exc
    return result.stdout.strip()


def _safe_dir(path: Path, *, mode: int = 0o700) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    return (
        stat.S_ISDIR(metadata.st_mode)
        and metadata.st_uid == 10001
        and stat.S_IMODE(metadata.st_mode) == mode
    )


def _rootless_socket_secure() -> bool:
    if not _safe_dir(ROOTLESS_SOCKET.parent):
        return False
    try:
        metadata = ROOTLESS_SOCKET.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISSOCK(metadata.st_mode) and metadata.st_uid == 10001


def _socket_state(path: Path, *, expected_uid: int = 10001) -> str:
    """Classify metadata as the dedicated user; never infer absence on EACCES."""
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "unavailable"
    return (
        "owned" if stat.S_ISSOCK(metadata.st_mode) and metadata.st_uid == expected_uid else "unsafe"
    )


def _binary_presence(command: str) -> str:
    """Search executable metadata only; absence is not an uninstall diagnosis."""
    search = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    try:
        home = getattr(pwd.getpwuid(10001), "pw_dir", "")
        if isinstance(home, str) and home.startswith("/") and ":" not in home:
            search = f"{home}/bin:{search}"
        return "available" if shutil.which(command, path=search) else "not_found_in_search_path"
    except (OSError, KeyError):
        return "unavailable"


def _parse_service_properties(raw: str) -> tuple[str, str, str, str]:
    """Only allowlisted states leave the host, never command output or paths."""
    unknown = ("unavailable", "unavailable", "unavailable", "unavailable")
    if len(raw) > 1024:
        return unknown
    allowed = {
        "LoadState": {"loaded", "not-found", "masked", "error", "bad-setting", "stub", "merged"},
        "ActiveState": {
            "active",
            "inactive",
            "failed",
            "activating",
            "deactivating",
            "reloading",
            "maintenance",
            "refreshing",
        },
        "SubState": {
            "dead",
            "running",
            "exited",
            "failed",
            "start",
            "start-pre",
            "start-post",
            "stop",
            "stop-sigterm",
            "stop-sigkill",
            "stop-post",
            "auto-restart",
            "reload",
        },
        "Result": {
            "success",
            "exit-code",
            "signal",
            "core-dump",
            "timeout",
            "resources",
            "start-limit-hit",
            "watchdog",
            "protocol",
            "oom-kill",
            "exec-condition",
        },
    }
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        key, separator, value = line.partition("=")
        if not separator or key in fields or key not in allowed or value not in allowed[key]:
            return unknown
        fields[key] = value
    if fields.keys() != allowed.keys():
        return unknown
    return fields["LoadState"], fields["ActiveState"], fields["SubState"], fields["Result"]


def _rootless_service_metadata(private_runtime_ready: bool) -> str:
    _require_dedicated_identity()
    binaries = [
        _binary_presence(command)
        for command in ("docker", "dockerd", "dockerd-rootless.sh", "dockerd-rootless-setuptool.sh")
    ]
    states = ("not_checked", "not_checked", "not_checked", "not_checked")
    if private_runtime_ready:
        try:
            result = subprocess.run(  # noqa: S603 - fixed read-only user-unit command, no shell
                (
                    "/usr/bin/systemctl",
                    "--user",
                    "--no-pager",
                    "show",
                    "docker.service",
                    "--property=LoadState,ActiveState,SubState,Result",
                ),
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=5,
                env={
                    "PATH": "/usr/bin:/bin",
                    "LC_ALL": "C",
                    "XDG_RUNTIME_DIR": "/run/user/10001",
                    "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/10001/bus",
                },
            )
            states = _parse_service_properties(result.stdout)
        except (OSError, subprocess.SubprocessError, UnicodeError):
            states = ("unavailable", "unavailable", "unavailable", "unavailable")
    return (
        f"BOCA_ROOTLESS_SERVICE load={states[0]} active={states[1]}"
        f" sub={states[2]} result={states[3]}"
        f" docker={binaries[0]} dockerd={binaries[1]}"
        f" wrapper={binaries[2]} setup={binaries[3]}"
    )


def inspect_prerequisites() -> None:
    """Observe only Boca's private runtime; metadata is not a Docker preflight."""
    uid = _require_dedicated_identity()

    try:
        runtime_safe = _safe_dir(ROOTLESS_SOCKET.parent)
    except OSError:
        runtime_safe = False
    private = _socket_state(PRIVATE_MANAGER_SOCKET) if runtime_safe else "not_checked"
    bus = _socket_state(USER_BUS_SOCKET) if runtime_safe else "not_checked"
    rootless = _socket_state(ROOTLESS_SOCKET) if runtime_safe else "not_checked"
    rootful = _socket_state(ROOTFUL_SOCKET, expected_uid=0)
    if rootful == "owned":
        rootful = "writable" if os.access(ROOTFUL_SOCKET, os.W_OK) else "not_writable"
    try:
        available = set(CGROUP_CONTROLLERS.read_text(encoding="ascii").split())
        controllers = ",".join(sorted({"cpu", "memory", "pids"} & available)) or "none"
    except OSError:
        controllers = "unavailable"
    state = (
        "METADATA_CANDIDATE"
        if runtime_safe
        and private == bus == rootless == "owned"
        and controllers == "cpu,memory,pids"
        and rootful in {"absent", "not_writable"}
        else "PREREQUISITES_UNPROVEN"
    )
    print(
        f"BOCA_HOST_INSPECT state={state} uid={uid}"
        f" runtime={'owned_private' if runtime_safe else 'unsafe_or_unavailable'}"
        f" private={private} bus={bus} rootless={rootless}"
        f" rootful={rootful} controllers={controllers}"
    )
    print(_rootless_service_metadata(runtime_safe and private == bus == "owned"))
    if state != "METADATA_CANDIDATE":
        raise PreflightError("prerequisite metadata unproven; no Docker operation attempted")


def _rootful_socket_inaccessible() -> bool:
    return not os.access(ROOTFUL_SOCKET, os.W_OK)


def _require_dedicated_identity() -> int:
    """Refuse setuid/wrapper privilege changes before probing any host path."""
    uid = os.getuid()
    if uid != 10001 or os.geteuid() != uid or os.getegid() != os.getgid():
        raise PreflightError("expected dedicated Boca identity")
    try:
        account = pwd.getpwuid(uid).pw_name
    except KeyError as exc:
        raise PreflightError("dedicated Boca identity is unavailable") from exc
    if account != "boca-deploy":
        raise PreflightError("expected dedicated boca-deploy account")
    return uid


def _validate_docker_boundary() -> None:
    _require_dedicated_identity()
    socket_secure = _rootless_socket_secure()
    rootful_inaccessible = _rootful_socket_inaccessible()
    if not socket_secure or not rootful_inaccessible:
        raise PreflightError("dedicated rootless Docker socket is unproven")
    info = _json_object(_run("docker", "info", "--format", "{{json .}}"), "daemon info")
    options = info.get("SecurityOptions")
    try:
        controllers = frozenset(CGROUP_CONTROLLERS.read_text(encoding="ascii").split())
    except OSError as exc:
        raise PreflightError("rootless cgroup delegation is unavailable") from exc
    validate_docker_boundary(
        DockerBoundarySnapshot(
            socket_secure=socket_secure,
            rootful_socket_inaccessible=rootful_inaccessible,
            daemon_rootless=isinstance(options, list) and "name=rootless" in options,
            cgroup_version=str(info.get("CgroupVersion", "")),
            cgroup_driver=str(info.get("CgroupDriver", "")),
            controllers=controllers,
        )
    )


def _root_ready() -> bool:
    if not _safe_dir(ROOT):
        return False
    if any(child.name != "compose.yaml" for child in ROOT.iterdir()):
        return False
    if COMPOSE.is_symlink():
        return False
    return os.access(ROOT, os.W_OK)


def _names(kind: str, label: str) -> set[str]:
    return set(_run("docker", kind, "ls", "-q", "--filter", label).splitlines())


def _checked_docker_storage_identity() -> tuple[Path, str, tuple[tuple[str, str], ...]]:
    """Prove backend and data path before measuring the private Docker store."""
    try:
        info = json.loads(_run("docker", "info", "--format", "{{json .}}"))
        if not isinstance(info, dict):
            raise PreflightError("rootless Docker storage backend is unproven")
        options = info.get("SecurityOptions")
        if (
            not isinstance(options, list)
            or "name=rootless" not in options
            or str(info.get("CgroupVersion")) != "2"
            or info.get("CgroupDriver") != "systemd"
        ):
            raise PreflightError("rootless Docker boundary changed during storage check")
        # The containerd image store can keep layers on another filesystem.
        # Until its dedicated root is proven, only classic drivers can pass.
        driver_status = info.get("DriverStatus")
        if (
            info.get("Driver") not in {"overlay2", "fuse-overlayfs", "vfs"}
            or not isinstance(driver_status, list)
            or any(
                not isinstance(item, list)
                or len(item) != 2
                or not all(isinstance(value, str) for value in item)
                or item[0] == "driver-type"
                for item in driver_status
            )
        ):
            raise PreflightError("rootless Docker storage backend is unproven")
        reported = info.get("DockerRootDir")
        home = Path(pwd.getpwuid(10001).pw_dir)
        if not isinstance(reported, str) or len(reported) > 4096:
            raise PreflightError("rootless Docker storage path is unproven")
        storage = Path(reported)
        if (
            not home.is_absolute()
            or home == Path("/")
            or not storage.is_absolute()
            or ".." in storage.parts
            or str(storage) != reported
            or home.resolve(strict=True) != home
            or not _safe_dir(home)
        ):
            raise PreflightError("rootless Docker storage path is unproven")
        relative = storage.relative_to(home)
        if not relative.parts:
            raise PreflightError("rootless Docker storage path is unproven")
        current = home
        for part in relative.parts:
            current /= part
            metadata = current.lstat()
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != 10001
                or stat.S_IMODE(metadata.st_mode) & 0o022
            ):
                raise PreflightError("rootless Docker storage path is unproven")
    except PreflightError:
        raise
    except (OSError, ValueError, KeyError, AttributeError, TypeError, RuntimeError) as exc:
        raise PreflightError("rootless Docker storage path is unproven") from exc
    return storage, info["Driver"], tuple(sorted((item[0], item[1]) for item in driver_status))


def _checked_docker_storage_dir() -> Path:
    """Compatibility wrapper for the read-only preflight capacity snapshot."""
    return _checked_docker_storage_identity()[0]


def _storage_snapshot() -> StorageSnapshot:
    """Observe both filesystems through the same validated rootless store."""
    _validate_docker_boundary()
    if not _safe_dir(ROOT):
        raise PreflightError("Boca staging directory changed during installation")
    docker_root, driver, driver_status = _checked_docker_storage_identity()
    try:
        stage_metadata = ROOT.stat()
        docker_metadata = docker_root.stat()
        socket_metadata = ROOTLESS_SOCKET.lstat()
        if not stat.S_ISSOCK(socket_metadata.st_mode) or socket_metadata.st_uid != 10001:
            raise PreflightError("Boca rootless Docker socket changed")
        stage = os.statvfs(ROOT)
        docker = os.statvfs(docker_root)
    except OSError as exc:
        raise PreflightError("Boca staging or rootless Docker capacity is unavailable") from exc
    return StorageSnapshot(
        docker_root=docker_root,
        driver=driver,
        driver_status=driver_status,
        stage_device=stage_metadata.st_dev,
        docker_device=docker_metadata.st_dev,
        stage_inode=stage_metadata.st_ino,
        docker_inode=docker_metadata.st_ino,
        socket_device=socket_metadata.st_dev,
        socket_inode=socket_metadata.st_ino,
        stage_free_bytes=stage.f_bavail * stage.f_frsize,
        stage_inodes=stage.f_favail,
        docker_free_bytes=docker.f_bavail * docker.f_frsize,
        docker_inodes=docker.f_favail,
    )


def _validate_storage_capacity(snapshot: StorageSnapshot) -> None:
    if (
        min(snapshot.stage_free_bytes, snapshot.docker_free_bytes) < 4 * 1024**3
        or min(snapshot.stage_inodes, snapshot.docker_inodes) < 50_000
    ):
        raise PreflightError("insufficient Boca staging or rootless Docker storage")


def _validate_storage_continuity(before: StorageSnapshot, after: StorageSnapshot) -> None:
    if (
        before.docker_root != after.docker_root
        or before.driver != after.driver
        or before.driver_status != after.driver_status
        or before.stage_device != after.stage_device
        or before.docker_device != after.docker_device
        or before.stage_inode != after.stage_inode
        or before.docker_inode != after.docker_inode
        or before.socket_device != after.socket_device
        or before.socket_inode != after.socket_inode
    ):
        raise PreflightError("Boca rootless Docker storage topology changed")
    _validate_storage_capacity(after)


def collect_snapshot() -> HostSnapshot:
    # The deployment identity owns only the rootless Docker endpoint; the key
    # is generated in a separate named volume within the container UID map.
    uid = _require_dedicated_identity()
    if not _root_ready():
        raise PreflightError("Boca-owned directory is unavailable or unsafe")
    _run("docker", "version", "--format", "{{.Server.Version}}")
    _run("docker", "compose", "version", "--short")
    if not {"--no-build", "--no-deps", "--wait"} <= set(
        _run("docker", "compose", "up", "--help").split()
    ):
        raise PreflightError("Docker Compose lacks required bounded start options")
    if "--format" not in _run("docker", "compose", "config", "--help"):
        raise PreflightError("Docker Compose lacks JSON config support")
    meminfo = Path("/proc/meminfo").read_text(encoding="ascii")
    match = re.search(r"^MemAvailable:\s+(\d+) kB$", meminfo, re.MULTILINE)
    if match is None:
        raise PreflightError("MemAvailable is unavailable")
    storage_dir = _checked_docker_storage_dir()
    try:
        stage_disk = os.statvfs(ROOT)
        docker_disk = os.statvfs(storage_dir)
    except OSError as exc:
        raise PreflightError("Boca capacity filesystems are unavailable") from exc
    containers = _run(
        "docker", "ps", "-a", "-q", "--filter", "label=com.docker.compose.project=boca-socios"
    ) or _run("docker", "ps", "-a", "-q", "--filter", "name=^/boca-socios-")
    # Check the whole Boca namespace, including resources missing Compose labels.
    volumes = _names("volume", "name=^boca-socios_")
    networks = _names("network", "name=^boca-socios_")
    return HostSnapshot(
        arch=platform.machine(),
        uid=uid,
        available_memory_kib=int(match.group(1)),
        available_disk_bytes=stage_disk.f_bavail * stage_disk.f_frsize,
        available_inodes=stage_disk.f_favail,
        docker_disk_bytes=docker_disk.f_bavail * docker_disk.f_frsize,
        docker_inodes=docker_disk.f_favail,
        root_ready=True,
        boca_containers=bool(containers),
        boca_volume=bool(volumes),
        boca_network=bool(networks),
        cpu_headroom=max(0.0, len(os.sched_getaffinity(0)) - os.getloadavg()[0]),
    )


def _verify_compose(expected_sha: str) -> None:
    if not _safe_dir(ROOT) or COMPOSE.is_symlink():
        raise PreflightError("unsafe staged Boca directory")
    metadata = COMPOSE.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 10001:
        raise PreflightError("unsafe staged Compose file")
    if stat.S_IMODE(metadata.st_mode) & 0o022 or metadata.st_size > 32_768:
        raise PreflightError("unsafe staged Compose permissions or size")
    if hashlib.sha256(COMPOSE.read_bytes()).hexdigest() != expected_sha:
        raise PreflightError("staged Compose SHA-256 differs from reviewed file")


def _compose_env(image: str) -> dict[str, str]:
    return {
        **os.environ,
        "BOCA_IMAGE": image,
        "BOCA_ENVIRONMENT": "staging",
    }


def _compose_args(*args: str) -> tuple[str, ...]:
    return ("docker", "compose", "-p", PROJECT, "-f", str(COMPOSE), *args)


def _validate_key_volume() -> None:
    volume = _json_object(
        _run("docker", "volume", "inspect", "--format", "{{json .}}", KEY_VOLUME),
        "key volume",
    )
    root = Path(_run("docker", "info", "--format", "{{.DockerRootDir}}"))
    mountpoint = volume.get("Mountpoint")
    expected = root / "volumes" / KEY_VOLUME / "_data"
    labels = volume.get("Labels")
    if (
        volume.get("Name") != KEY_VOLUME
        or volume.get("Driver") != "local"
        or volume.get("Scope") != "local"
        or volume.get("Options") not in (None, {})
        or not root.is_absolute()
        or root == Path("/")
        or mountpoint != str(expected)
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != PROJECT
        or labels.get("com.docker.compose.volume") != "boca_key"
    ):
        raise PreflightError("Boca key volume identity is unsafe")
    # A local driver can otherwise conceal a bind source behind the expected
    # volume name. Refuse path redirects even when Docker's labels match.
    try:
        if root.resolve(strict=True) != root or expected.resolve(strict=True) != expected:
            raise PreflightError("Boca key volume mountpoint is redirected")
    except (OSError, RuntimeError) as exc:
        raise PreflightError("Boca key volume mountpoint is unavailable") from exc


def _key_container(image: str, operation: str) -> tuple[str, ...]:
    if operation not in {"init", "verify"}:
        raise PreflightError("invalid key custody operation")
    init = operation == "init"
    return (
        "docker",
        "run",
        "--rm",
        "--pull",
        "never",
        "--user",
        "0:0" if init else "10001:10001",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        *(("--cap-add", "CHOWN") if init else ()),
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "16",
        "--memory",
        "64m",
        "--cpus",
        "0.25",
        "--mount",
        f"type=volume,source={KEY_VOLUME},target=/run/secrets,volume-nocopy"
        + ("" if init else ",readonly"),
        image,
        "python",
        "-m",
        "boca_socios.security.key_custody",
        operation,
    )


def _create_key(image: str) -> None:
    created = _run(
        "docker",
        "volume",
        "create",
        "--driver",
        "local",
        "--label",
        f"com.docker.compose.project={PROJECT}",
        "--label",
        "com.docker.compose.volume=boca_key",
        KEY_VOLUME,
    )
    if created != KEY_VOLUME:
        raise PreflightError("unexpected Boca key volume creation")
    _validate_key_volume()
    if _run(*_key_container(image, "init")) != "BOCA_KEY_READY":
        raise PreflightError("Boca key initialization did not confirm completion")
    # Volume creation/inspection is not atomic with a container run; reject a
    # changed named volume before treating the initialized key as usable.
    _validate_key_volume()
    if _run(*_key_container(image, "verify")) != "BOCA_KEY_READY":
        raise PreflightError("Boca key is not readable by the controller identity")


def _validate_coordinates(
    image: str, source_sha: str, compose_sha: str, *, read_only_preflight: bool = False
) -> None:
    if (
        not SHA_PATTERN.fullmatch(source_sha)
        or not DIGEST_PATTERN.fullmatch(compose_sha)
        or (image != "" if read_only_preflight else not IMAGE_PATTERN.fullmatch(image))
    ):
        raise PreflightError("invalid immutable deployment coordinates")


def _diagnostic_files(expected_sha: str) -> None:
    _require_dedicated_identity()
    if not _safe_dir(ROOT):
        raise PreflightError("Boca directory ownership or permissions changed")
    if {child.name for child in ROOT.iterdir()} != {"compose.yaml"}:
        raise PreflightError("unexpected Boca directory entries")
    _validate_key_volume()
    _verify_compose(expected_sha)


def _json_object(value: str, field: str) -> dict[str, object]:
    data = json.loads(value)
    if not isinstance(data, dict):
        raise PreflightError(f"invalid Boca {field} metadata")
    return data


def _string_tuple(value: object, field: str, *, nullable: bool = False) -> tuple[str, ...]:
    if nullable and value is None:
        return ()
    if not isinstance(value, list) or any(type(item) is not str for item in value):
        raise PreflightError(f"invalid Boca {field} metadata")
    return tuple(value)


def _cgroup_limits(container: str) -> CgroupLimits:
    raw = _run(
        "docker",
        "exec",
        "--user",
        "10001:10001",
        container,
        "python",
        "-m",
        "boca_socios.runtime_probe",
    )
    if len(raw) > 256:
        raise PreflightError("Boca cgroup receipt exceeds bounded output")
    receipt = _json_object(raw, "cgroup")
    if set(receipt) != {"cpu_quota", "cpu_period", "memory_bytes", "pids_limit"} or any(
        type(value) is not int for value in receipt.values()
    ):
        raise PreflightError("invalid Boca cgroup receipt")
    return CgroupLimits(
        cpu_quota=receipt["cpu_quota"],  # type: ignore[arg-type]
        cpu_period=receipt["cpu_period"],  # type: ignore[arg-type]
        memory_bytes=receipt["memory_bytes"],  # type: ignore[arg-type]
        pids_limit=receipt["pids_limit"],  # type: ignore[arg-type]
    )


def _validate_boca_network(container: str, network_id: str) -> None:
    """Inspect only the attached network by its exact ID; reject foreign peers."""
    raw = _run("docker", "network", "inspect", "--format", "{{json .}}", network_id)
    if len(raw) > 16_384:
        raise PreflightError("Boca network metadata exceeds bounded output")
    network = _json_object(raw, "network")
    labels, containers = network.get("Labels"), network.get("Containers")
    if (
        network.get("Id") != network_id
        or network.get("Name") != "boca-socios_boca_private"
        or network.get("Driver") != "bridge"
        or network.get("Scope") != "local"
        or network.get("Internal") is not False
        or network.get("Attachable") is not False
        or network.get("Ingress") is not False
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != PROJECT
        or labels.get("com.docker.compose.network") != "boca_private"
        or not isinstance(containers, dict)
        or set(containers) != {container}
    ):
        raise PreflightError("Boca private network identity or peers changed")


def collect_diagnostic(image: str, source_sha: str) -> DiagnosticSnapshot:
    container = _run(*_compose_args("ps", "-q", "controller"), env=_compose_env(image))
    if not re.fullmatch(r"[0-9a-f]{64}", container):
        raise PreflightError("expected exactly one Boca controller")
    config = _json_object(
        _run("docker", "inspect", "--format", "{{json .Config}}", container), "container config"
    )
    host = _json_object(
        _run("docker", "inspect", "--format", "{{json .HostConfig}}", container),
        "container host config",
    )
    network = _json_object(
        _run("docker", "inspect", "--format", "{{json .NetworkSettings}}", container),
        "container network settings",
    )
    networks = network.get("Networks")
    expected_network = "boca-socios_boca_private"
    if not isinstance(networks, dict) or set(networks) != {expected_network}:
        raise PreflightError("Boca controller network boundary changed")
    endpoint = networks[expected_network]
    if not isinstance(endpoint, dict) or type(endpoint.get("NetworkID")) is not str:
        raise PreflightError("Boca controller network identity is unavailable")
    network_id = endpoint["NetworkID"]
    network_ports = network.get("Ports")
    if not isinstance(network_ports, dict):
        raise PreflightError("missing or malformed Boca network ports")
    port_bindings = host.get("PortBindings")
    if not isinstance(port_bindings, dict):
        raise PreflightError("missing or malformed Boca port bindings")
    if host.get("PublishAllPorts") is not False:
        raise PreflightError("Boca automatic port publishing is not disabled")
    tmpfs = host.get("Tmpfs")
    if not isinstance(tmpfs, dict) or any(
        type(key) is not str or type(value) is not str for key, value in tmpfs.items()
    ):
        raise PreflightError("invalid Boca tmpfs metadata")
    cgroupns_mode = host.get("CgroupnsMode")
    if type(cgroupns_mode) is not str:
        raise PreflightError("missing Boca cgroup namespace metadata")
    mounts = json.loads(_run("docker", "inspect", "--format", "{{json .Mounts}}", container))
    if not isinstance(mounts, list) or len(mounts) != 2:
        raise PreflightError("unexpected Boca controller mounts")
    expected_mounts = {
        ("boca-socios_boca_data", "/data", True),
        (KEY_VOLUME, "/run/secrets", False),
    }
    actual_mounts: set[tuple[str, str, bool]] = set()
    for mount in mounts:
        if (
            not isinstance(mount, dict)
            or mount.get("Type") != "volume"
            or mount.get("Driver") != "local"
        ):
            raise PreflightError("unsafe Boca controller mount")
        name, destination, writable = mount.get("Name"), mount.get("Destination"), mount.get("RW")
        if (
            not isinstance(name, str)
            or not isinstance(destination, str)
            or type(writable) is not bool
        ):
            raise PreflightError("invalid Boca controller mount metadata")
        actual_mounts.add((name, destination, writable))
    if actual_mounts != expected_mounts:
        raise PreflightError("Boca controller volume boundary changed")
    _validate_boca_network(container, network_id)
    labels = config.get("Labels")
    entries = config.get("Env")
    if not isinstance(labels, dict) or not isinstance(entries, list):
        raise PreflightError("missing Boca labels or environment")
    environment: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, str) or "=" not in entry:
            raise PreflightError("invalid Boca environment metadata")
        name, value = entry.split("=", 1)
        if name in environment:
            raise PreflightError("duplicate Boca environment variable")
        environment[name] = value
    for name, expected in {
        "BOCA_ENVIRONMENT": "staging",
        "BOCA_DB_PATH": "/data/boca.sqlite3",
        "BOCA_MASTER_KEY_FILE": "/run/secrets/boca_master_key",
    }.items():
        if environment.get(name) != expected:
            raise PreflightError(f"Boca diagnostic {name} mismatch")
    repo_digests = json.loads(
        _run("docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image)
    )
    if not isinstance(repo_digests, list) or image not in repo_digests:
        raise PreflightError("Boca image digest mismatch")
    revision = _run(
        "docker",
        "image",
        "inspect",
        "--format",
        '{{index .Config.Labels "org.opencontainers.image.revision"}}',
        image,
    )
    snapshot = DiagnosticSnapshot(
        uid=os.getuid(),
        # The fixed in-container probe reads metadata only and emits no key bytes.
        key_secure=_run(
            "docker",
            "exec",
            "--user",
            "10001:10001",
            container,
            "python",
            "-m",
            "boca_socios.security.key_custody",
            "inspect",
        )
        == "BOCA_KEY_READY",
        mounts_secure=True,
        container_id=container,
        health=_run("docker", "inspect", "--format", "{{.State.Health.Status}}", container),
        image_ref=str(config.get("Image")),
        revision=revision,
        project=str(labels.get("com.docker.compose.project")),
        service=str(labels.get("com.docker.compose.service")),
        user=str(config.get("User")),
        runtime_mode=environment.get("BOCA_RUNTIME_MODE", ""),
        engine_mode=environment.get("BOCA_ENGINE_MODE", ""),
        cpu_nano=host.get("NanoCpus"),  # type: ignore[arg-type]
        memory_bytes=host.get("Memory"),  # type: ignore[arg-type]
        pids_limit=host.get("PidsLimit"),  # type: ignore[arg-type]
        read_only=host.get("ReadonlyRootfs"),  # type: ignore[arg-type]
        privileged=host.get("Privileged"),  # type: ignore[arg-type]
        has_ports=bool(port_bindings),
        network_mode=host.get("NetworkMode"),  # type: ignore[arg-type]
        networks=frozenset(networks),
        network_id=network_id,
        network_ports=bool(network_ports),
        cap_drop=_string_tuple(host.get("CapDrop"), "CapDrop"),
        cap_add=_string_tuple(host.get("CapAdd"), "CapAdd", nullable=True),
        security_opt=_string_tuple(host.get("SecurityOpt"), "SecurityOpt"),
        tmpfs=tuple(sorted(tmpfs.items())),
        cgroupns_mode=cgroupns_mode,
        cgroup=_cgroup_limits(container),
    )
    validate_diagnostic(snapshot, image, source_sha)
    return snapshot


def phase(phase_name: str, image: str, source_sha: str, compose_sha: str) -> None:
    _validate_coordinates(
        image,
        source_sha,
        compose_sha,
        read_only_preflight=phase_name in {"observe", "inspect-prerequisites"},
    )
    if phase_name == "inspect-prerequisites":
        inspect_prerequisites()
        return
    _validate_docker_boundary()
    if phase_name in {"diagnostic-config", "diagnostic"}:
        _diagnostic_files(compose_sha)
        if phase_name == "diagnostic-config":
            print(_run(*_compose_args("config", "--format", "json"), env=_compose_env(image)))
            return
        diagnostic_snapshot = collect_diagnostic(image, source_sha)
        print(
            "BOCA_DIAGNOSTIC_PASS"
            f" image={image} source_sha={source_sha}"
            f" health={diagnostic_snapshot.health} engine={diagnostic_snapshot.engine_mode} service=controller"
        )
        return
    validate_snapshot(host_snapshot := collect_snapshot())
    if phase_name in {"observe", "preflight"}:
        if COMPOSE.exists() or COMPOSE.is_symlink():
            raise PreflightError("Boca Compose already staged")
        print(
            "BOCA_PREFLIGHT_PASS"
            f" arch={host_snapshot.arch} uid={host_snapshot.uid}"
            f" mem_kib={host_snapshot.available_memory_kib}"
            f" stage_disk_bytes={host_snapshot.available_disk_bytes}"
            f" stage_inodes={host_snapshot.available_inodes}"
            f" docker_disk_bytes={host_snapshot.docker_disk_bytes}"
            f" docker_inodes={host_snapshot.docker_inodes}"
            f" cpu_headroom={host_snapshot.cpu_headroom:.2f}"
            " namespace=empty"
        )
        return
    if phase_name == "stage":
        if COMPOSE.exists() or COMPOSE.is_symlink():
            raise PreflightError("Boca Compose already staged")
        print("BOCA_STAGE_PASS")
        return
    _verify_compose(compose_sha)
    if phase_name == "config":
        print(_run(*_compose_args("config", "--format", "json"), env=_compose_env(image)))
        return
    if phase_name != "apply":
        raise PreflightError("unknown deployment phase")
    _run(*_compose_args("config", "-q"), env=_compose_env(image))
    before_pull = _storage_snapshot()
    _validate_storage_capacity(before_pull)
    _run("docker", "pull", image)
    repo_digests = json.loads(
        _run("docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image)
    )
    revision = _run(
        "docker",
        "image",
        "inspect",
        "--format",
        '{{index .Config.Labels "org.opencontainers.image.revision"}}',
        image,
    )
    if not isinstance(repo_digests, list) or image not in repo_digests or revision != source_sha:
        raise PreflightError("pulled image digest or source revision differs from authorization")
    _verify_compose(compose_sha)
    after_pull = _storage_snapshot()
    _validate_storage_continuity(before_pull, after_pull)
    _create_key(image)
    try:
        _run(
            *_compose_args(
                "up",
                "--no-build",
                "--no-deps",
                "--wait",
                "--wait-timeout",
                "90",
                "-d",
                "controller",
            ),
            env=_compose_env(image),
        )
        container = _run(*_compose_args("ps", "-q", "controller"), env=_compose_env(image))
        if not container or "\n" in container:
            raise PreflightError("expected exactly one Boca controller")
        if (
            _run("docker", "inspect", "--format", "{{.State.Health.Status}}", container)
            != "healthy"
        ):
            raise PreflightError("Boca controller did not become healthy")
        # The same strict contract used by the later read-only diagnostic must
        # hold before the first install can claim success.
        _diagnostic_files(compose_sha)
        collect_diagnostic(image, source_sha)
        final_capacity = _storage_snapshot()
        _validate_storage_continuity(after_pull, final_capacity)
    except (ValueError, OSError, TypeError, KeyError):
        try:
            _run(*_compose_args("stop", "controller"), env=_compose_env(image))
        except PreflightError:
            print(
                "BOCA_ROLLBACK_UNVERIFIED: controller stop failed; inventory Boca before retry",
                file=sys.stderr,
            )
        raise
    print(
        f"BOCA_DEPLOY_PASS image={image} source_sha={source_sha} service=controller"
        f" stage_free_bytes={final_capacity.stage_free_bytes}"
        f" stage_inodes={final_capacity.stage_inodes}"
        f" docker_free_bytes={final_capacity.docker_free_bytes}"
        f" docker_inodes={final_capacity.docker_inodes}"
        f" same_fs={'yes' if final_capacity.stage_device == final_capacity.docker_device else 'no'}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Boca-only first-install host gate")
    parser.add_argument(
        "phase",
        choices=(
            "inspect-prerequisites",
            "observe",
            "preflight",
            "stage",
            "config",
            "apply",
            "diagnostic-config",
            "diagnostic",
        ),
    )
    parser.add_argument("image")
    parser.add_argument("source_sha")
    parser.add_argument("compose_sha")
    args = parser.parse_args()
    try:
        phase(args.phase, args.image, args.source_sha, args.compose_sha)
    except (PreflightError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"BOCA_NO_GO: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
