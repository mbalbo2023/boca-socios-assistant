"""Bounded first-install host helper, streamed over SSH by the gated workflow.

This file uses only the Python standard library and never reads other projects.
Each invocation is a single phase; a failed phase is not retried automatically.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import errno
import hashlib
import http.client
import json
import os
import platform
import pwd
import re
import shutil
import socket
import ssl
import stat
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path("/srv/boca-socios")
COMPOSE = ROOT / "compose.yaml"
BETA_COMPOSE = ROOT / "compose.beta.yaml"
PROJECT = "boca-socios"
DATA_VOLUME = "boca-socios_boca_data"
KEY_VOLUME = "boca-socios_boca_key"
OWNER_VOLUME = "boca-socios_boca_owner"
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
SITE_ORIGIN = "https://boca-socios-consola-demo-20261031.mbalbo14901.chatgpt.site"
SITE_ENVELOPE_FIELDS = frozenset(
    {
        "version",
        "repository",
        "purpose",
        "uid",
        "site_origin",
        "recipient_fingerprint",
        "recipient_public_key",
        "ephemeral_public_key",
        "salt",
        "nonce",
        "ciphertext",
    }
)


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


def validate_site_snapshot(
    snapshot: HostSnapshot, volumes: set[str], *, require_owner: bool
) -> None:
    """Permit only the exact Boca owner volume; never an app or other namespace."""
    if snapshot.boca_volume != bool(volumes) or volumes not in (set(), {OWNER_VOLUME}):
        raise PreflightError("unexpected Boca volume inventory for Site bootstrap")
    if require_owner and volumes != {OWNER_VOLUME}:
        raise PreflightError("Boca owner volume is not installed")
    validate_snapshot(replace(snapshot, boca_volume=False))


def validate_beta_snapshot(
    snapshot: HostSnapshot, volumes: set[str], *, expected: set[str]
) -> None:
    """Allow only the named Boca volumes for the current new-install phase."""
    permitted = {OWNER_VOLUME, KEY_VOLUME, DATA_VOLUME}
    if (
        OWNER_VOLUME not in expected
        or not expected <= permitted
        or volumes != expected
        or snapshot.boca_volume != bool(volumes)
    ):
        raise PreflightError("unexpected Boca BETA volume inventory")
    validate_snapshot(replace(snapshot, boca_volume=False))


def _validate_beta_context(origin: str, owner: str) -> None:
    if not re.fullmatch(
        r"https://[a-z0-9][a-z0-9.-]{0,252}(?::[0-9]{2,5})?", origin
    ) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", owner):
        raise PreflightError("invalid private BETA coordinates")
    try:
        port = urlsplit(origin).port
    except ValueError as exc:
        raise PreflightError("invalid private BETA port") from exc
    if port is not None and not 1024 <= port <= 65535:
        raise PreflightError("invalid private BETA port")


def validate_docker_boundary(snapshot: DockerBoundarySnapshot) -> None:
    if snapshot.socket_secure is not True or snapshot.rootful_socket_inaccessible is not True:
        raise PreflightError("dedicated rootless socket or rootful Docker access is unsafe")
    if snapshot.daemon_rootless is not True:
        raise PreflightError("Docker daemon must be rootless for the dedicated Boca identity")
    if snapshot.cgroup_version != "2" or snapshot.cgroup_driver != "systemd":
        raise PreflightError("rootless Docker cannot prove enforceable cgroup limits")
    if not {"cpu", "memory", "pids"} <= snapshot.controllers:
        raise PreflightError("rootless CPU, memory and PID controllers must be delegated")


def _run(*args: str, env: dict[str, str] | None = None, input_data: str | None = None) -> str:
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
            args,
            check=True,
            text=True,
            capture_output=True,
            timeout=120,
            env=run_env,
            input=input_data,
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


def _candidate_file_metadata(path: Path, anchor: Path) -> tuple[str, int | None]:
    """Stat one candidate via no-follow directory descriptors; never open its data."""
    if (
        path.anchor != "/"
        or anchor.anchor != "/"
        or anchor == Path("/")
        or ".." in path.parts
        or ".." in anchor.parts
        or not path.is_relative_to(anchor)
        or path == anchor
        or len(str(path)) > 4096
        or len(path.parts) > 32
    ):
        return "unsafe-path", None
    descriptor: int | None = None
    try:
        flags = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        descriptor = os.open("/", flags)
        current = Path("/")
        for part in path.parts[1:-1]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            current /= part
            if current == anchor:
                metadata = os.fstat(descriptor)
                if metadata.st_uid != 10001 or stat.S_IMODE(metadata.st_mode) & 0o022:
                    return "unsafe-path", None
        metadata = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
        if stat.S_ISLNK(metadata.st_mode):
            return "unsafe-path", None
        if not stat.S_ISREG(metadata.st_mode):
            return "not-regular", None
        if not 0 <= metadata.st_size < 2**63:
            return "unavailable", None
        return "candidate-present", metadata.st_size
    except FileNotFoundError:
        return "candidate-absent", None
    except PermissionError:
        return "inaccessible", None
    except OSError as exc:
        return ("unsafe-path" if exc.errno in {errno.ELOOP, errno.ENOTDIR} else "unavailable"), None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _database_candidate_metadata() -> str:
    """Fixed locations are candidates, never a global database existence claim."""
    _require_dedicated_identity()
    candidates: tuple[tuple[str, Path, Path], ...] = ()
    try:
        raw_home = getattr(pwd.getpwuid(10001), "pw_dir", None)
        if (
            isinstance(raw_home, str)
            and raw_home.startswith("/")
            and not raw_home.startswith("//")
            and raw_home != "/"
            and len(raw_home) <= 4096
            and ".." not in Path(raw_home).parts
            and str(Path(raw_home)) == raw_home
        ):
            home = Path(raw_home)
            candidates = (
                (
                    "rootless_default",
                    home / ".local/share/docker/volumes/boca-socios_boca_data/_data/boca.sqlite3",
                    home,
                ),
                ("staging_root", ROOT / "boca.sqlite3", ROOT),
                ("staging_data", ROOT / "data/boca.sqlite3", ROOT),
            )
    except (KeyError, OSError, ValueError):
        pass
    lines = ["BOCA_DB_CANDIDATES location=UNVERIFIED scope=fixed_paths_only"]
    if not candidates:
        for label in ("rootless_default", "staging_root", "staging_data"):
            lines.append(
                f"BOCA_DB_CANDIDATE label={label} db=unavailable wal=unavailable shm=unavailable"
            )
        return "\n".join(lines)
    for label, path, anchor in candidates:
        fields = [f"BOCA_DB_CANDIDATE label={label}"]
        for name, suffix in (("db", ""), ("wal", "-wal"), ("shm", "-shm")):
            state, size = _candidate_file_metadata(Path(str(path) + suffix), anchor)
            fields.append(f"{name}={state}")
            if size is not None:
                fields.append(f"{name}_bytes={size}")
        lines.append(" ".join(fields))
    return "\n".join(lines)


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
    print(_database_candidate_metadata())
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


def _beta_root_ready() -> bool:
    if not _safe_dir(ROOT):
        return False
    try:
        entries = {child.name for child in ROOT.iterdir()}
    except OSError:
        return False
    return (
        entries == {BETA_COMPOSE.name}
        and not BETA_COMPOSE.is_symlink()
        and os.access(ROOT, os.W_OK)
    )


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


def collect_snapshot(*, beta_staged: bool = False) -> HostSnapshot:
    # The deployment identity owns only the rootless Docker endpoint; the key
    # is generated in a separate named volume within the container UID map.
    uid = _require_dedicated_identity()
    if not (_beta_root_ready() if beta_staged else _root_ready()):
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


def _verify_beta_compose(expected_sha: str) -> None:
    if not _beta_root_ready():
        raise PreflightError("unsafe staged BETA directory")
    metadata = BETA_COMPOSE.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 10001
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or metadata.st_size > 32_768
        or hashlib.sha256(BETA_COMPOSE.read_bytes()).hexdigest() != expected_sha
    ):
        raise PreflightError("staged BETA Compose differs from reviewed file")


def _compose_env(image: str) -> dict[str, str]:
    return {
        **os.environ,
        "BOCA_IMAGE": image,
        "BOCA_ENVIRONMENT": "staging",
    }


def _compose_args(*args: str) -> tuple[str, ...]:
    return ("docker", "compose", "-p", PROJECT, "-f", str(COMPOSE), *args)


def _beta_compose_env(image: str, origin: str, owner: str) -> dict[str, str]:
    return {
        **_compose_env(image),
        "BOCA_PANEL_ORIGIN": origin,
        "BOCA_OWNER_SUBJECT": owner,
    }


def _beta_compose_args(*args: str) -> tuple[str, ...]:
    return ("docker", "compose", "-p", PROJECT, "-f", str(BETA_COMPOSE), *args)


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


def _validate_owner_volume() -> None:
    volume = _json_object(
        _run("docker", "volume", "inspect", "--format", "{{json .}}", OWNER_VOLUME),
        "owner volume",
    )
    root = Path(_run("docker", "info", "--format", "{{.DockerRootDir}}"))
    expected = root / "volumes" / OWNER_VOLUME / "_data"
    labels = volume.get("Labels")
    if (
        volume.get("Name") != OWNER_VOLUME
        or volume.get("Driver") != "local"
        or volume.get("Scope") != "local"
        or volume.get("Options") not in (None, {})
        or not root.is_absolute()
        or root == Path("/")
        or volume.get("Mountpoint") != str(expected)
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != PROJECT
        or labels.get("com.docker.compose.volume") != "boca_owner"
    ):
        raise PreflightError("Boca owner volume identity is unsafe")
    try:
        if root.resolve(strict=True) != root or expected.resolve(strict=True) != expected:
            raise PreflightError("Boca owner volume mountpoint is redirected")
    except (OSError, RuntimeError) as exc:
        raise PreflightError("Boca owner volume mountpoint is unavailable") from exc


def _validate_data_volume() -> None:
    volume = _json_object(
        _run("docker", "volume", "inspect", "--format", "{{json .}}", DATA_VOLUME),
        "data volume",
    )
    root = Path(_run("docker", "info", "--format", "{{.DockerRootDir}}"))
    expected = root / "volumes" / DATA_VOLUME / "_data"
    labels = volume.get("Labels")
    if (
        volume.get("Name") != DATA_VOLUME
        or volume.get("Driver") != "local"
        or volume.get("Scope") != "local"
        or volume.get("Options") not in (None, {})
        or not root.is_absolute()
        or root == Path("/")
        or volume.get("Mountpoint") != str(expected)
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != PROJECT
        or labels.get("com.docker.compose.volume") != "boca_data"
    ):
        raise PreflightError("Boca data volume identity is unsafe")
    try:
        if root.resolve(strict=True) != root or expected.resolve(strict=True) != expected:
            raise PreflightError("Boca data volume mountpoint is redirected")
    except (OSError, RuntimeError) as exc:
        raise PreflightError("Boca data volume mountpoint is unavailable") from exc


def _owner_init_container(image: str) -> tuple[str, ...]:
    # The new empty volume starts root-owned in the container user namespace.
    # chmod precedes chown because this one-shot container retains only CHOWN.
    return (
        "docker",
        "run",
        "--rm",
        "--pull",
        "never",
        "--user",
        "0:0",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--cap-add",
        "CHOWN",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "16",
        "--memory",
        "64m",
        "--cpus",
        "0.25",
        "--mount",
        f"type=volume,source={OWNER_VOLUME},target=/run/owner,volume-nocopy",
        image,
        "python",
        "-c",
        "import os; os.chmod('/run/owner', 0o700); os.chown('/run/owner', 10001, 10001)",
    )


def _site_container(image: str, operation: str) -> tuple[str, ...]:
    if operation not in {"prepare", "install", "verify"} or not IMAGE_PATTERN.fullmatch(image):
        raise PreflightError("invalid Site bootstrap coordinates")
    return (
        "docker",
        "run",
        "--rm",
        "--pull",
        "never",
        *(("-i",) if operation == "install" else ()),
        "--user",
        "10001:10001",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "16",
        "--memory",
        "64m",
        "--cpus",
        "0.25",
        "--mount",
        f"type=volume,source={OWNER_VOLUME},target=/run/owner,volume-nocopy"
        + (",readonly" if operation == "verify" else ""),
        image,
        "python",
        "-m",
        "boca_socios.site_bootstrap",
        operation,
    )


def _site_envelope(value: str) -> str:
    """Accept only a canonical, bounded ciphertext envelope as transport data."""
    try:
        if not value or len(value) > 10923 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        if (
            not 0 < len(raw) <= 8192
            or base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != value
        ):
            raise ValueError

        def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, item in pairs:
                if key in result:
                    raise ValueError
                result[key] = item
            return result

        decoded = raw.decode("ascii")
        data = json.loads(decoded, object_pairs_hook=unique)
        if (
            not isinstance(data, dict)
            or set(data) != SITE_ENVELOPE_FIELDS
            or type(data["version"]) is not int
            or data["version"] != 1
            or data["repository"] != "mbalbo2023/boca-socios-assistant"
            or data["purpose"] != "boca-site-bridge-machine-v1"
            or type(data["uid"]) is not int
            or data["uid"] != 10001
            or data["site_origin"] != SITE_ORIGIN
            or json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True) != decoded
        ):
            raise ValueError
        sizes = {
            "recipient_public_key": (32, 32),
            "ephemeral_public_key": (32, 32),
            "salt": (16, 16),
            "nonce": (12, 12),
            "ciphertext": (16, 4096),
        }
        for key, (minimum, maximum) in sizes.items():
            token = data[key]
            if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
                raise ValueError
            binary = base64.b64decode(
                token + "=" * (-len(token) % 4), altchars=b"-_", validate=True
            )
            if (
                not minimum <= len(binary) <= maximum
                or base64.urlsafe_b64encode(binary).rstrip(b"=").decode("ascii") != token
            ):
                raise ValueError
        fingerprint = data["recipient_fingerprint"]
        if (
            not isinstance(fingerprint, str)
            or not DIGEST_PATTERN.fullmatch(fingerprint)
            or hashlib.sha256(
                base64.urlsafe_b64decode(data["recipient_public_key"] + "=")
            ).hexdigest()
            != fingerprint
        ):
            raise ValueError
    except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error) as exc:
        raise PreflightError("invalid sealed Site envelope") from exc
    return decoded


def _site_receipt(output: str, operation: str) -> str:
    if len(output) > 256:
        raise PreflightError("invalid Site bootstrap receipt")
    if operation == "prepare":
        match = re.fullmatch(
            r"BOCA_SITE_BOOTSTRAP state=(PREPARED|ALREADY_PREPARED)"
            r" public_key=([A-Za-z0-9_-]{43}) fingerprint=([0-9a-f]{64})",
            output,
        )
        if match is not None:
            try:
                public = base64.b64decode(match[2] + "=", altchars=b"-_", validate=True)
                if len(public) == 32 and hashlib.sha256(public).hexdigest() == match[3]:
                    return output
            except (ValueError, binascii.Error):
                pass
    elif operation in {"install", "verify"}:
        state = "CONFIGURED" if operation == "install" else "VERIFIED"
        if re.fullmatch(rf"BOCA_SITE_BOOTSTRAP state={state} fingerprint=[0-9a-f]{{64}}", output):
            return output
    raise PreflightError("invalid Site bootstrap receipt")


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


def _beta_check_container(image: str, origin: str, owner: str, operation: str) -> tuple[str, ...]:
    if operation not in {"check-beta-owner", "check-beta-config"}:
        raise PreflightError("invalid BETA preflight")
    _validate_beta_context(origin, owner)
    if not IMAGE_PATTERN.fullmatch(image):
        raise PreflightError("invalid BETA image")
    env = {
        "BOCA_ENVIRONMENT": "staging",
        "BOCA_RUNTIME_MODE": "simulation",
        "BOCA_ENGINE_MODE": "off",
        "BOCA_DB_PATH": "/data/boca.sqlite3",
        "BOCA_MASTER_KEY_FILE": "/run/secrets/boca_master_key",
        "BOCA_PANEL_ORIGIN": origin,
        "BOCA_OWNER_SUBJECT": owner,
        "BOCA_PASSKEY_CREDENTIAL_ID_FILE": "/run/owner/credential_id",
        "BOCA_PASSKEY_PUBLIC_KEY_DER_FILE": "/run/owner/public_key.der",
        "BOCA_TLS_CERT_FILE": "/run/owner/tls.crt",
        "BOCA_TLS_KEY_FILE": "/run/owner/tls.key",
        "BOCA_HEALTH_CA_FILE": "/run/owner/health-ca.pem",
        "BOCA_BIND_HOST": "0.0.0.0",  # noqa: S104 - isolated Boca bridge, host loopback only
        "BOCA_BIND_PORT": "8443",
    }
    return (
        "docker",
        "run",
        "--rm",
        "--pull",
        "never",
        "--user",
        "10001:10001",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "16",
        "--memory",
        "64m",
        "--cpus",
        "0.25",
        *(arg for pair in sorted(env.items()) for arg in ("--env", f"{pair[0]}={pair[1]}")),
        "--mount",
        f"type=volume,source={OWNER_VOLUME},target=/run/owner,volume-nocopy,readonly",
        *(
            (
                "--mount",
                f"type=volume,source={KEY_VOLUME},target=/run/secrets,volume-nocopy,readonly",
            )
            if operation == "check-beta-config"
            else ()
        ),
        image,
        "python",
        "-m",
        "boca_socios.runtime",
        operation,
    )


def _beta_check_receipt(output: str, operation: str) -> None:
    expected = (
        '{"event":"beta_owner_ready","mode":"simulation","engine":"off"}'
        if operation == "check-beta-owner"
        else '{"event":"beta_config_ready","mode":"simulation","engine":"off"}'
    )
    if output != expected:
        raise PreflightError("BETA image preflight did not confirm readiness")


def _beta_init_container(image: str) -> tuple[str, ...]:
    if not IMAGE_PATTERN.fullmatch(image):
        raise PreflightError("invalid BETA image")
    return (
        "docker",
        "run",
        "--rm",
        "--pull",
        "never",
        "--user",
        "10001:10001",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "64",
        "--memory",
        "256m",
        "--cpus",
        "0.50",
        "--env",
        "BOCA_ENVIRONMENT=staging",
        "--env",
        "BOCA_RUNTIME_MODE=simulation",
        "--env",
        "BOCA_ENGINE_MODE=off",
        "--env",
        "BOCA_DB_PATH=/data/boca.sqlite3",
        "--env",
        "BOCA_MASTER_KEY_FILE=/run/secrets/boca_master_key",
        "--mount",
        f"type=volume,source={DATA_VOLUME},target=/data",
        "--mount",
        f"type=volume,source={KEY_VOLUME},target=/run/secrets,volume-nocopy,readonly",
        image,
        "python",
        "-m",
        "boca_socios.runtime",
        "init-beta",
    )


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


def collect_diagnostic(
    image: str, source_sha: str, *, beta_origin: str = "", beta_owner: str = ""
) -> DiagnosticSnapshot:
    beta = bool(beta_origin)
    if beta:
        _validate_beta_context(beta_origin, beta_owner)
    args = _beta_compose_args if beta else _compose_args
    environment_vars = (
        _beta_compose_env(image, beta_origin, beta_owner) if beta else _compose_env(image)
    )
    container = _run(*args("ps", "-q", "controller"), env=environment_vars)
    if not re.fullmatch(r"[0-9a-f]{64}", container):
        raise PreflightError("expected exactly one Boca controller")
    if beta and set(_run("docker", "ps", "-a", "-q", "--no-trunc").splitlines()) != {container}:
        raise PreflightError("dedicated BETA daemon has an unexpected container")
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
    if not isinstance(mounts, list) or len(mounts) != (3 if beta else 2):
        raise PreflightError("unexpected Boca controller mounts")
    expected_mounts = {
        (DATA_VOLUME, "/data", True),
        (KEY_VOLUME, "/run/secrets", False),
    }
    if beta:
        expected_mounts.add((OWNER_VOLUME, "/run/owner", False))
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
        **(
            {
                "BOCA_PANEL_ORIGIN": beta_origin,
                "BOCA_OWNER_SUBJECT": beta_owner,
                "BOCA_PASSKEY_CREDENTIAL_ID_FILE": "/run/owner/credential_id",
                "BOCA_PASSKEY_PUBLIC_KEY_DER_FILE": "/run/owner/public_key.der",
                "BOCA_TLS_CERT_FILE": "/run/owner/tls.crt",
                "BOCA_TLS_KEY_FILE": "/run/owner/tls.key",
                "BOCA_HEALTH_CA_FILE": "/run/owner/health-ca.pem",
                "BOCA_HEALTH_MODE": "beta",
                "BOCA_BIND_HOST": "0.0.0.0",  # noqa: S104 - isolated Boca bridge
                "BOCA_BIND_PORT": "8443",
            }
            if beta
            else {}
        ),
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
    if beta:
        expected_ports = {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
        if port_bindings != expected_ports or network_ports != expected_ports:
            raise PreflightError("BETA host loopback port binding changed")
        restart = host.get("RestartPolicy")
        if (
            config.get("Cmd") != ["python", "-m", "boca_socios.runtime", "serve-beta"]
            or config.get("Entrypoint") not in (None, [])
            or not isinstance(restart, dict)
            or restart.get("Name") != "unless-stopped"
            or restart.get("MaximumRetryCount") != 0
        ):
            raise PreflightError("BETA command or restart policy changed")
        validate_diagnostic(
            replace(snapshot, has_ports=False, network_ports=False), image, source_sha
        )
        if environment.get("BOCA_SITE_BRIDGE_MODE", "off") != "off":
            raise PreflightError("BETA Site bridge activation is not authorized")
    else:
        validate_diagnostic(snapshot, image, source_sha)
    return snapshot


def _beta_loopback_health(container: str, origin: str) -> None:
    """Use the container's public CA only; connect to the host loopback publish."""
    authority = urlsplit(origin)
    if not authority.hostname:
        raise PreflightError("invalid BETA TLS hostname")
    ca = _run(
        "docker",
        "exec",
        "--user",
        "10001:10001",
        container,
        "python",
        "-c",
        "from pathlib import Path; print(Path('/run/owner/health-ca.pem').read_text(encoding='ascii'))",
    )
    if not 0 < len(ca) <= 16_384 or "-----BEGIN CERTIFICATE-----" not in ca:
        raise PreflightError("BETA trust anchor unavailable")
    context = ssl.create_default_context(cadata=ca)
    try:
        with socket.create_connection(("127.0.0.1", 8443), timeout=3) as plain:
            with context.wrap_socket(plain, server_hostname=authority.hostname) as secured:
                secured.settimeout(3)
                secured.sendall(
                    f"GET /healthz HTTP/1.1\r\nHost: {authority.netloc}\r\n"
                    "Connection: close\r\n\r\n".encode("ascii")
                )
                response = http.client.HTTPResponse(secured)
                response.begin()
                if response.status != 200 or response.read(64) != b"BOCA_BETA_READY":
                    raise PreflightError("BETA host loopback health unavailable")
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        raise PreflightError("BETA host loopback TLS unavailable") from exc


def _beta_inventory(*, staged: bool, expected: set[str]) -> HostSnapshot:
    snapshot = collect_snapshot(beta_staged=staged)
    if _run("docker", "ps", "-a", "-q", "--no-trunc"):
        raise PreflightError("dedicated BETA daemon must have no containers before install")
    volumes = _names("volume", "name=^boca-socios_")
    validate_beta_snapshot(snapshot, volumes, expected=expected)
    _validate_owner_volume()
    if _run("docker", "ps", "-a", "-q", "--filter", f"volume={OWNER_VOLUME}"):
        raise PreflightError("Boca owner volume is attached to a container")
    return snapshot


def _beta_pull(image: str, source_sha: str) -> None:
    before = _storage_snapshot()
    _validate_storage_capacity(before)
    _run("docker", "pull", image)
    digests = json.loads(
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
    if not isinstance(digests, list) or image not in digests or revision != source_sha:
        raise PreflightError("pulled BETA image differs from reviewed release")
    _validate_storage_continuity(before, _storage_snapshot())


def _beta_rollback(image: str, source_sha: str) -> None:
    global_ids = set(_run("docker", "ps", "-a", "-q", "--no-trunc").splitlines())
    labeled = set(
        _run(
            "docker",
            "ps",
            "-a",
            "-q",
            "--no-trunc",
            "--filter",
            f"label=com.docker.compose.project={PROJECT}",
        ).splitlines()
    )
    named = set(
        _run(
            "docker", "ps", "-a", "-q", "--no-trunc", "--filter", "name=^/boca-socios-"
        ).splitlines()
    )
    if global_ids != labeled or labeled != named or len(labeled) > 1:
        raise PreflightError("Boca rollback container inventory is uncertain")
    state = "NO_CONTROLLER"
    if labeled:
        container = next(iter(labeled))
        if not re.fullmatch(r"[0-9a-f]{64}", container):
            raise PreflightError("Boca rollback container ID is uncertain")
        record = _json_object(
            _run("docker", "inspect", "--format", "{{json .}}", container), "rollback container"
        )
        config = record.get("Config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        current_state = record.get("State")
        if (
            record.get("Id") != container
            or record.get("Name") != "/boca-socios-controller-1"
            or not isinstance(config, dict)
            or config.get("Image") != image
            or config.get("User") != "10001:10001"
            or not isinstance(labels, dict)
            or labels.get("com.docker.compose.project") != PROJECT
            or labels.get("com.docker.compose.service") != "controller"
            or labels.get("org.opencontainers.image.revision") != source_sha
            or not isinstance(current_state, dict)
            or type(current_state.get("Running")) is not bool
        ):
            raise PreflightError("Boca rollback controller identity is uncertain")
        if current_state["Running"]:
            _run("docker", "stop", "--time", "30", container)
            state = "STOPPED"
        else:
            state = "ALREADY_STOPPED"
        after = _json_object(
            _run("docker", "inspect", "--format", "{{json .State}}", container), "stopped state"
        )
        if after.get("Running") is not False or after.get("Restarting") is not False:
            raise PreflightError("Boca rollback controller stop is unverified")
    storage = _storage_snapshot()
    print(
        f"BOCA_BETA_ROLLBACK state={state} data=preserved key=preserved owner=preserved"
        f" stage=preserved stage_free_mib={storage.stage_free_bytes // 1024**2}"
        f" docker_free_mib={storage.docker_free_bytes // 1024**2}"
        f" stage_inodes={storage.stage_inodes} docker_inodes={storage.docker_inodes}"
    )


def _validate_beta_acceptance_receipt(raw: str) -> str:
    """Accept only the fixed disposable probe proof, never its arbitrary stdout."""
    if len(raw) > 384:
        raise PreflightError("BETA synthetic receipt exceeds bounded output")
    match = re.fullmatch(
        r"BOCA_SYNTHETIC_ACCEPTANCE state=PASS scope=container_loopback"
        r" requests=([0-9]{2}) median_ms=([0-9]{1,6}[.][0-9]{2})"
        r" p95_ms=([0-9]{1,6}[.][0-9]{2}) elapsed_ms=([0-9]{1,6}[.][0-9]{2})"
        r" cpu_ms=([0-9]{1,6}[.][0-9]{2}) process_peak_rss_kib=([0-9]{1,6})"
        r" scratch_bytes=([0-9]{1,7}) members=1 intents=1 notices=1"
        r" tls=verified engine=off site=not_contacted telegram=not_sent",
        raw,
    )
    if match is None:
        raise PreflightError("invalid BETA synthetic receipt")
    requests, median, p95, elapsed, cpu, rss, scratch = match.groups()
    if (
        not 18 <= int(requests) <= 64
        or not 0 <= float(median) <= float(p95) <= float(elapsed) <= 120_000
        or not 0 <= float(cpu) <= 120_000
        or not 0 < int(rss) <= 262_144
        or not 0 < int(scratch) <= 8 * 1024 * 1024
    ):
        raise PreflightError("BETA synthetic measurements are invalid")
    return raw


def _beta_acceptance_status(
    image: str, source_sha: str, compose_sha: str, origin: str, owner: str
) -> tuple[DiagnosticSnapshot, StorageSnapshot]:
    """Revalidate the whole installed Boca boundary before and after the probe."""
    _verify_beta_compose(compose_sha)
    snapshot = collect_snapshot(beta_staged=True)
    volumes = _names("volume", "name=^boca-socios_")
    networks = _names("network", "name=^boca-socios_")
    if volumes != {OWNER_VOLUME, KEY_VOLUME, DATA_VOLUME} or networks != {
        "boca-socios_boca_private"
    }:
        raise PreflightError("installed Boca namespace differs from reviewed BETA")
    if not snapshot.boca_containers or not snapshot.boca_volume or not snapshot.boca_network:
        raise PreflightError("installed Boca controller or resources are absent")
    validate_snapshot(
        replace(snapshot, boca_containers=False, boca_volume=False, boca_network=False)
    )
    _validate_owner_volume()
    _validate_key_volume()
    _validate_data_volume()
    _run(*_beta_compose_args("config", "-q"), env=_beta_compose_env(image, origin, owner))
    diagnostic = collect_diagnostic(image, source_sha, beta_origin=origin, beta_owner=owner)
    _beta_loopback_health(diagnostic.container_id, origin)
    capacity = _storage_snapshot()
    _validate_storage_capacity(capacity)
    return diagnostic, capacity


def _beta_acceptance_phase(
    image: str, source_sha: str, compose_sha: str, origin: str, owner: str
) -> None:
    _validate_beta_context(origin, owner)
    before, capacity_before = _beta_acceptance_status(image, source_sha, compose_sha, origin, owner)
    receipt = _validate_beta_acceptance_receipt(
        _run(
            "docker",
            "exec",
            "--user",
            "10001:10001",
            before.container_id,
            "python",
            "-m",
            "boca_socios.acceptance.host_probe",
        )
    )
    after, capacity_after = _beta_acceptance_status(image, source_sha, compose_sha, origin, owner)
    if after.container_id != before.container_id:
        raise PreflightError("Boca controller changed during synthetic acceptance")
    _validate_storage_continuity(capacity_before, capacity_after)
    print(
        f"BOCA_BETA_ACCEPTANCE state=PASS source_sha={source_sha} image={image}"
        + receipt.removeprefix("BOCA_SYNTHETIC_ACCEPTANCE state=PASS")
        + f" stage_free_mib={capacity_after.stage_free_bytes // 1024**2}"
        + f" docker_free_mib={capacity_after.docker_free_bytes // 1024**2}"
        + f" stage_inodes={capacity_after.stage_inodes}"
        + f" docker_inodes={capacity_after.docker_inodes}"
    )


def _beta_phase(
    operation: str, image: str, source_sha: str, compose_sha: str, origin: str, owner: str
) -> None:
    _validate_beta_context(origin, owner)
    if operation == "beta-rollback":
        _beta_rollback(image, source_sha)
        return
    if operation == "beta-acceptance":
        _beta_acceptance_phase(image, source_sha, compose_sha, origin, owner)
        return
    staged = operation in {"beta-config", "beta-apply"}
    if staged:
        _verify_beta_compose(compose_sha)
    snapshot = _beta_inventory(staged=staged, expected={OWNER_VOLUME})
    if not staged and (COMPOSE.exists() or BETA_COMPOSE.exists() or any(ROOT.iterdir())):
        raise PreflightError("Boca app files already staged; recovery review required")
    if operation in {"beta-preflight", "beta-stage"}:
        print(
            f"BOCA_BETA_PREFLIGHT state=PASS uid={snapshot.uid}"
            f" mem_kib={snapshot.available_memory_kib}"
            f" stage_free_mib={snapshot.available_disk_bytes // 1024**2}"
            f" docker_free_mib={snapshot.docker_disk_bytes // 1024**2}"
            f" stage_inodes={snapshot.available_inodes} docker_inodes={snapshot.docker_inodes}"
            " owner=existing app=absent"
        )
        return
    compose_env = _beta_compose_env(image, origin, owner)
    if operation == "beta-config":
        print(_run(*_beta_compose_args("config", "--format", "json"), env=compose_env))
        return
    if operation != "beta-apply":
        raise PreflightError("unknown BETA phase")
    _run(*_beta_compose_args("config", "-q"), env=compose_env)
    _beta_pull(image, source_sha)
    _verify_beta_compose(compose_sha)
    _beta_inventory(staged=True, expected={OWNER_VOLUME})
    _beta_check_receipt(
        _run(*_beta_check_container(image, origin, owner, "check-beta-owner")),
        "check-beta-owner",
    )
    _beta_inventory(staged=True, expected={OWNER_VOLUME})
    _create_key(image)
    _beta_inventory(staged=True, expected={OWNER_VOLUME, KEY_VOLUME})
    _beta_check_receipt(
        _run(*_beta_check_container(image, origin, owner, "check-beta-config")),
        "check-beta-config",
    )
    _beta_inventory(staged=True, expected={OWNER_VOLUME, KEY_VOLUME})
    created = _run(
        "docker",
        "volume",
        "create",
        "--driver",
        "local",
        "--label",
        f"com.docker.compose.project={PROJECT}",
        "--label",
        "com.docker.compose.volume=boca_data",
        DATA_VOLUME,
    )
    if created != DATA_VOLUME:
        raise PreflightError("unexpected Boca data volume creation")
    _validate_data_volume()
    if _run(*_beta_init_container(image)):
        raise PreflightError("BETA new-only database initialization had unexpected output")
    _validate_data_volume()
    _validate_key_volume()
    _validate_owner_volume()
    _beta_inventory(staged=True, expected={OWNER_VOLUME, KEY_VOLUME, DATA_VOLUME})
    _run(
        *_beta_compose_args(
            "up", "--no-build", "--no-deps", "--wait", "--wait-timeout", "90", "-d", "controller"
        ),
        env=compose_env,
    )
    _verify_beta_compose(compose_sha)
    _validate_data_volume()
    _validate_key_volume()
    _validate_owner_volume()
    diagnostic = collect_diagnostic(image, source_sha, beta_origin=origin, beta_owner=owner)
    _beta_loopback_health(diagnostic.container_id, origin)
    capacity = _storage_snapshot()
    _validate_storage_capacity(capacity)
    print(
        f"BOCA_BETA_INSTALL state=PASS source_sha={source_sha} image={image}"
        " service=controller host=loopback tls=verified engine=off site=off telegram=off"
        f" stage_free_mib={capacity.stage_free_bytes // 1024**2}"
        f" docker_free_mib={capacity.docker_free_bytes // 1024**2}"
        f" stage_inodes={capacity.stage_inodes} docker_inodes={capacity.docker_inodes}"
    )


def _site_phase(operation: str, image: str, source_sha: str, envelope: str) -> None:
    if (envelope and operation != "site-install") or (operation == "site-install" and not envelope):
        raise PreflightError("sealed Site envelope required only for install")
    decoded = _site_envelope(envelope) if operation == "site-install" else None
    if COMPOSE.exists() or COMPOSE.is_symlink():
        raise PreflightError("Boca Compose already staged; separate recovery review required")
    _site_daemon_empty()
    name = operation.removeprefix("site-")
    volumes = _names("volume", "name=^boca-socios_")
    validate_site_snapshot(collect_snapshot(), volumes, require_owner=name != "prepare")
    if volumes:
        _validate_owner_volume()
        if _run("docker", "ps", "-a", "-q", "--filter", f"volume={OWNER_VOLUME}"):
            raise PreflightError("Boca owner volume is attached to a container")
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
        raise PreflightError("pulled Site bootstrap image differs from reviewed release")
    _validate_storage_continuity(before_pull, _storage_snapshot())
    # Reject a changed namespace before the first owner-volume effect.
    _site_daemon_empty()
    current = _names("volume", "name=^boca-socios_")
    validate_site_snapshot(collect_snapshot(), current, require_owner=name != "prepare")
    if current != volumes:
        raise PreflightError("Boca owner volume inventory changed during bootstrap")
    if current and _run("docker", "ps", "-a", "-q", "--filter", f"volume={OWNER_VOLUME}"):
        raise PreflightError("Boca owner volume became attached to a container")
    if name == "prepare" and not current:
        created = _run(
            "docker",
            "volume",
            "create",
            "--driver",
            "local",
            "--label",
            f"com.docker.compose.project={PROJECT}",
            "--label",
            "com.docker.compose.volume=boca_owner",
            OWNER_VOLUME,
        )
        if created != OWNER_VOLUME:
            raise PreflightError("unexpected Boca owner volume creation")
        _validate_owner_volume()
        _site_daemon_empty()
        if _run(*_owner_init_container(image)):
            raise PreflightError("Boca owner directory preparation had unexpected output")
    _validate_owner_volume()
    _site_daemon_empty()
    receipt = _site_receipt(_run(*_site_container(image, name), input_data=decoded), name)
    _validate_owner_volume()
    _site_daemon_empty()
    print(receipt)


def _site_daemon_empty() -> None:
    """The dedicated rootless daemon cannot conceal foreign unlabeled containers."""
    if _run("docker", "ps", "-a", "-q", "--no-trunc"):
        raise PreflightError("dedicated Site daemon has an unexpected container")


def phase(
    phase_name: str,
    image: str,
    source_sha: str,
    compose_sha: str,
    envelope: str = "",
    beta_owner: str = "",
) -> None:
    beta = phase_name.startswith("beta-")
    if beta:
        if phase_name not in {
            "beta-preflight",
            "beta-stage",
            "beta-config",
            "beta-apply",
            "beta-rollback",
            "beta-acceptance",
        }:
            raise PreflightError("unknown BETA deployment phase")
        _validate_beta_context(envelope, beta_owner)
    elif beta_owner:
        raise PreflightError("unexpected BETA context outside BETA phase")
    elif envelope and phase_name != "site-install":
        raise PreflightError("unexpected Site envelope outside install phase")
    _validate_coordinates(
        image,
        source_sha,
        compose_sha,
        read_only_preflight=phase_name in {"observe", "inspect-prerequisites"},
    )
    if phase_name == "inspect-prerequisites":
        inspect_prerequisites()
        return
    if beta:
        _validate_docker_boundary()
        _beta_phase(phase_name, image, source_sha, compose_sha, envelope, beta_owner)
        return
    if phase_name.startswith("site-"):
        if phase_name not in {"site-prepare", "site-install", "site-verify"}:
            raise PreflightError("unknown Site bootstrap phase")
        _validate_docker_boundary()
        _site_phase(phase_name, image, source_sha, envelope)
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
            "site-prepare",
            "site-install",
            "site-verify",
            "beta-preflight",
            "beta-stage",
            "beta-config",
            "beta-apply",
            "beta-rollback",
            "beta-acceptance",
        ),
    )
    parser.add_argument("image")
    parser.add_argument("source_sha")
    parser.add_argument("compose_sha")
    parser.add_argument("envelope", nargs="?", default="")
    parser.add_argument("beta_owner", nargs="?", default="")
    args = parser.parse_args()
    try:
        phase(
            args.phase,
            args.image,
            args.source_sha,
            args.compose_sha,
            args.envelope,
            args.beta_owner,
        )
    except (PreflightError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"BOCA_NO_GO: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
