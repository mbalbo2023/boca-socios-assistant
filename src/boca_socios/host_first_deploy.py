"""Bounded first-install host helper, streamed over SSH by the gated workflow.

This file uses only the Python standard library and never reads other projects.
Each invocation is a single phase; a failed phase is not retried automatically.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import pwd
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path("/srv/boca-socios")
COMPOSE = ROOT / "compose.yaml"
SECRET_DIR = ROOT / "secrets"
KEY = SECRET_DIR / "master.key"
PROJECT = "boca-socios"
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
    root_ready: bool
    boca_containers: bool
    boca_volume: bool
    boca_network: bool
    cpu_headroom: float = 1.0


def validate_snapshot(snapshot: HostSnapshot) -> None:
    if snapshot.arch != "x86_64":
        raise PreflightError("host architecture must be x86_64")
    if snapshot.uid != 10001:
        raise PreflightError("dedicated deploy identity must have UID 10001")
    if snapshot.available_memory_kib < 768 * 1024:
        raise PreflightError("insufficient available host memory")
    if snapshot.cpu_headroom < 0.5:
        raise PreflightError("insufficient approximate host CPU headroom")
    if snapshot.available_disk_bytes < 4 * 1024**3 or snapshot.available_inodes < 50_000:
        raise PreflightError("insufficient free host storage")
    if not snapshot.root_ready:
        raise PreflightError("Boca-owned directory is unavailable or unsafe")
    if snapshot.boca_containers or snapshot.boca_volume or snapshot.boca_network:
        raise PreflightError("existing Boca namespace requires separate recovery review")


def _run(*args: str, env: dict[str, str] | None = None) -> str:
    try:
        result = subprocess.run(  # noqa: S603 - validated coordinates; fixed argv, no shell
            args, check=True, text=True, capture_output=True, timeout=120, env=env
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


def _root_ready() -> bool:
    if not _safe_dir(ROOT):
        return False
    if any(child.name not in {"compose.yaml", "secrets"} for child in ROOT.iterdir()):
        return False
    if SECRET_DIR.exists() or SECRET_DIR.is_symlink():
        if not _safe_dir(SECRET_DIR) or KEY.exists() or KEY.is_symlink():
            return False
        if any(SECRET_DIR.iterdir()):
            return False
    if COMPOSE.is_symlink():
        return False
    return os.access(ROOT, os.W_OK)


def _names(kind: str, label: str) -> set[str]:
    return set(_run("docker", kind, "ls", "-q", "--filter", label).splitlines())


def collect_snapshot() -> HostSnapshot:
    # The deployment identity is dedicated to Boca; matching container UID
    # keeps the owner-only bind-mounted secret readable without 0444 on host.
    try:
        dedicated = pwd.getpwuid(os.getuid()).pw_name == "boca-deploy"
    except KeyError:
        dedicated = False
    if not dedicated:
        raise PreflightError("expected dedicated boca-deploy account")
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
    disk = os.statvfs(str(ROOT))
    containers = _run(
        "docker", "ps", "-a", "-q", "--filter", "label=com.docker.compose.project=boca-socios"
    ) or _run("docker", "ps", "-a", "-q", "--filter", "name=^/boca-socios-")
    # Check the whole Boca namespace, including resources missing Compose labels.
    volumes = _names("volume", "name=^boca-socios_")
    networks = _names("network", "name=^boca-socios_")
    return HostSnapshot(
        arch=platform.machine(),
        uid=os.getuid(),
        available_memory_kib=int(match.group(1)),
        available_disk_bytes=disk.f_bavail * disk.f_frsize,
        available_inodes=disk.f_favail,
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
        "BOCA_MASTER_KEY_SOURCE": str(KEY),
    }


def _compose_args(*args: str) -> tuple[str, ...]:
    return ("docker", "compose", "-p", PROJECT, "-f", str(COMPOSE), *args)


def _create_key() -> None:
    if SECRET_DIR.exists() or SECRET_DIR.is_symlink():
        if not _safe_dir(SECRET_DIR):
            raise PreflightError("unsafe Boca secret directory")
    else:
        SECRET_DIR.mkdir(mode=0o700)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(KEY, flags, 0o400)
    with os.fdopen(descriptor, "wb") as output:
        output.write(base64.b64encode(os.urandom(32)) + b"\n")
        output.flush()
        os.fsync(output.fileno())


def _validate_coordinates(image: str, source_sha: str, compose_sha: str) -> None:
    if (
        not IMAGE_PATTERN.fullmatch(image)
        or not SHA_PATTERN.fullmatch(source_sha)
        or not DIGEST_PATTERN.fullmatch(compose_sha)
    ):
        raise PreflightError("invalid immutable deployment coordinates")


def phase(phase_name: str, image: str, source_sha: str, compose_sha: str) -> None:
    _validate_coordinates(image, source_sha, compose_sha)
    validate_snapshot(snapshot := collect_snapshot())
    if phase_name == "preflight":
        if COMPOSE.exists() or COMPOSE.is_symlink():
            raise PreflightError("Boca Compose already staged")
        print(
            "BOCA_PREFLIGHT_PASS"
            f" arch={snapshot.arch} uid={snapshot.uid}"
            f" mem_kib={snapshot.available_memory_kib}"
            f" disk_bytes={snapshot.available_disk_bytes} inodes={snapshot.available_inodes}"
            f" cpu_headroom={snapshot.cpu_headroom:.2f}"
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
    _create_key()
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
    except PreflightError:
        try:
            _run(*_compose_args("stop", "controller"), env=_compose_env(image))
        except PreflightError:
            pass
        raise
    print(f"BOCA_DEPLOY_PASS image={image} source_sha={source_sha} service=controller")


def main() -> int:
    parser = argparse.ArgumentParser(description="Boca-only first-install host gate")
    parser.add_argument("phase", choices=("preflight", "stage", "config", "apply"))
    parser.add_argument("image")
    parser.add_argument("source_sha")
    parser.add_argument("compose_sha")
    args = parser.parse_args()
    try:
        phase(args.phase, args.image, args.source_sha, args.compose_sha)
    except (PreflightError, OSError, ValueError) as exc:
        print(f"BOCA_NO_GO: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
