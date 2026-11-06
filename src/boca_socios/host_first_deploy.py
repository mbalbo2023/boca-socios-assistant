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
import math
import os
import platform
import pwd
import re
import shlex
import shutil
import socket
import ssl
import stat
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from time import monotonic, sleep
from typing import cast
from urllib.parse import urlsplit

ROOT = Path("/srv/boca-socios")
COMPOSE = ROOT / "compose.yaml"
BETA_COMPOSE = ROOT / "compose.beta.yaml"
# #323 opt-in **in-process only** overlay for a future single SSH transaction.
# Legacy per-phase CLI stays unchanged and cannot set this context from argv.
_PROTECTED_COMPOSE_OVERLAY: tuple[str, Path] | None = None
PROJECT = "boca-socios"
DATA_VOLUME = "boca-socios_boca_data"
KEY_VOLUME = "boca-socios_boca_key"
OWNER_VOLUME = "boca-socios_boca_owner"
ENROLL_STAGE = Path("/run/enrollment")
ENROLL_VOLUME = "boca-socios_owner_enroll_staging"
ENROLL_MARKER = ROOT / "owner-enroll-attempt.json"
ENROLL_NETWORK = "boca-socios_owner_enroll_private"
ENROLL_CONTAINER = "boca-socios-owner-enroll-1"
ENROLL_NETWORK_OPTIONS = {
    "com.docker.network.bridge.enable_ip_masquerade": "false",
    "com.docker.network.bridge.enable_icc": "false",
    "com.docker.network.bridge.host_binding_ipv4": "127.0.0.1",
}
# RCA #275: keep the original ICC=false diagnostic unchanged. Owner-approved
# enrollment uses the ICC=true profile only on its disposable Boca rootless
# bridge: no masquerade, exactly one authorized peer, loopback host binding.
PROBE_ICC_TRUE_OPTIONS = {
    **ENROLL_NETWORK_OPTIONS,
    "com.docker.network.bridge.enable_icc": "true",
}
OWNER_ENROLL_NETWORK_OPTIONS = dict(PROBE_ICC_TRUE_OPTIONS)
# Opt-in browser-ipc-v2 ONLY. The legacy singleton beta-install contract above
# and below is intentionally unchanged; these coordinates require their own
# protected, new-only attempt marker and dedicated cleanup in the SAME job.
BROWSER_COMPOSE = ROOT / "compose.beta.browser.yaml"
BROWSER_SECCOMP = ROOT / "seccomp_profile.json"
BROWSER_MARKER = ROOT / "browser-ipc-attempt.json"
BROWSER_IPC_VOLUME = "boca-socios_boca_browser_ipc"
BROWSER_BRIDGE = "boca-socios_boca_private"
BROWSER_IMAGE_PATTERN = re.compile(
    r"ghcr\.io/mbalbo2023/boca-socios-assistant-browser@sha256:[0-9a-f]{64}\Z"
)
BROWSER_ATTEMPT_PATTERN = re.compile(r"[1-9][0-9]{0,19}\Z")
BROWSER_MARKER_VERSION = "browser-ipc-new-only-v2"
BROWSER_ATTEMPT_LABEL = "boca.socios.browser-ipc-attempt"
# Option A is deliberately *not* the new-only browser-install path.  The
# deployed singleton remains running while its historical Docker identity is
# observed, and the read-only host gate below never stages files or images.
CUTOVER_LEGACY_NAME = f"{PROJECT}-controller-1"
CUTOVER_WORKER_NAME = f"{PROJECT}-browser-worker-1"
TELEGRAM_ATTEMPT_LABEL = "boca.socios.telegram-runtime-attempt"
BROWSER_STAGE_FILENAMES = frozenset(
    {"compose.beta.yaml", "compose.beta.browser.yaml", "seccomp_profile.json"}
)
BROWSER_MARKER_KEYS = frozenset(
    {
        "version",
        "attempt_id",
        "source_sha",
        "controller_digest",
        "browser_digest",
        "beta_compose_sha",
        "overlay_compose_sha",
        "seccomp_sha",
        "controller_image_absent",
        "browser_image_absent",
        "bridge_absent",
        "ipc_volume_absent",
    }
)
TELEGRAM_VOLUME = "boca-socios_boca_telegram"
TELEGRAM_NETWORK = "boca-socios_telegram_egress"
TELEGRAM_TEST_NAME = "boca-socios-telegram-test-1"
TELEGRAM_WORKER_NAME = "boca-socios-telegram-1"
ROOTLESS_SOCKET = Path("/run/user/10001/docker.sock")
PRIVATE_MANAGER_SOCKET = Path("/run/user/10001/systemd/private")
USER_BUS_SOCKET = Path("/run/user/10001/bus")
ROOTFUL_SOCKET = Path("/var/run/docker.sock")
PREFLIGHT_STORAGE_MIN_BYTES = 4 * 1024**3
# Owner-approved emergency *residual* for post-pull / installed Boca BETA only.
# This is not the pre-pull admission policy and not a measured runtime budget.
POSTINSTALL_STORAGE_MIN_BYTES = 1024**3
STORAGE_MIN_FREE_INODES = 50_000
CGROUP_CONTROLLERS = Path(
    "/sys/fs/cgroup/user.slice/user-10001.slice/user@10001.service/cgroup.controllers"
)
CPU_CGROUP_ROOT = Path("/sys/fs/cgroup")
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
OWNER_ENVELOPE_FIELDS = frozenset(
    {
        "version",
        "repository",
        "purpose",
        "uid",
        "panel_origin",
        "owner_subject",
        "recipient_public_key",
        "recipient_fingerprint",
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


def _validate_host_resource_observation(snapshot: HostSnapshot) -> None:
    """Reject invalid counters, not unbenchmarked host resource headroom.

    Pre/post-install resource use is measured during BETA acceptance. The
    controller retains its separately verified hard cgroup CPU/RAM/PID caps.
    """
    if snapshot.available_memory_kib <= 0:
        raise PreflightError("invalid host MemAvailable observation")
    if not math.isfinite(snapshot.cpu_headroom) or snapshot.cpu_headroom < 0:
        raise PreflightError("invalid host CPU headroom observation")


def _validate_storage_policy_threshold(min_free_bytes: int) -> None:
    """Only the two reviewed phase-specific floors may reach a host gate."""
    if type(min_free_bytes) is not int or min_free_bytes not in (
        PREFLIGHT_STORAGE_MIN_BYTES,
        POSTINSTALL_STORAGE_MIN_BYTES,
    ):
        raise PreflightError("invalid Boca storage capacity policy")


def validate_snapshot(
    snapshot: HostSnapshot, *, min_free_bytes: int = PREFLIGHT_STORAGE_MIN_BYTES
) -> None:
    _validate_storage_policy_threshold(min_free_bytes)
    if snapshot.arch != "x86_64":
        raise PreflightError("host architecture must be x86_64")
    if snapshot.uid != 10001:
        raise PreflightError("dedicated deploy identity must have UID 10001")
    _validate_host_resource_observation(snapshot)
    if (
        min(snapshot.available_disk_bytes, snapshot.docker_disk_bytes) < min_free_bytes
        or min(snapshot.available_inodes, snapshot.docker_inodes) < STORAGE_MIN_FREE_INODES
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
    snapshot: HostSnapshot,
    volumes: set[str],
    *,
    expected: set[str],
    min_free_bytes: int = PREFLIGHT_STORAGE_MIN_BYTES,
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
    validate_snapshot(replace(snapshot, boca_volume=False), min_free_bytes=min_free_bytes)


def _validate_beta_context(origin: str, owner: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", owner):
        raise PreflightError("invalid private BETA coordinates")
    if origin == "http://localhost:8443":
        return
    if not re.fullmatch(r"https://[a-z0-9][a-z0-9.-]{0,252}(?::[0-9]{2,5})?", origin):
        raise PreflightError("invalid private BETA coordinates")
    try:
        port = urlsplit(origin).port
    except ValueError as exc:
        raise PreflightError("invalid private BETA port") from exc
    if port is not None and not 1024 <= port <= 65535:
        raise PreflightError("invalid private BETA port")


def _validate_owner_context(origin: str, owner: str) -> None:
    """Match the standalone host's strict private RP contract."""
    _validate_beta_context(origin, owner)
    # Host custody and BETA are no longer allowed to prepare an HTTPS owner
    # volume from a stale protected secret. Legacy HTTPS library tests are
    # separate; only this new, owner-selected port-forward route deploys.
    if origin != "http://localhost:8443":
        raise PreflightError("invalid private owner origin")


def validate_docker_boundary(snapshot: DockerBoundarySnapshot) -> None:
    if snapshot.socket_secure is not True or snapshot.rootful_socket_inaccessible is not True:
        raise PreflightError("dedicated rootless socket or rootful Docker access is unsafe")
    if snapshot.daemon_rootless is not True:
        raise PreflightError("Docker daemon must be rootless for the dedicated Boca identity")
    if snapshot.cgroup_version != "2" or snapshot.cgroup_driver != "systemd":
        raise PreflightError("rootless Docker cannot prove enforceable cgroup limits")
    if not {"cpu", "memory", "pids"} <= snapshot.controllers:
        raise PreflightError("rootless CPU, memory and PID controllers must be delegated")


def _run(
    *args: str,
    env: dict[str, str] | None = None,
    input_data: str | None = None,
    timeout: float = 120,
) -> str:
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
            timeout=timeout,
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


def _readonly_capacity_metadata() -> str:
    """Aggregate metadata only; never infer daemon readiness from a binary."""
    memory, cpu, pids, engine = "unknown", "unknown", "unknown", "unknown"
    try:
        matched = re.search(
            r"^MemAvailable:\s+(\d+) kB$",
            Path("/proc/meminfo").read_text(encoding="ascii"),
            re.MULTILINE,
        )
        if matched is not None:
            memory = str(int(matched.group(1)))
        measured = max(0.0, len(os.sched_getaffinity(0)) - os.getloadavg()[0])
        if measured < 1_000_000:
            cpu = f"{measured:.2f}"
        directory = CGROUP_CONTROLLERS.parent
        current = (directory / "pids.current").read_text(encoding="ascii").strip()
        maximum = (directory / "pids.max").read_text(encoding="ascii").strip()
        if re.fullmatch(r"0|[1-9][0-9]{0,9}", current) and re.fullmatch(
            r"[1-9][0-9]{0,9}", maximum
        ):
            pids = str(max(0, int(maximum) - int(current)))
    except (OSError, ValueError, OverflowError):
        pass
    executable = shutil.which("dockerd")
    if executable is not None:
        try:
            result = subprocess.run(  # noqa: S603 - fixed --version, no shell or daemon access
                (executable, "--version"),
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
            match = re.fullmatch(
                r"Docker version ([0-9]+\.[0-9]+\.[0-9]+), build [0-9A-Za-z.-]+\s*", result.stdout
            )
            if result.returncode == 0 and match is not None:
                engine = match.group(1)
        except (OSError, subprocess.SubprocessError, UnicodeError):
            pass
    return (
        f"BOCA_HOST_CAPACITY mem_kib={memory} cpu_headroom={cpu} pids_free={pids}"
        f" dockerd_binary_version={engine} daemon_version=unverified storage=unverified"
        " capacity_gate=not_evaluated"
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
    print(_readonly_capacity_metadata())
    print(_database_candidate_metadata())
    if state != "METADATA_CANDIDATE":
        raise PreflightError("prerequisite metadata unproven; no Docker operation attempted")


def check_loopback_port() -> None:
    """Try only Boca's intended IPv4 host binding; never contact a listener.

    The socket closes before this phase returns. FREE is an instant observation,
    not a reservation or proof that a later Docker publication will succeed.
    """
    _require_dedicated_identity()
    state = "FREE"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 8443))
    except OSError as exc:
        state = "BUSY" if exc.errno == errno.EADDRINUSE else "ERROR"
    print(f"BOCA_PORT_CHECK state={state} address=127.0.0.1 port=8443 reserved=no")
    if state != "FREE":
        raise PreflightError("Boca loopback port unavailable")


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
    # Docker CLI `--quiet` has different contracts: `volume ls -q` returns
    # volume names, but `network ls -q` returns IDs. Every caller compares
    # this inventory to an allowlist of names, including selective cleanup.
    if kind == "network":
        return set(
            _run("docker", "network", "ls", "--format", "{{.Name}}", "--filter", label).splitlines()
        )
    if kind == "volume":
        return set(_run("docker", "volume", "ls", "-q", "--filter", label).splitlines())
    raise PreflightError("unsupported Docker inventory kind")


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


def _validate_storage_capacity(
    snapshot: StorageSnapshot, *, min_free_bytes: int = PREFLIGHT_STORAGE_MIN_BYTES
) -> None:
    _validate_storage_policy_threshold(min_free_bytes)
    if (
        min(snapshot.stage_free_bytes, snapshot.docker_free_bytes) < min_free_bytes
        or min(snapshot.stage_inodes, snapshot.docker_inodes) < STORAGE_MIN_FREE_INODES
    ):
        raise PreflightError("insufficient Boca staging or rootless Docker storage")


def _validate_storage_continuity(
    before: StorageSnapshot,
    after: StorageSnapshot,
    *,
    require_capacity: bool = True,
    min_free_bytes: int = PREFLIGHT_STORAGE_MIN_BYTES,
) -> None:
    _validate_storage_policy_threshold(min_free_bytes)
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
    if require_capacity:
        _validate_storage_capacity(after, min_free_bytes=min_free_bytes)


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
    base: tuple[str, ...] = ("docker", "compose", "-p", PROJECT, "-f", str(COMPOSE))
    if _PROTECTED_COMPOSE_OVERLAY is not None and _PROTECTED_COMPOSE_OVERLAY[0] == "first-install":
        base += ("-f", str(_PROTECTED_COMPOSE_OVERLAY[1]))
    return (*base, *args)


def _beta_compose_env(image: str, origin: str, owner: str) -> dict[str, str]:
    return {
        **_compose_env(image),
        "BOCA_PANEL_ORIGIN": origin,
        "BOCA_OWNER_SUBJECT": owner,
    }


def _beta_compose_args(*args: str) -> tuple[str, ...]:
    base: tuple[str, ...] = ("docker", "compose", "-p", PROJECT, "-f", str(BETA_COMPOSE))
    if _PROTECTED_COMPOSE_OVERLAY is not None and _PROTECTED_COMPOSE_OVERLAY[0] == "beta-install":
        base += ("-f", str(_PROTECTED_COMPOSE_OVERLAY[1]))
    return (*base, *args)


@contextmanager
def _use_protected_compose_overlay(operation: str, path: Path) -> Iterator[None]:
    """Attach reviewed overlay only inside one host process/lease lifetime.

    This is deliberately NOT exposed by phase() / existing public CLI. The
    transaction owns safe staging, SHA verification and removal of the file.
    """
    global _PROTECTED_COMPOSE_OVERLAY
    if (
        operation not in ("first-install", "beta-install")
        or path.parent != Path("/run/user/10001")
        or _PROTECTED_COMPOSE_OVERLAY is not None
    ):
        raise PreflightError("Boca protected Compose overlay context invalid")
    _PROTECTED_COMPOSE_OVERLAY = (operation, path)
    try:
        yield
    finally:
        _PROTECTED_COMPOSE_OVERLAY = None


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


def _owner_envelope(value: str, origin: str, subject: str) -> str:
    """Inspect only bounded ciphertext framing; the pinned image decrypts it."""
    _validate_owner_context(origin, subject)
    try:
        if not value or len(value) > 43691 or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
            raise ValueError
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        if (
            not 0 < len(raw) <= 32768
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
            or set(data) != OWNER_ENVELOPE_FIELDS
            or type(data["version"]) is not int
            or data["version"] != 1
            or data["repository"] != "mbalbo2023/boca-socios-assistant"
            or data["purpose"]
            != (
                "boca-owner-passkey-v2"
                if origin == "http://localhost:8443"
                else "boca-owner-passkey-tls-v1"
            )
            or type(data["uid"]) is not int
            or data["uid"] != 10001
            or data["panel_origin"] != origin
            or data["owner_subject"] != subject
            or json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True) != decoded
        ):
            raise ValueError
        for key, length in {
            "recipient_public_key": 32,
            "ephemeral_public_key": 32,
            "salt": 16,
            "nonce": 12,
        }.items():
            token = data[key]
            if not isinstance(token, str) or re.fullmatch(r"[A-Za-z0-9_-]+", token) is None:
                raise ValueError
            binary = base64.b64decode(
                token + "=" * (-len(token) % 4), altchars=b"-_", validate=True
            )
            if (
                len(binary) != length
                or base64.urlsafe_b64encode(binary).rstrip(b"=").decode() != token
            ):
                raise ValueError
        fingerprint = data["recipient_fingerprint"]
        if (
            not isinstance(fingerprint, str)
            or DIGEST_PATTERN.fullmatch(fingerprint) is None
            or hashlib.sha256(
                base64.urlsafe_b64decode(data["recipient_public_key"] + "=")
            ).hexdigest()
            != fingerprint
        ):
            raise ValueError
        token = data["ciphertext"]
        if not isinstance(token, str) or re.fullmatch(r"[A-Za-z0-9_-]+", token) is None:
            raise ValueError
        ciphertext = base64.b64decode(
            token + "=" * (-len(token) % 4), altchars=b"-_", validate=True
        )
        if (
            not 16 <= len(ciphertext) <= 32000
            or base64.urlsafe_b64encode(ciphertext).rstrip(b"=").decode() != token
        ):
            raise ValueError
    except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error) as exc:
        raise PreflightError("invalid sealed owner envelope") from exc
    return decoded


def _owner_receipt(output: str, operation: str) -> str:
    if len(output) > 256:
        raise PreflightError("invalid owner bootstrap receipt")
    if operation == "prepare":
        match = re.fullmatch(
            r"BOCA_OWNER_BOOTSTRAP state=(PREPARED|ALREADY_PREPARED)"
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
        if re.fullmatch(rf"BOCA_OWNER_BOOTSTRAP state={state} fingerprint=[0-9a-f]{{64}}", output):
            return output
    raise PreflightError("invalid owner bootstrap receipt")


def _owner_container(image: str, operation: str, origin: str, subject: str) -> tuple[str, ...]:
    if operation not in {"prepare", "inspect-prepared", "install", "install-staged", "verify"}:
        raise PreflightError("unknown owner custody operation")
    _validate_owner_context(origin, subject)
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
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=4m",  # noqa: S108 - bounded memory-only proof
        "--mount",
        f"type=volume,source={OWNER_VOLUME},target=/run/owner,volume-nocopy"
        + (",readonly" if operation in {"verify", "inspect-prepared"} else ""),
        *(
            (
                "--mount",
                f"type=volume,source={ENROLL_VOLUME},target=/run/enrollment,volume-nocopy,readonly",
            )
            if operation == "install-staged"
            else ()
        ),
        image,
        "python",
        "-m",
        "boca_socios.owner_bootstrap",
        "--",
        operation,
        origin,
        subject,
    )


def _owner_enroll_container(
    image: str, source_sha: str, subject: str, digest: str, public: str, fingerprint: str
) -> tuple[str, ...]:
    """HTTP only sees its own disposable ciphertext staging, never private volumes."""
    _validate_owner_context("http://localhost:8443", subject)
    if (
        IMAGE_PATTERN.fullmatch(image) is None
        or SHA_PATTERN.fullmatch(source_sha) is None
        or DIGEST_PATTERN.fullmatch(digest) is None
        or re.fullmatch(r"[A-Za-z0-9_-]{43}", public) is None
        or DIGEST_PATTERN.fullmatch(fingerprint) is None
    ):
        raise PreflightError("owner enrollment coordinates invalid")
    return (
        "docker",
        "run",
        "--detach",
        "--pull",
        "never",
        "--name",
        ENROLL_CONTAINER,
        "--label",
        f"com.docker.compose.project={PROJECT}",
        "--label",
        "com.docker.compose.service=owner-enroll",
        "--label",
        f"org.opencontainers.image.revision={source_sha}",
        "--user",
        "10001:10001",
        "--network",
        ENROLL_NETWORK,
        "--publish",
        "127.0.0.1:8443:8443/tcp",
        "--restart",
        "no",
        "--no-healthcheck",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "32",
        "--memory",
        "128m",
        "--cpus",
        "0.50",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=4m",  # noqa: S108 - bounded in-memory scratch
        "--mount",
        f"type=volume,source={ENROLL_VOLUME},target=/run/enrollment,volume-nocopy",
        image,
        "python",
        "-m",
        "boca_socios.owner_enrollment",
        "--",
        subject,
        digest,
        public,
        fingerprint,
    )


def _owner_enroll_init_container(image: str) -> tuple[str, ...]:
    """Prepare only the new disposable volume's container-UID ownership."""
    if IMAGE_PATTERN.fullmatch(image) is None:
        raise PreflightError("temporary Boca image invalid")
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
        f"type=volume,source={ENROLL_VOLUME},target=/run/enrollment,volume-nocopy",
        image,
        "python",
        "-c",
        "import os; os.chmod('/run/enrollment',0o700); os.chown('/run/enrollment',10001,10001)",
    )


def _owner_enroll_volume() -> None:
    """Prove the temporary staging volume cannot redirect into any host path."""
    volume = _json_object(
        _run("docker", "volume", "inspect", "--format", "{{json .}}", ENROLL_VOLUME),
        "owner enrollment volume",
    )
    root = Path(_run("docker", "info", "--format", "{{.DockerRootDir}}"))
    expected = root / "volumes" / ENROLL_VOLUME / "_data"
    labels = volume.get("Labels")
    if (
        volume.get("Name") != ENROLL_VOLUME
        or volume.get("Driver") != "local"
        or volume.get("Scope") != "local"
        or volume.get("Options") not in (None, {})
        or not root.is_absolute()
        or root == Path("/")
        or volume.get("Mountpoint") != str(expected)
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != PROJECT
        or labels.get("com.docker.compose.volume") != "owner_enroll_staging"
    ):
        raise PreflightError("temporary Boca volume identity unverified")
    try:
        if root.resolve(strict=True) != root or expected.resolve(strict=True) != expected:
            raise PreflightError("temporary Boca volume path redirected")
    except (OSError, RuntimeError) as exc:
        raise PreflightError("temporary Boca volume path unavailable") from exc


def _owner_enroll_preflight(image: str, source_sha: str, origin: str, subject: str) -> None:
    """Refuse unrelated state before the first disposable Boca side effect."""
    _validate_owner_context(origin, subject)
    if IMAGE_PATTERN.fullmatch(image) is None or SHA_PATTERN.fullmatch(source_sha) is None:
        raise PreflightError("owner enrollment release coordinates invalid")
    version = _run("docker", "version", "--format", "{{.Server.Version}}")
    match = re.fullmatch(r"([0-9]{1,3})\.[0-9]{1,3}\.[0-9]{1,3}(?:[-+][A-Za-z0-9._-]+)?", version)
    if match is None or int(match[1]) < 28:
        # Older Docker can leak loopback-published ports onto the host L2.
        raise PreflightError("Docker engine loopback-port isolation unverified")
    if not _safe_dir(ROOT) or any(ROOT.iterdir()):
        raise PreflightError("Boca enrollment staging directory must be empty")
    _site_daemon_empty()
    volumes = _names("volume", "name=^boca-socios_")
    validate_site_snapshot(collect_snapshot(), volumes, require_owner=True)
    if volumes != {OWNER_VOLUME} or _names("network", "name=^boca-socios_"):
        raise PreflightError("owner enrollment requires its existing private owner volume only")
    _validate_owner_volume()
    if _run("docker", "ps", "-a", "-q", "--filter", f"volume={OWNER_VOLUME}"):
        raise PreflightError("owner volume is attached to a container")
    _validate_storage_capacity(_storage_snapshot())


def _owner_enroll_port_free() -> bool:
    """An instant non-listening bind; port collision never authorizes eviction."""
    _require_dedicated_identity()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 8443))
    except OSError:
        return False
    return True


def _owner_enroll_image_preexisting(image: str) -> bool:
    """Only an exact image-inspect absence proves a new pull is disposable.

    An image-list digest display may omit a reference that already exists.
    All other Docker errors fail closed before the attempt marker is written.
    """
    if IMAGE_PATTERN.fullmatch(image) is None:
        raise PreflightError("owner enrollment image invalid")
    try:
        _run("docker", "image", "inspect", "--format", "{{json .}}", image)
    except PreflightError as exc:
        cause = exc.__cause__
        if (
            isinstance(cause, subprocess.CalledProcessError)
            and cause.returncode != 0
            and isinstance(cause.stderr, str)
            and re.search(
                r"(?:^|: )No such image: " + re.escape(image) + r"\s*\Z",
                cause.stderr,
            )
        ):
            return False
        raise
    return True


def _owner_enroll_write_marker(
    image: str, source_sha: str, compose_sha: str, digest: str, existing_image: bool
) -> None:
    """Record exact provenance *before* pull; no bearer token is persisted."""
    record = {
        "image": image,
        "source_sha": source_sha,
        "compose_sha": compose_sha,
        "capability_sha256": digest,
        "image_preexisting": existing_image,
    }
    content = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("ascii")
    try:
        fd = os.open(
            ENROLL_MARKER,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fchmod(output.fileno(), 0o400)
            os.fsync(output.fileno())
        directory = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        raise PreflightError("owner enrollment attempt marker is unavailable") from exc


def _owner_enroll_read_marker(image: str, source_sha: str, compose_sha: str, digest: str) -> bool:
    """Exact regular-file identity is required before offline import."""
    try:
        fd = os.open(ENROLL_MARKER, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as item:
            metadata = os.fstat(item.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != 10001
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) != 0o400
                or metadata.st_size > 1024
            ):
                raise PreflightError("owner enrollment marker identity changed")
            raw = item.read(1025)
        record = json.loads(raw)
    except (OSError, ValueError, TypeError) as exc:
        raise PreflightError("owner enrollment marker unavailable") from exc
    expected = {
        "image": image,
        "source_sha": source_sha,
        "compose_sha": compose_sha,
        "capability_sha256": digest,
    }
    if (
        not isinstance(record, dict)
        or {key: record.get(key) for key in expected} != expected
        or set(record) != set(expected) | {"image_preexisting"}
        or type(record.get("image_preexisting")) is not bool
        or json.dumps(record, sort_keys=True, separators=(",", ":")).encode("ascii") != raw
    ):
        raise PreflightError("owner enrollment marker provenance changed")
    return bool(record["image_preexisting"])


def _owner_enroll_container_state(image: str, source_sha: str) -> tuple[str, bool, int]:
    """Positive identity from the *entire* dedicated daemon, not a label filter alone."""
    ids = _run("docker", "ps", "-a", "-q", "--no-trunc").splitlines()
    if len(ids) != 1 or re.fullmatch(r"[0-9a-f]{64}", ids[0]) is None:
        raise PreflightError("temporary Boca container inventory unverified")
    container = ids[0]
    record = _json_object(
        _run("docker", "container", "inspect", "--format", "{{json .}}", container),
        "owner enrollment container",
    )
    config, host, state = record.get("Config"), record.get("HostConfig"), record.get("State")
    network_settings = record.get("NetworkSettings")
    mounts = record.get("Mounts")
    labels = config.get("Labels") if isinstance(config, dict) else None
    expected_binding = {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
    if (
        record.get("Id") != container
        or record.get("Name") != "/" + ENROLL_CONTAINER
        or not isinstance(config, dict)
        or config.get("Image") != image
        or config.get("User") != "10001:10001"
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != PROJECT
        or labels.get("com.docker.compose.service") != "owner-enroll"
        or labels.get("org.opencontainers.image.revision") != source_sha
        or not isinstance(host, dict)
        or host.get("NetworkMode") != ENROLL_NETWORK
        or host.get("PortBindings") != expected_binding
        or host.get("ReadonlyRootfs") is not True
        or host.get("Privileged") is not False
        or host.get("CapDrop") != ["ALL"]
        or host.get("PidsLimit") != 32
        or host.get("Memory") != 128 * 1024**2
        or host.get("NanoCpus") != 500_000_000
        or not isinstance(state, dict)
        or not isinstance(network_settings, dict)
        or not isinstance(network_settings.get("Networks"), dict)
        or set(network_settings["Networks"]) != {ENROLL_NETWORK}
        or (
            network_settings.get("Ports") != expected_binding
            and not (state.get("Running") is False and network_settings.get("Ports") in ({}, None))
        )
        or type(state.get("Running")) is not bool
        or state.get("Restarting") is not False
        or type(state.get("ExitCode")) is not int
        or not isinstance(mounts, list)
        or len(mounts) != 1
        or mounts[0].get("Type") != "volume"
        or mounts[0].get("Name") != ENROLL_VOLUME
        or mounts[0].get("Destination") != "/run/enrollment"
        or mounts[0].get("RW") is not True
    ):
        raise PreflightError("temporary Boca container identity or exposure unverified")
    return container, state["Running"], state["ExitCode"]


def _owner_enroll_network(container: str, *, icc_true: bool = False) -> None:
    names = _names("network", "name=^boca-socios_")
    if names != {ENROLL_NETWORK}:
        raise PreflightError("temporary Boca network inventory unverified")
    record = _json_object(
        _run("docker", "network", "inspect", "--format", "{{json .}}", ENROLL_NETWORK),
        "owner enrollment network",
    )
    labels, peers = record.get("Labels"), record.get("Containers")
    if (
        record.get("Name") != ENROLL_NETWORK
        or record.get("Driver") != "bridge"
        or record.get("Internal") is not False
        or record.get("Options") != (PROBE_ICC_TRUE_OPTIONS if icc_true else ENROLL_NETWORK_OPTIONS)
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != PROJECT
        or labels.get("com.docker.compose.network") != "owner_enroll_private"
        or not isinstance(peers, dict)
        or set(peers) - {container}
    ):
        raise PreflightError("temporary Boca network isolation unverified")


def _owner_enroll_ready() -> bool:
    """GET only the verified local Boca listener; no bearer token in this probe."""
    try:
        connection = http.client.HTTPConnection("127.0.0.1", 8443, timeout=2)
        try:
            connection.request("GET", "/activar", headers={"Host": "localhost:8443"})
            response = connection.getresponse()
            return (
                response.status == 200
                and response.getheader("Cache-Control") == "no-store"
                and len(response.read(16_385)) <= 16_384
            )
        finally:
            connection.close()
    except (OSError, http.client.HTTPException):
        return False


def _network_probe_error(error: PreflightError) -> str:
    """Classify only a bounded Docker cause; never print vendor stderr."""
    cause = error.__cause__
    if isinstance(cause, subprocess.TimeoutExpired):
        return "timeout"
    if not isinstance(cause, subprocess.CalledProcessError):
        return "unclassified"
    detail = cause.stderr
    if not isinstance(detail, str) or len(detail) > 4096 or "\x00" in detail or "\r" in detail:
        return "unclassified"
    message = detail.lower()
    if any(marker in message for marker in ("iptables", "nftables", "netfilter", "xtables")):
        # Only machine-owned category codes leave the host. These patterns
        # distinguish known Docker firewall failure families, not host facts.
        if "xtables.lock" in message and (
            "permission denied" in message or "cannot open" in message or "can't open" in message
        ):
            return "firewall_lock_denied"
        if (
            "incompatible" in message and ("nft" in message or "legacy" in message)
        ) or "use 'nft' tool" in message:
            return "firewall_backend_mismatch"
        if "table does not exist" in message or "no such table" in message:
            return "firewall_table_missing"
        if "no chain/target/match by that name" in message or "chain does not exist" in message:
            return "firewall_chain_missing"
        if "bridge-nf-call-iptables" in message and any(
            marker in message for marker in ("no such file", "not found", "does not exist")
        ):
            return "firewall_bridge_netfilter_unavailable"
        if "couldn't load match" in message or "could not load match" in message:
            return "firewall_match_unavailable"
        if "chain_add failed" in message and "operation not supported" in message:
            return "firewall_chain_add_unsupported"
        if "operation not supported" in message:
            return "firewall_operation_unsupported"
        if "bridge-nf-call-iptables" in message:
            return "firewall_unsupported"
        if "permission denied" in message or "operation not permitted" in message:
            return "firewall_permission"
        return "firewall"
    if "could not find an available, non-overlapping" in message:
        return "ipam_exhausted"
    if "pool overlaps" in message or "address pool overlaps" in message:
        return "ipam_overlap"
    if "already exists" in message:
        return "already_exists"
    if "operation not permitted" in message or "permission denied" in message:
        return "permission"
    if "invalid argument" in message:
        return "invalid_config"
    if "unsupported" in message or "not supported" in message:
        return "unsupported"
    return "unclassified"


def _network_probe_cleanup(*, icc_true: bool = False) -> None:
    """Remove only the exactly identified unused Boca diagnostic network."""
    _site_daemon_empty()
    names = _names("network", "name=^boca-socios_")
    if names == {ENROLL_NETWORK}:
        if icc_true:
            _owner_enroll_network("", icc_true=True)
        else:
            _owner_enroll_network("")
        _run("docker", "network", "rm", ENROLL_NETWORK)
    elif names:
        raise PreflightError("unverified rootless network inventory")
    if _names("network", "name=^boca-socios_"):
        raise PreflightError("temporary Boca network was not removed")
    _site_daemon_empty()


def _network_probe(*, icc_true: bool = False) -> None:
    """Reproduce only the rootless Boca bridge creation, with proven cleanup.

    No image, container, published port, third-party traffic, or owner data
    mutation. The explicit ICC=true variant only tests the upstream Moby RCA
    without changing the hardened owner-enrollment network. The exact network
    has to be absent before and after; uncertain objects remain untouched.
    """
    # All phases emit fixed labels only. In particular, a failed preflight
    # must not leave the runner with only an ambiguous, absent receipt.
    phase = "preflight_boundary"
    try:
        if not _safe_dir(ROOT) or any(ROOT.iterdir()):
            raise PreflightError("Boca network probe requires empty staging")
        phase = "preflight_namespace"
        _site_daemon_empty()
        volumes = _names("volume", "name=^boca-socios_")
        if volumes != {OWNER_VOLUME} or _names("network", "name=^boca-socios_"):
            raise PreflightError("Boca network probe requires empty namespace")
        validate_site_snapshot(collect_snapshot(), volumes, require_owner=True)
        phase = "preflight_owner_volume"
        _validate_owner_volume()
        phase = "preflight_storage"
        _validate_storage_capacity(_storage_snapshot())
    except (PreflightError, OSError):
        # On preflight failures, remote cleanup is not proven. The workflow's
        # independent Boca-only cleanup/stop steps are still mandatory.
        print(f"BOCA_NETWORK_PROBE result=NO_GO reason={phase} cleanup=INDETERMINATE")
        raise

    outcome = "PASS"
    reason = "none"
    cleanup = "VERIFIED"
    try:
        try:
            phase = "network_create"
            created = _run(
                "docker",
                "network",
                "create",
                "--driver",
                "bridge",
                "--opt",
                "com.docker.network.bridge.enable_ip_masquerade=false",
                "--opt",
                f"com.docker.network.bridge.enable_icc={'true' if icc_true else 'false'}",
                "--opt",
                "com.docker.network.bridge.host_binding_ipv4=127.0.0.1",
                "--label",
                f"com.docker.compose.project={PROJECT}",
                "--label",
                "com.docker.compose.network=owner_enroll_private",
                ENROLL_NETWORK,
            )
            if re.fullmatch(r"[0-9a-f]{64}", created) is None:
                raise PreflightError("Docker network create returned unexpected ID")
            phase = "network_inspect"
            if icc_true:
                _owner_enroll_network("", icc_true=True)
            else:
                _owner_enroll_network("")
        except PreflightError as exc:
            outcome = "NO_GO"
            if phase == "network_inspect":
                reason = phase
            else:
                classifier = _network_probe_error(exc)
                reason = phase if classifier == "unclassified" else classifier
    finally:
        try:
            _network_probe_cleanup(icc_true=icc_true)
        except PreflightError:
            cleanup = "INDETERMINATE"
            if outcome == "PASS":
                outcome = "NO_GO"
                reason = "cleanup"

    print(f"BOCA_NETWORK_PROBE result={outcome} reason={reason} cleanup={cleanup}")
    if outcome != "PASS" or cleanup != "VERIFIED":
        raise PreflightError("Boca network probe NO_GO")


def _owner_enroll_start(
    image: str, source_sha: str, origin: str, subject: str, digest: str, compose_sha: str = ""
) -> None:
    phase_code = "preflight"
    try:
        phase_code = "coordinates"
        if DIGEST_PATTERN.fullmatch(digest) is None:
            raise PreflightError("owner capability digest must be SHA-256 hex")
        phase_code = "preflight"
        _owner_enroll_preflight(image, source_sha, origin, subject)
        phase_code = "port"
        if not _owner_enroll_port_free():
            raise PreflightError("Boca loopback port 8443 BUSY; no occupant changed")
        phase_code = "storage"
        before = _storage_snapshot()
        phase_code = "image_inventory"
        existing_image = _owner_enroll_image_preexisting(image)
        phase_code = "marker"
        _owner_enroll_write_marker(image, source_sha, compose_sha, digest, existing_image)
        phase_code = "pull"
        _run("docker", "pull", image)
        phase_code = "image_provenance"
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
            raise PreflightError("owner enrollment image differs from reviewed release")
        phase_code = "storage_continuity"
        _validate_storage_continuity(before, _storage_snapshot())
        phase_code = "recipient"
        receipt = _owner_receipt(
            _run(*_owner_container(image, "inspect-prepared", origin, subject)), "prepare"
        )
        match = re.fullmatch(
            r"BOCA_OWNER_BOOTSTRAP state=ALREADY_PREPARED public_key=([A-Za-z0-9_-]{43}) fingerprint=([0-9a-f]{64})",
            receipt,
        )
        if match is None:
            raise PreflightError("owner X25519 recipient must be prepared before enrollment")
        _site_daemon_empty()
        _validate_owner_volume()
        phase_code = "volume_create"
        created = _run(
            "docker",
            "volume",
            "create",
            "--driver",
            "local",
            "--label",
            f"com.docker.compose.project={PROJECT}",
            "--label",
            "com.docker.compose.volume=owner_enroll_staging",
            ENROLL_VOLUME,
        )
        if created != ENROLL_VOLUME:
            raise PreflightError("temporary Boca staging volume creation unverified")
        phase_code = "volume_verify"
        _owner_enroll_volume()
        phase_code = "volume_permissions"
        if _run(*_owner_enroll_init_container(image)):
            raise PreflightError("temporary Boca staging ownership preparation unverified")
        _owner_enroll_volume()
        phase_code = "network_create"
        network = _run(
            "docker",
            "network",
            "create",
            "--driver",
            "bridge",
            "--opt",
            "com.docker.network.bridge.enable_ip_masquerade=false",
            "--opt",
            "com.docker.network.bridge.enable_icc=true",
            "--opt",
            "com.docker.network.bridge.host_binding_ipv4=127.0.0.1",
            "--label",
            f"com.docker.compose.project={PROJECT}",
            "--label",
            "com.docker.compose.network=owner_enroll_private",
            ENROLL_NETWORK,
        )
        if re.fullmatch(r"[0-9a-f]{64}", network) is None:
            raise PreflightError("temporary Boca network creation unverified")
        phase_code = "network_verify"
        _owner_enroll_network("", icc_true=True)
        phase_code = "container_create"
        launched = _run(
            *_owner_enroll_container(image, source_sha, subject, digest, match[1], match[2])
        )
        if re.fullmatch(r"[0-9a-f]{64}", launched) is None:
            raise PreflightError("temporary Boca container launch unverified")
        phase_code = "container_verify"
        container, running, _ = _owner_enroll_container_state(image, source_sha)
        if launched != container or not running:
            raise PreflightError("temporary Boca enrollment listener did not start")
        _owner_enroll_network(container, icc_true=True)
        phase_code = "listener_health"
        deadline = monotonic() + 10
        while monotonic() < deadline:
            if _owner_enroll_ready():
                print(
                    f"BOCA_OWNER_ENROLL state=READY address=127.0.0.1 port=8443 ttl=900 source_sha={source_sha}"
                )
                return
            sleep(0.25)
        raise PreflightError("temporary Boca enrollment listener not ready")
    except (PreflightError, OSError, ValueError, TypeError, KeyError) as exc:
        # A fixed phase code is safe for Actions; raw host details remain private.
        raise PreflightError(f"owner enrollment phase={phase_code}") from exc


def _owner_enroll_wait(
    image: str, source_sha: str, compose_sha: str, origin: str, subject: str, digest: str
) -> None:
    """Wait for proof only; Actions must recheck current main before offline import."""
    _validate_owner_context(origin, subject)
    _owner_enroll_read_marker(image, source_sha, compose_sha, digest)
    _validate_owner_volume()
    container, running, _ = _owner_enroll_container_state(image, source_sha)
    _owner_enroll_network(container, icc_true=True)
    if running:
        # The dedicated HTTP process has its own 900-second monotonic deadline.
        # Docker wait supplies a bounded additional host-side ceiling.
        if _run("docker", "wait", container, timeout=930) != "0":
            raise PreflightError("owner enrollment browser proof not completed")
    stopped, running, exit_code = _owner_enroll_container_state(image, source_sha)
    if stopped != container or running or exit_code != 0:
        raise PreflightError("owner enrollment HTTP did not finish successfully")
    _owner_enroll_network(container, icc_true=True)
    _owner_enroll_volume()
    print(f"BOCA_OWNER_ENROLL state=PROOF_STAGED source_sha={source_sha}")


def _owner_enroll_finish(
    image: str, source_sha: str, compose_sha: str, origin: str, subject: str, digest: str
) -> None:
    """Offline import requires a successful prior wait and current-main recheck."""
    _validate_owner_context(origin, subject)
    _owner_enroll_read_marker(image, source_sha, compose_sha, digest)
    _validate_owner_volume()
    container, running, exit_code = _owner_enroll_container_state(image, source_sha)
    if running or exit_code != 0:
        raise PreflightError("owner enrollment HTTP proof not staged successfully")
    _owner_enroll_network(container, icc_true=True)
    _owner_enroll_volume()
    _validate_owner_volume()
    receipt = _owner_receipt(
        _run(*_owner_container(image, "install-staged", origin, subject)),
        "install",
    )
    verified = _owner_receipt(_run(*_owner_container(image, "verify", origin, subject)), "verify")
    fingerprint = receipt.rsplit("=", 1)[1]
    if verified.rsplit("=", 1)[1] != fingerprint:
        raise PreflightError("offline owner custody verification did not match installation")
    _validate_owner_volume()
    print(
        f"BOCA_OWNER_ENROLL state=CONFIGURED_VERIFIED source_sha={source_sha} fingerprint={fingerprint}"
    )


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
    _validate_owner_context(origin, owner)
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
        or set(containers) != ({container} if container else set())
    ):
        raise PreflightError("Boca private network identity or peers changed")


def collect_diagnostic(
    image: str, source_sha: str, *, beta_origin: str = "", beta_owner: str = ""
) -> DiagnosticSnapshot:
    beta = bool(beta_origin)
    if beta:
        _validate_owner_context(beta_origin, beta_owner)
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
    if (
        beta
        and beta_origin == "http://localhost:8443"
        and any(
            name in environment
            for name in ("BOCA_TLS_CERT_FILE", "BOCA_TLS_KEY_FILE", "BOCA_HEALTH_CA_FILE")
        )
    ):
        raise PreflightError("unexpected Boca HTTP BETA TLS configuration")
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
    """Probe the exact Boca port on host loopback, never another web server."""
    authority = urlsplit(origin)
    if not authority.hostname:
        raise PreflightError("invalid BETA hostname")
    if origin == "http://localhost:8443":
        try:
            with socket.create_connection(("127.0.0.1", 8443), timeout=3) as connection:
                connection.settimeout(3)
                connection.sendall(
                    b"GET /healthz HTTP/1.1\r\nHost: localhost:8443\r\nConnection: close\r\n\r\n"
                )
                response = http.client.HTTPResponse(connection)
                response.begin()
                if response.status != 200 or response.read(64) != b"BOCA_BETA_READY":
                    raise PreflightError("BETA host loopback health unavailable")
            return
        except (OSError, http.client.HTTPException) as exc:
            raise PreflightError("BETA host SSH-loopback HTTP unavailable") from exc
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


def _beta_inventory(
    *,
    staged: bool,
    expected: set[str],
    min_free_bytes: int = PREFLIGHT_STORAGE_MIN_BYTES,
) -> HostSnapshot:
    snapshot = collect_snapshot(beta_staged=staged)
    if _run("docker", "ps", "-a", "-q", "--no-trunc"):
        raise PreflightError("dedicated BETA daemon must have no containers before install")
    volumes = _names("volume", "name=^boca-socios_")
    validate_beta_snapshot(snapshot, volumes, expected=expected, min_free_bytes=min_free_bytes)
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
    _validate_storage_continuity(
        before, _storage_snapshot(), min_free_bytes=POSTINSTALL_STORAGE_MIN_BYTES
    )


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
        r" local_http=verified engine=off site=not_contacted telegram=not_sent",
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
    base_volumes = {OWNER_VOLUME, KEY_VOLUME, DATA_VOLUME}
    if volumes not in (base_volumes, base_volumes | {TELEGRAM_VOLUME}):
        raise PreflightError("installed Boca namespace differs from reviewed BETA")
    if TELEGRAM_VOLUME in volumes:
        _telegram_volume()
    network_ids = _run(
        "docker", "network", "ls", "--no-trunc", "-q", "--filter", "name=^boca-socios_"
    ).splitlines()
    if len(network_ids) != 1 or not re.fullmatch(r"[0-9a-f]{64}", network_ids[0]):
        raise PreflightError("installed Boca network inventory differs from reviewed BETA")
    if (
        snapshot.arch != "x86_64"
        or snapshot.uid != 10001
        or not snapshot.root_ready
        or not snapshot.boca_containers
        or not snapshot.boca_volume
        or not snapshot.boca_network
    ):
        raise PreflightError("installed Boca controller identity or resources are unsafe")
    # ADR0112/#307: CPU/RAM host headroom is observational after deployment.
    # Invalid counters still fail; actual runtime/health and cgroup limits
    # are verified by the downstream diagnostic and synthetic acceptance.
    _validate_host_resource_observation(snapshot)
    _validate_owner_volume()
    _validate_key_volume()
    _validate_data_volume()
    _run(*_beta_compose_args("config", "-q"), env=_beta_compose_env(image, origin, owner))
    diagnostic = collect_diagnostic(image, source_sha, beta_origin=origin, beta_owner=owner)
    if network_ids[0] != diagnostic.network_id:
        raise PreflightError("installed Boca network identity changed")
    _beta_loopback_health(diagnostic.container_id, origin)
    capacity = _storage_snapshot()
    _validate_storage_capacity(capacity, min_free_bytes=POSTINSTALL_STORAGE_MIN_BYTES)
    return diagnostic, capacity


def _beta_resume_port_available() -> None:
    """Check the one permitted host loopback binding without contacting a service."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 8443))
    except OSError as exc:
        raise PreflightError("BETA resume exclusive loopback port unavailable") from exc


def _beta_stopped_controller(
    image: str, source_sha: str, compose_sha: str, origin: str, owner: str
) -> str:
    """Authenticate one previously installed, stopped Boca controller before start.

    No compose up/pull, volume creation, database init, browser or Telegram effects.
    Docker is the *dedicated* Boca rootless daemon, validated by the caller.
    """
    _verify_beta_compose(compose_sha)
    volumes = _names("volume", "name=^boca-socios_")
    required_volumes = {OWNER_VOLUME, KEY_VOLUME, DATA_VOLUME}
    if volumes not in (required_volumes, required_volumes | {TELEGRAM_VOLUME}):
        raise PreflightError("BETA resume volume namespace changed")
    _validate_owner_volume()
    _validate_key_volume()
    _validate_data_volume()
    if TELEGRAM_VOLUME in volumes:
        _telegram_volume()
    if _names("network", "name=^boca-socios_") != {"boca-socios_boca_private"}:
        raise PreflightError("BETA resume network namespace changed")
    ids = _run("docker", "ps", "-a", "-q", "--no-trunc").splitlines()
    if len(ids) != 1 or re.fullmatch(r"[0-9a-f]{64}", ids[0]) is None:
        raise PreflightError("BETA resume requires one stopped Boca controller")
    container = ids[0]
    for args in (
        ("--filter", f"label=com.docker.compose.project={PROJECT}"),
        ("--filter", "name=^/boca-socios-controller-1$"),
    ):
        if _run("docker", "ps", "-a", "-q", "--no-trunc", *args).splitlines() != [container]:
            raise PreflightError("BETA resume controller identity is ambiguous")
    record = _json_object(
        _run("docker", "inspect", "--format", "{{json .}}", container), "BETA resume controller"
    )
    config, host = record.get("Config"), record.get("HostConfig")
    state, network = record.get("State"), record.get("NetworkSettings")
    if (
        not isinstance(config, dict)
        or not isinstance(host, dict)
        or not isinstance(state, dict)
        or not isinstance(network, dict)
    ):
        raise PreflightError("BETA resume Docker metadata is incomplete")
    labels = config.get("Labels")
    expected_ports = {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
    restart = host.get("RestartPolicy")
    if (
        record.get("Id") != container
        or record.get("Name") != "/boca-socios-controller-1"
        or config.get("Image") != image
        or config.get("User") != "10001:10001"
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != PROJECT
        or labels.get("com.docker.compose.service") != "controller"
        or labels.get("com.docker.compose.container-number") != "1"
        or labels.get("org.opencontainers.image.revision") != source_sha
        or state.get("Running") is not False
        or state.get("Restarting") is not False
        or state.get("Status") != "exited"
        or config.get("Cmd") != ["python", "-m", "boca_socios.runtime", "serve-beta"]
        or config.get("Entrypoint") not in (None, [])
        or host.get("NetworkMode") != "boca-socios_boca_private"
        or host.get("PortBindings") != expected_ports
        or host.get("PublishAllPorts") is not False
        or host.get("NanoCpus") != 500_000_000
        or host.get("Memory") != 268_435_456
        or host.get("PidsLimit") != 64
        or host.get("ReadonlyRootfs") is not True
        or host.get("Privileged") is not False
        or host.get("CapDrop") != ["ALL"]
        or host.get("CapAdd") not in (None, [])
        or host.get("SecurityOpt") != ["no-new-privileges:true"]
        or host.get("CgroupnsMode") not in ("", "private")
        or host.get("Tmpfs") != {"/tmp": "rw,noexec,nosuid,size=16m"}  # noqa: S108
        or not isinstance(restart, dict)
        or restart.get("Name") != "unless-stopped"
        or restart.get("MaximumRetryCount") != 0
    ):
        raise PreflightError("BETA resume stopped controller contract changed")
    entries = config.get("Env")
    if not isinstance(entries, list) or any(type(entry) is not str for entry in entries):
        raise PreflightError("BETA resume environment is unavailable")
    environment: dict[str, str] = {}
    for entry in entries:
        if "=" not in entry:
            raise PreflightError("BETA resume environment is malformed")
        name, value = entry.split("=", 1)
        if name in environment:
            raise PreflightError("BETA resume environment has duplicate keys")
        environment[name] = value
    expected_environment = {
        "BOCA_ENVIRONMENT": "staging",
        "BOCA_RUNTIME_MODE": "simulation",
        "BOCA_ENGINE_MODE": "off",
        "BOCA_PANEL_ORIGIN": origin,
        "BOCA_OWNER_SUBJECT": owner,
        "BOCA_DB_PATH": "/data/boca.sqlite3",
        "BOCA_MASTER_KEY_FILE": "/run/secrets/boca_master_key",
        "BOCA_PASSKEY_CREDENTIAL_ID_FILE": "/run/owner/credential_id",
        "BOCA_PASSKEY_PUBLIC_KEY_DER_FILE": "/run/owner/public_key.der",
        "BOCA_BIND_HOST": "0.0.0.0",  # noqa: S104 - only container bridge
        "BOCA_BIND_PORT": "8443",
        "BOCA_HEALTH_MODE": "beta",
    }
    if any(environment.get(name) != value for name, value in expected_environment.items()):
        raise PreflightError("BETA resume simulation or owner context changed")
    if (
        any(
            name in environment
            for name in (
                "BOCA_BROWSER_BACKEND",
                "BOCA_TLS_CERT_FILE",
                "BOCA_TLS_KEY_FILE",
                "BOCA_HEALTH_CA_FILE",
                "BOCA_TELEGRAM_TOKEN",
            )
        )
        or environment.get("BOCA_SITE_BRIDGE_MODE", "off") != "off"
    ):
        raise PreflightError("BETA resume external access selector was activated")
    attached = network.get("Networks")
    if not isinstance(attached, dict) or set(attached) != {"boca-socios_boca_private"}:
        raise PreflightError("BETA resume network attachment changed")
    endpoint = attached["boca-socios_boca_private"]
    if not isinstance(endpoint, dict):
        raise PreflightError("BETA resume network endpoint is unavailable")
    network_id = endpoint.get("NetworkID")
    if not isinstance(network_id, str) or re.fullmatch(r"[0-9a-f]{64}", network_id) is None:
        raise PreflightError("BETA resume network ID is uncertain")
    if network.get("Ports") not in (None, {}, {"8443/tcp": None}, expected_ports):
        raise PreflightError("BETA resume stopped port exposure is unexpected")
    mounts = record.get("Mounts")
    if not isinstance(mounts, list) or len(mounts) != 3:
        raise PreflightError("BETA resume volume mounts changed")
    mounted: set[tuple[str, str, bool]] = set()
    for mount in mounts:
        if (
            not isinstance(mount, dict)
            or mount.get("Type") != "volume"
            or mount.get("Driver") != "local"
            or not isinstance(mount.get("Name"), str)
            or not isinstance(mount.get("Destination"), str)
            or type(mount.get("RW")) is not bool
        ):
            raise PreflightError("BETA resume volume identity is invalid")
        mounted.add((mount["Name"], mount["Destination"], mount["RW"]))
    if mounted != {
        (DATA_VOLUME, "/data", True),
        (KEY_VOLUME, "/run/secrets", False),
        (OWNER_VOLUME, "/run/owner", False),
    }:
        raise PreflightError("BETA resume volume custody changed")
    _validate_boca_network("", network_id)
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
        raise PreflightError("BETA resume image no longer matches reviewed release")
    _beta_resume_port_available()
    _run(*_beta_compose_args("config", "-q"), env=_beta_compose_env(image, origin, owner))
    return container


def _beta_resume_phase(
    image: str, source_sha: str, compose_sha: str, origin: str, owner: str
) -> None:
    """Resume the installed singleton, never reinstall or rebuild its volumes."""
    _validate_owner_context(origin, owner)
    container = _beta_stopped_controller(image, source_sha, compose_sha, origin, owner)
    try:
        started = _run("docker", "start", container)
        if started != container:
            raise PreflightError("BETA resumed unexpected controller ID")
        for attempt in range(45):
            health = _run("docker", "inspect", "--format", "{{.State.Health.Status}}", container)
            if health == "healthy":
                break
            if health != "starting" or attempt == 44:
                raise PreflightError("BETA resumed controller health is not verified")
            sleep(2)
        diagnostic, _ = _beta_acceptance_status(image, source_sha, compose_sha, origin, owner)
        if diagnostic.container_id != container or diagnostic.health != "healthy":
            raise PreflightError("BETA resume controller ID or health changed")
    except (PreflightError, OSError, ValueError, TypeError):
        # Only the exact authenticated Boca controller may be stopped. No volume
        # deletion, compose up/down, image pulls or access to other services.
        _run("docker", "stop", "--time", "30", container)
        raise
    print(
        f"BOCA_BETA_START state=RUNNING source_sha={source_sha} image={image}"
        " service=controller host=127.0.0.1:8443"
        " data=preserved key=preserved owner=preserved engine=off"
    )


def _beta_acceptance_phase(
    image: str, source_sha: str, compose_sha: str, origin: str, owner: str
) -> None:
    _validate_owner_context(origin, owner)
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
    _validate_storage_continuity(
        capacity_before, capacity_after, min_free_bytes=POSTINSTALL_STORAGE_MIN_BYTES
    )
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
    _validate_owner_context(origin, owner)
    if operation == "beta-rollback":
        _beta_rollback(image, source_sha)
        return
    if operation == "beta-acceptance":
        _beta_acceptance_phase(image, source_sha, compose_sha, origin, owner)
        return
    if operation == "beta-start":
        _beta_resume_phase(image, source_sha, compose_sha, origin, owner)
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
    print(
        "BOCA_BETA_CAPACITY phase=pre_apply state=OBSERVED"
        f" mem_kib={snapshot.available_memory_kib}"
        f" cpu_headroom={snapshot.cpu_headroom:.2f} postdeploy_measurement=required",
        flush=True,
    )
    _run(*_beta_compose_args("config", "-q"), env=compose_env)
    _beta_pull(image, source_sha)
    _verify_beta_compose(compose_sha)
    _beta_inventory(
        staged=True, expected={OWNER_VOLUME}, min_free_bytes=POSTINSTALL_STORAGE_MIN_BYTES
    )
    _beta_check_receipt(
        _run(*_beta_check_container(image, origin, owner, "check-beta-owner")),
        "check-beta-owner",
    )
    _beta_inventory(
        staged=True, expected={OWNER_VOLUME}, min_free_bytes=POSTINSTALL_STORAGE_MIN_BYTES
    )
    _create_key(image)
    _beta_inventory(
        staged=True,
        expected={OWNER_VOLUME, KEY_VOLUME},
        min_free_bytes=POSTINSTALL_STORAGE_MIN_BYTES,
    )
    _beta_check_receipt(
        _run(*_beta_check_container(image, origin, owner, "check-beta-config")),
        "check-beta-config",
    )
    _beta_inventory(
        staged=True,
        expected={OWNER_VOLUME, KEY_VOLUME},
        min_free_bytes=POSTINSTALL_STORAGE_MIN_BYTES,
    )
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
    _beta_inventory(
        staged=True,
        expected={OWNER_VOLUME, KEY_VOLUME, DATA_VOLUME},
        min_free_bytes=POSTINSTALL_STORAGE_MIN_BYTES,
    )
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
    _validate_storage_capacity(capacity, min_free_bytes=POSTINSTALL_STORAGE_MIN_BYTES)
    print(
        f"BOCA_BETA_INSTALL state=PASS source_sha={source_sha} image={image}"
        " service=controller host=loopback local_http=verified engine=off site=off telegram=off"
        f" stage_free_mib={capacity.stage_free_bytes // 1024**2}"
        f" docker_free_mib={capacity.docker_free_bytes // 1024**2}"
        f" stage_inodes={capacity.stage_inodes} docker_inodes={capacity.docker_inodes}"
    )


def _browser_coordinates(
    image: str,
    source_sha: str,
    beta_sha: str,
    origin: str,
    owner: str,
    browser_image: str,
    overlay_sha: str,
    seccomp_sha: str,
    attempt_id: str,
) -> None:
    """Keep every browser phase bound to reviewed immutable, private inputs."""
    _validate_coordinates(image, source_sha, beta_sha)
    _validate_owner_context(origin, owner)
    if (
        not BROWSER_IMAGE_PATTERN.fullmatch(browser_image)
        or not DIGEST_PATTERN.fullmatch(overlay_sha)
        or not DIGEST_PATTERN.fullmatch(seccomp_sha)
        or not BROWSER_ATTEMPT_PATTERN.fullmatch(attempt_id)
        or browser_image == image
        or len({beta_sha, overlay_sha, seccomp_sha}) != 3
    ):
        raise PreflightError("invalid immutable browser IPC coordinates")


def _browser_root_entries(expected: set[str] | frozenset[str]) -> None:
    _require_dedicated_identity()
    if not _safe_dir(ROOT):
        raise PreflightError("private Boca staging directory is unsafe")
    metadata = ROOT.lstat()
    if metadata.st_gid != 10001 or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise PreflightError("private Boca staging directory identity changed")
    try:
        entries = {item.name for item in ROOT.iterdir()}
    except OSError as exc:
        raise PreflightError("Boca staging directory cannot be inventoried") from exc
    if entries != expected:
        raise PreflightError("Boca browser staging contains unexpected files")


def _browser_root_file(name: str, *, max_size: int) -> bytes:
    """Read only a proven regular Boca file; FIFO cannot block the workflow.

    The final filename is resolved relative to the already-checked directory
    descriptor, with O_NOFOLLOW and O_NONBLOCK before fstat/read. A symlink,
    FIFO, device, replaced inode, wrong UID/mode or oversize is always NO_GO.
    """
    if name not in BROWSER_STAGE_FILENAMES | {BROWSER_MARKER.name}:
        raise PreflightError("unreviewed Boca browser staging filename")
    if not _safe_dir(ROOT):
        raise PreflightError("Boca staging directory is unavailable")
    directory = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        root_stat = os.fstat(directory)
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or root_stat.st_uid != 10001
            or root_stat.st_gid != 10001
            or stat.S_IMODE(root_stat.st_mode) != 0o700
        ):
            raise PreflightError("Boca staging directory descriptor is unsafe")
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory,
        )
        try:
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != 10001
                or before.st_gid != 10001
                or before.st_nlink != 1
                or stat.S_IMODE(before.st_mode) != 0o600
                or not 0 < before.st_size <= max_size
            ):
                raise PreflightError("Boca browser staged file identity is unsafe")
            data = bytearray()
            while len(data) <= max_size:
                chunk = os.read(descriptor, max_size + 1 - len(data))
                if not chunk:
                    break
                data.extend(chunk)
            after = os.fstat(descriptor)
            if (
                len(data) != before.st_size
                or len(data) > max_size
                or (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                    before.st_ctime_ns,
                )
                != (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                )
            ):
                raise PreflightError("Boca browser staged file changed while reading")
            if (ROOT.lstat().st_dev, ROOT.lstat().st_ino) != (
                root_stat.st_dev,
                root_stat.st_ino,
            ):
                raise PreflightError("Boca staging directory replaced while reading")
            return bytes(data)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise PreflightError("Boca browser staged file unavailable") from exc
    finally:
        os.close(directory)


def _browser_json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    record: dict[str, object] = {}
    for key, value in pairs:
        if key in record:
            raise PreflightError("duplicate browser IPC JSON field")
        record[key] = value
    return record


def _browser_read_marker(
    image: str,
    source_sha: str,
    beta_sha: str,
    browser_image: str,
    overlay_sha: str,
    seccomp_sha: str,
    attempt_id: str,
) -> dict[str, object]:
    raw = _browser_root_file(BROWSER_MARKER.name, max_size=1024)
    try:
        marker = json.loads(raw, object_pairs_hook=_browser_json_pairs)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise PreflightError("browser IPC attempt marker is invalid") from exc
    if not isinstance(marker, dict) or set(marker) != BROWSER_MARKER_KEYS:
        raise PreflightError("browser IPC attempt marker schema changed")
    canonical = json.dumps(marker, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "ascii"
    )
    if raw != canonical:
        raise PreflightError("browser IPC marker is not canonical for selective cleanup")
    expected = {
        "version": BROWSER_MARKER_VERSION,
        "attempt_id": attempt_id,
        "source_sha": source_sha,
        "controller_digest": image,
        "browser_digest": browser_image,
        "beta_compose_sha": beta_sha,
        "overlay_compose_sha": overlay_sha,
        "seccomp_sha": seccomp_sha,
    }
    for name, value in expected.items():
        if type(marker[name]) is not str or marker[name] != value:
            raise PreflightError("browser IPC attempt marker coordinates differ")
    for name in (
        "controller_image_absent",
        "browser_image_absent",
        "bridge_absent",
        "ipc_volume_absent",
    ):
        if type(marker[name]) is not bool:
            raise PreflightError("browser IPC attempt marker preexistence is invalid")
    if marker["bridge_absent"] is not True or marker["ipc_volume_absent"] is not True:
        raise PreflightError("browser IPC attempt is not new-only")
    return marker


def _browser_write_marker(marker: dict[str, object]) -> None:
    """Exclusive 0600 creation; never replace an existing file or symlink."""
    _browser_root_entries(set())
    raw = json.dumps(marker, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "ascii"
    )
    if not 0 < len(raw) <= 1024 or set(marker) != BROWSER_MARKER_KEYS:
        raise PreflightError("invalid browser IPC marker payload")
    directory = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        root_stat = os.fstat(directory)
        if root_stat.st_uid != 10001 or root_stat.st_gid != 10001:
            raise PreflightError("browser staging root identity changed")
        fd = os.open(
            BROWSER_MARKER.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=directory,
        )
        created = os.fstat(fd)
        try:
            os.fchmod(fd, 0o600)
            offset = 0
            while offset < len(raw):
                offset += os.write(fd, raw[offset:])
            os.fsync(fd)
        except OSError:
            # Only our freshly O_EXCL-created inode may be removed here.
            entry = BROWSER_MARKER.lstat()
            if (
                (entry.st_dev, entry.st_ino) == (created.st_dev, created.st_ino)
                and entry.st_uid == 10001
                and stat.S_ISREG(entry.st_mode)
            ):
                os.unlink(BROWSER_MARKER.name, dir_fd=directory)
            raise
        finally:
            os.close(fd)
        os.fsync(directory)
    except OSError as exc:
        raise PreflightError("browser IPC marker could not be staged safely") from exc
    finally:
        os.close(directory)


def _browser_verify_staged(beta_sha: str, overlay_sha: str, seccomp_sha: str) -> None:
    _browser_root_entries(BROWSER_STAGE_FILENAMES | {BROWSER_MARKER.name})
    for name, digest in (
        (BETA_COMPOSE.name, beta_sha),
        (BROWSER_COMPOSE.name, overlay_sha),
        (BROWSER_SECCOMP.name, seccomp_sha),
    ):
        data = _browser_root_file(name, max_size=32_768)
        if hashlib.sha256(data).hexdigest() != digest:
            raise PreflightError("browser IPC staged file differs from reviewed SHA-256")
        if name == BROWSER_SECCOMP.name:
            try:
                profile = json.loads(data, object_pairs_hook=_browser_json_pairs)
            except (UnicodeError, ValueError, TypeError) as exc:
                raise PreflightError("browser seccomp JSON is invalid") from exc
            if (
                not isinstance(profile, dict)
                or profile.get("defaultAction") != "SCMP_ACT_ERRNO"
                or not isinstance(profile.get("archMap"), list)
                or not profile["archMap"]
                or not isinstance(profile.get("syscalls"), list)
                or not profile["syscalls"]
            ):
                raise PreflightError("reviewed browser seccomp deny-by-default profile missing")


def _browser_docker_ids() -> set[str]:
    ids = set(_run("docker", "ps", "-a", "-q", "--no-trunc").splitlines())
    if any(re.fullmatch(r"[0-9a-f]{64}", container) is None for container in ids):
        raise PreflightError("dedicated Docker container inventory is malformed")
    return ids


def _browser_inventory(
    *,
    containers: set[str],
    volumes: set[str],
    bridges: set[str],
) -> None:
    """A Boca-exclusive rootless daemon; foreign objects are a hard stop."""
    actual_ids = _browser_docker_ids()
    named_ids = set(
        _run(
            "docker", "ps", "-a", "-q", "--no-trunc", "--filter", "name=^/boca-socios-"
        ).splitlines()
    )
    labeled_ids = set(
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
    if actual_ids != containers or named_ids != containers or labeled_ids != containers:
        raise PreflightError("dedicated Boca daemon contains an unexpected container")
    all_volumes = set(_run("docker", "volume", "ls", "-q").splitlines())
    boca_volumes = _names("volume", "name=^boca-socios_")
    if all_volumes != volumes or boca_volumes != volumes:
        raise PreflightError("dedicated Boca volume inventory changed")
    all_networks = set(_run("docker", "network", "ls", "--format", "{{.Name}}").splitlines())
    boca_networks = _names("network", "name=^boca-socios_")
    if (
        not all_networks <= {"none", "host", "bridge"} | bridges
        or boca_networks != bridges
        or not bridges <= all_networks
    ):
        raise PreflightError("dedicated Boca network inventory changed")


def _browser_image_absent(image: str, source_sha: str) -> bool:
    """Inspect the *exact digest*; list output cannot prove nonexistence.

    Only Docker's literal `No such image: <exact-ref>` for this invocation
    counts as absent. A daemon outage, permissions error, malformed output,
    mismatched revision or ambiguous diagnostic is a hard NO_GO. This evidence
    controls later NEW-only image deletion by the dedicated cleanup helper.
    """
    if not (IMAGE_PATTERN.fullmatch(image) or BROWSER_IMAGE_PATTERN.fullmatch(image)):
        raise PreflightError("unreviewed browser IPC image reference")
    environment = dict(os.environ)
    for name in (
        "DOCKER_CONTEXT",
        "DOCKER_CONFIG",
        "DOCKER_TLS",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    ):
        environment.pop(name, None)
    environment["DOCKER_HOST"] = f"unix://{ROOTLESS_SOCKET}"
    try:
        result = subprocess.run(  # noqa: S603 - fixed Docker inspect, no shell
            ("docker", "image", "inspect", "--format", "{{json .}}", image),  # noqa: S607 - same rootless Docker CLI as _run
            check=False,
            text=True,
            capture_output=True,
            timeout=20,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PreflightError("browser IPC exact image inventory unavailable") from exc
    if (
        result.returncode == 1
        and result.stdout == ""
        and result.stderr.strip()
        in {
            f"Error: No such image: {image}",
            f"Error response from daemon: No such image: {image}",
        }
    ):
        return True
    if result.returncode != 0 or result.stderr or not 0 < len(result.stdout) <= 65_536:
        raise PreflightError("browser IPC exact image inventory is ambiguous")
    record = _json_object(result.stdout, "browser IPC exact image")
    digests = record.get("RepoDigests")
    config = record.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    if (
        digests != [image]
        or record.get("RepoTags") not in (None, [])
        or type(record.get("Size")) is not int
        or cast(int, record["Size"]) <= 0
        or not isinstance(labels, dict)
        or labels.get("org.opencontainers.image.revision") != source_sha
    ):
        raise PreflightError("preexisting browser IPC image identity is unproven")
    return False


def _browser_port_free() -> None:
    """A bind/close, no contact with the host listener or other ports."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 8443))
    except OSError as exc:
        raise PreflightError("private Boca localhost:8443 is not free") from exc


def _browser_engine_version() -> str:
    """Docker <28 can expose loopback-published TCP to adjacent L2 hosts.

    This is a browser-v2-only stop gate; never update the shared daemon or
    mutate its networking as a workaround. Unknown/prerelease versions need a
    separate protected isolation review, not a guessed rootless exemption.
    """
    value = _run("docker", "version", "--format", "{{.Server.Version}}")
    match = re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value)
    if match is None or int(match.group(1)) < 28:
        raise PreflightError("Docker Engine >=28 required for private localhost publication")
    return value


@dataclass(frozen=True)
class CpuCapacity:
    """Structural ceiling, never idle CPU or a performance measurement."""

    daemon_startup_count: int
    effective_cpus: int
    ceiling: Fraction
    scope: str


def _cpu_read(parent: int, name: str, *, expected: os.stat_result | None = None) -> str:
    """Bounded kernel/config reads; a FIFO or symlink cannot block the probe."""

    def identity(value: os.stat_result) -> tuple[int, ...]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_uid,
            value.st_gid,
            value.st_nlink,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or (
            expected is not None and identity(metadata) != identity(expected)
        ):
            raise PreflightError("CPU structural ceiling UNKNOWN: invalid or changed control file")
        raw = os.read(descriptor, 4097)
        if len(raw) > 4096 or (
            expected is not None and identity(os.fstat(descriptor)) != identity(metadata)
        ):
            raise PreflightError(
                "CPU structural ceiling UNKNOWN: oversized or changed control file"
            )
        return raw.decode("ascii").strip()
    finally:
        os.close(descriptor)


def _cpu_mask(value: str, *, separator: str, empty: bool = False) -> frozenset[int]:
    if not value and empty:
        return frozenset()
    selected: set[int] = set()
    for part in value.split(separator):
        match = re.fullmatch(r"(0|[1-9][0-9]{0,5})(?:-(0|[1-9][0-9]{0,5}))?", part)
        if match is None:
            raise PreflightError("CPU structural ceiling UNKNOWN: invalid CPU mask")
        first = int(match.group(1))
        last = int(match.group(2) or first)
        if last < first or last >= 1_000_000:
            raise PreflightError("CPU structural ceiling UNKNOWN: invalid CPU range")
        values = set(range(first, last + 1))
        if selected & values:
            raise PreflightError("CPU structural ceiling UNKNOWN: repeated CPU range")
        selected.update(values)
    if not selected:
        raise PreflightError("CPU structural ceiling UNKNOWN: empty effective CPU mask")
    return frozenset(selected)


def _cpu_systemd_quota(value: str) -> Fraction | None:
    # systemd FORMAT_TIMESPAN(..., 0), not an integer-microseconds interface.
    if value == "infinity":
        return None
    scales = {
        "y": Fraction(31557600),
        "month": Fraction(2629800),
        "w": Fraction(604800),
        "d": Fraction(86400),
        "h": Fraction(3600),
        "min": Fraction(60),
        "s": Fraction(1),
        "ms": Fraction(1, 1000),
        "us": Fraction(1, 1000000),
    }
    result = Fraction(0)
    previous = Fraction(10**12)
    for token in value.split(" "):
        match = re.fullmatch(r"([0-9]{1,18}(?:[.][0-9]{1,6})?)(month|min|ms|us|[ywdhs])", token)
        if match is None:
            raise PreflightError("CPU structural ceiling UNKNOWN: invalid systemd quota")
        scale = scales[match.group(2)]
        if scale >= previous:
            raise PreflightError("CPU structural ceiling UNKNOWN: repeated quota unit")
        previous = scale
        result += Fraction(match.group(1)) * scale
    if result <= 0:
        raise PreflightError("CPU structural ceiling UNKNOWN: nonpositive quota")
    return result


def _cpu_systemd_properties(unit: str | None, keys: tuple[str, ...]) -> dict[str, str]:
    if not _safe_dir(ROOTLESS_SOCKET.parent) or any(
        _socket_state(path) != "owned" for path in (PRIVATE_MANAGER_SOCKET, USER_BUS_SOCKET)
    ):
        raise PreflightError("CPU structural ceiling UNKNOWN: private manager unproven")
    raw = _run(
        "/usr/bin/systemctl",
        "--user",
        "--no-pager",
        "show",
        "--all",
        *((unit,) if unit else ()),
        "--property=" + ",".join(keys),
        env={
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            "XDG_RUNTIME_DIR": "/run/user/10001",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/10001/bus",
        },
        timeout=5,
    )
    if len(raw) > 4096:
        raise PreflightError("CPU structural ceiling UNKNOWN: manager response oversized")
    result: dict[str, str] = {}
    for line in raw.splitlines():
        key, separator, value = line.partition("=")
        if not separator or key not in keys or key in result:
            raise PreflightError("CPU structural ceiling UNKNOWN: manager response invalid")
        result[key] = value
    if set(result) != set(keys):
        raise PreflightError("CPU structural ceiling UNKNOWN: manager response incomplete")
    return result


def _cpu_default_parent() -> None:
    # The protected daemon start already verifies the exact unit/config bytes.
    # Recheck the relevant private config before applying Moby's default parent.
    home = Path(pwd.getpwuid(10001).pw_dir)
    descriptor = os.open(home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in (".config", "docker"):
            metadata = os.fstat(descriptor)
            if metadata.st_uid != 10001 or stat.S_IMODE(metadata.st_mode) != 0o700:
                raise PreflightError("CPU structural ceiling UNKNOWN: private config unproven")
            following = os.open(
                component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = following
        metadata = os.fstat(descriptor)
        config_metadata = os.stat("daemon.json", dir_fd=descriptor, follow_symlinks=False)
        if (
            metadata.st_uid != 10001
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or config_metadata.st_uid != 10001
            or stat.S_IMODE(config_metadata.st_mode) != 0o600
            or config_metadata.st_nlink != 1
        ):
            raise PreflightError("CPU structural ceiling UNKNOWN: private config unproven")
        pairs = json.loads(
            _cpu_read(descriptor, "daemon.json", expected=config_metadata), object_pairs_hook=list
        )
        if not isinstance(pairs, list) or any(
            not isinstance(pair, tuple) or len(pair) != 2 or not isinstance(pair[0], str)
            for pair in pairs
        ):
            raise PreflightError("CPU structural ceiling UNKNOWN: config invalid")
        config = dict(pairs)
        if (
            len(config) != len(pairs)
            or config.get("cgroup-parent", "") != ""
            or config.get("exec-opts") != ["native.cgroupdriver=systemd"]
        ):
            raise PreflightError("CPU structural ceiling UNKNOWN: default parent unproven")
    finally:
        os.close(descriptor)


def _cpu_online() -> frozenset[int]:
    descriptor = os.open("/sys/devices/system/cpu", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        return _cpu_mask(_cpu_read(descriptor, "online"), separator=",")
    finally:
        os.close(descriptor)


def _cpu_structural_capacity() -> CpuCapacity:
    """Resolve Docker's rootless systemd branch without creating its cgroup.

    Moby uses user.slice by default; runc places that slice below the private
    manager's ControlGroup. The daemon's own service cgroup is a sibling, not
    the container parent. Missing undelegated cpuset controls inherit the last
    proven ancestor mask. Missing required/illegible controls are UNKNOWN.
    """
    descriptors: list[int] = []
    try:
        _cpu_default_parent()
        info = _json_object(_run("docker", "info", "--format", "{{json .}}"), "CPU daemon info")
        count = info.get("NCPU")
        if type(count) is not int or not 0 < count < 1_000_000:
            raise PreflightError("CPU structural ceiling UNKNOWN: daemon startup count")
        manager_keys = ("ControlGroup", "SystemState")
        slice_keys = (
            "LoadState",
            "NeedDaemonReload",
            "ActiveState",
            "ControlGroup",
            "CPUQuotaPerSecUSec",
            "AllowedCPUs",
        )
        manager = _cpu_systemd_properties(None, manager_keys)
        unit = _cpu_systemd_properties("user.slice", slice_keys)
        expected = "/" + str(CGROUP_CONTROLLERS.parent.relative_to(CPU_CGROUP_ROOT))
        if (
            manager["ControlGroup"] != expected
            or manager["SystemState"] not in {"running", "degraded"}
            or unit["LoadState"] != "loaded"
            or unit["NeedDaemonReload"] != "no"
            or unit["ActiveState"] not in {"active", "inactive"}
        ):
            raise PreflightError("CPU structural ceiling UNKNOWN: manager/slice identity")
        selected = _cpu_online()
        ceiling = Fraction(count)
        # Effective loaded configuration also covers an inactive implicit slice.
        quota = _cpu_systemd_quota(unit["CPUQuotaPerSecUSec"])
        if quota is not None:
            ceiling = min(ceiling, quota)
        allowed = _cpu_mask(unit["AllowedCPUs"], separator=" ", empty=True)
        if allowed:
            selected &= allowed
        descriptors.append(os.open(CPU_CGROUP_ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
        components = (*Path(expected).parts[1:], "user.slice")
        enabled = set(_cpu_read(descriptors[-1], "cgroup.controllers").split())
        if "cpuset" in enabled:
            selected &= _cpu_mask(
                _cpu_read(descriptors[-1], "cpuset.cpus.effective"), separator=","
            )
        scope = "materialized"
        for index, component in enumerate(components):
            parent = descriptors[-1]
            enabled = set(_cpu_read(parent, "cgroup.subtree_control").split())
            try:
                descriptor = os.open(
                    component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
                )
            except FileNotFoundError:
                if (
                    index != len(components) - 1
                    or unit["ActiveState"] != "inactive"
                    or unit["ControlGroup"]
                ):
                    raise
                scope = "configured"
                # LoadUnit resolves implicit slices and their drop-ins without
                # starting them. Running/degraded uses AllowedCPUs, not the
                # distinct startup mask. Never infer unlimited from absence.
                break
            descriptors.append(descriptor)
            if "cpu" in enabled:
                raw = _cpu_read(descriptor, "cpu.max")
                match = re.fullmatch(r"(max|[1-9][0-9]{0,17}) ([1-9][0-9]{0,17})", raw)
                if match is None:
                    raise PreflightError("CPU structural ceiling UNKNOWN: invalid kernel quota")
                if match.group(1) != "max":
                    ceiling = min(ceiling, Fraction(int(match.group(1)), int(match.group(2))))
            elif index != len(components) - 1:
                # The independently verified manager delegation requires CPU
                # at all these ancestors. Its future child may not enable it
                # until a scope requests CPUAccounting; use loaded config then.
                raise PreflightError("CPU structural ceiling UNKNOWN: delegation changed")
            if "cpuset" in enabled:
                selected &= _cpu_mask(_cpu_read(descriptor, "cpuset.cpus.effective"), separator=",")
        if scope == "materialized" and unit["ControlGroup"] != expected + "/user.slice":
            raise PreflightError("CPU structural ceiling UNKNOWN: slice cgroup mismatch")
        if (
            not selected
            or manager != _cpu_systemd_properties(None, manager_keys)
            or unit != _cpu_systemd_properties("user.slice", slice_keys)
        ):
            raise PreflightError("CPU structural ceiling UNKNOWN: empty or changed context")
        return CpuCapacity(count, len(selected), min(ceiling, Fraction(len(selected))), scope)
    except (OSError, ValueError, KeyError, UnicodeError, TypeError) as exc:
        raise PreflightError("CPU structural ceiling UNKNOWN: controls unavailable") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _browser_capacity(
    *, min_free_bytes: int = PREFLIGHT_STORAGE_MIN_BYTES
) -> tuple[int, float, int, StorageSnapshot]:
    """Observe resources before operations, without an unbenchmarked admission veto.

    Container-specific cgroup caps and storage safety checks remain enforced.
    CPU/memory/PID consumption must be measured on the deployed BETA; the old
    1536/1792 MiB and 1.75/2 CPU preventive buffers were not benchmarks.
    Invalid or nonpositive physical resource observations still fail closed.
    """
    memory, observed_cpu, _load, free_pids, storage = _observe_browser_capacity()
    _validate_storage_capacity(storage, min_free_bytes=min_free_bytes)
    cpu = observed_cpu.ceiling
    if memory <= 0 or cpu <= 0 or free_pids <= 0:
        raise PreflightError("host resource counters show no capacity to launch Boca")
    return memory, float(cpu), free_pids, storage


def _observe_browser_capacity() -> tuple[int, CpuCapacity, float | None, int, StorageSnapshot]:
    """Observe aggregate metadata; configured reserve policy is evaluated separately."""
    _validate_docker_boundary()
    storage = _storage_snapshot()
    cpu = _cpu_structural_capacity()
    try:
        load: float | None = os.getloadavg()[0]
        if load is not None and (not math.isfinite(load) or not 0 <= load < 1_000_000):
            load = None
    except (OSError, ValueError, OverflowError):
        load = None
    try:
        meminfo = Path("/proc/meminfo").read_text(encoding="ascii")
        memory = re.search(r"^MemAvailable:\s+(\d+) kB$", meminfo, re.MULTILINE)
        pids_dir = CGROUP_CONTROLLERS.parent
        pids_current = pids_dir.joinpath("pids.current").read_text(encoding="ascii").strip()
        pids_max = pids_dir.joinpath("pids.max").read_text(encoding="ascii").strip()
        if (
            memory is None
            or not pids_current.isdecimal()
            or not pids_max.isdecimal()
            or pids_current.startswith("0")
            and pids_current != "0"
            or pids_max.startswith("0")
        ):
            raise PreflightError("rootless CPU/memory/PID headroom is unproven")
        free_pids = int(pids_max) - int(pids_current)
        if free_pids < 0:
            raise PreflightError("rootless PID counters are inconsistent")
    except (OSError, ValueError, OverflowError) as exc:
        raise PreflightError("rootless CPU/memory/PID headroom is unavailable") from exc
    return int(memory.group(1)), cpu, load, free_pids, storage


def _infrastructure_budget(resource_budget: str) -> tuple[int, float, int]:
    budgets = {
        "1.5cpu-1024m-192pids": (1536, 1.75, 256),
        "1.75cpu-1152m-224pids": (1792, 2.0, 288),
    }
    if resource_budget not in budgets:
        raise PreflightError("invalid infrastructure reserve policy selection")
    return budgets[resource_budget]


def _infrastructure_preflight(source_sha: str, resource_budget: str) -> None:
    """No image, owner, staging, container, volume or application effects."""
    required_memory, required_cpu, required_pids = _infrastructure_budget(resource_budget)
    _require_dedicated_identity()
    _validate_docker_boundary()
    engine = _browser_engine_version()
    if platform.machine() != "x86_64":
        raise PreflightError("infrastructure architecture is unsupported")
    _browser_root_entries(set())
    _browser_inventory(containers=set(), volumes=set(), bridges=set())
    if not {"--no-build", "--no-deps", "--wait"} <= set(
        _run("docker", "compose", "up", "--help").split()
    ) or "--format" not in _run("docker", "compose", "config", "--help"):
        raise PreflightError("Docker Compose bounded operations are unavailable")
    _browser_port_free()
    memory, observed_cpu, load, pids, storage = _observe_browser_capacity()
    cpu = observed_cpu.ceiling
    after = _storage_snapshot()
    _validate_storage_continuity(storage, after, require_capacity=False)
    _browser_inventory(containers=set(), volumes=set(), bridges=set())
    _browser_root_entries(set())
    _browser_port_free()
    checks = {
        "memory": memory >= required_memory * 1024,
        "cpu": cpu >= required_cpu,
        "pids": pids >= required_pids,
        "storage": min(
            storage.stage_free_bytes,
            storage.docker_free_bytes,
            after.stage_free_bytes,
            after.docker_free_bytes,
        )
        >= 4 * 1024**3
        and min(
            storage.stage_inodes, storage.docker_inodes, after.stage_inodes, after.docker_inodes
        )
        >= 50_000,
    }
    print(
        f"BOCA_INFRA_OBSERVATION source_sha={source_sha} engine={engine}"
        f" memory_kib={memory} daemon_startup_cpu_count={observed_cpu.daemon_startup_count}"
        f" effective_cpus={observed_cpu.effective_cpus} cpu_ceiling={float(cpu):.6f}"
        f" cpu_scope={observed_cpu.scope} load1={format(load, '.6f') if load is not None else 'UNKNOWN'}"
        f" load_policy=advisory pids_free={pids}"
        f" stage_free_bytes={after.stage_free_bytes} stage_inodes={after.stage_inodes}"
        f" docker_free_bytes={after.docker_free_bytes} docker_inodes={after.docker_inodes}",
        flush=True,
    )
    # These values are capacity-planning references, not measured BETA needs.
    # Under the owner's approved sequence, publish the complete observation
    # and measure actual use only after a synthetic, isolated deployment.
    details = " ".join(f"{name}={'PASS' if result else 'BELOW'}" for name, result in checks.items())
    print(
        f"BOCA_INFRA_POLICY source_sha={source_sha} budget={resource_budget}"
        f" memory_mib={required_memory} cpu_required={required_cpu:.2f} pids_required={required_pids}"
        f" {details} result=OBSERVED meaning=postdeploy_measurement_required",
        flush=True,
    )


def _browser_preflight_inventory() -> tuple[int, float, int, StorageSnapshot]:
    _browser_root_entries(set())
    _browser_inventory(containers=set(), volumes={OWNER_VOLUME}, bridges=set())
    _validate_owner_volume()
    if _run("docker", "ps", "-a", "-q", "--filter", f"volume={OWNER_VOLUME}"):
        raise PreflightError("private Boca owner volume is attached")
    _browser_port_free()
    return _browser_capacity()


def _browser_staged_inventory(
    *,
    volumes: set[str],
    containers: set[str] | None = None,
    bridges: set[str] | None = None,
) -> None:
    _browser_inventory(
        containers=set() if containers is None else containers,
        volumes=volumes,
        bridges=set() if bridges is None else bridges,
    )
    _validate_owner_volume()


def _browser_stage(
    image: str,
    source_sha: str,
    beta_sha: str,
    browser_image: str,
    overlay_sha: str,
    seccomp_sha: str,
    attempt_id: str,
) -> None:
    memory, cpu, pids, storage = _browser_preflight_inventory()
    marker: dict[str, object] = {
        "version": BROWSER_MARKER_VERSION,
        "attempt_id": attempt_id,
        "source_sha": source_sha,
        "controller_digest": image,
        "browser_digest": browser_image,
        "beta_compose_sha": beta_sha,
        "overlay_compose_sha": overlay_sha,
        "seccomp_sha": seccomp_sha,
        "controller_image_absent": _browser_image_absent(image, source_sha),
        "browser_image_absent": _browser_image_absent(browser_image, source_sha),
        "bridge_absent": True,
        "ipc_volume_absent": True,
    }
    _browser_write_marker(marker)
    print(
        f"BOCA_BROWSER_STAGE_PASS attempt={attempt_id} uid=10001 owner=existing"
        " namespace=new-only no_worker=yes"
        f" mem_kib={memory} cpu_ceiling={cpu:.2f} pids_free={pids}"
        f" stage_free_mib={storage.stage_free_bytes // 1024**2}"
        f" docker_free_mib={storage.docker_free_bytes // 1024**2}"
    )


def _browser_compose_args(
    *arguments: str,
    base_file: Path | None = None,
    overlay_file: Path | None = None,
) -> tuple[str, ...]:
    """Resolve only explicit reviewed cutover files, or unchanged legacy defaults."""
    return (
        "docker",
        "compose",
        "-p",
        PROJECT,
        "-f",
        str(BETA_COMPOSE if base_file is None else base_file),
        "-f",
        str(BROWSER_COMPOSE if overlay_file is None else overlay_file),
        *arguments,
    )


def _browser_compose_env(
    image: str,
    origin: str,
    owner: str,
    browser_image: str,
    attempt_id: str,
    *,
    seccomp_file: Path | None = None,
) -> dict[str, str]:
    return {
        **_beta_compose_env(image, origin, owner),
        "BOCA_BROWSER_IMAGE": browser_image,
        "BOCA_BROWSER_ATTEMPT_ID": attempt_id,
        "BOCA_BROWSER_SECCOMP_PATH": str(BROWSER_SECCOMP if seccomp_file is None else seccomp_file),
    }


def _browser_compose_model(
    image: str,
    origin: str,
    owner: str,
    browser_image: str,
    attempt_id: str,
    *,
    base_file: Path | None = None,
    overlay_file: Path | None = None,
    seccomp_file: Path | None = None,
) -> str:
    """Host-side essential boundary, in addition to runner's full C1 validator."""
    if any(path is not None for path in (base_file, overlay_file, seccomp_file)):
        stage = ROOT / f"cutover-a-{attempt_id}"
        if not BROWSER_ATTEMPT_PATTERN.fullmatch(attempt_id) or (
            base_file,
            overlay_file,
            seccomp_file,
        ) != (
            stage / BETA_COMPOSE.name,
            stage / BROWSER_COMPOSE.name,
            stage / BROWSER_SECCOMP.name,
        ):
            raise PreflightError("cutover Compose only accepts exact verified Boca stage paths")
    raw = _run(
        *_browser_compose_args(
            "config", "--format", "json", base_file=base_file, overlay_file=overlay_file
        ),
        env=_browser_compose_env(
            image, origin, owner, browser_image, attempt_id, seccomp_file=seccomp_file
        ),
    )
    if not 0 < len(raw) <= 65_536:
        raise PreflightError("resolved browser IPC Compose model is unbounded")
    model = _json_object(raw, "browser IPC Compose")
    if set(model) != {"name", "services", "volumes", "networks"} or model["name"] != PROJECT:
        raise PreflightError("resolved browser IPC project boundary changed")
    services = model.get("services")
    volumes = model.get("volumes")
    networks = model.get("networks")
    if (
        not isinstance(services, dict)
        or set(services) != {"controller", "browser-worker"}
        or not isinstance(volumes, dict)
        or set(volumes) != {"boca_owner", "boca_key", "boca_data", "boca_browser_ipc"}
        or not isinstance(networks, dict)
        or set(networks) != {"boca_private"}
    ):
        raise PreflightError("browser IPC services or named resources changed")
    controller = services["controller"]
    worker = services["browser-worker"]
    if not isinstance(controller, dict) or not isinstance(worker, dict):
        raise PreflightError("browser IPC service metadata invalid")
    expected_port = [
        {
            "mode": "ingress",
            "host_ip": "127.0.0.1",
            "target": 8443,
            "published": "8443",
            "protocol": "tcp",
        }
    ]
    expected_labels = {BROWSER_ATTEMPT_LABEL: attempt_id}
    if (
        controller.get("image") != image
        or controller.get("user") != "10001:10001"
        or controller.get("restart") != "no"
        or controller.get("command") != ["python", "-m", "boca_socios.runtime", "serve-beta"]
        or controller.get("ports") != expected_port
        or controller.get("labels") != expected_labels
        or controller.get("networks") != {"boca_private": None}
        or controller.get("read_only") is not True
        or not isinstance(controller.get("environment"), dict)
        or controller["environment"].get("BOCA_BROWSER_BACKEND") != "ipc"
        or controller["environment"].get("BOCA_RUNTIME_MODE") != "simulation"
        or controller["environment"].get("BOCA_ENGINE_MODE") != "off"
        or controller["environment"].get("BOCA_PANEL_ORIGIN") != origin
        or controller["environment"].get("BOCA_OWNER_SUBJECT") != owner
    ):
        raise PreflightError("browser IPC controller isolation changed")
    expected_worker = {
        "image": browser_image,
        "command": ["python", "-m", "boca_socios.browser.ipc_worker"],
        "user": "10002:10002",
        "network_mode": "none",
        "restart": "no",
        "read_only": True,
        "cgroup": "private",
        "ipc": "private",
        "cap_drop": ["ALL"],
        "cap_add": ["SYS_CHROOT"],
        "pids_limit": 128,
        "mem_limit": "805306368",
        "cpus": 1,
        "security_opt": [
            "no-new-privileges:true",
            f"seccomp={BROWSER_SECCOMP if seccomp_file is None else seccomp_file}",
        ],
        "labels": expected_labels,
        "environment": {
            "BOCA_ENVIRONMENT": "staging",
            "BOCA_RUNTIME_MODE": "simulation",
            "BOCA_ENGINE_MODE": "off",
        },
    }
    if (
        any(
            type(worker.get(key)) is not type(value) or worker.get(key) != value
            for key, value in expected_worker.items()
        )
        or "ports" in worker
        or "networks" in worker
        or worker.get("privileged") is not None
        or worker.get("init") is not True
        or worker.get("shm_size") != "67108864"
        or worker.get("stop_grace_period") != "8s"
        or worker.get("tmpfs")
        != [
            "/tmp:rw,noexec,nosuid,size=32m",  # noqa: S108 - container tmpfs
            "/home/boca-browser:rw,noexec,nosuid,size=16m",
        ]
    ):
        raise PreflightError("browser IPC worker isolation changed")
    for service, expected_mounts in (
        (
            controller,
            {
                ("boca_data", "/data", False),
                ("boca_key", "/run/secrets", True),
                ("boca_owner", "/run/owner", True),
                ("boca_browser_ipc", "/run/boca-browser-ipc", True),
            },
        ),
        (worker, {("boca_browser_ipc", "/run/boca-browser-ipc", False)}),
    ):
        mounts = service.get("volumes")
        if not isinstance(mounts, list) or len(mounts) != len(expected_mounts):
            raise PreflightError("browser IPC service mounts changed")
        observed: set[tuple[str, str, bool]] = set()
        for mount in mounts:
            if (
                not isinstance(mount, dict)
                or set(mount) - {"type", "source", "target", "volume", "read_only"}
                or mount.get("type") != "volume"
                or type(mount.get("source")) is not str
                or type(mount.get("target")) is not str
                or not isinstance(mount.get("volume", {}), dict)
                or mount.get("volume", {})
            ):
                raise PreflightError("browser IPC service mount options changed")
            observed.add((mount["source"], mount["target"], mount.get("read_only", False)))
        if observed != expected_mounts:
            raise PreflightError("browser IPC owner/key/data/worker mount boundary changed")
    if volumes["boca_browser_ipc"] != {
        "name": BROWSER_IPC_VOLUME,
        "external": True,
    }:
        raise PreflightError("browser IPC external volume changed")
    return raw


def _browser_validate_image(image: str, source_sha: str) -> None:
    if _browser_image_absent(image, source_sha):
        raise PreflightError("browser IPC pulled image did not become inspectable")


def _browser_pull_both(image: str, browser_image: str, source_sha: str) -> None:
    before = _storage_snapshot()
    current = before
    for reference in (image, browser_image):
        # Every pull begins above the original 4 GiB admission floor. A
        # completed pull may fall below 4 GiB, but must retain 1 GiB/50k
        # inodes on BOTH Boca staging and Docker root before further effects.
        _validate_storage_capacity(current)
        _run("docker", "pull", reference)
        _browser_validate_image(reference, source_sha)
        current = _storage_snapshot()
        _validate_storage_continuity(before, current, min_free_bytes=POSTINSTALL_STORAGE_MIN_BYTES)


def _browser_validate_ipc_volume(attempt_id: str) -> None:
    volume = _json_object(
        _run("docker", "volume", "inspect", "--format", "{{json .}}", BROWSER_IPC_VOLUME),
        "browser IPC volume",
    )
    docker_root = _checked_docker_storage_dir()
    expected = docker_root / "volumes" / BROWSER_IPC_VOLUME / "_data"
    labels = volume.get("Labels")
    if (
        volume.get("Name") != BROWSER_IPC_VOLUME
        or volume.get("Driver") != "local"
        or volume.get("Scope") != "local"
        or volume.get("Options") not in (None, {})
        or volume.get("Mountpoint") != str(expected)
        or not isinstance(labels, dict)
        or labels
        != {
            "com.docker.compose.project": PROJECT,
            "com.docker.compose.volume": "boca_browser_ipc",
            BROWSER_ATTEMPT_LABEL: attempt_id,
        }
    ):
        raise PreflightError("browser IPC volume is not privately identified")
    try:
        if expected.resolve(strict=True) != expected:
            raise PreflightError("browser IPC mountpoint is redirected")
    except (OSError, RuntimeError) as exc:
        raise PreflightError("browser IPC volume mountpoint is unavailable") from exc


def _browser_named_probe(phase_name: str, attempt_id: str, command: tuple[str, ...]) -> str:
    """Give every `docker run --rm` a C2b-cleanable positive attempt ID.

    A lost CLI/SSH can leave a daemon container alive despite `--rm`. Exactly
    one of seven known named probes may exist at a time, so the same protected
    job can inspect/stop it selectively without touching any other workload.
    """
    permitted = {
        "ipc-dir-init",
        "synthetic-ipc",
        "key-init",
        "key-verify",
        "owner-check",
        "config-check",
        "data-init",
    }
    if (
        phase_name not in permitted
        or not BROWSER_ATTEMPT_PATTERN.fullmatch(attempt_id)
        or command[:3] != ("docker", "run", "--rm")
        or "--name" in command
        or "--label" in command
        or "--detach" in command
        or "-d" in command
    ):
        raise PreflightError("unreviewed browser IPC one-shot helper")
    return _run(
        "docker",
        "run",
        "--name",
        f"boca-socios-browser-ipc-probe-{phase_name}-{attempt_id}",
        "--label",
        f"com.docker.compose.project={PROJECT}",
        "--label",
        f"{BROWSER_ATTEMPT_LABEL}={attempt_id}",
        "--label",
        f"boca.socios.browser-ipc-phase={phase_name}",
        "--ipc=private",
        "--cgroupns=private",
        *command[2:],
        timeout=75 if phase_name == "synthetic-ipc" else 120,
    )


def _browser_create_key(image: str, attempt_id: str) -> None:
    """Legacy key custody, with named helpers only for the opt-in v2 path."""
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
        raise PreflightError("unexpected browser IPC key volume creation")
    _validate_key_volume()
    if (
        _browser_named_probe("key-init", attempt_id, _key_container(image, "init"))
        != "BOCA_KEY_READY"
    ):
        raise PreflightError("browser IPC key initialization is unverified")
    _validate_key_volume()
    if (
        _browser_named_probe("key-verify", attempt_id, _key_container(image, "verify"))
        != "BOCA_KEY_READY"
    ):
        raise PreflightError("browser IPC key access is unverified")


def _browser_create_ipc_volume(browser_image: str, attempt_id: str) -> None:
    created = _run(
        "docker",
        "volume",
        "create",
        "--driver",
        "local",
        "--label",
        f"com.docker.compose.project={PROJECT}",
        "--label",
        "com.docker.compose.volume=boca_browser_ipc",
        "--label",
        f"{BROWSER_ATTEMPT_LABEL}={attempt_id}",
        BROWSER_IPC_VOLUME,
    )
    if created != BROWSER_IPC_VOLUME:
        raise PreflightError("browser IPC volume creation had unexpected identity")
    _browser_validate_ipc_volume(attempt_id)
    # A bounded one-shot rootless user-namespace tool gives the socket-only
    # volume UID10002 / mode0711. It never sees owner/key/data or the network.
    initializer = (
        "import os,stat; p='/run/boca-browser-ipc'; "
        "os.chown(p,10002,10002); os.chmod(p,0o711); "
        "s=os.stat(p,follow_symlinks=False); "
        "assert stat.S_ISDIR(s.st_mode) and s.st_uid==10002 and s.st_gid==10002 "
        "and stat.S_IMODE(s.st_mode)==0o711; print('BOCA_BROWSER_IPC_DIR_PASS')"
    )
    receipt = _browser_named_probe(
        "ipc-dir-init",
        attempt_id,
        (
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
            "--cap-add",
            "FOWNER",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "16",
            "--memory",
            "64m",
            "--cpus",
            "0.25",
            "--mount",
            f"type=volume,source={BROWSER_IPC_VOLUME},target=/run/boca-browser-ipc,volume-nocopy",
            browser_image,
            "python",
            "-c",
            initializer,
        ),
    )
    if receipt != "BOCA_BROWSER_IPC_DIR_PASS":
        raise PreflightError("browser IPC directory owner or mode is unverified")
    _browser_validate_ipc_volume(attempt_id)


def _browser_service_id(
    service: str, image: str, origin: str, owner: str, browser_image: str, attempt_id: str
) -> str:
    if service not in {"controller", "browser-worker"}:
        raise PreflightError("unknown Boca IPC service")
    container = _run(
        *_browser_compose_args("ps", "-q", service),
        env=_browser_compose_env(image, origin, owner, browser_image, attempt_id),
    )
    if re.fullmatch(r"[0-9a-f]{64}", container) is None:
        raise PreflightError("expected one exact Boca IPC service ID")
    return container


def _browser_inspect_record(container: str) -> dict[str, object]:
    raw = _run("docker", "inspect", "--format", "{{json .}}", container)
    if not 0 < len(raw) < 65_536:
        raise PreflightError("Boca IPC container inspection is unbounded")
    record = _json_object(raw, "browser IPC container")
    if record.get("Id") != container:
        raise PreflightError("Boca IPC container identity changed")
    return record


def _browser_config_and_host(
    record: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    config, host = record.get("Config"), record.get("HostConfig")
    if not isinstance(config, dict) or not isinstance(host, dict):
        raise PreflightError("Boca IPC config or host isolation is unavailable")
    return config, host


def _browser_check_service_labels(
    record: dict[str, object],
    *,
    container: str,
    service: str,
    image: str,
    source_sha: str,
    user: str,
    attempt_id: str,
    running: bool = True,
    verify_runtime: bool = True,
) -> tuple[dict[str, object], dict[str, object]]:
    config, host = _browser_config_and_host(record)
    state = record.get("State")
    labels = config.get("Labels")
    restart = host.get("RestartPolicy")
    if (
        record.get("Name") != f"/{PROJECT}-{service}-1"
        or config.get("Image") != image
        or config.get("User") != user
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != PROJECT
        or labels.get("com.docker.compose.service") != service
        or labels.get(BROWSER_ATTEMPT_LABEL) != attempt_id
        or labels.get("org.opencontainers.image.revision") != source_sha
        or not isinstance(state, dict)
        or state.get("Running") is not running
        or state.get("Restarting") is not False
        or running
        and verify_runtime
        and (
            not isinstance(state.get("Health"), dict) or state["Health"].get("Status") != "healthy"
        )
        or type(record.get("RestartCount")) is not int
        or record["RestartCount"] != 0
        or not isinstance(restart, dict)
        or restart.get("Name") != "no"
        or restart.get("MaximumRetryCount") != 0
        or host.get("ReadonlyRootfs") is not True
        or host.get("Privileged") is not False
        or host.get("PublishAllPorts") is not False
        or host.get("Init") is not True
    ):
        raise PreflightError("Boca IPC service identity, health or no-retry boundary changed")
    return config, host


def _browser_check_mounts(record: dict[str, object], *, controller: bool) -> None:
    mounts = record.get("Mounts")
    expected = (
        {
            (DATA_VOLUME, "/data", True),
            (KEY_VOLUME, "/run/secrets", False),
            (OWNER_VOLUME, "/run/owner", False),
            (BROWSER_IPC_VOLUME, "/run/boca-browser-ipc", False),
        }
        if controller
        else {(BROWSER_IPC_VOLUME, "/run/boca-browser-ipc", True)}
    )
    if not isinstance(mounts, list) or len(mounts) != len(expected):
        raise PreflightError("Boca IPC service has an unexpected mount count")
    actual: set[tuple[str, str, bool]] = set()
    for mount in mounts:
        if (
            not isinstance(mount, dict)
            or mount.get("Type") != "volume"
            or mount.get("Driver") != "local"
            or type(mount.get("Name")) is not str
            or type(mount.get("Destination")) is not str
            or type(mount.get("RW")) is not bool
        ):
            raise PreflightError("Boca IPC service mount is unsafe")
        actual.add((mount["Name"], mount["Destination"], mount["RW"]))
    if actual != expected:
        raise PreflightError("Boca IPC service mount leaves approved volume boundary")


def _browser_worker_probe(container: str) -> None:
    """Kernel-observed cgroup/no-egress/seccomp, not only a seccomp path string."""
    code = (
        "import json,os,pathlib; p=pathlib.Path; "
        "c=p('/sys/fs/cgroup'); "
        "q,t=map(int,(c/'cpu.max').read_text().split()); "
        "s=dict(x.split(':',1) for x in p('/proc/self/status').read_text().splitlines() "
        "if ':' in x); "
        "print(json.dumps({'uid':os.geteuid(),'gid':os.getegid(),"
        "'cpu_quota':q,'cpu_period':t,"
        "'memory_bytes':int((c/'memory.max').read_text()),"
        "'pids_limit':int((c/'pids.max').read_text()),"
        "'seccomp':int(s['Seccomp']),'filters':int(s['Seccomp_filters']),"
        "'no_new_privs':int(s['NoNewPrivs']),"
        "'interfaces':sorted(os.listdir('/sys/class/net'))},sort_keys=True))"
    )
    raw = _run(
        "docker",
        "exec",
        "--user",
        "10002:10002",
        container,
        "python",
        "-c",
        code,
        timeout=15,
    )
    if len(raw) > 512:
        raise PreflightError("worker kernel isolation receipt is unbounded")
    evidence = _json_object(raw, "worker kernel isolation")
    if (
        set(evidence)
        != {
            "uid",
            "gid",
            "cpu_quota",
            "cpu_period",
            "memory_bytes",
            "pids_limit",
            "seccomp",
            "filters",
            "no_new_privs",
            "interfaces",
        }
        or any(type(evidence[key]) is not int for key in evidence if key != "interfaces")
        or evidence["uid"] != 10002
        or evidence["gid"] != 10002
        or not 0 < cast(int, evidence["cpu_period"]) <= 1_000_000
        or evidence["cpu_quota"] != evidence["cpu_period"]
        or evidence["memory_bytes"] != 805_306_368
        or evidence["pids_limit"] != 128
        or evidence["seccomp"] != 2
        or cast(int, evidence["filters"]) < 1
        or evidence["no_new_privs"] != 1
        or evidence["interfaces"] != ["lo"]
    ):
        raise PreflightError("worker effective UID/cgroup/seccomp/no-egress unproven")


def _browser_effective_seccomp_options(
    value: object, expected_sha: str, *, staged_profile: bytes | None = None
) -> None:
    """Docker CLI sends compact effective JSON, not the staged host pathname.

    Compare exact UTF-8 JSON bytes with whitespace removed *outside* quoted
    strings, mirroring Docker's json.Compact. Keeping string escapes/key order
    makes even a subtly different or injected profile NO_GO. The separate
    in-worker kernel probe must also report Seccomp=2 and filter count >= 1.
    """
    raw = (
        _browser_root_file(BROWSER_SECCOMP.name, max_size=32_768)
        if staged_profile is None
        else staged_profile
    )
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise PreflightError("browser effective seccomp file differs from reviewed SHA-256")
    try:
        json.loads(raw, object_pairs_hook=_browser_json_pairs)
        compact = bytearray()
        quoted = False
        escaped = False
        for item in raw:
            if quoted:
                compact.append(item)
                if escaped:
                    escaped = False
                elif item == ord("\\"):
                    escaped = True
                elif item == ord('"'):
                    quoted = False
            elif item == ord('"'):
                quoted = True
                compact.append(item)
            elif item not in (ord(" "), ord("\t"), ord("\r"), ord("\n")):
                compact.append(item)
        if quoted or escaped:
            raise PreflightError("browser seccomp JSON string is incomplete")
        effective = "seccomp=" + compact.decode("utf-8")
    except (UnicodeError, ValueError, TypeError) as exc:
        raise PreflightError("browser effective seccomp JSON is invalid") from exc
    if value != ["no-new-privileges:true", effective]:
        raise PreflightError("worker did not load exact reviewed effective seccomp JSON")


def _browser_worker_postflight(
    container: str,
    browser_image: str,
    source_sha: str,
    attempt_id: str,
    seccomp_sha: str,
    *,
    running: bool = True,
    verify_runtime: bool = True,
    staged_seccomp: bytes | None = None,
) -> None:
    record = _browser_inspect_record(container)
    config, host = _browser_check_service_labels(
        record,
        container=container,
        service="browser-worker",
        image=browser_image,
        source_sha=source_sha,
        user="10002:10002",
        attempt_id=attempt_id,
        running=running,
        verify_runtime=verify_runtime,
    )
    environment = config.get("Env")
    if not isinstance(environment, list) or any(type(item) is not str for item in environment):
        raise PreflightError("worker environment could not be verified")
    variables: dict[str, str] = {}
    for entry in environment:
        if "=" not in entry:
            raise PreflightError("worker environment entry is invalid")
        name, value = entry.split("=", 1)
        if name in variables:
            raise PreflightError("worker environment has duplicate names")
        variables[name] = value
    expected = {
        "BOCA_ENVIRONMENT": "staging",
        "BOCA_RUNTIME_MODE": "simulation",
        "BOCA_ENGINE_MODE": "off",
        "BOCA_OBSERVER_STOP": "1",
    }
    if (
        {name: value for name, value in variables.items() if name.startswith("BOCA_")} != expected
        or config.get("Cmd") != ["python", "-m", "boca_socios.browser.ipc_worker"]
        or config.get("Entrypoint") not in (None, [])
        or config.get("ExposedPorts") not in (None, {})
        or host.get("NetworkMode") != "none"
        or host.get("IpcMode") != "private"
        or host.get("CgroupnsMode") != "private"
        or host.get("NanoCpus") != 1_000_000_000
        or host.get("Memory") != 805_306_368
        or host.get("PidsLimit") != 128
        or host.get("ShmSize") != 67_108_864
        or host.get("CapDrop") != ["ALL"]
        # Docker inspect may canonicalize the sole reviewed capability.
        or host.get("CapAdd") not in (["SYS_CHROOT"], ["CAP_SYS_CHROOT"])
        or host.get("PortBindings") not in (None, {})
        or host.get("Tmpfs")
        != {
            "/tmp": "rw,noexec,nosuid,size=32m",  # noqa: S108 - container tmpfs
            "/home/boca-browser": "rw,noexec,nosuid,size=16m",
        }
    ):
        raise PreflightError("browser worker Docker isolation changed")
    if staged_seccomp is None:
        # Preserve the original new-only call contract and its strict tests.
        _browser_effective_seccomp_options(host.get("SecurityOpt"), seccomp_sha)
    else:
        _browser_effective_seccomp_options(
            host.get("SecurityOpt"), seccomp_sha, staged_profile=staged_seccomp
        )
    networks = record.get("NetworkSettings")
    if not isinstance(networks, dict) or networks.get("Ports") not in (None, {}):
        raise PreflightError("browser worker has unexpected IP ports")
    attached = networks.get("Networks")
    if not isinstance(attached, dict) or not set(attached) <= {"none"}:
        raise PreflightError("browser worker has an IP network attachment")
    for endpoint in attached.values():
        if (
            not isinstance(endpoint, dict)
            or endpoint.get("IPAddress") not in (None, "")
            or endpoint.get("GlobalIPv6Address") not in (None, "")
        ):
            raise PreflightError("browser worker received an IP address")
    _browser_check_mounts(record, controller=False)
    if running and verify_runtime:
        _browser_worker_probe(container)


def _cutover_validate_coordinates(
    legacy_image: str,
    legacy_sha: str,
    legacy_compose_sha: str,
    target_image: str,
    target_sha: str,
    browser_image: str,
    expected_legacy_id: str,
) -> None:
    """Bind historical *installed* provenance independently from a new release.

    GitHub Actions checks the two immutable release manifests separately.  A
    caller-controlled SHA/digest alone is never sufficient permission for an
    effect.  This function is used by the read-only observation and by offline
    command-contract tests, never by the new-only browser-install branch.
    """
    _validate_coordinates(legacy_image, legacy_sha, legacy_compose_sha)
    if (
        not IMAGE_PATTERN.fullmatch(target_image)
        or not SHA_PATTERN.fullmatch(target_sha)
        or not BROWSER_IMAGE_PATTERN.fullmatch(browser_image)
        or target_sha == legacy_sha
        or target_image == legacy_image
        or (expected_legacy_id != "" and re.fullmatch(r"[0-9a-f]{64}", expected_legacy_id) is None)
    ):
        raise PreflightError("cutover A historical and target release identities are unproven")


def _cutover_observe(
    legacy_image: str,
    legacy_sha: str,
    legacy_compose_sha: str,
    origin: str,
    owner: str,
    target_image: str,
    target_sha: str,
    browser_image: str,
    expected_legacy_id: str,
) -> None:
    """Observe the installed controller without interrupting Chrome/passkey.

    This uses the *historical* beta Compose SHA, not the future candidate
    Compose SHA.  It proves the singleton's existing ID, owner/key/data,
    rootless daemon, precise localhost listener and fixed simulation policy.
    It never pulls, creates, stops, stages or deletes Docker resources.
    """
    _cutover_validate_coordinates(
        legacy_image,
        legacy_sha,
        legacy_compose_sha,
        target_image,
        target_sha,
        browser_image,
        expected_legacy_id,
    )
    _validate_owner_context(origin, owner)
    _browser_engine_version()
    diagnostic, _storage = _beta_acceptance_status(
        legacy_image, legacy_sha, legacy_compose_sha, origin, owner
    )
    if expected_legacy_id and diagnostic.container_id != expected_legacy_id:
        raise PreflightError("cutover A installed controller ID differs from historic receipt")
    actual_volumes = _names("volume", "name=^boca-socios_")
    required = {OWNER_VOLUME, KEY_VOLUME, DATA_VOLUME}
    if actual_volumes not in (required, required | {TELEGRAM_VOLUME}):
        raise PreflightError("cutover A original persistent Boca inventory changed")
    _browser_inventory(
        containers={diagnostic.container_id},
        volumes=actual_volumes,
        bridges={BROWSER_BRIDGE},
    )
    _browser_root_entries({BETA_COMPOSE.name})
    if diagnostic.health != "healthy":
        raise PreflightError("cutover A original controller is not healthy")
    print(
        "BOCA_CUTOVER_A_OBSERVE state=READY"
        f" legacy_sha={legacy_sha} legacy_id={diagnostic.container_id}"
        f" legacy_image={legacy_image} target_sha={target_sha}"
        f" target_image={target_image} browser_image={browser_image}"
        " original=RUNNING port=127.0.0.1:8443 worker=absent"
        " owner=preserved key=preserved data=preserved effects=none"
    )


def _cutover_legacy_record(
    container_id: str,
    legacy_image: str,
    legacy_sha: str,
    *,
    name: str,
    running: bool,
    restart_policy: str = "unless-stopped",
) -> dict[str, object]:
    """Authenticate exact legacy ID on each side of any future handoff.

    The stop/rename helpers below remain inaccessible from protected workflow
    dispatch until the separate complete cutover/compensation design is
    simulated on an isolated Docker runner and peer-reviewed.
    """
    if (
        re.fullmatch(r"[0-9a-f]{64}", container_id) is None
        or not IMAGE_PATTERN.fullmatch(legacy_image)
        or not SHA_PATTERN.fullmatch(legacy_sha)
        or restart_policy not in ("unless-stopped", "no")
        or name != CUTOVER_LEGACY_NAME
        and re.fullmatch(r"boca-socios-controller-legacy-[1-9][0-9]{0,19}", name) is None
    ):
        raise PreflightError("cutover A original controller coordinate invalid")
    record = _browser_inspect_record(container_id)
    config, host = _browser_config_and_host(record)
    state = record.get("State")
    labels = config.get("Labels")
    restart = host.get("RestartPolicy")
    network = record.get("NetworkSettings")
    if (
        record.get("Name") != f"/{name}"
        or config.get("Image") != legacy_image
        or config.get("User") != "10001:10001"
        or config.get("Cmd") != ["python", "-m", "boca_socios.runtime", "serve-beta"]
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != PROJECT
        or labels.get("com.docker.compose.service") != "controller"
        or labels.get("com.docker.compose.container-number") != "1"
        or labels.get("org.opencontainers.image.revision") != legacy_sha
        or BROWSER_ATTEMPT_LABEL in labels
        or not isinstance(state, dict)
        or state.get("Running") is not running
        or state.get("Restarting") is not False
        or not isinstance(restart, dict)
        or restart.get("Name") != restart_policy
        or restart.get("MaximumRetryCount") != 0
        or host.get("NetworkMode") != BROWSER_BRIDGE
        or host.get("PortBindings") != {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
        or host.get("ReadonlyRootfs") is not True
        or host.get("Privileged") is not False
        or host.get("PublishAllPorts") is not False
        or host.get("CapDrop") != ["ALL"]
        or host.get("CapAdd") not in (None, [])
        or host.get("Init") is not True
        or host.get("NanoCpus") != 500_000_000
        or host.get("Memory") != 268_435_456
        or host.get("PidsLimit") != 64
        or not isinstance(network, dict)
        or set(network.get("Networks", {})) != {BROWSER_BRIDGE}
    ):
        raise PreflightError("cutover A original identity/restart/port isolation changed")
    mounts = record.get("Mounts")
    if not isinstance(mounts, list) or len(mounts) != 3:
        raise PreflightError("cutover A original persistent mounts changed")
    observed: set[tuple[str, str, bool]] = set()
    for mount in mounts:
        if (
            not isinstance(mount, dict)
            or mount.get("Type") != "volume"
            or mount.get("Driver") != "local"
            or type(mount.get("Name")) is not str
            or type(mount.get("Destination")) is not str
            or type(mount.get("RW")) is not bool
        ):
            raise PreflightError("cutover A original mount identity uncertain")
        observed.add((mount["Name"], mount["Destination"], mount["RW"]))
    if observed != {
        (DATA_VOLUME, "/data", True),
        (KEY_VOLUME, "/run/secrets", False),
        (OWNER_VOLUME, "/run/owner", False),
    }:
        raise PreflightError("cutover A original owner/key/data custody changed")
    return record


def _cutover_park_original(
    original_id: str,
    legacy_image: str,
    legacy_sha: str,
    attempt_id: str,
) -> None:
    """Future handoff primitive: disable restart, stop, park, or compensate.

    Not wired into Actions: a complete host transition needs separately
    reviewed stage/IPC, bounded worker, candidate and postflight recovery.
    """
    if not BROWSER_ATTEMPT_PATTERN.fullmatch(attempt_id):
        raise PreflightError("cutover A attempt must be an immutable Actions run ID")
    parked_name = f"{PROJECT}-controller-legacy-{attempt_id}"
    _cutover_legacy_record(
        original_id, legacy_image, legacy_sha, name=CUTOVER_LEGACY_NAME, running=True
    )
    try:
        # A stopped legacy container with unless-stopped may be restarted on
        # daemon restart during the handoff, colliding with the candidate's
        # fixed 127.0.0.1:8443. Change only its immutable ID first and verify.
        _run("docker", "update", "--restart=no", original_id, timeout=20)
        _cutover_legacy_record(
            original_id,
            legacy_image,
            legacy_sha,
            name=CUTOVER_LEGACY_NAME,
            running=True,
            restart_policy="no",
        )
        # A transport timeout from stop can occur *after* Docker stopped the
        # container.  Include stop in the compensation scope rather than
        # assuming an unsuccessful CLI return was effect-free.
        _run("docker", "stop", "--time", "8", original_id, timeout=30)
        _cutover_legacy_record(
            original_id,
            legacy_image,
            legacy_sha,
            name=CUTOVER_LEGACY_NAME,
            running=False,
            restart_policy="no",
        )
        _run("docker", "rename", original_id, parked_name, timeout=20)
        _cutover_legacy_record(
            original_id,
            legacy_image,
            legacy_sha,
            name=parked_name,
            running=False,
            restart_policy="no",
        )
        _browser_port_free()
    except (PreflightError, OSError, ValueError, KeyError, TypeError):
        try:
            snapshot = _browser_inspect_record(original_id)
            current_state = snapshot.get("State")
            if (
                snapshot.get("Name") == f"/{CUTOVER_LEGACY_NAME}"
                and isinstance(current_state, dict)
                and current_state.get("Running") is True
            ):
                # The failed stop had no effect, so do not restart an already
                # running controller or accidentally change the known port.
                policy = snapshot.get("HostConfig")
                restart = policy.get("RestartPolicy") if isinstance(policy, dict) else None
                if not isinstance(restart, dict):
                    raise PreflightError("cutover original restart policy unreadable")
                actual = restart.get("Name")
                if actual == "no":
                    _cutover_legacy_record(
                        original_id,
                        legacy_image,
                        legacy_sha,
                        name=CUTOVER_LEGACY_NAME,
                        running=True,
                        restart_policy="no",
                    )
                    _run("docker", "update", "--restart=unless-stopped", original_id, timeout=20)
                elif actual != "unless-stopped":
                    raise PreflightError("cutover original restart policy unexpectedly changed")
                _cutover_legacy_record(
                    original_id, legacy_image, legacy_sha, name=CUTOVER_LEGACY_NAME, running=True
                )
            else:
                _cutover_restore_original(original_id, legacy_image, legacy_sha, attempt_id)
        except (PreflightError, OSError, ValueError, KeyError, TypeError) as exc:
            raise PreflightError(
                "cutover A park failed; original restoration INDETERMINATE, no retry"
            ) from exc
        raise PreflightError("cutover A park failed; exact original RUNNING again") from None


def _cutover_restore_original(
    original_id: str, legacy_image: str, legacy_sha: str, attempt_id: str
) -> None:
    """Recovery uses the original immutable ID, never a Compose service name."""
    if not BROWSER_ATTEMPT_PATTERN.fullmatch(attempt_id):
        raise PreflightError("cutover A recovery attempt is invalid")
    parked = f"{PROJECT}-controller-legacy-{attempt_id}"
    record = _browser_inspect_record(original_id)
    if record.get("Name") == f"/{parked}":
        _cutover_legacy_record(
            original_id,
            legacy_image,
            legacy_sha,
            name=parked,
            running=False,
            restart_policy="no",
        )
        _run("docker", "rename", original_id, CUTOVER_LEGACY_NAME, timeout=20)
    _cutover_legacy_record(
        original_id,
        legacy_image,
        legacy_sha,
        name=CUTOVER_LEGACY_NAME,
        running=False,
        restart_policy="no",
    )
    _browser_port_free()
    if _run("docker", "start", original_id, timeout=30) != original_id:
        raise PreflightError("cutover A exact original start receipt unverified")
    _browser_wait_healthy(original_id)
    _cutover_legacy_record(
        original_id,
        legacy_image,
        legacy_sha,
        name=CUTOVER_LEGACY_NAME,
        running=True,
        restart_policy="no",
    )
    _run("docker", "update", "--restart=unless-stopped", original_id, timeout=20)
    _cutover_legacy_record(
        original_id, legacy_image, legacy_sha, name=CUTOVER_LEGACY_NAME, running=True
    )


def _cutover_worker_create_argv(
    browser_image: str, source_sha: str, attempt_id: str, config_hash: str
) -> tuple[str, ...]:
    """Plan a worker without Compose reconciling/stopping the live singleton.

    This is deliberately just an argv builder, not an authorized host phase.
    Docker create/start and Compose discovery must pass disposable CI first.
    Its image inherits the pinned OCI revision label and the reviewed seccomp
    profile is a host-local, SHA-proven file, never supplied by the caller.
    """
    if (
        not BROWSER_IMAGE_PATTERN.fullmatch(browser_image)
        or not SHA_PATTERN.fullmatch(source_sha)
        or not BROWSER_ATTEMPT_PATTERN.fullmatch(attempt_id)
        or not DIGEST_PATTERN.fullmatch(config_hash)
    ):
        raise PreflightError("cutover A worker image or attempt unreviewed")
    health = (
        "from boca_socios.browser.on_demand import validate_worker_boundary; "
        "from boca_socios.browser.ipc_worker import validate_no_egress_namespace; "
        "from boca_socios.browser.ipc_protocol import SOCKET_PATH, socket_identity; "
        "validate_worker_boundary(); validate_no_egress_namespace(); socket_identity(SOCKET_PATH)"
    )
    return (
        "docker",
        "create",
        "--pull",
        "never",
        "--name",
        CUTOVER_WORKER_NAME,
        "--label",
        f"com.docker.compose.project={PROJECT}",
        "--label",
        "com.docker.compose.service=browser-worker",
        "--label",
        "com.docker.compose.container-number=1",
        "--label",
        f"com.docker.compose.config-hash={config_hash}",
        "--label",
        "com.docker.compose.oneoff=False",
        "--label",
        f"{BROWSER_ATTEMPT_LABEL}={attempt_id}",
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
        f"seccomp={ROOT / f'cutover-a-{attempt_id}' / BROWSER_SECCOMP.name}",
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
        "/tmp:rw,noexec,nosuid,size=32m",  # noqa: S108 - container tmpfs
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
        "--mount",
        f"type=volume,source={BROWSER_IPC_VOLUME},target=/run/boca-browser-ipc,volume-nocopy",
        "--health-cmd",
        f"python -c {shlex.quote(health)}",
        "--health-interval",
        "2s",
        "--health-timeout",
        "3s",
        "--health-retries",
        "3",
        "--health-start-period",
        "5s",
        browser_image,
        "python",
        "-m",
        "boca_socios.browser.ipc_worker",
    )


def _cutover_candidate_create_argv(
    target_image: str,
    source_sha: str,
    attempt_id: str,
    origin: str,
    owner: str,
    config_hash: str,
) -> tuple[str, ...]:
    """Plan a no-restart candidate without touching the legacy controller.

    The original must be positively parked and localhost free before a future
    reviewed executor is permitted to send this command to Docker.
    """
    if (
        not IMAGE_PATTERN.fullmatch(target_image)
        or not SHA_PATTERN.fullmatch(source_sha)
        or not BROWSER_ATTEMPT_PATTERN.fullmatch(attempt_id)
        or not DIGEST_PATTERN.fullmatch(config_hash)
    ):
        raise PreflightError("cutover A candidate image or attempt unreviewed")
    _validate_owner_context(origin, owner)
    values = {
        "BOCA_ENVIRONMENT": "staging",
        "BOCA_RUNTIME_MODE": "simulation",
        "BOCA_ENGINE_MODE": "off",
        "BOCA_BROWSER_BACKEND": "ipc",
        "BOCA_DB_PATH": "/data/boca.sqlite3",
        "BOCA_MASTER_KEY_FILE": "/run/secrets/boca_master_key",
        "BOCA_PANEL_ORIGIN": origin,
        "BOCA_OWNER_SUBJECT": owner,
        "BOCA_PASSKEY_CREDENTIAL_ID_FILE": "/run/owner/credential_id",
        "BOCA_PASSKEY_PUBLIC_KEY_DER_FILE": "/run/owner/public_key.der",
        "BOCA_BIND_HOST": "0.0.0.0",  # noqa: S104 - private container bridge only
        "BOCA_BIND_PORT": "8443",
        "BOCA_HEALTH_MODE": "beta",
    }
    return (
        "docker",
        "create",
        "--pull",
        "never",
        "--name",
        CUTOVER_LEGACY_NAME,
        "--label",
        f"com.docker.compose.project={PROJECT}",
        "--label",
        "com.docker.compose.service=controller",
        "--label",
        "com.docker.compose.container-number=1",
        "--label",
        f"com.docker.compose.config-hash={config_hash}",
        "--label",
        "com.docker.compose.oneoff=False",
        "--label",
        f"{BROWSER_ATTEMPT_LABEL}={attempt_id}",
        "--user",
        "10001:10001",
        "--restart",
        "no",
        "--init",
        "--network",
        BROWSER_BRIDGE,
        "--publish",
        "127.0.0.1:8443:8443/tcp",
        "--read-only",
        "--security-opt",
        "no-new-privileges:true",
        "--cap-drop",
        "ALL",
        "--pids-limit",
        "64",
        "--memory",
        "256m",
        "--cpus",
        "0.50",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=16m",  # noqa: S108 - container tmpfs
        *(arg for name, value in sorted(values.items()) for arg in ("--env", f"{name}={value}")),
        "--mount",
        f"type=volume,source={DATA_VOLUME},target=/data,volume-nocopy",
        "--mount",
        f"type=volume,source={KEY_VOLUME},target=/run/secrets,volume-nocopy,readonly",
        "--mount",
        f"type=volume,source={OWNER_VOLUME},target=/run/owner,volume-nocopy,readonly",
        "--mount",
        f"type=volume,source={BROWSER_IPC_VOLUME},target=/run/boca-browser-ipc,volume-nocopy,readonly",
        "--health-cmd",
        "python -m boca_socios.healthcheck",
        "--health-interval",
        "30s",
        "--health-timeout",
        "5s",
        "--health-retries",
        "3",
        "--health-start-period",
        "15s",
        target_image,
        "python",
        "-m",
        "boca_socios.runtime",
        "serve-beta",
    )


def _cutover_candidate_name_id() -> str | None:
    """Use exact Docker *name*, never Compose service, during dual-label handoff."""
    raw = _run(
        "docker",
        "ps",
        "-a",
        "-q",
        "--no-trunc",
        "--filter",
        f"name=^/{CUTOVER_LEGACY_NAME}$",
        timeout=20,
    )
    ids = raw.splitlines()
    if len(ids) > 1 or any(re.fullmatch(r"[0-9a-f]{64}", item) is None for item in ids):
        raise PreflightError("cutover A candidate has ambiguous exact-name inventory")
    return ids[0] if ids else None


def _cutover_worker_name_id() -> str | None:
    raw = _run(
        "docker",
        "ps",
        "-a",
        "-q",
        "--no-trunc",
        "--filter",
        f"name=^/{CUTOVER_WORKER_NAME}$",
        timeout=20,
    )
    ids = raw.splitlines()
    if len(ids) > 1 or any(re.fullmatch(r"[0-9a-f]{64}", item) is None for item in ids):
        raise PreflightError("cutover A worker exact-name inventory ambiguous")
    return ids[0] if ids else None


def _cutover_compensate_worker(
    browser_image: str,
    target_sha: str,
    attempt_id: str,
    seccomp_sha: str,
    staged_seccomp: bytes,
) -> None:
    """No broad prune. Remove only positively authenticated attempt resources."""
    worker = _cutover_worker_name_id()
    if worker is not None:
        record = _browser_inspect_record(worker)
        state = record.get("State")
        if not isinstance(state, dict) or type(state.get("Running")) is not bool:
            raise PreflightError("cutover A worker stop state unknown")
        running = state["Running"]
        _browser_worker_postflight(
            worker,
            browser_image,
            target_sha,
            attempt_id,
            seccomp_sha,
            running=running,
            verify_runtime=False,
            staged_seccomp=staged_seccomp,
        )
        if running:
            if _run("docker", "stop", "--time", "8", worker, timeout=30) != worker:
                raise PreflightError("cutover A worker stop receipt unverified")
            _browser_worker_postflight(
                worker,
                browser_image,
                target_sha,
                attempt_id,
                seccomp_sha,
                running=False,
                verify_runtime=False,
                staged_seccomp=staged_seccomp,
            )
        if _run("docker", "rm", worker, timeout=20) != worker:
            raise PreflightError("cutover A worker selective removal receipt unverified")
        if _cutover_worker_name_id() is not None:
            raise PreflightError("cutover A worker remained after selective removal")
    ipc = _names("volume", f"name=^{BROWSER_IPC_VOLUME}$")
    if ipc:
        if ipc != {BROWSER_IPC_VOLUME}:
            raise PreflightError("cutover A IPC volume name inventory ambiguous")
        _browser_validate_ipc_volume(attempt_id)
        if _run("docker", "volume", "rm", BROWSER_IPC_VOLUME, timeout=20) != BROWSER_IPC_VOLUME:
            raise PreflightError("cutover A IPC volume selective removal unverified")
        if _names("volume", f"name=^{BROWSER_IPC_VOLUME}$"):
            raise PreflightError("cutover A IPC volume survived selective removal")


def _cutover_prepare_worker(
    original_id: str,
    legacy_image: str,
    legacy_sha: str,
    browser_image: str,
    target_sha: str,
    attempt_id: str,
    worker_config_hash: str,
    seccomp_sha: str,
    staged_seccomp: bytes,
) -> str:
    """Future one-worker install while original controller remains RUNNING.

    Precondition: immutable images have been pulled and exact staging already
    verified by the future protected Action. This helper cannot be dispatched.
    It never invokes ``docker compose up`` or opens a worker IP network.
    """
    if (
        re.fullmatch(r"[0-9a-f]{64}", original_id) is None
        or not BROWSER_ATTEMPT_PATTERN.fullmatch(attempt_id)
        or not DIGEST_PATTERN.fullmatch(seccomp_sha)
        or hashlib.sha256(staged_seccomp).hexdigest() != seccomp_sha
    ):
        raise PreflightError("cutover A worker source/attempt/seccomp coordinates invalid")
    _cutover_legacy_record(
        original_id, legacy_image, legacy_sha, name=CUTOVER_LEGACY_NAME, running=True
    )
    worker_create = _cutover_worker_create_argv(
        browser_image, target_sha, attempt_id, worker_config_hash
    )
    if _cutover_worker_name_id() is not None:
        raise PreflightError("cutover A worker already exists before attempt")
    if _names("volume", f"name=^{BROWSER_IPC_VOLUME}$"):
        raise PreflightError("cutover A IPC volume already exists before attempt")
    try:
        _browser_create_ipc_volume(browser_image, attempt_id)
        created = _run(*worker_create, timeout=60)
        if re.fullmatch(r"[0-9a-f]{64}", created) is None or created == original_id:
            raise PreflightError("cutover A worker create returned invalid ID")
        if _cutover_worker_name_id() != created:
            raise PreflightError("cutover A worker name/ID differs after create")
        _browser_worker_postflight(
            created,
            browser_image,
            target_sha,
            attempt_id,
            seccomp_sha,
            running=False,
            verify_runtime=False,
            staged_seccomp=staged_seccomp,
        )
        if _run("docker", "start", created, timeout=30) != created:
            raise PreflightError("cutover A worker start receipt invalid")
        _browser_wait_healthy(created)
        _browser_worker_postflight(
            created,
            browser_image,
            target_sha,
            attempt_id,
            seccomp_sha,
            staged_seccomp=staged_seccomp,
        )
        _cutover_legacy_record(
            original_id, legacy_image, legacy_sha, name=CUTOVER_LEGACY_NAME, running=True
        )
        return created
    except (PreflightError, OSError, ValueError, KeyError, TypeError):
        try:
            _cutover_compensate_worker(
                browser_image, target_sha, attempt_id, seccomp_sha, staged_seccomp
            )
            _cutover_legacy_record(
                original_id, legacy_image, legacy_sha, name=CUTOVER_LEGACY_NAME, running=True
            )
        except (PreflightError, OSError, ValueError, KeyError, TypeError) as exc:
            raise PreflightError(
                "cutover A worker failed; selective cleanup INDETERMINATE, no retry"
            ) from exc
        raise PreflightError("cutover A worker failed; original controller RUNNING") from None


def _cutover_candidate_postflight(
    container_id: str,
    target_image: str,
    target_sha: str,
    attempt_id: str,
    origin: str,
    owner: str,
    config_hash: str,
    *,
    verify_runtime: bool = True,
) -> bool:
    """Authenticate candidate's exact ID including reviewed Compose hash."""
    if re.fullmatch(r"[0-9a-f]{64}", container_id) is None or not DIGEST_PATTERN.fullmatch(
        config_hash
    ):
        raise PreflightError("cutover A candidate ID/config-hash invalid")
    record = _browser_inspect_record(container_id)
    config = record.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    state = record.get("State")
    if (
        record.get("Id") != container_id
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.config-hash") != config_hash
        or not isinstance(state, dict)
        or type(state.get("Running")) is not bool
    ):
        raise PreflightError("cutover A candidate exact reviewed identity changed")
    running = cast(bool, state["Running"])
    _browser_controller_postflight(
        container_id,
        target_image,
        target_sha,
        attempt_id,
        origin,
        owner,
        running=running,
        verify_runtime=running and verify_runtime,
    )
    return running


def _cutover_compensate_candidate(
    original_id: str,
    legacy_image: str,
    legacy_sha: str,
    target_image: str,
    target_sha: str,
    attempt_id: str,
    origin: str,
    owner: str,
    config_hash: str,
) -> None:
    """Only remove a positively identified new attempt, then revive old ID."""
    candidate_id = _cutover_candidate_name_id()
    if candidate_id is not None:
        if candidate_id == original_id:
            raise PreflightError("cutover A candidate name points at original ID")
        if _cutover_candidate_postflight(
            candidate_id,
            target_image,
            target_sha,
            attempt_id,
            origin,
            owner,
            config_hash,
            verify_runtime=False,
        ):
            if _run("docker", "stop", "--time", "8", candidate_id, timeout=30) != candidate_id:
                raise PreflightError("cutover A candidate stop receipt uncertain")
            if _cutover_candidate_postflight(
                candidate_id,
                target_image,
                target_sha,
                attempt_id,
                origin,
                owner,
                config_hash,
                verify_runtime=False,
            ):
                raise PreflightError("cutover A candidate still running after stop")
        if _run("docker", "rm", candidate_id, timeout=20) != candidate_id:
            raise PreflightError("cutover A candidate selective delete receipt uncertain")
        if _cutover_candidate_name_id() is not None:
            raise PreflightError("cutover A candidate remained after selective removal")
    _browser_port_free()
    _cutover_restore_original(original_id, legacy_image, legacy_sha, attempt_id)


def _cutover_activate_candidate(
    original_id: str,
    legacy_image: str,
    legacy_sha: str,
    target_image: str,
    target_sha: str,
    browser_image: str,
    worker_id: str,
    attempt_id: str,
    origin: str,
    owner: str,
    config_hash: str,
    seccomp_sha: str,
    staged_seccomp: bytes,
) -> str:
    """Future effectful handoff AFTER park; inaccessible from all workflows.

    Keeps old ID parked until a **different** positive-acceptance retirement
    step, so every candidate-create/start/health failure is recoverable.  No
    service-name based Docker compose up/down or broad cleanup is used.
    """
    if (
        re.fullmatch(r"[0-9a-f]{64}", original_id) is None
        or re.fullmatch(r"[0-9a-f]{64}", worker_id) is None
        or not BROWSER_ATTEMPT_PATTERN.fullmatch(attempt_id)
        or not DIGEST_PATTERN.fullmatch(seccomp_sha)
    ):
        raise PreflightError("cutover A effectful coordinates invalid")
    _cutover_legacy_record(
        original_id,
        legacy_image,
        legacy_sha,
        name=f"{PROJECT}-controller-legacy-{attempt_id}",
        running=False,
        restart_policy="no",
    )
    try:
        _browser_worker_postflight(
            worker_id,
            browser_image,
            target_sha,
            attempt_id,
            seccomp_sha,
            staged_seccomp=staged_seccomp,
        )
        _browser_port_free()
        if _cutover_candidate_name_id() is not None:
            raise PreflightError("cutover A candidate name was not available")
        created = _run(
            *_cutover_candidate_create_argv(
                target_image, target_sha, attempt_id, origin, owner, config_hash
            ),
            timeout=60,
        )
        if re.fullmatch(r"[0-9a-f]{64}", created) is None or created == original_id:
            raise PreflightError("cutover A candidate creation ID unverified")
        if _cutover_candidate_name_id() != created:
            raise PreflightError("cutover A candidate name/ID differs after create")
        if _cutover_candidate_postflight(
            created, target_image, target_sha, attempt_id, origin, owner, config_hash
        ):
            raise PreflightError("cutover A candidate unexpectedly started at create")
        if _run("docker", "start", created, timeout=30) != created:
            raise PreflightError("cutover A candidate start receipt unverified")
        _browser_wait_healthy(created)
        if not _cutover_candidate_postflight(
            created, target_image, target_sha, attempt_id, origin, owner, config_hash
        ):
            raise PreflightError("cutover A candidate failed to become running")
        _beta_loopback_health(created, origin)
        _cutover_legacy_record(
            original_id,
            legacy_image,
            legacy_sha,
            name=f"{PROJECT}-controller-legacy-{attempt_id}",
            running=False,
            restart_policy="no",
        )
        return created
    except (PreflightError, OSError, ValueError, KeyError, TypeError):
        try:
            _cutover_compensate_candidate(
                original_id,
                legacy_image,
                legacy_sha,
                target_image,
                target_sha,
                attempt_id,
                origin,
                owner,
                config_hash,
            )
            # A failed candidate must not strand the attempt-only worker/IPC
            # after the original exact ID has been restored. Reuse the
            # independently authenticated, selective worker compensator.
            # Never remove a worker if its exact expected ID has drifted.
            if _cutover_worker_name_id() != worker_id:
                raise PreflightError("cutover A worker identity changed during compensation")
            _cutover_compensate_worker(
                browser_image, target_sha, attempt_id, seccomp_sha, staged_seccomp
            )
        except (PreflightError, OSError, ValueError, KeyError, TypeError) as exc:
            raise PreflightError(
                "cutover A candidate failed; original/worker recovery INDETERMINATE, no retry"
            ) from exc
        raise PreflightError(
            "cutover A candidate failed; original exact ID restored RUNNING and worker removed"
        ) from None


def _cutover_retire_accepted_original(
    original_id: str,
    legacy_image: str,
    legacy_sha: str,
    candidate_id: str,
    target_image: str,
    target_sha: str,
    worker_id: str,
    browser_image: str,
    attempt_id: str,
    origin: str,
    owner: str,
    config_hash: str,
    seccomp_sha: str,
    staged_seccomp: bytes,
    stage_dir: Path,
) -> None:
    """Future separate commit point, only after positive candidate acceptance.

    Once the accepted candidate owns 8443, old ID cannot be restarted without
    a port collision. Unknown retirement outcome is explicitly INDETERMINATE;
    never blindly retry deletion or restore the parked ID over the new one.
    This helper is NOT wired to phase() or any protected GitHub workflow.
    """
    if (
        re.fullmatch(r"[0-9a-f]{64}", candidate_id) is None
        or candidate_id == original_id
        or re.fullmatch(r"[0-9a-f]{64}", worker_id) is None
        or not BROWSER_ATTEMPT_PATTERN.fullmatch(attempt_id)
        or stage_dir != ROOT / f"cutover-a-{attempt_id}"
        or not DIGEST_PATTERN.fullmatch(seccomp_sha)
    ):
        raise PreflightError("cutover A accepted retirement coordinates invalid")
    _cutover_legacy_record(
        original_id,
        legacy_image,
        legacy_sha,
        name=f"{PROJECT}-controller-legacy-{attempt_id}",
        running=False,
        restart_policy="no",
    )
    if _cutover_candidate_name_id() != candidate_id or not _cutover_candidate_postflight(
        candidate_id, target_image, target_sha, attempt_id, origin, owner, config_hash
    ):
        raise PreflightError("cutover A accepted candidate identity/health changed")
    _browser_worker_postflight(
        worker_id,
        browser_image,
        target_sha,
        attempt_id,
        seccomp_sha,
        staged_seccomp=staged_seccomp,
    )
    _beta_loopback_health(candidate_id, origin)
    try:
        if _run("docker", "rm", original_id, timeout=30) != original_id:
            raise PreflightError("cutover A original retirement receipt unverified")
        if original_id in _browser_docker_ids():
            raise PreflightError("cutover A original still exists after retirement")
        compose = (
            "docker",
            "compose",
            "-p",
            PROJECT,
            "-f",
            str(stage_dir / BETA_COMPOSE.name),
            "-f",
            str(stage_dir / BROWSER_COMPOSE.name),
            "ps",
            "-a",
            "-q",
        )
        if (
            _run(*compose, "controller", timeout=30) != candidate_id
            or _run(*compose, "browser-worker", timeout=30) != worker_id
        ):
            raise PreflightError("cutover A Compose singleton service discovery differs")
    except (PreflightError, OSError, ValueError, KeyError, TypeError) as exc:
        raise PreflightError(
            "cutover A original retirement/Compose outcome INDETERMINATE; do not retry"
        ) from exc


def _browser_worker_network_inventory() -> set[str]:
    """Compose may precreate Boca's bridge when starting a network-none worker."""
    boca = _names("network", "name=^boca-socios_")
    if boca not in (set(), {BROWSER_BRIDGE}):
        raise PreflightError("browser IPC worker created an unexpected network")
    if boca:
        record = _json_object(
            _run("docker", "network", "inspect", "--format", "{{json .}}", BROWSER_BRIDGE),
            "browser IPC staged bridge",
        )
        labels = record.get("Labels")
        if (
            record.get("Name") != BROWSER_BRIDGE
            or record.get("Driver") != "bridge"
            or record.get("Scope") != "local"
            or record.get("Internal") is not False
            or record.get("Attachable") is not False
            or record.get("Ingress") is not False
            or not isinstance(labels, dict)
            or labels.get("com.docker.compose.project") != PROJECT
            or labels.get("com.docker.compose.network") != "boca_private"
            or record.get("Containers") not in (None, {})
        ):
            raise PreflightError("browser IPC pre-controller bridge is unsafe")
    return boca


def _browser_synthetic_socket_smoke(image: str, attempt_id: str) -> None:
    """Kernel SO_PEERCRED across UID10001->10002 for ONE fixed fake command.

    Uses a short-lived, network-none controller-image probe with the single
    IPC mount RO. The worker's Chromium sandbox operates only fake HTML.
    Never mounts owner/key/data, never supplies a member/event/URL or retries.
    """
    code = (
        "import asyncio; "
        "from boca_socios.browser.ipc_client import UnixSyntheticBrowser; "
        "from boca_socios.browser.contracts import SimulationOutcome; "
        "outcome=asyncio.run(UnixSyntheticBrowser(timeout_seconds=25)."
        "simulate_general_reservation()); "
        "assert outcome is SimulationOutcome.RESERVED_IN_SIMULATOR; "
        "print('BOCA_BROWSER_IPC_SYNTHETIC_PASS')"
    )
    receipt = _browser_named_probe(
        "synthetic-ipc",
        attempt_id,
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
            f"type=volume,source={BROWSER_IPC_VOLUME},target=/run/boca-browser-ipc,volume-nocopy,readonly",
            image,
            "python",
            "-c",
            code,
        ),
    )
    if receipt != "BOCA_BROWSER_IPC_SYNTHETIC_PASS":
        raise PreflightError("cross-container SO_PEERCRED and synthetic IPC unverified")


def _browser_controller_postflight(
    container: str,
    image: str,
    source_sha: str,
    attempt_id: str,
    origin: str,
    owner: str,
    *,
    running: bool = True,
    verify_runtime: bool = True,
) -> None:
    record = _browser_inspect_record(container)
    config, host = _browser_check_service_labels(
        record,
        container=container,
        service="controller",
        image=image,
        source_sha=source_sha,
        user="10001:10001",
        attempt_id=attempt_id,
        running=running,
        verify_runtime=verify_runtime,
    )
    environment = config.get("Env")
    if not isinstance(environment, list) or any(type(item) is not str for item in environment):
        raise PreflightError("browser IPC controller environment invalid")
    variables: dict[str, str] = {}
    for entry in environment:
        if "=" not in entry:
            raise PreflightError("browser IPC controller environment entry invalid")
        name, value = entry.split("=", 1)
        if name in variables:
            raise PreflightError("browser IPC controller environment duplicates")
        variables[name] = value
    for name, expected in {
        "BOCA_ENVIRONMENT": "staging",
        "BOCA_RUNTIME_MODE": "simulation",
        "BOCA_ENGINE_MODE": "off",
        "BOCA_BROWSER_BACKEND": "ipc",
        "BOCA_PANEL_ORIGIN": origin,
        "BOCA_OWNER_SUBJECT": owner,
        "BOCA_DB_PATH": "/data/boca.sqlite3",
        "BOCA_MASTER_KEY_FILE": "/run/secrets/boca_master_key",
        "BOCA_PASSKEY_CREDENTIAL_ID_FILE": "/run/owner/credential_id",
        "BOCA_PASSKEY_PUBLIC_KEY_DER_FILE": "/run/owner/public_key.der",
        "BOCA_BIND_HOST": "0.0.0.0",  # noqa: S104 - container bridge, host loopback
        "BOCA_BIND_PORT": "8443",
        "BOCA_HEALTH_MODE": "beta",
    }.items():
        if variables.get(name) != expected:
            raise PreflightError("browser IPC controller runtime selector changed")
    if any(
        name in variables
        for name in (
            "BOCA_TLS_CERT_FILE",
            "BOCA_TLS_KEY_FILE",
            "BOCA_HEALTH_CA_FILE",
            "BOCA_SITE_BRIDGE_MODE",
            "BOCA_TELEGRAM_TOKEN",
        )
    ):
        raise PreflightError("browser IPC controller gained external/TLS configuration")
    expected_ports = {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
    networks = record.get("NetworkSettings")
    if not isinstance(networks, dict):
        raise PreflightError("browser IPC controller network inventory invalid")
    attached = networks.get("Networks")
    if not isinstance(attached, dict) or set(attached) != {BROWSER_BRIDGE}:
        raise PreflightError("browser IPC controller joined unexpected network")
    endpoint = attached[BROWSER_BRIDGE]
    if (
        not isinstance(endpoint, dict)
        or type(endpoint.get("NetworkID")) is not str
        or re.fullmatch(r"[0-9a-f]{64}", endpoint["NetworkID"]) is None
        or host.get("NetworkMode") != BROWSER_BRIDGE
        or host.get("PortBindings") != expected_ports
        or (
            networks.get("Ports") != expected_ports
            if running
            else networks.get("Ports") not in (None, {}, {"8443/tcp": None})
        )
        or host.get("NanoCpus") != 500_000_000
        or host.get("Memory") != 268_435_456
        or host.get("PidsLimit") != 64
        or host.get("CapDrop") != ["ALL"]
        or host.get("CapAdd") not in (None, [])
        or host.get("SecurityOpt") != ["no-new-privileges:true"]
        or host.get("CgroupnsMode") not in ("", "private")
        or host.get("Tmpfs")
        != {
            "/tmp": "rw,noexec,nosuid,size=16m"  # noqa: S108 - container tmpfs
        }
        or config.get("Cmd") != ["python", "-m", "boca_socios.runtime", "serve-beta"]
        or config.get("Entrypoint") not in (None, [])
    ):
        raise PreflightError("browser IPC controller HostConfig/port boundary changed")
    _browser_check_mounts(record, controller=True)
    if not running:
        return
    _validate_boca_network(container, endpoint["NetworkID"])
    if not verify_runtime:
        return
    limits = _cgroup_limits(container)
    if (
        type(limits.cpu_quota) is not int
        or type(limits.cpu_period) is not int
        or not 0 < limits.cpu_period <= 1_000_000
        or 2 * limits.cpu_quota != limits.cpu_period
        or limits.memory_bytes != 268_435_456
        or limits.pids_limit != 64
    ):
        raise PreflightError("browser IPC controller effective cgroup limits changed")


def _browser_apply(
    image: str,
    source_sha: str,
    beta_sha: str,
    origin: str,
    owner: str,
    browser_image: str,
    overlay_sha: str,
    seccomp_sha: str,
    attempt_id: str,
) -> None:
    _browser_engine_version()
    marker = _browser_read_marker(
        image, source_sha, beta_sha, browser_image, overlay_sha, seccomp_sha, attempt_id
    )
    _browser_verify_staged(beta_sha, overlay_sha, seccomp_sha)
    _browser_staged_inventory(volumes={OWNER_VOLUME})
    _browser_port_free()
    _browser_capacity()
    if _browser_image_absent(image, source_sha) != marker["controller_image_absent"]:
        raise PreflightError("controller image pre-attempt marker is stale")
    if _browser_image_absent(browser_image, source_sha) != marker["browser_image_absent"]:
        raise PreflightError("worker image pre-attempt marker is stale")
    _browser_compose_model(image, origin, owner, browser_image, attempt_id)
    _browser_pull_both(image, browser_image, source_sha)
    marker_after_pull = _browser_read_marker(
        image, source_sha, beta_sha, browser_image, overlay_sha, seccomp_sha, attempt_id
    )
    if marker_after_pull != marker:
        raise PreflightError("browser IPC pre-attempt inventory marker changed after image pulls")
    _browser_verify_staged(beta_sha, overlay_sha, seccomp_sha)
    _browser_staged_inventory(volumes={OWNER_VOLUME})
    _browser_port_free()
    # Recheck observable host state and storage after both image pulls, before
    # IPC/key/data effects. Actual RAM/CPU/PID demand is measured post-deploy.
    _, _, _, after_pull = _browser_capacity(min_free_bytes=POSTINSTALL_STORAGE_MIN_BYTES)
    _browser_create_ipc_volume(browser_image, attempt_id)
    _browser_staged_inventory(volumes={OWNER_VOLUME, BROWSER_IPC_VOLUME})
    environment = _browser_compose_env(image, origin, owner, browser_image, attempt_id)
    _run(
        *_browser_compose_args(
            "up",
            "--no-build",
            "--no-deps",
            "--wait",
            "--wait-timeout",
            "90",
            "-d",
            "browser-worker",
        ),
        env=environment,
        timeout=110,
    )
    worker = _browser_service_id("browser-worker", image, origin, owner, browser_image, attempt_id)
    bridges = _browser_worker_network_inventory()
    _browser_staged_inventory(
        volumes={OWNER_VOLUME, BROWSER_IPC_VOLUME}, containers={worker}, bridges=bridges
    )
    _browser_validate_ipc_volume(attempt_id)
    _browser_worker_postflight(worker, browser_image, source_sha, attempt_id, seccomp_sha)
    _browser_synthetic_socket_smoke(image, attempt_id)
    _browser_staged_inventory(
        volumes={OWNER_VOLUME, BROWSER_IPC_VOLUME}, containers={worker}, bridges=bridges
    )
    # The synthetic worker has proven a real UID10001/10002 AF_UNIX exchange.
    # Only now may the established BETA owner/key/data new-only path proceed.
    _beta_check_receipt(
        _browser_named_probe(
            "owner-check",
            attempt_id,
            _beta_check_container(image, origin, owner, "check-beta-owner"),
        ),
        "check-beta-owner",
    )
    _browser_create_key(image, attempt_id)
    _validate_key_volume()
    _browser_staged_inventory(
        volumes={OWNER_VOLUME, BROWSER_IPC_VOLUME, KEY_VOLUME},
        containers={worker},
        bridges=bridges,
    )
    _beta_check_receipt(
        _browser_named_probe(
            "config-check",
            attempt_id,
            _beta_check_container(image, origin, owner, "check-beta-config"),
        ),
        "check-beta-config",
    )
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
        raise PreflightError("browser IPC BETA data volume creation was unexpected")
    _validate_data_volume()
    if _browser_named_probe("data-init", attempt_id, _beta_init_container(image)):
        raise PreflightError("browser IPC new-only BETA init output was unexpected")
    _validate_owner_volume()
    _validate_key_volume()
    _validate_data_volume()
    _browser_staged_inventory(
        volumes={OWNER_VOLUME, BROWSER_IPC_VOLUME, KEY_VOLUME, DATA_VOLUME},
        containers={worker},
        bridges=bridges,
    )
    _browser_port_free()
    if (
        _browser_read_marker(
            image, source_sha, beta_sha, browser_image, overlay_sha, seccomp_sha, attempt_id
        )
        != marker
    ):
        raise PreflightError("browser IPC pre-attempt inventory marker changed before controller")
    _browser_verify_staged(beta_sha, overlay_sha, seccomp_sha)
    _browser_compose_model(image, origin, owner, browser_image, attempt_id)
    _run(
        *_browser_compose_args(
            "up",
            "--no-build",
            "--no-deps",
            "--wait",
            "--wait-timeout",
            "90",
            "-d",
            "controller",
        ),
        env=environment,
        timeout=110,
    )
    controller = _browser_service_id("controller", image, origin, owner, browser_image, attempt_id)
    _browser_inventory(
        containers={worker, controller},
        volumes={OWNER_VOLUME, BROWSER_IPC_VOLUME, KEY_VOLUME, DATA_VOLUME},
        bridges={BROWSER_BRIDGE},
    )
    _browser_worker_postflight(worker, browser_image, source_sha, attempt_id, seccomp_sha)
    _browser_controller_postflight(controller, image, source_sha, attempt_id, origin, owner)
    _browser_validate_ipc_volume(attempt_id)
    _validate_owner_volume()
    _validate_key_volume()
    _validate_data_volume()
    _beta_loopback_health(controller, origin)
    if (
        _browser_read_marker(
            image, source_sha, beta_sha, browser_image, overlay_sha, seccomp_sha, attempt_id
        )
        != marker
    ):
        raise PreflightError("browser IPC pre-attempt inventory marker changed before completion")
    _validate_storage_continuity(
        after_pull, _storage_snapshot(), min_free_bytes=POSTINSTALL_STORAGE_MIN_BYTES
    )
    print(
        f"BOCA_BROWSER_IPC_INSTALL_PASS attempt={attempt_id} source_sha={source_sha}"
        " services=controller,browser-worker host=127.0.0.1:8443"
        " worker_network=none ipc=synthetic owner=preserved engine=off"
    )


def _browser_existing_attempt(
    image: str,
    source_sha: str,
    beta_sha: str,
    browser_image: str,
    overlay_sha: str,
    seccomp_sha: str,
) -> str:
    """Resolve an installed attempt only from the protected canonical marker."""
    _require_dedicated_identity()
    raw = _browser_root_file(BROWSER_MARKER.name, max_size=1024)
    try:
        marker = json.loads(raw, object_pairs_hook=_browser_json_pairs)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise PreflightError("installed browser marker unavailable") from exc
    attempt = marker.get("attempt_id") if isinstance(marker, dict) else None
    if type(attempt) is not str or not BROWSER_ATTEMPT_PATTERN.fullmatch(attempt):
        raise PreflightError("installed browser attempt unavailable")
    _browser_read_marker(
        image, source_sha, beta_sha, browser_image, overlay_sha, seccomp_sha, attempt
    )
    return attempt


@dataclass(frozen=True)
class BrowserInstalled:
    controller: str
    worker: str
    marker: dict[str, object]
    telegram: bool
    sender: str = ""


def _browser_installed(
    image: str,
    source_sha: str,
    beta_sha: str,
    origin: str,
    owner: str,
    browser_image: str,
    overlay_sha: str,
    seccomp_sha: str,
    attempt_id: str,
    *,
    running: bool,
    telegram_owner: tuple[str, str] = ("", ""),
    allow_sender_failed: bool = False,
    require_capacity: bool = True,
    allow_service_failed: bool = False,
) -> BrowserInstalled:
    """Exact dual topology, including stopped-state proof before any start.

    No initialization, migration, pull, creation or deletion occurs here.
    Telegram custody may exist; an active sender is a separate explicit gate.
    """
    _browser_engine_version()
    marker = _browser_read_marker(
        image, source_sha, beta_sha, browser_image, overlay_sha, seccomp_sha, attempt_id
    )
    _browser_verify_staged(beta_sha, overlay_sha, seccomp_sha)
    _browser_compose_model(image, origin, owner, browser_image, attempt_id)
    ids: list[str] = []
    service_states: list[bool] = []
    for service, reference in (("controller", image), ("browser-worker", browser_image)):
        container = _run(
            "docker",
            "ps",
            "-a",
            "-q",
            "--no-trunc",
            "--filter",
            f"name=^/{PROJECT}-{service}-1$",
        )
        if re.fullmatch(r"[0-9a-f]{64}", container) is None:
            raise PreflightError("installed browser service identity unavailable")
        record = _browser_inspect_record(container)
        observed = running
        if allow_service_failed:
            state = record.get("State")
            if not isinstance(state, dict) or type(state.get("Running")) is not bool:
                raise PreflightError("installed browser service state unavailable during cleanup")
            observed = state["Running"]
        service_states.append(observed)
        _browser_validate_image(reference, source_sha)
        image_id = _run("docker", "image", "inspect", "--format", "{{.Id}}", reference)
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) or record.get("Image") != image_id:
            raise PreflightError("installed browser service image ID differs from approved digest")
        ids.append(container)
    controller, worker = ids
    controller_running, worker_running = service_states
    if controller == worker:
        raise PreflightError("installed browser services have duplicate identity")
    volumes = set(_run("docker", "volume", "ls", "-q").splitlines())
    required = {OWNER_VOLUME, KEY_VOLUME, DATA_VOLUME, BROWSER_IPC_VOLUME}
    if volumes not in (required, required | {TELEGRAM_VOLUME}):
        raise PreflightError("installed browser volume inventory changed")
    networks = _names("network", "name=^boca-socios_")
    if networks not in ({BROWSER_BRIDGE}, {BROWSER_BRIDGE, TELEGRAM_NETWORK}):
        raise PreflightError("installed browser network inventory changed")
    expected_ids = {controller, worker}
    actual_ids = _browser_docker_ids()
    sender = ""
    sender_attempt = ""
    sender_running = running
    if actual_ids != expected_ids:
        if len(actual_ids - expected_ids) != 1 or not expected_ids < actual_ids:
            raise PreflightError("installed browser daemon gained unknown containers")
        if (
            not all(telegram_owner)
            or TELEGRAM_VOLUME not in volumes
            or TELEGRAM_NETWORK not in networks
        ):
            raise PreflightError("installed Telegram owner or resources unavailable")
        sender = next(iter(actual_ids - expected_ids))
        sender_running = running
        if allow_sender_failed:
            sender_state = _browser_inspect_record(sender).get("State")
            if not isinstance(sender_state, dict) or type(sender_state.get("Running")) is not bool:
                raise PreflightError("Telegram sender state unavailable")
            sender_running = sender_state["Running"]
        sender_attempt = _telegram_worker_inspect(
            sender, image, source_sha, *telegram_owner, attempt_id, running=sender_running
        )
        if sender_running and not allow_sender_failed:
            _telegram_worker_ready(sender, source_sha)
        expected_ids.add(sender)
    _browser_inventory(containers=expected_ids, volumes=volumes, bridges=networks)
    _browser_worker_postflight(
        worker,
        browser_image,
        source_sha,
        attempt_id,
        seccomp_sha,
        running=worker_running,
        verify_runtime=not allow_service_failed,
    )
    _browser_controller_postflight(
        controller,
        image,
        source_sha,
        attempt_id,
        origin,
        owner,
        running=controller_running,
        verify_runtime=not allow_service_failed,
    )
    if not controller_running:
        record = _browser_inspect_record(controller)
        network = cast(dict[str, object], record["NetworkSettings"])
        attached = cast(dict[str, dict[str, str]], network["Networks"])
        _validate_boca_network("", attached[BROWSER_BRIDGE]["NetworkID"])
    _browser_validate_ipc_volume(attempt_id)
    _validate_owner_volume()
    _validate_key_volume()
    _validate_data_volume()
    if TELEGRAM_VOLUME in volumes:
        _telegram_volume()
    if TELEGRAM_NETWORK in networks:
        _telegram_egress(sender if running and (not allow_sender_failed or sender_running) else "")
        if sender:
            network_record = _json_object(
                _run("docker", "network", "inspect", "--format", "{{json .}}", TELEGRAM_NETWORK),
                "Telegram runtime network",
            )
            labels = network_record.get("Labels")
            if (
                not isinstance(labels, dict)
                or labels.get(BROWSER_ATTEMPT_LABEL) != attempt_id
                or labels.get(TELEGRAM_ATTEMPT_LABEL) != sender_attempt
            ):
                raise PreflightError("Telegram sender and egress attempts differ")
    capacity = _storage_snapshot()
    if require_capacity:
        _validate_storage_capacity(capacity, min_free_bytes=POSTINSTALL_STORAGE_MIN_BYTES)
    if marker != _browser_read_marker(
        image, source_sha, beta_sha, browser_image, overlay_sha, seccomp_sha, attempt_id
    ):
        raise PreflightError("installed browser marker changed during validation")
    return BrowserInstalled(controller, worker, marker, TELEGRAM_VOLUME in volumes, sender)


def _browser_wait_healthy(container: str) -> None:
    deadline = monotonic() + 90
    while monotonic() < deadline:
        record = _browser_inspect_record(container)
        state = record.get("State")
        if not isinstance(state, dict) or state.get("Running") is not True:
            raise PreflightError("started browser service exited")
        health = state.get("Health")
        if isinstance(health, dict) and health.get("Status") == "healthy":
            return
        if not isinstance(health, dict) or health.get("Status") != "starting":
            raise PreflightError("started browser service health failed")
        sleep(0.5)
    raise PreflightError("started browser service health deadline expired")


def _browser_lifecycle(
    operation: str,
    image: str,
    source_sha: str,
    beta_sha: str,
    origin: str,
    owner: str,
    browser_image: str,
    overlay_sha: str,
    seccomp_sha: str,
    attempt_id: str,
    expected_bot_id: str = "",
    expected_chat_hmac: str = "",
) -> None:
    coordinates = (
        image,
        source_sha,
        beta_sha,
        origin,
        owner,
        browser_image,
        overlay_sha,
        seccomp_sha,
        attempt_id,
    )
    owner_assertion = (expected_bot_id, expected_chat_hmac)
    initial = _browser_installed(
        *coordinates, running=operation != "browser-start", telegram_owner=owner_assertion
    )
    before_storage = _storage_snapshot()
    if operation == "browser-restart":
        # Stop only the exact verified IDs, preserving data, keys and ownership.
        for container in tuple(filter(None, (initial.sender, initial.controller, initial.worker))):
            if _run("docker", "stop", "--time", "35", container, timeout=45) != container:
                raise PreflightError("existing browser service stop is unverified")
        stopped = _browser_installed(*coordinates, running=False, telegram_owner=owner_assertion)
        if stopped != initial:
            raise PreflightError("installed browser identity changed while stopping")
    if operation in {"browser-start", "browser-restart"}:
        _browser_capacity(min_free_bytes=POSTINSTALL_STORAGE_MIN_BYTES)
        _browser_port_free()
        # No compose up/recreate: restart:no remains mandatory.
        for container in tuple(filter(None, (initial.worker, initial.controller, initial.sender))):
            if _run("docker", "start", container, timeout=30) != container:
                raise PreflightError("existing browser service start is unverified")
            if container == initial.sender:
                _telegram_worker_ready(container, source_sha)
            else:
                _browser_wait_healthy(container)
        if (
            _browser_installed(*coordinates, running=True, telegram_owner=owner_assertion)
            != initial
        ):
            raise PreflightError("installed browser identity changed while starting")
    _beta_loopback_health(initial.controller, origin)
    receipt = ""
    if operation == "browser-acceptance":
        # Exercise the real isolated browser from the actual controller identity.
        code = (
            "import asyncio; from boca_socios.browser.ipc_client import UnixSyntheticBrowser; "
            "from boca_socios.browser.contracts import SimulationOutcome; "
            "r=asyncio.run(UnixSyntheticBrowser(timeout_seconds=25).simulate_general_reservation()); "
            "assert r is SimulationOutcome.RESERVED_IN_SIMULATOR; "
            "print('BOCA_BROWSER_IPC_SYNTHETIC_PASS')"
        )
        if (
            _run(
                "docker",
                "exec",
                "--user",
                "10001:10001",
                initial.controller,
                "python",
                "-c",
                code,
                timeout=35,
            )
            != "BOCA_BROWSER_IPC_SYNTHETIC_PASS"
        ):
            raise PreflightError("installed controller browser IPC acceptance unverified")
        receipt = _validate_beta_acceptance_receipt(
            _run(
                "docker",
                "exec",
                "--user",
                "10001:10001",
                initial.controller,
                "python",
                "-m",
                "boca_socios.acceptance.host_probe",
                timeout=120,
            )
        )
    if _browser_installed(*coordinates, running=True, telegram_owner=owner_assertion) != initial:
        raise PreflightError("installed browser identity changed before lifecycle completion")
    _validate_storage_continuity(
        before_storage, _storage_snapshot(), min_free_bytes=POSTINSTALL_STORAGE_MIN_BYTES
    )
    if receipt:
        print(receipt)
    print(
        f"BOCA_BROWSER_LIFECYCLE_PASS operation={operation} source_sha={source_sha}"
        f" attempt={attempt_id} services=controller,browser-worker{',telegram' if initial.sender else ''}"
        " host=127.0.0.1:8443 data=preserved key=preserved owner=preserved engine=off"
    )


def _browser_phase(
    operation: str,
    image: str,
    source_sha: str,
    beta_sha: str,
    origin: str,
    owner: str,
    browser_image: str,
    overlay_sha: str,
    seccomp_sha: str,
    attempt_id: str,
    expected_bot_id: str = "",
    expected_chat_hmac: str = "",
    *,
    telegram_attempt_id: str = "",
) -> None:
    _browser_engine_version()
    if operation.startswith("browser-telegram-"):
        _browser_telegram_phase(
            operation,
            image,
            source_sha,
            beta_sha,
            origin,
            owner,
            browser_image,
            overlay_sha,
            seccomp_sha,
            attempt_id,
            expected_bot_id,
            expected_chat_hmac,
            telegram_attempt_id,
        )
        return
    if operation in {"browser-start", "browser-restart", "browser-status", "browser-acceptance"}:
        _browser_lifecycle(
            operation,
            image,
            source_sha,
            beta_sha,
            origin,
            owner,
            browser_image,
            overlay_sha,
            seccomp_sha,
            attempt_id,
            expected_bot_id,
            expected_chat_hmac,
        )
        return
    if operation == "browser-preflight":
        memory, cpu, pids, storage = _browser_preflight_inventory()
        _browser_image_absent(image, source_sha)
        _browser_image_absent(browser_image, source_sha)
        print(
            "BOCA_BROWSER_PREFLIGHT_PASS uid=10001 owner=existing namespace=new-only"
            " port=127.0.0.1:8443 state=FREE"
            f" mem_kib={memory} cpu_ceiling={cpu:.2f} pids_free={pids}"
            f" stage_free_mib={storage.stage_free_bytes // 1024**2}"
            f" docker_free_mib={storage.docker_free_bytes // 1024**2}"
        )
        return
    if operation == "browser-stage":
        _browser_stage(
            image, source_sha, beta_sha, browser_image, overlay_sha, seccomp_sha, attempt_id
        )
        return
    _browser_read_marker(
        image, source_sha, beta_sha, browser_image, overlay_sha, seccomp_sha, attempt_id
    )
    _browser_verify_staged(beta_sha, overlay_sha, seccomp_sha)
    if operation == "browser-config":
        _browser_staged_inventory(volumes={OWNER_VOLUME})
        _browser_port_free()
        _browser_capacity()
        print(_browser_compose_model(image, origin, owner, browser_image, attempt_id))
        return
    if operation == "browser-apply":
        _browser_apply(
            image,
            source_sha,
            beta_sha,
            origin,
            owner,
            browser_image,
            overlay_sha,
            seccomp_sha,
            attempt_id,
        )
        return
    raise PreflightError("unknown browser IPC phase")


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


def _owner_phase(
    operation: str, image: str, source_sha: str, origin: str, subject: str, envelope: str
) -> None:
    """Provision only the isolated owner volume, never an app or real DB."""
    _validate_owner_context(origin, subject)
    if (operation == "owner-install") != bool(envelope):
        raise PreflightError("sealed owner envelope required only for install")
    decoded = _owner_envelope(envelope, origin, subject) if envelope else None
    if any(path.exists() or path.is_symlink() for path in (COMPOSE, BETA_COMPOSE)):
        raise PreflightError("Boca Compose already staged; separate recovery review required")
    _site_daemon_empty()
    name = operation.removeprefix("owner-")
    volumes = _names("volume", "name=^boca-socios_")
    validate_site_snapshot(collect_snapshot(), volumes, require_owner=name != "prepare")
    if volumes:
        _validate_owner_volume()
        if _run("docker", "ps", "-a", "-q", "--filter", f"volume={OWNER_VOLUME}"):
            raise PreflightError("Boca owner volume is attached to a container")
    before_pull = _storage_snapshot()
    _validate_storage_capacity(before_pull)
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
        raise PreflightError("pulled owner bootstrap image differs from reviewed release")
    _validate_storage_continuity(before_pull, _storage_snapshot())
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
    receipt = _owner_receipt(
        _run(*_owner_container(image, name, origin, subject), input_data=decoded), name
    )
    _validate_owner_volume()
    _site_daemon_empty()
    print(receipt)


def _site_daemon_empty() -> None:
    """The dedicated rootless daemon cannot conceal foreign unlabeled containers."""
    if _run("docker", "ps", "-a", "-q", "--no-trunc"):
        raise PreflightError("dedicated Site daemon has an unexpected container")


def _telegram_envelope(value: str) -> str:
    """Validate ciphertext framing before passing it only on helper stdin."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{100,5500}", value):
        raise PreflightError("sealed Telegram envelope invalid")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        envelope = json.loads(decoded)
    except (ValueError, binascii.Error):
        raise PreflightError("sealed Telegram envelope invalid") from None
    if (
        len(decoded) > 4096
        or base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value
        or not isinstance(envelope, dict)
        or set(envelope)
        != {
            "version",
            "repository",
            "purpose",
            "uid",
            "recipient_public_key",
            "recipient_fingerprint",
            "ephemeral_public_key",
            "salt",
            "nonce",
            "ciphertext",
        }
        or type(envelope.get("version")) is not int
        or envelope.get("version") != 1
        or envelope.get("repository") != "mbalbo2023/boca-socios-assistant"
        or envelope.get("purpose") != "boca-telegram-bot-v1"
        or type(envelope.get("uid")) is not int
        or envelope.get("uid") != 10001
        or decoded
        != json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
            "ascii"
        )
    ):
        raise PreflightError("sealed Telegram envelope invalid")
    return decoded.decode("ascii")


def _telegram_volume() -> None:
    volume = _json_object(
        _run("docker", "volume", "inspect", "--format", "{{json .}}", TELEGRAM_VOLUME),
        "Telegram volume",
    )
    root = Path(_run("docker", "info", "--format", "{{.DockerRootDir}}"))
    expected = root / "volumes" / TELEGRAM_VOLUME / "_data"
    labels = volume.get("Labels")
    if (
        volume.get("Name") != TELEGRAM_VOLUME
        or volume.get("Driver") != "local"
        or volume.get("Scope") != "local"
        or volume.get("Options") not in (None, {})
        or not root.is_absolute()
        or root == Path("/")
        or volume.get("Mountpoint") != str(expected)
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != PROJECT
        or labels.get("com.docker.compose.volume") != "boca_telegram"
    ):
        raise PreflightError("Boca Telegram volume identity is unsafe")
    try:
        if root.resolve(strict=True) != root or expected.resolve(strict=True) != expected:
            raise PreflightError("Boca Telegram volume mountpoint redirected")
    except (OSError, RuntimeError) as exc:
        raise PreflightError("Boca Telegram volume mountpoint unavailable") from exc


def _telegram_container(image: str, module: str, action: str, *, writable: bool) -> tuple[str, ...]:
    if module not in {"telegram_bootstrap", "telegram_storage_gate"} or action not in {
        "prepare",
        "install",
        "verify",
        "migrate",
    }:
        raise PreflightError("unknown Telegram helper")
    secret = module == "telegram_bootstrap"
    volume = TELEGRAM_VOLUME if secret else DATA_VOLUME
    target = "/run/telegram" if secret else "/data"
    return (
        "docker",
        "run",
        "--rm",
        *(("-i",) if secret and action == "install" else ()),
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
        "--mount",
        f"type=volume,source={volume},target={target},volume-nocopy"
        + ("" if writable else ",readonly"),
        image,
        "python",
        "-m",
        f"boca_socios.{module}",
        action,
    )


def _telegram_installed(
    image: str,
    source_sha: str,
    compose_sha: str,
    origin: str,
    owner: str,
    *browser_context: str,
) -> bool:
    """Require a stopped controller from this exact release before any effect."""
    if browser_context:
        if len(browser_context) != 4:
            raise PreflightError("incomplete Telegram browser context")
        browser_image, overlay_sha, seccomp_sha, attempt_id = browser_context
        return _browser_installed(
            image,
            source_sha,
            compose_sha,
            origin,
            owner,
            browser_image,
            overlay_sha,
            seccomp_sha,
            attempt_id,
            running=False,
        ).telegram
    _verify_beta_compose(compose_sha)
    ids = _run("docker", "ps", "-a", "-q", "--no-trunc").splitlines()
    if len(ids) != 1 or not re.fullmatch(r"[0-9a-f]{64}", ids[0]):
        raise PreflightError("dedicated Telegram daemon inventory changed")
    record = _json_object(
        _run("docker", "inspect", "--format", "{{json .}}", ids[0]), "installed BETA controller"
    )
    config = record.get("Config")
    host = record.get("HostConfig")
    state = record.get("State")
    mounts = record.get("Mounts")
    labels = config.get("Labels") if isinstance(config, dict) else None
    entries = config.get("Env") if isinstance(config, dict) else None
    if not isinstance(entries, list) or any(
        not isinstance(item, str) or "=" not in item for item in entries
    ):
        raise PreflightError("installed BETA environment unavailable")
    environment = dict(item.split("=", 1) for item in entries)
    if len(environment) != len(entries) or any(
        environment.get(key) != expected
        for key, expected in {
            "BOCA_ENVIRONMENT": "staging",
            "BOCA_RUNTIME_MODE": "simulation",
            "BOCA_ENGINE_MODE": "off",
            "BOCA_DB_PATH": "/data/boca.sqlite3",
            "BOCA_MASTER_KEY_FILE": "/run/secrets/boca_master_key",
            "BOCA_PANEL_ORIGIN": origin,
            "BOCA_OWNER_SUBJECT": owner,
            "BOCA_SITE_BRIDGE_MODE": "off",
        }.items()
        if key in environment or key != "BOCA_SITE_BRIDGE_MODE"
    ):
        raise PreflightError("installed BETA environment changed")
    if (
        record.get("Id") != ids[0]
        or record.get("Name") != "/boca-socios-controller-1"
        or not isinstance(config, dict)
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != PROJECT
        or labels.get("com.docker.compose.service") != "controller"
        or labels.get("com.docker.compose.container-number") != "1"
        or labels.get("org.opencontainers.image.revision") != source_sha
        or config.get("Image") != image
        or config.get("User") != "10001:10001"
        or config.get("Cmd") != ["python", "-m", "boca_socios.runtime", "serve-beta"]
        or not isinstance(state, dict)
        or state.get("Running") is not False
        or not isinstance(host, dict)
        or host.get("NanoCpus") != 500_000_000
        or host.get("Memory") != 268_435_456
        or host.get("PidsLimit") != 64
        or host.get("ReadonlyRootfs") is not True
        or host.get("Privileged") is not False
        or host.get("PublishAllPorts") is not False
        or host.get("PortBindings") != {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
        or host.get("NetworkMode") != "boca-socios_boca_private"
        or host.get("CapDrop") != ["ALL"]
        or host.get("SecurityOpt") != ["no-new-privileges:true"]
        or not isinstance(mounts, list)
        or len(mounts) != 3
        or {
            (item.get("Type"), item.get("Name"), item.get("Destination"), item.get("RW"))
            for item in mounts
            if isinstance(item, dict)
        }
        != {
            ("volume", DATA_VOLUME, "/data", True),
            ("volume", KEY_VOLUME, "/run/secrets", False),
            ("volume", OWNER_VOLUME, "/run/owner", False),
        }
    ):
        raise PreflightError("installed BETA controller provenance changed")
    image_id = record.get("Image")
    if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise PreflightError("installed BETA image identity changed")
    local_image = _json_object(
        _run("docker", "image", "inspect", "--format", "{{json .}}", image_id),
        "installed image",
    )
    image_config = local_image.get("Config")
    digests = local_image.get("RepoDigests")
    if (
        local_image.get("Id") != image_id
        or not isinstance(digests, list)
        or image not in digests
        or not isinstance(image_config, dict)
        or not isinstance(image_config.get("Labels"), dict)
        or image_config["Labels"].get("org.opencontainers.image.revision") != source_sha
    ):
        raise PreflightError("installed image differs from reviewed release")
    volumes = set(_run("docker", "volume", "ls", "-q").splitlines())
    expected = {DATA_VOLUME, KEY_VOLUME, OWNER_VOLUME}
    if volumes not in (expected, expected | {TELEGRAM_VOLUME}):
        raise PreflightError("dedicated Telegram volume inventory changed")
    networks = set(_run("docker", "network", "ls", "--format", "{{.Name}}").splitlines())
    baseline = {"bridge", "host", "none", "boca-socios_boca_private"}
    if networks not in (baseline, baseline | {TELEGRAM_NETWORK}):
        raise PreflightError("dedicated Telegram network inventory changed")
    network = _json_object(
        _run("docker", "network", "inspect", "--format", "{{json .}}", "boca-socios_boca_private"),
        "BETA network",
    )
    network_labels = network.get("Labels")
    if (
        network.get("Name") != "boca-socios_boca_private"
        or network.get("Driver") != "bridge"
        or network.get("Scope") != "local"
        or network.get("Internal") is not False
        or network.get("Attachable") is not False
        or network.get("Ingress") is not False
        or network.get("Containers") != {}
        or not isinstance(network_labels, dict)
        or network_labels.get("com.docker.compose.project") != PROJECT
        or network_labels.get("com.docker.compose.network") != "boca_private"
    ):
        raise PreflightError("dedicated Telegram network provenance changed")
    if TELEGRAM_NETWORK in networks:
        _telegram_egress()
    _validate_data_volume()
    _validate_key_volume()
    _validate_owner_volume()
    if TELEGRAM_VOLUME in volumes:
        _telegram_volume()
    _validate_storage_capacity(_storage_snapshot(), min_free_bytes=POSTINSTALL_STORAGE_MIN_BYTES)
    return TELEGRAM_VOLUME in volumes


def _telegram_egress(container: str = "") -> None:
    network = _json_object(
        _run("docker", "network", "inspect", "--format", "{{json .}}", TELEGRAM_NETWORK),
        "Telegram egress network",
    )
    labels = network.get("Labels")
    if (
        network.get("Name") != TELEGRAM_NETWORK
        or network.get("Driver") != "bridge"
        or network.get("Scope") != "local"
        or network.get("Internal") is not False
        or network.get("Attachable") is not False
        or network.get("Ingress") is not False
        or not isinstance(network.get("Containers"), dict)
        or set(cast(dict[str, object], network["Containers"]))
        != ({container} if container else set())
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != PROJECT
        or labels.get("com.docker.compose.network") != "telegram_egress"
    ):
        raise PreflightError("Telegram egress provenance changed")


def _telegram_test_container(
    image: str, source_sha: str, expected_bot_id: str, expected_chat_hmac: str
) -> tuple[str, ...]:
    return (
        "docker",
        "run",
        "--pull",
        "never",
        "--name",
        TELEGRAM_TEST_NAME,
        "--label",
        f"com.docker.compose.project={PROJECT}",
        "--label",
        "com.docker.compose.service=telegram-test",
        "--label",
        "com.docker.compose.container-number=1",
        "--user",
        "10001:10001",
        "--network",
        TELEGRAM_NETWORK,
        "--read-only",
        "--no-healthcheck",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "32",
        "--memory",
        "128m",
        "--cpus",
        "0.25",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=8m",  # noqa: S108 - private capped container tmpfs
        "--env",
        "BOCA_ENVIRONMENT=staging",
        "--env",
        "BOCA_RUNTIME_MODE=simulation",
        "--env",
        "BOCA_ENGINE_MODE=off",
        "--env",
        "BOCA_TELEGRAM_DISPATCH_MODE=explicit",
        "--mount",
        f"type=volume,source={DATA_VOLUME},target=/data,volume-nocopy",
        "--mount",
        f"type=volume,source={TELEGRAM_VOLUME},target=/run/telegram,volume-nocopy,readonly",
        image,
        "python",
        "-m",
        "boca_socios.telegram_one_shot",
        "test",
        source_sha,
        expected_bot_id,
        expected_chat_hmac,
    )


def _telegram_worker_container(
    image: str, source_sha: str, bot_id: str, chat_hmac: str, attempt_id: str, runtime_attempt: str
) -> tuple[str, ...]:
    command = list(_telegram_test_container(image, source_sha, bot_id, chat_hmac))
    command[command.index(TELEGRAM_TEST_NAME)] = TELEGRAM_WORKER_NAME
    command[command.index("com.docker.compose.service=telegram-test")] = (
        "com.docker.compose.service=telegram"
    )
    command[-5] = "boca_socios.notify.telegram_worker"
    command[-4] = "serve"
    command[command.index("no-new-privileges")] = "no-new-privileges:true"
    return (
        *command[:2],
        "--detach",
        "--init",
        "--restart",
        "no",
        "--ipc=private",
        "--cgroupns=private",
        "--label",
        f"{BROWSER_ATTEMPT_LABEL}={attempt_id}",
        "--label",
        f"{TELEGRAM_ATTEMPT_LABEL}={runtime_attempt}",
        "--env",
        "BOCA_DB_PATH=/data/boca.sqlite3",
        *command[2:],
    )


def _telegram_worker_inspect(
    container: str,
    image: str,
    source_sha: str,
    bot_id: str,
    chat_hmac: str,
    attempt_id: str,
    *,
    running: bool,
    runtime_attempt: str = "",
) -> str:
    if re.fullmatch(r"[1-9][0-9]{0,15}", bot_id) is None or not DIGEST_PATTERN.fullmatch(chat_hmac):
        raise PreflightError("Telegram runtime owner assertion unavailable")
    record = _browser_inspect_record(container)
    config, host = _browser_config_and_host(record)
    state = record.get("State")
    labels = config.get("Labels")
    expected_command = [
        "python",
        "-m",
        "boca_socios.notify.telegram_worker",
        "serve",
        source_sha,
        bot_id,
        chat_hmac,
    ]
    image_record = _json_object(
        _run("docker", "image", "inspect", "--format", "{{json .}}", image), "Telegram worker image"
    )
    image_config = image_record.get("Config")
    entries = config.get("Env")
    if not isinstance(image_config, dict) or not isinstance(entries, list):
        raise PreflightError("Telegram worker environment unavailable")
    # The source image plus the same four test variables and one exact DB path.
    actual = [
        item
        for item in entries
        if not isinstance(item, str) or not item.startswith("BOCA_DB_PATH=")
    ]
    baseline = image_config.get("Env")
    if not isinstance(baseline, list):
        raise PreflightError("Telegram worker image environment unavailable")
    base = [
        item
        for item in baseline
        if not isinstance(item, str) or not item.startswith("BOCA_DB_PATH=")
    ]
    if (
        entries.count("BOCA_DB_PATH=/data/boca.sqlite3") != 1
        or len(actual) != len(entries) - 1
        or not _telegram_test_environment(actual, base)
    ):
        raise PreflightError("Telegram worker environment differs from reviewed image")
    if (
        record.get("Name") != f"/{TELEGRAM_WORKER_NAME}"
        or record.get("Image") != image_record.get("Id")
        or not isinstance(image_record.get("RepoDigests"), list)
        or image not in cast(list[object], image_record["RepoDigests"])
        or not isinstance(image_config.get("Labels"), dict)
        or image_config["Labels"].get("org.opencontainers.image.revision") != source_sha
        or config.get("Image") != image
        or config.get("User") != "10001:10001"
        or config.get("WorkingDir") != "/app"
        or config.get("Entrypoint") not in (None, [])
        or config.get("Cmd") != expected_command
        or not isinstance(config.get("Healthcheck"), dict)
        or cast(dict[str, object], config["Healthcheck"]).get("Test") != ["NONE"]
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != PROJECT
        or labels.get("com.docker.compose.service") != "telegram"
        or labels.get("com.docker.compose.container-number") != "1"
        or labels.get(BROWSER_ATTEMPT_LABEL) != attempt_id
        or not isinstance(labels.get(TELEGRAM_ATTEMPT_LABEL), str)
        or not BROWSER_ATTEMPT_PATTERN.fullmatch(labels[TELEGRAM_ATTEMPT_LABEL])
        or (runtime_attempt and labels.get(TELEGRAM_ATTEMPT_LABEL) != runtime_attempt)
        or labels.get("org.opencontainers.image.revision") != source_sha
        or not isinstance(state, dict)
        or state.get("Running") is not running
        or state.get("Restarting") is not False
        or record.get("RestartCount") != 0
        or host.get("RestartPolicy") != {"Name": "no", "MaximumRetryCount": 0}
        or host.get("NanoCpus") != 250_000_000
        or host.get("Memory") != 134_217_728
        or host.get("PidsLimit") != 32
        or host.get("ReadonlyRootfs") is not True
        or host.get("Privileged") is not False
        or host.get("PublishAllPorts") is not False
        or host.get("Init") is not True
        or host.get("IpcMode") != "private"
        or host.get("CgroupnsMode") != "private"
        or host.get("NetworkMode") != TELEGRAM_NETWORK
        or host.get("PortBindings") not in ({}, None)
        or host.get("CapDrop") != ["ALL"]
        or host.get("CapAdd") not in ([], None)
        or host.get("SecurityOpt") != ["no-new-privileges:true"]
        or host.get("Tmpfs") != {"/tmp": "rw,noexec,nosuid,size=8m"}  # noqa: S108 - container tmpfs
    ):
        raise PreflightError("Telegram worker identity or isolation changed")
    mounts = record.get("Mounts")
    expected_mounts = {
        ("volume", DATA_VOLUME, "/data", True, "local"),
        ("volume", TELEGRAM_VOLUME, "/run/telegram", False, "local"),
    }
    if (
        not isinstance(mounts, list)
        or len(mounts) != 2
        or {
            (
                item.get("Type"),
                item.get("Name"),
                item.get("Destination"),
                item.get("RW"),
                item.get("Driver"),
            )
            for item in mounts
            if isinstance(item, dict)
        }
        != expected_mounts
    ):
        raise PreflightError("Telegram worker mounts changed")
    network = record.get("NetworkSettings")
    if (
        not isinstance(network, dict)
        or network.get("Ports") not in ({}, None)
        or not isinstance(network.get("Networks"), dict)
        or set(network["Networks"]) != {TELEGRAM_NETWORK}
    ):
        raise PreflightError("Telegram worker network changed")
    return cast(str, cast(dict[str, object], labels)[TELEGRAM_ATTEMPT_LABEL])


def _telegram_worker_ready(container: str, source_sha: str) -> None:
    expected = (
        f"BOCA_TELEGRAM_READY state=VERIFIED source_sha={source_sha} api_accepted=1 identity=pinned"
    )
    deadline = monotonic() + 15
    while monotonic() < deadline:
        record = _browser_inspect_record(container)
        state = record.get("State")
        started = state.get("StartedAt") if isinstance(state, dict) else None
        if (
            not isinstance(state, dict)
            or state.get("Running") is not True
            or not isinstance(started, str)
            or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z", started) is None
        ):
            raise PreflightError("Telegram worker startup failed")
        receipt = _run("docker", "logs", "--since", started, "--tail", "2", container, timeout=5)
        if receipt == expected:
            return
        if receipt:
            raise PreflightError("Telegram worker ready receipt is unverified")
        sleep(0.2)
    raise PreflightError("Telegram worker ready receipt timed out")


def _browser_telegram_phase(
    operation: str,
    image: str,
    source_sha: str,
    beta_sha: str,
    origin: str,
    owner: str,
    browser_image: str,
    overlay_sha: str,
    seccomp_sha: str,
    attempt_id: str,
    bot_id: str,
    chat_hmac: str,
    runtime_attempt: str,
) -> None:
    coordinates = (
        image,
        source_sha,
        beta_sha,
        origin,
        owner,
        browser_image,
        overlay_sha,
        seccomp_sha,
        attempt_id,
    )
    if (
        re.fullmatch(r"[1-9][0-9]{0,15}", bot_id) is None
        or not DIGEST_PATTERN.fullmatch(chat_hmac)
        or not BROWSER_ATTEMPT_PATTERN.fullmatch(runtime_attempt)
    ):
        raise PreflightError("Telegram owner identity missing")
    cleanup = operation == "browser-telegram-cleanup"
    initial = _browser_installed(
        *coordinates,
        running=True,
        telegram_owner=(bot_id, chat_hmac),
        allow_sender_failed=cleanup,
        require_capacity=not cleanup,
        allow_service_failed=cleanup,
    )
    if not initial.telegram:
        raise PreflightError("Telegram private custody must already exist")
    networks = _names("network", "name=^boca-socios_")
    before_storage = _storage_snapshot()
    if cleanup:
        if TELEGRAM_NETWORK in networks:
            network = _json_object(
                _run("docker", "network", "inspect", "--format", "{{json .}}", TELEGRAM_NETWORK),
                "Telegram startup network",
            )
            labels = network.get("Labels")
            if (
                not isinstance(labels, dict)
                or labels.get(BROWSER_ATTEMPT_LABEL) != attempt_id
                or labels.get(TELEGRAM_ATTEMPT_LABEL) != runtime_attempt
            ):
                raise PreflightError("Telegram cleanup cannot identify startup network")
        if initial.sender:
            record = _browser_inspect_record(initial.sender)
            state = cast(dict[str, object], record["State"])
            # Check the current run before the first stop/remove; install identity
            # alone cannot distinguish a concurrent or prior sender attempt.
            _telegram_worker_inspect(
                initial.sender,
                image,
                source_sha,
                bot_id,
                chat_hmac,
                attempt_id,
                running=bool(state["Running"]),
                runtime_attempt=runtime_attempt,
            )
            if state["Running"]:
                if (
                    _run("docker", "stop", "--time", "10", initial.sender, timeout=20)
                    != initial.sender
                ):
                    raise PreflightError("Telegram failed-start stop unverified")
            _telegram_worker_inspect(
                initial.sender,
                image,
                source_sha,
                bot_id,
                chat_hmac,
                attempt_id,
                running=False,
                runtime_attempt=runtime_attempt,
            )
            if _run("docker", "rm", initial.sender) != initial.sender:
                raise PreflightError("Telegram failed-start removal unverified")
        if TELEGRAM_NETWORK in networks:
            _telegram_egress()
            if _run("docker", "network", "rm", TELEGRAM_NETWORK) != TELEGRAM_NETWORK:
                raise PreflightError("Telegram failed-start network removal unverified")
        after = _browser_installed(
            *coordinates,
            running=True,
            telegram_owner=(bot_id, chat_hmac),
            require_capacity=False,
            allow_service_failed=True,
        )
        if (
            after.sender
            or TELEGRAM_NETWORK in _names("network", "name=^boca-socios_")
            or (after.controller, after.worker, after.marker)
            != (initial.controller, initial.worker, initial.marker)
        ):
            raise PreflightError("Telegram failed-start residues remain")
        after_storage = _storage_snapshot()
        _validate_storage_continuity(before_storage, after_storage, require_capacity=False)
        print(
            f"BOCA_BROWSER_TELEGRAM_CLEANUP_STORAGE attempt={runtime_attempt}"
            f" before_stage_free_bytes={before_storage.stage_free_bytes}"
            f" after_stage_free_bytes={after_storage.stage_free_bytes}"
            f" before_stage_inodes={before_storage.stage_inodes}"
            f" after_stage_inodes={after_storage.stage_inodes}"
            f" before_docker_free_bytes={before_storage.docker_free_bytes}"
            f" after_docker_free_bytes={after_storage.docker_free_bytes}"
            f" before_docker_inodes={before_storage.docker_inodes}"
            f" after_docker_inodes={after_storage.docker_inodes}"
        )
        print(
            f"BOCA_BROWSER_TELEGRAM_CLEANUP_PASS source_sha={source_sha} attempt={attempt_id} sender=absent network=absent data=preserved key=preserved owner=preserved"
        )
        return
    if initial.sender or TELEGRAM_NETWORK in networks:
        raise PreflightError("Telegram startup requires absent sender and egress; no blind retry")
    _browser_capacity(min_free_bytes=POSTINSTALL_STORAGE_MIN_BYTES)
    if operation == "browser-telegram-preflight":
        print(
            f"BOCA_BROWSER_TELEGRAM_PREFLIGHT_PASS source_sha={source_sha} attempt={attempt_id} sender=absent network=absent"
        )
        return
    if operation != "browser-telegram-start":
        raise PreflightError("unknown Telegram browser lifecycle operation")
    created = _run(
        "docker",
        "network",
        "create",
        "--driver",
        "bridge",
        "--label",
        f"com.docker.compose.project={PROJECT}",
        "--label",
        "com.docker.compose.network=telegram_egress",
        "--label",
        f"{BROWSER_ATTEMPT_LABEL}={attempt_id}",
        "--label",
        f"{TELEGRAM_ATTEMPT_LABEL}={runtime_attempt}",
        TELEGRAM_NETWORK,
    )
    if re.fullmatch(r"[0-9a-f]{64}", created) is None:
        raise PreflightError("Telegram startup egress creation unverified")
    _telegram_egress()
    sender = _run(
        *_telegram_worker_container(
            image, source_sha, bot_id, chat_hmac, attempt_id, runtime_attempt
        )
    )
    if re.fullmatch(r"[0-9a-f]{64}", sender) is None:
        raise PreflightError("Telegram startup identity unverified")
    _telegram_worker_ready(sender, source_sha)
    final = _browser_installed(*coordinates, running=True, telegram_owner=(bot_id, chat_hmac))
    if final.sender != sender or (final.controller, final.worker, final.marker) != (
        initial.controller,
        initial.worker,
        initial.marker,
    ):
        raise PreflightError("Telegram startup changed installed identities")
    _telegram_worker_inspect(
        sender,
        image,
        source_sha,
        bot_id,
        chat_hmac,
        attempt_id,
        running=True,
        runtime_attempt=runtime_attempt,
    )
    _validate_storage_continuity(
        before_storage, _storage_snapshot(), min_free_bytes=POSTINSTALL_STORAGE_MIN_BYTES
    )
    print(
        f"BOCA_BROWSER_LIFECYCLE_PASS operation={operation} source_sha={source_sha} attempt={attempt_id} services=controller,browser-worker,telegram host=127.0.0.1:8443 data=preserved key=preserved owner=preserved engine=off"
    )


def _telegram_test_environment(actual: object, base: object) -> bool:
    """Compare the test's environment with the immutable image plus four fixed values."""

    def entries(value: object) -> dict[str, str] | None:
        if not isinstance(value, list) or any(
            not isinstance(item, str) or "=" not in item for item in value
        ):
            return None
        result = dict(item.split("=", 1) for item in value)
        return result if len(result) == len(value) else None

    baseline, observed = entries(base), entries(actual)
    if baseline is None or observed is None:
        return False
    baseline.update(
        BOCA_ENVIRONMENT="staging",
        BOCA_RUNTIME_MODE="simulation",
        BOCA_ENGINE_MODE="off",
        BOCA_TELEGRAM_DISPATCH_MODE="explicit",
    )
    return observed == baseline


def _telegram_test_finished(
    image: str,
    source_sha: str,
    expected_bot_id: str,
    expected_chat_hmac: str,
    controller_id: str,
    baseline_ids: set[str] | None = None,
) -> str:
    ids = _run("docker", "ps", "-a", "-q", "--no-trunc").splitlines()
    baseline = {controller_id} if baseline_ids is None else baseline_ids
    if (
        len(ids) != len(baseline) + 1
        or not baseline <= set(ids)
        or controller_id not in baseline
        or any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in ids)
    ):
        raise PreflightError("Telegram test container inventory changed")
    candidates = []
    for container_id in ids:
        record = _json_object(
            _run("docker", "inspect", "--format", "{{json .}}", container_id), "test container"
        )
        if record.get("Name") == f"/{TELEGRAM_TEST_NAME}":
            candidates.append((container_id, record))
    if len(candidates) != 1:
        raise PreflightError("Telegram test container unavailable")
    container_id, record = candidates[0]
    config, state, host = record.get("Config"), record.get("State"), record.get("HostConfig")
    mounts = record.get("Mounts")
    network_settings = record.get("NetworkSettings")
    image_record = _json_object(
        _run("docker", "image", "inspect", "--format", "{{json .}}", image),
        "Telegram test image",
    )
    image_id = image_record.get("Id")
    image_config = image_record.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    entries = config.get("Env") if isinstance(config, dict) else None
    if not isinstance(image_config, dict) or not _telegram_test_environment(
        entries, image_config.get("Env")
    ):
        raise PreflightError("Telegram test environment changed")
    if (
        record.get("Id") != container_id
        or record.get("Image") != image_id
        or not isinstance(config, dict)
        or config.get("Image") != image
        or config.get("User") != "10001:10001"
        or config.get("Entrypoint") is not None
        or config.get("WorkingDir") != "/app"
        or config.get("Healthcheck")
        != {
            "Test": ["NONE"],
            "Interval": 30_000_000_000,
            "Timeout": 5_000_000_000,
            "StartPeriod": 15_000_000_000,
            "Retries": 3,
        }
        or config.get("Cmd")
        != [
            "python",
            "-m",
            "boca_socios.telegram_one_shot",
            "test",
            source_sha,
            expected_bot_id,
            expected_chat_hmac,
        ]
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != PROJECT
        or labels.get("com.docker.compose.service") != "telegram-test"
        or labels.get("com.docker.compose.container-number") != "1"
        or labels.get("org.opencontainers.image.revision") != source_sha
        or not isinstance(state, dict)
        or state.get("Running") is not False
        or state.get("ExitCode") != 0
        or not isinstance(host, dict)
        or host.get("NanoCpus") != 250_000_000
        or host.get("Memory") != 134_217_728
        or host.get("PidsLimit") != 32
        or host.get("ReadonlyRootfs") is not True
        or host.get("Privileged") is not False
        or host.get("PortBindings") != {}
        or host.get("PublishAllPorts") is not False
        or host.get("NetworkMode") != TELEGRAM_NETWORK
        or host.get("CapDrop") != ["ALL"]
        or host.get("CapAdd") not in (None, [])
        or host.get("SecurityOpt") != ["no-new-privileges"]
        or host.get("Tmpfs") != {"/tmp": "rw,noexec,nosuid,size=8m"}  # noqa: S108 - private container
        or not isinstance(mounts, list)
        or len(mounts) != 2
        or {
            (
                item.get("Type"),
                item.get("Name"),
                item.get("Destination"),
                item.get("RW"),
                item.get("Driver"),
            )
            for item in mounts
            if isinstance(item, dict)
        }
        != {
            ("volume", DATA_VOLUME, "/data", True, "local"),
            ("volume", TELEGRAM_VOLUME, "/run/telegram", False, "local"),
        }
        or not isinstance(network_settings, dict)
        or network_settings.get("Ports") != {}
        or not isinstance(network_settings.get("Networks"), dict)
        or set(network_settings["Networks"]) not in (set(), {TELEGRAM_NETWORK})
    ):
        raise PreflightError("Telegram test container provenance changed")
    return container_id


def _telegram_test_phase(
    image: str,
    source_sha: str,
    compose_sha: str,
    origin: str,
    owner: str,
    expected_bot_id: str,
    expected_chat_hmac: str,
    *browser_context: str,
) -> None:
    if not _telegram_installed(image, source_sha, compose_sha, origin, owner, *browser_context):
        raise PreflightError("Telegram private volume unavailable")
    custody = _run(*_telegram_container(image, "telegram_bootstrap", "verify", writable=False))
    schema = _run(*_telegram_container(image, "telegram_storage_gate", "verify", writable=False))
    if (
        re.fullmatch(r"BOCA_TELEGRAM_BOOTSTRAP state=VERIFIED fingerprint=[0-9a-f]{64}", custody)
        is None
        or schema != "BOCA_TELEGRAM_STORAGE state=VERIFIED schema=0007"
    ):
        raise PreflightError("Telegram custody or schema unverified")
    networks = set(_run("docker", "network", "ls", "--format", "{{.Name}}").splitlines())
    if TELEGRAM_NETWORK not in networks:
        created = _run(
            "docker",
            "network",
            "create",
            "--driver",
            "bridge",
            "--label",
            f"com.docker.compose.project={PROJECT}",
            "--label",
            "com.docker.compose.network=telegram_egress",
            TELEGRAM_NETWORK,
        )
        if re.fullmatch(r"[0-9a-f]{64}", created) is None:
            raise PreflightError("Telegram egress creation unverified")
    _telegram_egress()
    _telegram_installed(image, source_sha, compose_sha, origin, owner, *browser_context)
    baseline_ids = set(_run("docker", "ps", "-a", "-q", "--no-trunc").splitlines())
    if len(baseline_ids) != (2 if browser_context else 1) or any(
        re.fullmatch(r"[0-9a-f]{64}", value) is None for value in baseline_ids
    ):
        raise PreflightError("Telegram controller inventory changed")
    controller_id = sorted(baseline_ids)[0]
    receipt = _run(
        *_telegram_test_container(image, source_sha, expected_bot_id, expected_chat_hmac)
    )
    if receipt != (
        f"BOCA_TELEGRAM_TEST state=API_ACCEPTED source_sha={source_sha}"
        " synthetic=1 human_receipt=unverified"
    ):
        raise PreflightError("Telegram API acceptance receipt unverified")
    container_id = _telegram_test_finished(
        image,
        source_sha,
        expected_bot_id,
        expected_chat_hmac,
        controller_id,
        baseline_ids if browser_context else None,
    )
    if _run("docker", "rm", container_id) != container_id:
        raise PreflightError("Telegram disposable test removal unverified")
    _telegram_installed(image, source_sha, compose_sha, origin, owner, *browser_context)
    _telegram_egress()
    if _run("docker", "network", "rm", TELEGRAM_NETWORK) != TELEGRAM_NETWORK:
        raise PreflightError("Telegram disposable egress removal unverified")
    _telegram_installed(image, source_sha, compose_sha, origin, owner, *browser_context)
    print(receipt)


def _telegram_phase(
    operation: str,
    image: str,
    source_sha: str,
    compose_sha: str,
    origin: str,
    owner: str,
    envelope: str,
    expected_bot_id: str = "",
    expected_chat_hmac: str = "",
    *browser_context: str,
) -> None:
    if (operation == "telegram-install") != bool(envelope):
        raise PreflightError("sealed Telegram envelope required only for install")
    decoded = _telegram_envelope(envelope) if envelope else None
    if operation == "telegram-test":
        if (
            re.fullmatch(r"[1-9][0-9]{0,15}", expected_bot_id) is None
            or re.fullmatch(r"[0-9a-f]{64}", expected_chat_hmac) is None
        ):
            raise PreflightError("Telegram owner assertion missing")
    elif expected_bot_id or expected_chat_hmac:
        raise PreflightError("unexpected Telegram owner assertion")
    present = _telegram_installed(image, source_sha, compose_sha, origin, owner, *browser_context)
    if operation == "telegram-test":
        _telegram_test_phase(
            image,
            source_sha,
            compose_sha,
            origin,
            owner,
            expected_bot_id,
            expected_chat_hmac,
            *browser_context,
        )
        return
    if operation == "telegram-migrate":
        if present:
            raise PreflightError("Telegram volume already present before migration")
        receipt = _run(
            *_telegram_container(image, "telegram_storage_gate", "migrate", writable=True)
        )
        if receipt != "BOCA_TELEGRAM_STORAGE state=MIGRATED schema=0007":
            raise PreflightError("Telegram database migration receipt unverified")
    else:
        receipt = _run(
            *_telegram_container(image, "telegram_storage_gate", "verify", writable=False)
        )
        if receipt != "BOCA_TELEGRAM_STORAGE state=VERIFIED schema=0007":
            raise PreflightError("Telegram database schema unverified")
    if operation == "telegram-migrate":
        _telegram_installed(image, source_sha, compose_sha, origin, owner, *browser_context)
        print(f"BOCA_TELEGRAM_HOST state=SCHEMA_READY source_sha={source_sha} schema=0007")
        return
    if operation == "telegram-prepare" and not present:
        created = _run(
            "docker",
            "volume",
            "create",
            "--driver",
            "local",
            "--label",
            f"com.docker.compose.project={PROJECT}",
            "--label",
            "com.docker.compose.volume=boca_telegram",
            TELEGRAM_VOLUME,
        )
        if created != TELEGRAM_VOLUME:
            raise PreflightError("unexpected Boca Telegram volume creation")
        _telegram_volume()
        # The empty named volume starts root-owned; only CHOWN is retained.
        command = (
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
            f"type=volume,source={TELEGRAM_VOLUME},target=/run/telegram,volume-nocopy",
            image,
            "python",
            "-c",
            "import os; os.chmod('/run/telegram',0o700); os.chown('/run/telegram',10001,10001)",
        )
        if _run(*command):
            raise PreflightError("Boca Telegram directory preparation had unexpected output")
    if operation not in {"telegram-prepare", "telegram-install", "telegram-verify"}:
        raise PreflightError("unknown Telegram phase")
    if not _telegram_installed(image, source_sha, compose_sha, origin, owner, *browser_context):
        raise PreflightError("Boca Telegram private volume unavailable")
    action = operation.removeprefix("telegram-")
    output = _run(
        *_telegram_container(image, "telegram_bootstrap", action, writable=action != "verify"),
        input_data=decoded,
    )
    if action == "prepare":
        pattern = r"BOCA_TELEGRAM_BOOTSTRAP state=(PREPARED|ALREADY_PREPARED) public_key=[A-Za-z0-9_-]{43} fingerprint=[0-9a-f]{64}"
    else:
        pattern = rf"BOCA_TELEGRAM_BOOTSTRAP state={'CONFIGURED' if action == 'install' else 'VERIFIED'} fingerprint=[0-9a-f]{{64}}"
    if re.fullmatch(pattern, output) is None or len(output) > 180:
        raise PreflightError("Boca Telegram custody receipt unverified")
    _telegram_installed(image, source_sha, compose_sha, origin, owner, *browser_context)
    print(output)


def phase(
    phase_name: str,
    image: str,
    source_sha: str,
    compose_sha: str,
    envelope: str = "",
    beta_owner: str = "",
    telegram_envelope: str = "",
    expected_bot_id: str = "",
    expected_chat_hmac: str = "",
    owner_envelope: str = "",
    enroll_digest: str = "",
    *,
    browser_image: str = "",
    browser_overlay_sha: str = "",
    browser_seccomp_sha: str = "",
    browser_attempt_id: str = "",
    telegram_attempt_id: str = "",
    infrastructure_budget: str = "",
    target_image: str = "",
    target_sha: str = "",
    legacy_container_id: str = "",
) -> None:
    if phase_name == "cutover-a-observe":
        if any(
            (
                telegram_envelope,
                expected_bot_id,
                expected_chat_hmac,
                owner_envelope,
                enroll_digest,
                browser_overlay_sha,
                browser_seccomp_sha,
                browser_attempt_id,
                telegram_attempt_id,
                infrastructure_budget,
            )
        ):
            raise PreflightError("unexpected private/attempt argument in cutover observation")
        _validate_docker_boundary()
        _cutover_observe(
            image,
            source_sha,
            compose_sha,
            envelope,
            beta_owner,
            target_image,
            target_sha,
            browser_image,
            legacy_container_id,
        )
        return
    if target_image or target_sha or legacy_container_id:
        raise PreflightError("cutover A coordinates supplied to unrelated host phase")
    if phase_name in {
        "network-probe",
        "network-probe-cleanup",
        "network-probe-icc-true",
        "network-probe-icc-true-cleanup",
    }:
        _validate_coordinates(image, source_sha, compose_sha, read_only_preflight=True)
        if any(
            (
                envelope,
                beta_owner,
                telegram_envelope,
                expected_bot_id,
                expected_chat_hmac,
                owner_envelope,
                enroll_digest,
                browser_image,
                browser_overlay_sha,
                browser_seccomp_sha,
                browser_attempt_id,
                telegram_attempt_id,
                infrastructure_budget,
            )
        ):
            raise PreflightError("unexpected private context in Boca network probe")
        _validate_docker_boundary()
        icc_true = "icc-true" in phase_name
        if phase_name.endswith("cleanup"):
            _network_probe_cleanup(icc_true=icc_true)
            print("BOCA_NETWORK_PROBE_CLEANUP state=VERIFIED network=absent")
        else:
            _network_probe(icc_true=icc_true)
        return
    if phase_name == "infrastructure-preflight":
        _validate_coordinates(image, source_sha, compose_sha, read_only_preflight=True)
        if any(
            (
                envelope,
                beta_owner,
                telegram_envelope,
                expected_bot_id,
                expected_chat_hmac,
                owner_envelope,
                enroll_digest,
                browser_image,
                browser_overlay_sha,
                browser_seccomp_sha,
                browser_attempt_id,
                telegram_attempt_id,
            )
        ):
            raise PreflightError("unexpected private or image context in infrastructure preflight")
        _infrastructure_preflight(source_sha, infrastructure_budget)
        return
    if infrastructure_budget:
        raise PreflightError("infrastructure budget supplied to unrelated phase")
    sender_phase = phase_name in {
        "browser-telegram-preflight",
        "browser-telegram-start",
        "browser-telegram-cleanup",
    }
    if sender_phase:
        if not BROWSER_ATTEMPT_PATTERN.fullmatch(telegram_attempt_id):
            raise PreflightError("Telegram startup attempt must be a protected Actions run ID")
    elif telegram_attempt_id:
        raise PreflightError("Telegram startup attempt supplied to unrelated phase")
    browser = phase_name.startswith("browser-")
    if browser:
        if phase_name not in {
            "browser-preflight",
            "browser-stage",
            "browser-config",
            "browser-apply",
            "browser-start",
            "browser-restart",
            "browser-status",
            "browser-acceptance",
            "browser-telegram-preflight",
            "browser-telegram-start",
            "browser-telegram-cleanup",
        }:
            raise PreflightError("unknown browser IPC phase")
        if telegram_envelope or owner_envelope or enroll_digest:
            raise PreflightError("unexpected private context in browser IPC phase")
        browser_lifecycle = phase_name in {
            "browser-start",
            "browser-restart",
            "browser-status",
            "browser-acceptance",
            "browser-telegram-preflight",
            "browser-telegram-start",
            "browser-telegram-cleanup",
        }
        if (sender_phase or expected_bot_id or expected_chat_hmac) and (
            not browser_lifecycle
            or re.fullmatch(r"[1-9][0-9]{0,15}", expected_bot_id) is None
            or not DIGEST_PATTERN.fullmatch(expected_chat_hmac)
        ):
            raise PreflightError("unexpected or invalid Telegram owner assertion")
        if browser_attempt_id == "existing" and phase_name in {
            "browser-start",
            "browser-restart",
            "browser-status",
            "browser-acceptance",
            "browser-telegram-preflight",
            "browser-telegram-start",
            "browser-telegram-cleanup",
        }:
            browser_attempt_id = _browser_existing_attempt(
                image,
                source_sha,
                compose_sha,
                browser_image,
                browser_overlay_sha,
                browser_seccomp_sha,
            )
        _browser_coordinates(
            image,
            source_sha,
            compose_sha,
            envelope,
            beta_owner,
            browser_image,
            browser_overlay_sha,
            browser_seccomp_sha,
            browser_attempt_id,
        )
        _validate_docker_boundary()
        _browser_phase(
            phase_name,
            image,
            source_sha,
            compose_sha,
            envelope,
            beta_owner,
            browser_image,
            browser_overlay_sha,
            browser_seccomp_sha,
            browser_attempt_id,
            *((expected_bot_id, expected_chat_hmac) if expected_bot_id else ()),
            **({"telegram_attempt_id": telegram_attempt_id} if sender_phase else {}),
        )
        return
    browser_context: tuple[str, ...] = ()
    if phase_name.startswith("telegram-") and browser_image:
        if browser_attempt_id != "existing":
            raise PreflightError("Telegram browser operation requires installed attempt")
        browser_attempt_id = _browser_existing_attempt(
            image,
            source_sha,
            compose_sha,
            browser_image,
            browser_overlay_sha,
            browser_seccomp_sha,
        )
        _browser_coordinates(
            image,
            source_sha,
            compose_sha,
            envelope,
            beta_owner,
            browser_image,
            browser_overlay_sha,
            browser_seccomp_sha,
            browser_attempt_id,
        )
        browser_context = (
            browser_image,
            browser_overlay_sha,
            browser_seccomp_sha,
            browser_attempt_id,
        )
    elif browser_image or browser_overlay_sha or browser_seccomp_sha or browser_attempt_id:
        raise PreflightError("browser IPC coordinates supplied to legacy phase")
    beta = phase_name.startswith("beta-")
    telegram = phase_name.startswith("telegram-")
    owner_custody = phase_name.startswith("owner-")
    owner_enroll = phase_name in {
        "owner-enroll-start",
        "owner-enroll-wait",
        "owner-enroll-finish",
    }
    if owner_custody:
        if phase_name not in {
            "owner-prepare",
            "owner-install",
            "owner-verify",
            "owner-enroll-start",
            "owner-enroll-wait",
            "owner-enroll-finish",
        }:
            raise PreflightError("unknown owner custody phase")
        _validate_owner_context(envelope, beta_owner)
        if telegram_envelope or expected_bot_id or expected_chat_hmac:
            raise PreflightError("unexpected Telegram arguments in owner phase")
        if owner_enroll and (DIGEST_PATTERN.fullmatch(enroll_digest) is None or owner_envelope):
            raise PreflightError("owner capability digest must be SHA-256 hex")
        if not owner_enroll and enroll_digest:
            raise PreflightError("unexpected owner capability digest")
    elif owner_envelope:
        raise PreflightError("unexpected owner envelope outside owner phase")
    elif enroll_digest:
        raise PreflightError("unexpected owner capability digest")
    if beta:
        if phase_name not in {
            "beta-preflight",
            "beta-stage",
            "beta-config",
            "beta-apply",
            "beta-rollback",
            "beta-acceptance",
            "beta-start",
        }:
            raise PreflightError("unknown BETA deployment phase")
        _validate_owner_context(envelope, beta_owner)
        if telegram_envelope or expected_bot_id or expected_chat_hmac:
            raise PreflightError("unexpected Telegram envelope outside Telegram phase")
    elif telegram:
        if phase_name not in {
            "telegram-migrate",
            "telegram-prepare",
            "telegram-install",
            "telegram-verify",
            "telegram-test",
        }:
            raise PreflightError("unknown Telegram host phase")
        _validate_beta_context(envelope, beta_owner)
    elif owner_custody:
        pass
    elif beta_owner:
        raise PreflightError("unexpected BETA context outside BETA phase")
    elif telegram_envelope:
        raise PreflightError("unexpected Telegram envelope outside Telegram phase")
    elif expected_bot_id or expected_chat_hmac:
        raise PreflightError("unexpected Telegram owner assertion outside Telegram phase")
    elif envelope and phase_name != "site-install":
        raise PreflightError("unexpected Site envelope outside install phase")
    _validate_coordinates(
        image,
        source_sha,
        compose_sha,
        read_only_preflight=phase_name in {"observe", "inspect-prerequisites", "port-check"},
    )
    if phase_name == "inspect-prerequisites":
        inspect_prerequisites()
        return
    if phase_name == "port-check":
        check_loopback_port()
        return
    if owner_custody:
        _validate_docker_boundary()
        if phase_name == "owner-enroll-start":
            _owner_enroll_start(image, source_sha, envelope, beta_owner, enroll_digest, compose_sha)
        elif phase_name == "owner-enroll-wait":
            _owner_enroll_wait(image, source_sha, compose_sha, envelope, beta_owner, enroll_digest)
        elif phase_name == "owner-enroll-finish":
            _owner_enroll_finish(
                image, source_sha, compose_sha, envelope, beta_owner, enroll_digest
            )
        else:
            _owner_phase(phase_name, image, source_sha, envelope, beta_owner, owner_envelope)
        return
    if beta:
        _validate_docker_boundary()
        _beta_phase(phase_name, image, source_sha, compose_sha, envelope, beta_owner)
        return
    if telegram:
        _validate_docker_boundary()
        _telegram_phase(
            phase_name,
            image,
            source_sha,
            compose_sha,
            envelope,
            beta_owner,
            telegram_envelope,
            expected_bot_id,
            expected_chat_hmac,
            *browser_context,
        )
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
            "infrastructure-preflight",
            "network-probe",
            "network-probe-cleanup",
            "network-probe-icc-true",
            "network-probe-icc-true-cleanup",
            "port-check",
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
            "owner-prepare",
            "owner-install",
            "owner-verify",
            "owner-enroll-start",
            "owner-enroll-wait",
            "owner-enroll-finish",
            "beta-preflight",
            "beta-stage",
            "beta-config",
            "beta-apply",
            "beta-rollback",
            "beta-acceptance",
            "beta-start",
            "browser-preflight",
            "browser-stage",
            "browser-config",
            "browser-apply",
            "browser-start",
            "browser-restart",
            "browser-status",
            "browser-acceptance",
            "browser-telegram-preflight",
            "browser-telegram-start",
            "browser-telegram-cleanup",
            "cutover-a-observe",
            "telegram-migrate",
            "telegram-prepare",
            "telegram-install",
            "telegram-verify",
            "telegram-test",
        ),
    )
    parser.add_argument("image")
    parser.add_argument("source_sha")
    parser.add_argument("compose_sha")
    parser.add_argument("envelope", nargs="?", default="")
    parser.add_argument("beta_owner", nargs="?", default="")
    parser.add_argument("telegram_envelope", nargs="?", default="")
    parser.add_argument("expected_bot_id", nargs="?", default="")
    parser.add_argument("expected_chat_hmac", nargs="?", default="")
    parser.add_argument("owner_envelope", nargs="?", default="")
    parser.add_argument("enroll_digest", nargs="?", default="")
    parser.add_argument("--browser-image", default="")
    parser.add_argument("--browser-overlay-sha", default="")
    parser.add_argument("--browser-seccomp-sha", default="")
    parser.add_argument("--browser-attempt-id", default="")
    parser.add_argument("--telegram-attempt-id", default="")
    parser.add_argument("--infrastructure-budget", default="")
    parser.add_argument("--cutover-target-image", default="")
    parser.add_argument("--cutover-target-sha", default="")
    parser.add_argument("--cutover-legacy-id", default="")
    args = parser.parse_args()
    try:
        phase(
            args.phase,
            args.image,
            args.source_sha,
            args.compose_sha,
            args.envelope,
            args.beta_owner,
            args.telegram_envelope,
            args.expected_bot_id,
            args.expected_chat_hmac,
            args.owner_envelope,
            args.enroll_digest,
            browser_image=args.browser_image,
            browser_overlay_sha=args.browser_overlay_sha,
            browser_seccomp_sha=args.browser_seccomp_sha,
            browser_attempt_id=args.browser_attempt_id,
            **(
                {"telegram_attempt_id": args.telegram_attempt_id}
                if args.telegram_attempt_id
                else {}
            ),
            **(
                {"infrastructure_budget": args.infrastructure_budget}
                if args.infrastructure_budget
                else {}
            ),
            **({"target_image": args.cutover_target_image} if args.cutover_target_image else {}),
            **({"target_sha": args.cutover_target_sha} if args.cutover_target_sha else {}),
            **({"legacy_container_id": args.cutover_legacy_id} if args.cutover_legacy_id else {}),
        )
    except (PreflightError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"BOCA_NO_GO: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
