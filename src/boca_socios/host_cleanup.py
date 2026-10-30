"""Conservative Boca-only cleanup candidate for a failed first installation.

This standalone standard-library module is streamed by the guarded failure
step of the single protected Actions workflow after a first-install attempt.
It does not authorize a host operation by itself.
Any Boca container or ambiguous image blocks deletion. Key/data volumes and
networks are always preserved, even if the exact unreferenced image is removed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path("/srv/boca-socios")
COMPOSE = ROOT / "compose.yaml"
ROOTLESS_SOCKET = Path("/run/user/10001/docker.sock")
ROOTFUL_SOCKET = Path("/var/run/docker.sock")
DOCKER = "/usr/bin/docker"
IMAGE_PATTERN = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class CleanupError(ValueError):
    """The artifact or the cleanup outcome cannot be proven safe."""


class ImageAbsent(CleanupError):
    """The exact Boca image reference is not present on the dedicated daemon."""


class CleanupIndeterminate(CleanupError):
    """A bounded mutation began but its final outcome cannot be certified."""


@dataclass(frozen=True)
class CapacitySnapshot:
    docker_root: Path
    stage_device: int
    docker_device: int
    stage_free_bytes: int
    stage_inodes: int
    docker_free_bytes: int
    docker_inodes: int


@dataclass(frozen=True)
class CleanupResult:
    removed_image: bool
    removed_stage: bool
    retained_state: bool
    before: CapacitySnapshot
    after: CapacitySnapshot
    image_size_bytes: int


def _validate_coordinates(image: str, source_sha: str, compose_sha: str) -> None:
    if (
        not IMAGE_PATTERN.fullmatch(image)
        or not SHA_PATTERN.fullmatch(source_sha)
        or not DIGEST_PATTERN.fullmatch(compose_sha)
    ):
        raise CleanupError("invalid immutable Boca coordinates")


def _check_identity() -> None:
    uid = os.getuid()
    if uid != 10001 or os.geteuid() != uid or os.getegid() != os.getgid():
        raise CleanupError("expected dedicated Boca identity")
    try:
        account = pwd.getpwuid(10001).pw_name
    except KeyError as exc:
        raise CleanupError("expected dedicated Boca identity") from exc
    if account != "boca-deploy":
        raise CleanupError("expected dedicated Boca identity")


def _safe_private_runtime() -> bool:
    try:
        directory = ROOTLESS_SOCKET.parent.lstat()
    except OSError:
        return False
    if not (
        stat.S_ISDIR(directory.st_mode)
        and directory.st_uid == 10001
        and stat.S_IMODE(directory.st_mode) == 0o700
    ):
        return False
    try:
        socket = ROOTLESS_SOCKET.lstat()
    except OSError:
        return False
    return stat.S_ISSOCK(socket.st_mode) and socket.st_uid == 10001


def _run(*args: str) -> str:
    # Never inherit a remote/rootful Docker context or transport from SSH.
    environment = dict(os.environ)
    for key in ("DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        environment.pop(key, None)
    environment["DOCKER_HOST"] = f"unix://{ROOTLESS_SOCKET}"
    try:
        result = subprocess.run(  # noqa: S603 - fixed Docker argv, validated coordinates
            (DOCKER, *args),
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CleanupError("Boca-only Docker query or operation failed") from exc
    if result.returncode:
        # Only the exact image-inspection miss is a safe absence. Every other
        # Docker failure is uncertain and cannot lead to a deletion.
        if (
            args[:2] == ("image", "inspect")
            and len(args) == 5
            and re.search(
                r"(?:^|: )No such image: " + re.escape(args[-1]) + r"\s*\Z", result.stderr
            )
        ):
            raise ImageAbsent("exact Boca image absent")
        raise CleanupError("Boca-only Docker query or operation failed")
    if len(result.stdout) > 16_384:
        raise CleanupError("Boca Docker metadata exceeds bounded output")
    return result.stdout.strip()


def _check_rootless_boundary() -> None:
    if not _safe_private_runtime() or os.access(ROOTFUL_SOCKET, os.W_OK):
        raise CleanupError("dedicated rootless Docker boundary is unproven")
    try:
        info = json.loads(_run("info", "--format", "{{json .}}"))
    except (TypeError, json.JSONDecodeError) as exc:
        raise CleanupError("dedicated rootless Docker metadata is unavailable") from exc
    if (
        not isinstance(info, dict)
        or not isinstance(info.get("SecurityOptions"), list)
        or "name=rootless" not in info["SecurityOptions"]
        or str(info.get("CgroupVersion")) != "2"
        or info.get("CgroupDriver") != "systemd"
    ):
        raise CleanupError("dedicated rootless Docker boundary is unproven")


def _checked_root() -> None:
    try:
        metadata = ROOT.lstat()
    except OSError as exc:
        raise CleanupError("private Boca directory is unavailable") from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != 10001
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise CleanupError("private Boca directory contains uncertain state")
    try:
        entries = {child.name for child in ROOT.iterdir()}
    except OSError as exc:
        raise CleanupError("private Boca directory is unavailable") from exc
    if entries - {"compose.yaml"}:
        raise CleanupError("private Boca directory contains uncertain state")


def _checked_stage(compose_sha: str) -> bool:
    _checked_root()
    try:
        metadata = COMPOSE.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise CleanupError("staged Compose metadata is unavailable") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 10001
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or metadata.st_size > 32_768
    ):
        raise CleanupError("staged Compose identity is unsafe")
    try:
        actual_hash = hashlib.sha256(COMPOSE.read_bytes()).hexdigest()
    except OSError as exc:
        raise CleanupError("staged Compose content is unavailable") from exc
    if actual_hash != compose_sha:
        raise CleanupError("staged Compose differs from the exact Boca candidate")
    return True


def validate_image(metadata: object, image: str, source_sha: str) -> int:
    """Accept only one untagged Boca digest with the exact source label."""
    if not isinstance(metadata, dict):
        raise CleanupError("Boca image metadata is invalid")
    config = metadata.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    size = metadata.get("Size")
    if (
        metadata.get("RepoDigests") != [image]
        or metadata.get("RepoTags") not in (None, [])
        or not isinstance(labels, dict)
        or labels.get("org.opencontainers.image.revision") != source_sha
        or type(size) is not int
        or size < 0
    ):
        raise CleanupError("Boca image is shared, changed or unproven")
    return size


def _checked_docker_storage_dir() -> Path:
    """Use the same conservative data-root contract as the standalone preflight."""
    try:
        info = json.loads(_run("info", "--format", "{{json .}}"))
        if not isinstance(info, dict):
            raise CleanupError("rootless Docker storage backend is unproven")
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
            raise CleanupError("rootless Docker storage backend is unproven")
        reported = info.get("DockerRootDir")
        home = Path(pwd.getpwuid(10001).pw_dir)
        if not isinstance(reported, str) or len(reported) > 4096:
            raise CleanupError("rootless Docker storage path is unproven")
        storage = Path(reported)
        if (
            not home.is_absolute()
            or home == Path("/")
            or not storage.is_absolute()
            or ".." in storage.parts
            or str(storage) != reported
            or home.resolve(strict=True) != home
        ):
            raise CleanupError("rootless Docker storage path is unproven")
        home_meta = home.lstat()
        if (
            not stat.S_ISDIR(home_meta.st_mode)
            or home_meta.st_uid != 10001
            or stat.S_IMODE(home_meta.st_mode) != 0o700
        ):
            raise CleanupError("rootless Docker storage path is unproven")
        relative = storage.relative_to(home)
        if not relative.parts:
            raise CleanupError("rootless Docker storage path is unproven")
        current = home
        for part in relative.parts:
            current /= part
            metadata = current.lstat()
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != 10001
                or stat.S_IMODE(metadata.st_mode) & 0o022
            ):
                raise CleanupError("rootless Docker storage path is unproven")
    except CleanupError:
        raise
    except (OSError, ValueError, KeyError, AttributeError, TypeError) as exc:
        raise CleanupError("rootless Docker storage path is unproven") from exc
    return storage


def _capacity() -> CapacitySnapshot:
    docker_root = _checked_docker_storage_dir()
    try:
        stage_device = ROOT.stat().st_dev
        docker_device = docker_root.stat().st_dev
        stage = os.statvfs(ROOT)
        docker = os.statvfs(docker_root)
    except OSError as exc:
        raise CleanupError("Boca staging or rootless Docker capacity is unavailable") from exc
    return CapacitySnapshot(
        docker_root=docker_root,
        stage_device=stage_device,
        docker_device=docker_device,
        stage_free_bytes=stage.f_bavail * stage.f_frsize,
        stage_inodes=stage.f_favail,
        docker_free_bytes=docker.f_bavail * docker.f_frsize,
        docker_inodes=docker.f_favail,
    )


def _retained_boca_state() -> bool:
    # Filters prevent enumerating other project names or metadata. Any Boca
    # container blocks deletion; volumes and networks are never deleted.
    if _run("ps", "-a", "-q", "--filter", "label=com.docker.compose.project=boca-socios"):
        raise CleanupError("Boca controller or container must be retained")
    if _run("ps", "-a", "-q", "--filter", "name=^/boca-socios-"):
        raise CleanupError("Boca controller or container must be retained")
    volumes = _run("volume", "ls", "-q", "--filter", "name=^boca-socios_")
    networks = _run("network", "ls", "-q", "--filter", "name=^boca-socios_")
    return bool(volumes or networks)


def clean_failed_install(image: str, source_sha: str, compose_sha: str) -> CleanupResult:
    """Discard only an unreferenced Boca image and exact staged Compose file."""
    _check_identity()  # UID first: never probe another user's private runtime.
    _validate_coordinates(image, source_sha, compose_sha)
    _check_rootless_boundary()
    staged = _checked_stage(compose_sha)
    retained_state = _retained_boca_state()
    try:
        image_json = json.loads(_run("image", "inspect", "--format", "{{json .}}", image))
    except ImageAbsent:
        image_size = 0
        has_image = False
    except (TypeError, json.JSONDecodeError) as exc:
        raise CleanupError("exact Boca image metadata is invalid") from exc
    else:
        image_size = validate_image(image_json, image, source_sha)
        has_image = True
        if _run("ps", "-a", "-q", "--filter", f"ancestor={image}"):
            raise CleanupError("exact Boca image is referenced by a container")
    before = _capacity()
    mutation_attempted = False
    try:
        if has_image:
            mutation_attempted = True
            _run("image", "rm", "--no-prune", image)
        if staged and not retained_state:
            if not _checked_stage(compose_sha):
                raise CleanupError("staged Compose changed during cleanup")
            mutation_attempted = True
            COMPOSE.unlink()  # The private directory and exact regular file were rechecked.
        after = _capacity()
        if (
            before.docker_root != after.docker_root
            or before.stage_device != after.stage_device
            or before.docker_device != after.docker_device
        ):
            raise CleanupError("Boca storage topology changed during cleanup")
    except (CleanupError, OSError) as exc:
        if mutation_attempted:
            raise CleanupIndeterminate("bounded Boca cleanup outcome is unverified") from exc
        raise
    result = CleanupResult(
        removed_image=has_image,
        removed_stage=staged and not retained_state,
        retained_state=retained_state,
        before=before,
        after=after,
        image_size_bytes=image_size,
    )
    if retained_state:
        state = "PARTIAL" if has_image else "RETAINED"
    else:
        state = "CLEANED" if staged or has_image else "ALREADY_CLEAN"
    print(
        "BOCA_CLEANUP"
        f" state={state}"
        f" image={'removed' if has_image else 'absent'}"
        f" stage={'retained' if staged and retained_state else 'removed' if staged else 'absent'}"
        f" retained={'yes' if retained_state else 'no'}"
        f" image_logical_mib={image_size // 1024**2}"
        f" same_fs={'yes' if before.stage_device == before.docker_device else 'no'}"
        f" stage_free_mib_before={before.stage_free_bytes // 1024**2}"
        f" stage_free_mib_after={after.stage_free_bytes // 1024**2}"
        f" docker_free_mib_before={before.docker_free_bytes // 1024**2}"
        f" docker_free_mib_after={after.docker_free_bytes // 1024**2}"
        f" stage_inodes_before={before.stage_inodes}"
        f" stage_inodes_after={after.stage_inodes}"
        f" docker_inodes_before={before.docker_inodes}"
        f" docker_inodes_after={after.docker_inodes}"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Conservative Boca-only failed-install cleanup")
    parser.add_argument("image")
    parser.add_argument("source_sha")
    parser.add_argument("compose_sha")
    args = parser.parse_args(argv)
    try:
        clean_failed_install(args.image, args.source_sha, args.compose_sha)
    except CleanupIndeterminate:
        print("BOCA_CLEANUP_INDETERMINADO: re-inventory Boca before retry", file=sys.stderr)
        return 1
    except (CleanupError, OSError, ValueError) as exc:
        print(f"BOCA_CLEANUP_NO_GO: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
