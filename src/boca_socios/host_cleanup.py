"""Conservative Boca-only cleanup after a failed protected installation.

This standalone standard-library module is streamed by the guarded failure
step of the single protected Actions workflow after a staged install attempt.
It does not authorize a host operation by itself.
The first-install contract retains all containers and networks. The BETA
contract can stop/remove only its exact controller and empty private network.
No contract ever deletes a key, data or owner volume or a shared image.
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
BETA_COMPOSE = ROOT / "compose.beta.yaml"
BETA_NETWORK = "boca-socios_boca_private"
BETA_CONTROLLER = "/boca-socios-controller-1"
BETA_VOLUMES = frozenset(
    {"boca-socios_boca_owner", "boca-socios_boca_key", "boca-socios_boca_data"}
)
OWNER_VOLUME = "boca-socios_boca_owner"
ENROLL_VOLUME = "boca-socios_owner_enroll_staging"
ENROLL_MARKER = ROOT / "owner-enroll-attempt.json"
ENROLL_NETWORK = "boca-socios_owner_enroll_private"
ENROLL_CONTAINER = "boca-socios-owner-enroll-1"
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


@dataclass(frozen=True)
class BetaCleanupResult(CleanupResult):
    removed_container: bool
    removed_network: bool


@dataclass(frozen=True)
class EnrollmentCleanupResult:
    removed_container: bool
    removed_network: bool
    removed_image: bool
    removed_stage: bool
    removed_marker: bool
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
    for key in (
        "DOCKER_CONTEXT",
        "DOCKER_CONFIG",
        "DOCKER_TLS",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    ):
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


def _checked_root_entries(allowed: frozenset[str]) -> None:
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
    if entries - allowed:
        raise CleanupError("private Boca directory contains uncertain state")


def _checked_root() -> None:
    _checked_root_entries(frozenset({"compose.yaml"}))


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


def _checked_beta_stage(compose_sha: str) -> bool:
    """Prove a new-only BETA staged file; never follow or discard a symlink."""
    _checked_root_entries(frozenset({"compose.beta.yaml"}))
    try:
        metadata = BETA_COMPOSE.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise CleanupError("BETA staged Compose metadata is unavailable") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 10001
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or metadata.st_size > 32_768
    ):
        raise CleanupError("BETA staged Compose identity is unsafe")
    try:
        actual = hashlib.sha256(BETA_COMPOSE.read_bytes()).hexdigest()
    except OSError as exc:
        raise CleanupError("BETA staged Compose content is unavailable") from exc
    if actual != compose_sha:
        raise CleanupError("BETA staged Compose differs from the reviewed candidate")
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


def _beta_container_id(image: str, source_sha: str) -> str | None:
    """Reject other or ambiguous containers even on the dedicated daemon."""
    all_ids = set(_run("ps", "-a", "-q", "--no-trunc").splitlines())
    labeled = set(
        _run(
            "ps",
            "-a",
            "-q",
            "--no-trunc",
            "--filter",
            "label=com.docker.compose.project=boca-socios",
        ).splitlines()
    )
    named = set(
        _run("ps", "-a", "-q", "--no-trunc", "--filter", "name=^/boca-socios-").splitlines()
    )
    if all_ids != labeled or labeled != named or len(labeled) > 1:
        raise CleanupError("BETA container inventory is uncertain")
    if not labeled:
        return None
    container = next(iter(labeled))
    if not re.fullmatch(r"[0-9a-f]{64}", container):
        raise CleanupError("BETA container ID is uncertain")
    try:
        record = json.loads(_run("container", "inspect", "--format", "{{json .}}", container))
    except (TypeError, json.JSONDecodeError) as exc:
        raise CleanupError("BETA container metadata is invalid") from exc
    if not isinstance(record, dict):
        raise CleanupError("BETA container metadata is invalid")
    config = record.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    host = record.get("HostConfig")
    state = record.get("State")
    mounts = record.get("Mounts")
    expected_mounts = {
        ("boca-socios_boca_data", "/data", True),
        ("boca-socios_boca_key", "/run/secrets", False),
        ("boca-socios_boca_owner", "/run/owner", False),
    }
    if (
        record.get("Id") != container
        or record.get("Name") != BETA_CONTROLLER
        or not isinstance(config, dict)
        or config.get("Image") != image
        or config.get("User") != "10001:10001"
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != "boca-socios"
        or labels.get("com.docker.compose.service") != "controller"
        or labels.get("org.opencontainers.image.revision") != source_sha
        or not isinstance(host, dict)
        or host.get("NetworkMode") != BETA_NETWORK
        or not isinstance(state, dict)
        or type(state.get("Running")) is not bool
        or state.get("Restarting") is not False
        or not isinstance(mounts, list)
        or len(mounts) != 3
        or any(
            not isinstance(mount, dict)
            or mount.get("Type") != "volume"
            or type(mount.get("RW")) is not bool
            for mount in mounts
        )
        or {(mount.get("Name"), mount.get("Destination"), mount.get("RW")) for mount in mounts}
        != expected_mounts
    ):
        raise CleanupError("BETA controller identity or persistent mounts are uncertain")
    return container


def _beta_volumes() -> frozenset[str]:
    names = frozenset(
        _run("volume", "ls", "--format", "{{.Name}}", "--filter", "name=^boca-socios_").splitlines()
    )
    if "boca-socios_boca_owner" not in names or not names.issubset(BETA_VOLUMES):
        raise CleanupError("BETA persistent volume inventory is uncertain")
    return names


def _beta_network(container: str | None) -> bool:
    names = set(
        _run(
            "network", "ls", "--format", "{{.Name}}", "--filter", "name=^boca-socios_"
        ).splitlines()
    )
    if not names:
        return False
    if names != {BETA_NETWORK}:
        raise CleanupError("BETA network inventory is uncertain")
    try:
        record = json.loads(_run("network", "inspect", "--format", "{{json .}}", BETA_NETWORK))
    except (TypeError, json.JSONDecodeError) as exc:
        raise CleanupError("BETA network metadata is invalid") from exc
    if not isinstance(record, dict):
        raise CleanupError("BETA network metadata is invalid")
    labels = record.get("Labels")
    peers = record.get("Containers")
    if (
        record.get("Name") != BETA_NETWORK
        or record.get("Driver") != "bridge"
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != "boca-socios"
        or labels.get("com.docker.compose.network") != "boca_private"
        or not isinstance(peers, dict)
        or set(peers) - ({container} if container else set())
    ):
        raise CleanupError("BETA network has unproven identity or attachments")
    return True


def _beta_image_size(image: str, source_sha: str) -> tuple[bool, int]:
    try:
        record = json.loads(_run("image", "inspect", "--format", "{{json .}}", image))
    except ImageAbsent:
        return False, 0
    except (TypeError, json.JSONDecodeError) as exc:
        raise CleanupError("BETA image metadata is invalid") from exc
    return True, validate_image(record, image, source_sha)


def clean_failed_beta_install(image: str, source_sha: str, compose_sha: str) -> BetaCleanupResult:
    """Clean only the exact aborted BETA attempt; never touch persistent volumes."""
    _check_identity()
    _validate_coordinates(image, source_sha, compose_sha)
    _check_rootless_boundary()
    staged = _checked_beta_stage(compose_sha)
    container = _beta_container_id(image, source_sha)
    before_volumes = _beta_volumes()
    network = _beta_network(container)
    has_image, image_size = _beta_image_size(image, source_sha)
    before = _capacity()
    mutation_attempted = False
    try:
        if container is not None:
            # A failed prior rollback is not authority to delete an unknown
            # process. This identity was just checked against the exact digest,
            # SHA, Compose service and all three persistent mount destinations.
            record = json.loads(_run("container", "inspect", "--format", "{{json .}}", container))
            if not isinstance(record, dict) or not isinstance(record.get("State"), dict):
                raise CleanupError("BETA controller state is unavailable")
            if record["State"].get("Running") is True:
                mutation_attempted = True
                _run("container", "stop", "--time", "30", container)
            confirmed = _beta_container_id(image, source_sha)
            if confirmed != container:
                raise CleanupError("BETA container changed before removal")
            state = json.loads(_run("container", "inspect", "--format", "{{json .}}", container))
            if (
                not isinstance(state, dict)
                or not isinstance(state.get("State"), dict)
                or state["State"].get("Running") is not False
                or state["State"].get("Restarting") is not False
            ):
                raise CleanupError("BETA controller did not stop safely")
            mutation_attempted = True
            _run("container", "rm", container)  # No --volumes or --force.
            if _beta_container_id(image, source_sha) is not None:
                raise CleanupError("BETA container remained after removal")
        if network:
            if not _beta_network(None):
                raise CleanupError("BETA network changed before removal")
            mutation_attempted = True
            _run("network", "rm", BETA_NETWORK)
            if _beta_network(None):
                raise CleanupError("BETA network remained after removal")
        if has_image:
            if _run("ps", "-a", "-q", "--filter", f"ancestor={image}"):
                raise CleanupError("BETA image is still referenced by a container")
            if not _beta_image_size(image, source_sha)[0]:
                raise CleanupError("BETA image changed before removal")
            mutation_attempted = True
            _run("image", "rm", "--no-prune", image)
            if _beta_image_size(image, source_sha)[0]:
                raise CleanupError("BETA image remained after removal")
        if staged:
            if not _checked_beta_stage(compose_sha):
                raise CleanupError("BETA staged file changed before removal")
            mutation_attempted = True
            BETA_COMPOSE.unlink()
            if _checked_beta_stage(compose_sha):
                raise CleanupError("BETA staged file remained after removal")
        after_volumes = _beta_volumes()
        after = _capacity()
        if (
            after_volumes != before_volumes
            or before.docker_root != after.docker_root
            or before.stage_device != after.stage_device
            or before.docker_device != after.docker_device
        ):
            raise CleanupError("BETA persistent state or storage topology changed")
    except (CleanupError, OSError, TypeError, ValueError, KeyError) as exc:
        if mutation_attempted:
            raise CleanupIndeterminate("bounded BETA cleanup outcome is unverified") from exc
        raise CleanupError("BETA cleanup failed before any deletion") from exc
    cleaned = bool(container or network or has_image or staged)
    result = BetaCleanupResult(
        removed_image=has_image,
        removed_stage=staged,
        retained_state=bool(before_volumes),
        before=before,
        after=after,
        image_size_bytes=image_size,
        removed_container=container is not None,
        removed_network=network,
    )
    print(
        "BOCA_BETA_CLEANUP"
        f" state={'CLEANED' if cleaned else 'ALREADY_CLEAN'}"
        f" container={'removed' if container else 'absent'}"
        f" network={'removed' if network else 'absent'}"
        f" image={'removed' if has_image else 'absent'}"
        f" stage={'removed' if staged else 'absent'}"
        " volumes=preserved"
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


def _checked_enroll_marker(
    image: str, source_sha: str, compose_sha: str
) -> dict[str, object] | None:
    """A private, exact creation-before-pull record authorizes disposable deletion."""
    _checked_root_entries(frozenset({ENROLL_MARKER.name}))
    try:
        metadata = ENROLL_MARKER.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CleanupError("owner enrollment attempt metadata unavailable") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 10001
        or metadata.st_gid != 10001
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) not in (0o400, 0o600)
        or not 0 < metadata.st_size <= 1024
    ):
        raise CleanupError("owner enrollment attempt provenance unsafe")
    try:
        raw = ENROLL_MARKER.read_bytes()
        value = json.loads(raw)
    except (OSError, TypeError, ValueError, UnicodeError) as exc:
        raise CleanupError("owner enrollment attempt provenance invalid") from exc
    if (
        not isinstance(value, dict)
        or set(value)
        != {"image", "source_sha", "compose_sha", "capability_sha256", "image_preexisting"}
        or value.get("image") != image
        or value.get("source_sha") != source_sha
        or value.get("compose_sha") != compose_sha
        or not isinstance(value.get("capability_sha256"), str)
        or DIGEST_PATTERN.fullmatch(value["capability_sha256"]) is None
        or type(value.get("image_preexisting")) is not bool
        or raw != json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")
    ):
        raise CleanupError("owner enrollment attempt provenance invalid")
    return value


def _checked_enroll_staging_volume() -> None:
    """Only Docker's bounded named staging volume is disposable.

    Rootless host UID and container UID use different user-namespace mappings;
    host bind paths must not be substituted for this named volume.
    """
    try:
        record = json.loads(_run("volume", "inspect", "--format", "{{json .}}", ENROLL_VOLUME))
        root = _checked_docker_storage_dir()
        expected = root / "volumes" / ENROLL_VOLUME / "_data"
    except (CleanupError, TypeError, ValueError, OSError) as exc:
        raise CleanupError("owner enrollment staging volume metadata invalid") from exc
    if not isinstance(record, dict):
        raise CleanupError("owner enrollment staging volume metadata invalid")
    labels = record.get("Labels")
    if (
        record.get("Name") != ENROLL_VOLUME
        or record.get("Driver") != "local"
        or record.get("Scope") != "local"
        or record.get("Options") not in (None, {})
        or record.get("Mountpoint") != str(expected)
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != "boca-socios"
        or labels.get("com.docker.compose.volume") != "owner_enroll_staging"
    ):
        raise CleanupError("owner enrollment staging volume identity unsafe")
    try:
        if root.resolve(strict=True) != root or expected.resolve(strict=True) != expected:
            raise CleanupError("owner enrollment staging volume mountpoint redirected")
    except (OSError, RuntimeError) as exc:
        raise CleanupError("owner enrollment staging volume mountpoint unavailable") from exc


def _enroll_container_id(
    image: str, source_sha: str, marker: dict[str, object] | None
) -> str | None:
    """Inventory the ENTIRE dedicated daemon before touching a single container."""
    all_ids = set(_run("ps", "-a", "-q", "--no-trunc").splitlines())
    labeled = set(
        _run(
            "ps",
            "-a",
            "-q",
            "--no-trunc",
            "--filter",
            "label=com.docker.compose.project=boca-socios",
        ).splitlines()
    )
    named = set(
        _run("ps", "-a", "-q", "--no-trunc", "--filter", f"name=^/{ENROLL_CONTAINER}$").splitlines()
    )
    if all_ids != labeled or labeled != named or len(all_ids) > 1:
        raise CleanupError("owner enrollment daemon container inventory uncertain")
    if not all_ids:
        return None
    if marker is None:
        raise CleanupError("owner enrollment container lacks original attempt marker")
    container_id = next(iter(all_ids))
    if re.fullmatch(r"[0-9a-f]{64}", container_id) is None:
        raise CleanupError("owner enrollment container ID invalid")
    try:
        record = json.loads(_run("container", "inspect", "--format", "{{json .}}", container_id))
    except (ValueError, TypeError) as exc:
        raise CleanupError("owner enrollment container metadata invalid") from exc
    if not isinstance(record, dict):
        raise CleanupError("owner enrollment container metadata invalid")
    config = record.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    command = config.get("Cmd") if isinstance(config, dict) else None
    host = record.get("HostConfig")
    state = record.get("State")
    mounts = record.get("Mounts")
    net_state = record.get("NetworkSettings")
    restart = host.get("RestartPolicy") if isinstance(host, dict) else None
    expected_binding = {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
    if (
        record.get("Id") != container_id
        or record.get("Name") != "/" + ENROLL_CONTAINER
        or not isinstance(config, dict)
        or config.get("Image") != image
        or config.get("User") != "10001:10001"
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != "boca-socios"
        or labels.get("com.docker.compose.service") != "owner-enroll"
        or labels.get("org.opencontainers.image.revision") != source_sha
        or not isinstance(command, list)
        or len(command) != 7
        or command[:3] != ["python", "-m", "boca_socios.owner_enrollment"]
        or not isinstance(command[3], str)
        or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", command[3]) is None
        or command[4] != marker["capability_sha256"]
        or not isinstance(command[5], str)
        or re.fullmatch(r"[A-Za-z0-9_-]{43}", command[5]) is None
        or not isinstance(command[6], str)
        or DIGEST_PATTERN.fullmatch(command[6]) is None
        or not isinstance(host, dict)
        or host.get("NetworkMode") != ENROLL_NETWORK
        or host.get("PortBindings") != expected_binding
        or host.get("ReadonlyRootfs") is not True
        or host.get("Privileged") is not False
        or host.get("CapDrop") != ["ALL"]
        or host.get("CapAdd") not in (None, [])
        or not isinstance(restart, dict)
        or restart.get("Name") != "no"
        or type(host.get("Memory")) is not int
        or not 0 < host["Memory"] <= 256 * 1024**2
        or type(host.get("NanoCpus")) is not int
        or not 0 < host["NanoCpus"] <= 500_000_000
        or type(host.get("PidsLimit")) is not int
        or not 0 < host["PidsLimit"] <= 64
        or not isinstance(mounts, list)
        or len(mounts) != 1
        or not isinstance(mounts[0], dict)
        or mounts[0].get("Type") != "volume"
        or mounts[0].get("Name") != ENROLL_VOLUME
        or mounts[0].get("Destination") != "/run/enrollment"
        or mounts[0].get("RW") is not True
        or not isinstance(state, dict)
        or type(state.get("Running")) is not bool
        or state.get("Restarting") is not False
        or not isinstance(net_state, dict)
        or (
            net_state.get("Ports") != expected_binding
            and not (state.get("Running") is False and net_state.get("Ports") in ({}, None))
        )
        or not isinstance(net_state.get("Networks"), dict)
        or set(net_state["Networks"]) != {ENROLL_NETWORK}
    ):
        raise CleanupError("owner enrollment container identity or isolation uncertain")
    return container_id


def _enroll_network(container_id: str | None, marker: dict[str, object] | None) -> bool:
    names = set(
        _run(
            "network", "ls", "--format", "{{.Name}}", "--filter", "name=^boca-socios_"
        ).splitlines()
    )
    if not names:
        return False
    if names != {ENROLL_NETWORK} or marker is None:
        raise CleanupError("owner enrollment network namespace uncertain")
    try:
        record = json.loads(_run("network", "inspect", "--format", "{{json .}}", ENROLL_NETWORK))
    except (TypeError, ValueError) as exc:
        raise CleanupError("owner enrollment network metadata invalid") from exc
    if not isinstance(record, dict):
        raise CleanupError("owner enrollment network metadata invalid")
    labels = record.get("Labels")
    peers = record.get("Containers")
    if (
        record.get("Name") != ENROLL_NETWORK
        or re.fullmatch(r"[0-9a-f]{64}", str(record.get("Id"))) is None
        or record.get("Driver") != "bridge"
        or record.get("Internal") is not True
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != "boca-socios"
        or labels.get("com.docker.compose.network") != "owner_enroll_private"
        or not isinstance(peers, dict)
        or set(peers) - ({container_id} if container_id else set())
    ):
        raise CleanupError("owner enrollment network identity or peers uncertain")
    return True


def _enroll_volumes(marker: dict[str, object] | None) -> frozenset[str]:
    volumes = frozenset(
        _run("volume", "ls", "--format", "{{.Name}}", "--filter", "name=^boca-socios_").splitlines()
    )
    if not volumes.issubset({OWNER_VOLUME, ENROLL_VOLUME}) or (
        marker is not None and OWNER_VOLUME not in volumes
    ):
        raise CleanupError("owner enrollment persistent volume inventory uncertain")
    if ENROLL_VOLUME in volumes:
        if marker is None:
            raise CleanupError("owner enrollment staging volume lacks attempt marker")
        _checked_enroll_staging_volume()
    return volumes


def _enroll_disposable_image(image: str, source_sha: str) -> tuple[bool, int]:
    try:
        record = json.loads(_run("image", "inspect", "--format", "{{json .}}", image))
    except ImageAbsent:
        return False, 0
    except (TypeError, ValueError) as exc:
        raise CleanupError("owner enrollment disposable image metadata invalid") from exc
    return True, validate_image(record, image, source_sha)


def clean_owner_enroll_artifacts(
    image: str, source_sha: str, compose_sha: str
) -> EnrollmentCleanupResult:
    """Remove only proven temporary Boca owner-enrollment artifacts.

    Called on success AND failure by the same protected Actions job. Persistent
    owner/key/data are NEVER deletion candidates, including partial failures.
    """
    _check_identity()
    _validate_coordinates(image, source_sha, compose_sha)
    _check_rootless_boundary()
    marker = _checked_enroll_marker(image, source_sha, compose_sha)
    container_id = _enroll_container_id(image, source_sha, marker)
    network = _enroll_network(container_id, marker)
    volumes = _enroll_volumes(marker)
    staged = ENROLL_VOLUME in volumes
    if marker is None and (staged or container_id or network):
        raise CleanupError("owner enrollment artifacts lack attempt provenance")
    preexisting_image = marker is None or marker["image_preexisting"] is True
    image_present, image_size = (
        (False, 0) if preexisting_image else _enroll_disposable_image(image, source_sha)
    )
    before = _capacity()
    attempted = False
    try:
        if container_id is not None:
            inspected = json.loads(
                _run("container", "inspect", "--format", "{{json .}}", container_id)
            )
            if not isinstance(inspected, dict) or not isinstance(inspected.get("State"), dict):
                raise CleanupError("owner enrollment container state invalid")
            if inspected["State"].get("Running") is True:
                attempted = True
                _run("container", "stop", "--time", "15", container_id)
            if _enroll_container_id(image, source_sha, marker) != container_id:
                raise CleanupError("owner enrollment container changed before removal")
            inspected = json.loads(
                _run("container", "inspect", "--format", "{{json .}}", container_id)
            )
            if (
                not isinstance(inspected, dict)
                or not isinstance(inspected.get("State"), dict)
                or inspected["State"].get("Running") is not False
                or inspected["State"].get("Restarting") is not False
            ):
                raise CleanupError("owner enrollment service did not stop safely")
            attempted = True
            _run("container", "rm", container_id)
            if _enroll_container_id(image, source_sha, marker) is not None:
                raise CleanupError("owner enrollment container remained after removal")
        if network:
            if not _enroll_network(None, marker):
                raise CleanupError("owner enrollment network changed before removal")
            attempted = True
            _run("network", "rm", ENROLL_NETWORK)
            if _enroll_network(None, marker):
                raise CleanupError("owner enrollment network remained after removal")
        if image_present:
            if _run("ps", "-a", "-q", "--filter", f"ancestor={image}"):
                raise CleanupError("owner enrollment image still referenced")
            if not _enroll_disposable_image(image, source_sha)[0]:
                raise CleanupError("owner enrollment image changed before removal")
            attempted = True
            _run("image", "rm", "--no-prune", image)
            if _enroll_disposable_image(image, source_sha)[0]:
                raise CleanupError("owner enrollment image remained after removal")
        if staged:
            _checked_enroll_staging_volume()
            if _run("ps", "-a", "-q", "--filter", f"volume={ENROLL_VOLUME}"):
                raise CleanupError("owner enrollment staging volume still attached")
            attempted = True
            _run("volume", "rm", ENROLL_VOLUME)
            if ENROLL_VOLUME in _enroll_volumes(marker):
                raise CleanupError("owner enrollment staging volume remained after removal")
        if marker is not None:
            if _checked_enroll_marker(image, source_sha, compose_sha) != marker:
                raise CleanupError("owner enrollment marker changed before removal")
            attempted = True
            ENROLL_MARKER.unlink()
            if _checked_enroll_marker(image, source_sha, compose_sha) is not None:
                raise CleanupError("owner enrollment marker remained after removal")
        after_volumes = _enroll_volumes(None)
        after = _capacity()
        if (
            after_volumes != volumes - {ENROLL_VOLUME}
            or before.docker_root != after.docker_root
            or before.stage_device != after.stage_device
            or before.docker_device != after.docker_device
        ):
            raise CleanupError("owner enrollment persistent state or storage topology changed")
    except (CleanupError, OSError, ValueError, TypeError, KeyError) as exc:
        if attempted:
            raise CleanupIndeterminate("owner enrollment cleanup outcome unverified") from exc
        raise CleanupError("owner enrollment cleanup refused before deletion") from exc
    cleaned = bool(container_id or network or image_present or staged or marker)
    result = EnrollmentCleanupResult(
        removed_container=container_id is not None,
        removed_network=network,
        removed_image=image_present,
        removed_stage=staged,
        removed_marker=marker is not None,
        before=before,
        after=after,
        image_size_bytes=image_size,
    )
    print(
        "BOCA_OWNER_ENROLL_CLEANUP"
        f" state={'CLEANED' if cleaned else 'ALREADY_CLEAN'}"
        f" container={'removed' if container_id else 'absent'}"
        f" network={'removed' if network else 'absent'}"
        f" image={'removed' if image_present else 'retained' if preexisting_image else 'absent'}"
        f" stage={'removed' if staged else 'absent'}"
        f" marker={'removed' if marker else 'absent'}"
        " volumes=preserved"
        f" image_logical_mib={image_size // 1024**2}"
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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--beta", action="store_true", help="exact served-BETA cleanup contract")
    mode.add_argument("--enroll", action="store_true", help="one-use owner enrollment cleanup")
    parser.add_argument("image")
    parser.add_argument("source_sha")
    parser.add_argument("compose_sha")
    args = parser.parse_args(argv)
    try:
        if args.enroll:
            clean_owner_enroll_artifacts(args.image, args.source_sha, args.compose_sha)
        elif args.beta:
            clean_failed_beta_install(args.image, args.source_sha, args.compose_sha)
        else:
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
