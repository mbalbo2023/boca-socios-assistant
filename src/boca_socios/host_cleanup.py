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
ENROLL_NETWORK_OPTIONS = {
    "com.docker.network.bridge.enable_ip_masquerade": "false",
    "com.docker.network.bridge.enable_icc": "false",
    "com.docker.network.bridge.host_binding_ipv4": "127.0.0.1",
}
BROWSER_IPC_MARKER = ROOT / "browser-ipc-attempt.json"
BROWSER_IPC_OVERLAY = ROOT / "compose.beta.browser.yaml"
BROWSER_IPC_SECCOMP = ROOT / "seccomp_profile.json"
BROWSER_IPC_VOLUME = "boca-socios_boca_browser_ipc"
BROWSER_IPC_WORKER = "/boca-socios-browser-worker-1"
BROWSER_IPC_ATTEMPT_LABEL = "boca.socios.browser-ipc-attempt"
BROWSER_IPC_PROBE_PHASE_LABEL = "boca.socios.browser-ipc-phase"
BROWSER_IPC_DIR_INIT_CODE = (
    "import os,stat; p='/run/boca-browser-ipc'; "
    "os.chown(p,10002,10002); os.chmod(p,0o711); "
    "s=os.stat(p,follow_symlinks=False); "
    "assert stat.S_ISDIR(s.st_mode) and s.st_uid==10002 and s.st_gid==10002 "
    "and stat.S_IMODE(s.st_mode)==0o711; print('BOCA_BROWSER_IPC_DIR_PASS')"
)
BROWSER_IPC_SYNTHETIC_CODE = (
    "import asyncio; "
    "from boca_socios.browser.ipc_client import UnixSyntheticBrowser; "
    "from boca_socios.browser.contracts import SimulationOutcome; "
    "outcome=asyncio.run(UnixSyntheticBrowser(timeout_seconds=25)."
    "simulate_general_reservation()); "
    "assert outcome is SimulationOutcome.RESERVED_IN_SIMULATOR; "
    "print('BOCA_BROWSER_IPC_SYNTHETIC_PASS')"
)
BROWSER_IMAGE_PATTERN = re.compile(
    r"ghcr\.io/mbalbo2023/boca-socios-assistant-browser@sha256:[0-9a-f]{64}\Z"
)
ATTEMPT_PATTERN = re.compile(r"[1-9][0-9]{0,19}\Z")
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


@dataclass(frozen=True)
class BrowserIPCCleanupResult:
    """A narrowly inventoried failed browser IPC attempt (never a broad prune)."""

    removed_controller: bool
    removed_worker: bool
    removed_probe: bool
    removed_network: bool
    retained_network: bool
    removed_ipc_volume: bool
    removed_image: bool
    retained_image: bool
    removed_browser_image: bool
    retained_browser_image: bool
    removed_beta_stage: bool
    removed_overlay_stage: bool
    removed_seccomp_stage: bool
    removed_partials: int
    removed_marker: bool
    before: CapacitySnapshot
    after: CapacitySnapshot


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
    # A pinned 32 KiB browser seccomp document is embedded (minified) in
    # Docker's HostConfig.SecurityOpt. An exact container inspect is still
    # bounded, but needs more room than the generic metadata limit.
    inspected_container = (
        args[:4] == ("container", "inspect", "--format", "{{json .}}")
        and len(args) == 5
        and re.fullmatch(r"[0-9a-f]{64}", args[4]) is not None
    )
    if len(result.stdout) > (65_536 if inspected_container else 16_384):
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
    # Preserve recognition of an exited legacy attempt. Only the exact new
    # eight-argument shape has a terminator; a legacy subject may itself be "--".
    if (
        isinstance(command, list)
        and len(command) == 8
        and command[:4] == ["python", "-m", "boca_socios.owner_enrollment", "--"]
    ):
        command = command[:3] + command[4:]
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
        or record.get("Internal") is not False
        or record.get("Options") != ENROLL_NETWORK_OPTIONS
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


def _browser_ipc_coordinates(
    image: str,
    source_sha: str,
    beta_sha: str,
    browser_image: str,
    overlay_sha: str,
    seccomp_sha: str,
    attempt_id: str,
) -> None:
    _validate_coordinates(image, source_sha, beta_sha)
    if (
        BROWSER_IMAGE_PATTERN.fullmatch(browser_image) is None
        or DIGEST_PATTERN.fullmatch(overlay_sha) is None
        or DIGEST_PATTERN.fullmatch(seccomp_sha) is None
        or ATTEMPT_PATTERN.fullmatch(attempt_id) is None
    ):
        raise CleanupError("invalid immutable browser IPC attempt coordinates")


def _browser_ipc_read_private(
    path: Path, metadata: os.stat_result, limit: int, *, expected_links: int = 1
) -> bytes:
    """A pathname swap to FIFO/symlink cannot block or redirect a provenance read."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_uid != metadata.st_uid
                or opened.st_gid != metadata.st_gid
                or opened.st_nlink != expected_links
                or opened.st_dev != metadata.st_dev
                or opened.st_ino != metadata.st_ino
                or opened.st_size != metadata.st_size
                or opened.st_size > limit
            ):
                raise CleanupError("browser IPC provenance file changed while opening")
            raw = os.read(descriptor, limit + 1)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise CleanupError("browser IPC provenance file cannot be opened safely") from exc
    if len(raw) != metadata.st_size:
        raise CleanupError("browser IPC provenance file changed while reading")
    return raw


def _browser_ipc_embedded_seccomp(marker: dict[str, object] | None) -> str:
    """Match Docker CLI's json.Compact of the *reviewed staged profile*.

    `docker --security-opt seccomp=/path` sends its compact JSON to the daemon,
    not the path. Checking for a path in HostConfig would reject every valid
    worker; checking only the `seccomp=` prefix would permit `unconfined`.
    """
    if marker is None or type(marker.get("seccomp_sha")) is not str:
        raise CleanupError("browser IPC worker lacks reviewed staged seccomp profile")
    seccomp_sha = marker["seccomp_sha"]
    if not isinstance(seccomp_sha, str) or not _browser_ipc_stage(BROWSER_IPC_SECCOMP, seccomp_sha):
        raise CleanupError("browser IPC worker lacks reviewed staged seccomp profile")
    metadata = BROWSER_IPC_SECCOMP.lstat()

    def unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, child in pairs:
            if key in value:
                raise CleanupError("browser IPC seccomp has duplicate JSON keys")
            value[key] = child
        return value

    try:
        raw = _browser_ipc_read_private(BROWSER_IPC_SECCOMP, metadata, 32768)
        # The first _browser_ipc_stage check cannot authorize these bytes:
        # another UID10001 process could replace the file between opens.
        if hashlib.sha256(raw).hexdigest() != seccomp_sha:
            raise CleanupError("browser IPC seccomp changed during effective-profile verification")
        text = raw.decode("utf-8")
        if not isinstance(json.loads(text, object_pairs_hook=unique_fields), dict):
            raise CleanupError("browser IPC seccomp profile is not a JSON object")
    except (UnicodeError, ValueError) as exc:
        raise CleanupError("browser IPC staged seccomp profile invalid") from exc
    # Docker CLI parseSecurityOpts uses encoding/json.Compact: it removes
    # whitespace outside strings but preserves original bytes within them.
    compact: list[str] = []
    in_string = escaped = False
    for char in text:
        if in_string:
            compact.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            compact.append(char)
            in_string = True
        elif char not in " \t\n\r":
            compact.append(char)
    return "seccomp=" + "".join(compact)


def _browser_ipc_attempt_marker(
    image: str,
    source_sha: str,
    beta_sha: str,
    browser_image: str,
    overlay_sha: str,
    seccomp_sha: str,
    attempt_id: str,
) -> dict[str, object] | None:
    """Exact creation-before-pull provenance; no duplicate or extra JSON fields."""
    partials = {f".browser-ipc-{kind}-{attempt_id}.part" for kind in ("base", "overlay", "seccomp")}
    _checked_root_entries(
        frozenset(
            {
                BROWSER_IPC_MARKER.name,
                BETA_COMPOSE.name,
                BROWSER_IPC_OVERLAY.name,
                BROWSER_IPC_SECCOMP.name,
            }
            | partials
        )
    )
    try:
        metadata = BROWSER_IPC_MARKER.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CleanupError("browser IPC attempt marker unavailable") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 10001
        or metadata.st_gid != 10001
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or not 0 < metadata.st_size <= 1024
    ):
        raise CleanupError("browser IPC attempt marker identity unsafe")
    expected: dict[str, object] = {
        "version": "browser-ipc-new-only-v2",
        "attempt_id": attempt_id,
        "source_sha": source_sha,
        "controller_digest": image,
        "browser_digest": browser_image,
        "beta_compose_sha": beta_sha,
        "overlay_compose_sha": overlay_sha,
        "seccomp_sha": seccomp_sha,
        "controller_image_absent": False,
        "browser_image_absent": False,
        "bridge_absent": True,
        "ipc_volume_absent": True,
    }
    try:
        raw = _browser_ipc_read_private(BROWSER_IPC_MARKER, metadata, 1024)
        value = json.loads(raw)
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise CleanupError("browser IPC attempt marker invalid") from exc
    if (
        len(raw) != metadata.st_size
        or not isinstance(value, dict)
        or set(value) != set(expected)
        or any(
            type(value[key]) is not str
            for key in (
                "version",
                "attempt_id",
                "source_sha",
                "controller_digest",
                "browser_digest",
                "beta_compose_sha",
                "overlay_compose_sha",
                "seccomp_sha",
            )
        )
        or any(
            value[key] != expected[key]
            for key in expected
            if key not in {"controller_image_absent", "browser_image_absent"}
        )
        or any(
            type(value[key]) is not bool
            for key in (
                "controller_image_absent",
                "browser_image_absent",
                "bridge_absent",
                "ipc_volume_absent",
            )
        )
        or raw != json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")
    ):
        raise CleanupError("browser IPC attempt marker changed or is not new-only")
    return value


def _browser_ipc_stage(
    path: Path,
    sha: str | None,
    *,
    partial: bool = False,
    pair: tuple[Path, str] | None = None,
) -> bool:
    """Admit only one inode, or the exact reviewed final+.part two-link pair.

    The staging helper publishes a final name with link(2), then removes its
    original .part name. A crash between those two calls has exactly two links
    to *one* regular UID10001 inode. Other hardlinks are never disposable.
    """
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise CleanupError("browser IPC staged file unavailable") from exc
    links = metadata.st_nlink
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 10001
        or metadata.st_gid != 10001
        or links not in (1, 2)
        or (
            stat.S_IMODE(metadata.st_mode) != 0o600
            if partial
            else stat.S_IMODE(metadata.st_mode) & 0o022 != 0
        )
        or metadata.st_size > 32768
    ):
        raise CleanupError("browser IPC staged file identity unsafe")
    if links == 2:
        if pair is None or path.parent != ROOT or pair[0].parent != ROOT or pair[0] == path:
            raise CleanupError("browser IPC staged file has unproven hardlink")
        sibling, paired_sha = pair
        try:
            counterpart = sibling.lstat()
        except OSError as exc:
            raise CleanupError("browser IPC staged hardlink counterpart unavailable") from exc
        if (
            not stat.S_ISREG(counterpart.st_mode)
            or counterpart.st_uid != 10001
            or counterpart.st_gid != 10001
            or counterpart.st_nlink != 2
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or stat.S_IMODE(counterpart.st_mode) != 0o600
            or counterpart.st_dev != metadata.st_dev
            or counterpart.st_ino != metadata.st_ino
            or counterpart.st_size != metadata.st_size
            or DIGEST_PATTERN.fullmatch(paired_sha) is None
            or (sha is not None and sha != paired_sha)
        ):
            raise CleanupError("browser IPC staged hardlink pair is not exact")
        raw = _browser_ipc_read_private(path, metadata, 32768, expected_links=2)
        if hashlib.sha256(raw).hexdigest() != paired_sha:
            raise CleanupError("browser IPC staged hardlink bytes differ from reviewed source")
        return True
    if sha is not None:
        raw = _browser_ipc_read_private(path, metadata, 32768)
        if len(raw) != metadata.st_size or hashlib.sha256(raw).hexdigest() != sha:
            raise CleanupError("browser IPC staged file differs from reviewed source")
    return True


def _browser_ipc_stages(
    marker: dict[str, object] | None,
    beta_sha: str,
    overlay_sha: str,
    seccomp_sha: str,
    attempt_id: str,
) -> tuple[dict[Path, bool], dict[Path, bool]]:
    slots = (
        ("base", BETA_COMPOSE, beta_sha),
        ("overlay", BROWSER_IPC_OVERLAY, overlay_sha),
        ("seccomp", BROWSER_IPC_SECCOMP, seccomp_sha),
    )
    actual_finals: dict[Path, bool] = {}
    actual_partials: dict[Path, bool] = {}
    for kind, final, sha in slots:
        partial_path = ROOT / f".browser-ipc-{kind}-{attempt_id}.part"
        actual_finals[final] = _browser_ipc_stage(final, sha, pair=(partial_path, sha))
        actual_partials[partial_path] = _browser_ipc_stage(
            partial_path, None, partial=True, pair=(final, sha)
        )
    if marker is None and (any(actual_finals.values()) or any(actual_partials.values())):
        raise CleanupError("browser IPC staged files lack attempt provenance")
    return actual_finals, actual_partials


def _browser_ipc_unlink_stage(
    path: Path,
    sha: str | None,
    *,
    partial: bool = False,
    pair: tuple[Path, str] | None = None,
) -> None:
    """Delete one reviewed Boca basename through a pinned private directory FD.

    A two-link pair must still consist of the exact final+.part names with
    matching SHA. Revalidate both inode and directory immediately before and
    after unlinkat; a changed pathname or a third hardlink is never accepted.
    """
    if path.parent != ROOT or not _browser_ipc_stage(path, sha, partial=partial, pair=pair):
        raise CleanupError("browser IPC stage changed before unlink")
    metadata = path.lstat()
    root_meta = ROOT.lstat()
    directory = -1
    opened_file = -1
    try:
        directory = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        pinned_root = os.fstat(directory)
        if (
            not stat.S_ISDIR(pinned_root.st_mode)
            or pinned_root.st_uid != 10001
            or pinned_root.st_gid != 10001
            or stat.S_IMODE(pinned_root.st_mode) != 0o700
            or pinned_root.st_dev != root_meta.st_dev
            or pinned_root.st_ino != root_meta.st_ino
        ):
            raise CleanupError("browser IPC cleanup directory was replaced")
        opened_file = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=directory,
        )
        opened_meta = os.fstat(opened_file)
        if (
            not stat.S_ISREG(opened_meta.st_mode)
            or opened_meta.st_uid != 10001
            or opened_meta.st_gid != 10001
            or opened_meta.st_dev != metadata.st_dev
            or opened_meta.st_ino != metadata.st_ino
            or opened_meta.st_nlink != metadata.st_nlink
            or opened_meta.st_size != metadata.st_size
            or stat.S_IMODE(opened_meta.st_mode) != stat.S_IMODE(metadata.st_mode)
        ):
            raise CleanupError("browser IPC staged inode changed before unlink")
        current = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        if (
            current.st_dev != opened_meta.st_dev
            or current.st_ino != opened_meta.st_ino
            or current.st_nlink != opened_meta.st_nlink
            or current.st_uid != 10001
            or current.st_gid != 10001
        ):
            raise CleanupError("browser IPC staged name changed before unlink")
        expected_sha = (
            sha
            if sha is not None
            else pair[1]
            if pair is not None and opened_meta.st_nlink == 2
            else None
        )
        if expected_sha is not None:
            if hashlib.sha256(os.read(opened_file, 32769)).hexdigest() != expected_sha:
                raise CleanupError("browser IPC stage content changed before unlink")
        if opened_meta.st_nlink == 2:
            if pair is None:
                raise CleanupError("browser IPC unpaired staged hardlink")
            sibling, _ = pair
            if sibling.parent != ROOT:
                raise CleanupError("browser IPC staged hardlink leaves private directory")
            sibling_meta = os.stat(sibling.name, dir_fd=directory, follow_symlinks=False)
            if (
                not stat.S_ISREG(sibling_meta.st_mode)
                or sibling_meta.st_dev != opened_meta.st_dev
                or sibling_meta.st_ino != opened_meta.st_ino
                or sibling_meta.st_nlink != 2
                or sibling_meta.st_uid != 10001
                or sibling_meta.st_gid != 10001
                or stat.S_IMODE(sibling_meta.st_mode) != 0o600
            ):
                raise CleanupError("browser IPC paired name changed before unlink")
        os.unlink(path.name, dir_fd=directory)
        try:
            os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise CleanupError("browser IPC staged basename remained after unlink")
        if opened_meta.st_nlink == 2 and pair is not None:
            remaining, expected_sha = pair
            if not _browser_ipc_stage(remaining, expected_sha):
                raise CleanupError("browser IPC reviewed counterpart missing after unlink")
        root_after = ROOT.lstat()
        if root_after.st_dev != pinned_root.st_dev or root_after.st_ino != pinned_root.st_ino:
            raise CleanupError("browser IPC cleanup directory moved during unlink")
    except OSError as exc:
        raise CleanupError("browser IPC pinned staging unlink failed") from exc
    finally:
        if opened_file >= 0:
            os.close(opened_file)
        if directory >= 0:
            os.close(directory)


@dataclass(frozen=True)
class _BrowserIPCProbeSpec:
    image_is_browser: bool
    user: str
    command: tuple[str, ...]
    mounts: frozenset[tuple[str, str, bool]]
    capabilities: tuple[str, ...]
    pids: int = 16
    memory: int = 64 * 1024**2
    nano_cpus: int = 250_000_000


def _browser_ipc_probe_spec(phase: str) -> _BrowserIPCProbeSpec | None:
    """The seven reviewed, sequential one-shot phases; never arbitrary run."""
    ipc_rw = frozenset({(BROWSER_IPC_VOLUME, "/run/boca-browser-ipc", True)})
    ipc_ro = frozenset({(BROWSER_IPC_VOLUME, "/run/boca-browser-ipc", False)})
    key_rw = frozenset({("boca-socios_boca_key", "/run/secrets", True)})
    key_ro = frozenset({("boca-socios_boca_key", "/run/secrets", False)})
    owner_ro = frozenset({("boca-socios_boca_owner", "/run/owner", False)})
    data_rw = frozenset({("boca-socios_boca_data", "/data", True)})
    specs = {
        "ipc-dir-init": _BrowserIPCProbeSpec(
            True,
            "0:0",
            ("python", "-c", BROWSER_IPC_DIR_INIT_CODE),
            ipc_rw,
            ("CHOWN", "FOWNER"),
        ),
        "synthetic-ipc": _BrowserIPCProbeSpec(
            False,
            "10001:10001",
            ("python", "-c", BROWSER_IPC_SYNTHETIC_CODE),
            ipc_ro,
            (),
        ),
        "key-init": _BrowserIPCProbeSpec(
            False,
            "0:0",
            ("python", "-m", "boca_socios.security.key_custody", "init"),
            key_rw,
            ("CHOWN",),
        ),
        "key-verify": _BrowserIPCProbeSpec(
            False,
            "10001:10001",
            ("python", "-m", "boca_socios.security.key_custody", "verify"),
            key_ro,
            (),
        ),
        "owner-check": _BrowserIPCProbeSpec(
            False,
            "10001:10001",
            ("python", "-m", "boca_socios.runtime", "check-beta-owner"),
            owner_ro,
            (),
        ),
        "config-check": _BrowserIPCProbeSpec(
            False,
            "10001:10001",
            ("python", "-m", "boca_socios.runtime", "check-beta-config"),
            owner_ro | key_ro,
            (),
        ),
        "data-init": _BrowserIPCProbeSpec(
            False,
            "10001:10001",
            ("python", "-m", "boca_socios.runtime", "init-beta"),
            data_rw | key_ro,
            (),
            pids=64,
            memory=256 * 1024**2,
            nano_cpus=500_000_000,
        ),
    }
    return specs.get(phase)


def _browser_ipc_probe_phase(name: object, attempt_id: str) -> str | None:
    if not isinstance(name, str):
        return None
    prefix = "/boca-socios-browser-ipc-probe-"
    suffix = "-" + attempt_id
    if not (name.startswith(prefix) and name.endswith(suffix)):
        return None
    phase = name[len(prefix) : -len(suffix)]
    return phase if _browser_ipc_probe_spec(phase) is not None else None


def _browser_ipc_container_ids(
    image: str,
    source_sha: str,
    browser_image: str,
    attempt_id: str,
    marker: dict[str, object] | None,
) -> dict[str, str]:
    """Entire rootless daemon must contain only 0/1/2 exact Boca attempt units."""
    all_ids = set(_run("ps", "-a", "-q", "--no-trunc").splitlines())
    project = set(
        _run(
            "ps",
            "-a",
            "-q",
            "--no-trunc",
            "--filter",
            "label=com.docker.compose.project=boca-socios",
        ).splitlines()
    )
    attempts = set(
        _run(
            "ps",
            "-a",
            "-q",
            "--no-trunc",
            "--filter",
            f"label={BROWSER_IPC_ATTEMPT_LABEL}={attempt_id}",
        ).splitlines()
    )
    names = set(
        _run("ps", "-a", "-q", "--no-trunc", "--filter", "name=^/boca-socios-").splitlines()
    )
    if (
        all_ids != project
        or all_ids != attempts
        or all_ids != names
        or len(all_ids) > 3
        or any(re.fullmatch(r"[0-9a-f]{64}", item) is None for item in all_ids)
        or (marker is None and all_ids)
    ):
        raise CleanupError("browser IPC rootless daemon container inventory uncertain")
    found: dict[str, str] = {}
    for container_id in sorted(all_ids):
        try:
            record = json.loads(
                _run("container", "inspect", "--format", "{{json .}}", container_id)
            )
        except (TypeError, ValueError) as exc:
            raise CleanupError("browser IPC container inspect invalid") from exc
        if not isinstance(record, dict):
            raise CleanupError("browser IPC container inspect invalid")
        config, host, state = record.get("Config"), record.get("HostConfig"), record.get("State")
        mounts, network = record.get("Mounts"), record.get("NetworkSettings")
        labels = config.get("Labels") if isinstance(config, dict) else None
        if (
            record.get("Id") != container_id
            or not isinstance(config, dict)
            or not isinstance(labels, dict)
            or labels.get("com.docker.compose.project") != "boca-socios"
            or labels.get(BROWSER_IPC_ATTEMPT_LABEL) != attempt_id
            or labels.get("org.opencontainers.image.revision") != source_sha
            or not isinstance(host, dict)
            or host.get("ReadonlyRootfs") is not True
            or host.get("Privileged") is not False
            or not isinstance(host.get("RestartPolicy"), dict)
            or host["RestartPolicy"].get("Name") != "no"
            or not isinstance(state, dict)
            or type(state.get("Running")) is not bool
            or state.get("Restarting") is not False
            or not isinstance(mounts, list)
            or not isinstance(network, dict)
            or not isinstance(network.get("Networks"), dict)
            or any(
                not isinstance(m, dict)
                or m.get("Type") != "volume"
                or type(m.get("RW")) is not bool
                for m in mounts
            )
        ):
            raise CleanupError("browser IPC container identity or isolation uncertain")
        name = record.get("Name")
        ports = network.get("Ports")
        actual_mounts = {(m.get("Name"), m.get("Destination"), m.get("RW")) for m in mounts}
        if name == BETA_CONTROLLER:
            kind = "controller"
            expected_mounts = {
                ("boca-socios_boca_data", "/data", True),
                ("boca-socios_boca_key", "/run/secrets", False),
                ("boca-socios_boca_owner", "/run/owner", False),
                (BROWSER_IPC_VOLUME, "/run/boca-browser-ipc", False),
            }
            expected_port = {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
            if (
                config.get("Image") != image
                or config.get("User") != "10001:10001"
                or config.get("Cmd") != ["python", "-m", "boca_socios.runtime", "serve-beta"]
                or labels.get("com.docker.compose.service") != "controller"
                or host.get("NetworkMode") != BETA_NETWORK
                or host.get("PortBindings") != expected_port
                or host.get("CapDrop") != ["ALL"]
                or host.get("CapAdd") not in (None, [])
                or host.get("SecurityOpt") != ["no-new-privileges:true"]
                or type(host.get("PidsLimit")) is not int
                or not 0 < host["PidsLimit"] <= 64
                or type(host.get("Memory")) is not int
                or not 0 < host["Memory"] <= 256 * 1024**2
                or type(host.get("NanoCpus")) is not int
                or not 0 < host["NanoCpus"] <= 500_000_000
                or set(network["Networks"]) != {BETA_NETWORK}
                or (
                    ports != expected_port
                    and not (state["Running"] is False and ports in ({}, None))
                )
                or actual_mounts != expected_mounts
                or len(mounts) != 4
            ):
                raise CleanupError("browser IPC controller ports or mounts differ")
        elif name == BROWSER_IPC_WORKER:
            kind = "worker"
            expected_seccomp = _browser_ipc_embedded_seccomp(marker)
            if (
                config.get("Image") != browser_image
                or config.get("User") != "10002:10002"
                or config.get("Cmd") != ["python", "-m", "boca_socios.browser.ipc_worker"]
                or labels.get("com.docker.compose.service") != "browser-worker"
                or host.get("NetworkMode") != "none"
                or host.get("IpcMode") != "private"
                or host.get("CgroupnsMode") != "private"
                or host.get("Init") is not True
                or host.get("PidMode") not in (None, "", "private")
                or host.get("Devices") not in (None, [])
                or host.get("PortBindings") not in (None, {})
                or ports not in ({}, None)
                or set(network["Networks"]) != {"none"}
                or actual_mounts != {(BROWSER_IPC_VOLUME, "/run/boca-browser-ipc", True)}
                or len(mounts) != 1
                or host.get("CapDrop") != ["ALL"]
                or host.get("CapAdd") not in (["SYS_CHROOT"], ["CAP_SYS_CHROOT"])
                or type(host.get("PidsLimit")) is not int
                or not 0 < host["PidsLimit"] <= 128
                or type(host.get("Memory")) is not int
                or not 0 < host["Memory"] <= 768 * 1024**2
                or type(host.get("NanoCpus")) is not int
                or not 0 < host["NanoCpus"] <= 1_000_000_000
                or not isinstance(host.get("SecurityOpt"), list)
                or len(host["SecurityOpt"]) != 2
                or "no-new-privileges:true" not in host["SecurityOpt"]
                or expected_seccomp not in host["SecurityOpt"]
            ):
                raise CleanupError("browser IPC worker egress or sandbox differs")
        else:
            phase = _browser_ipc_probe_phase(name, attempt_id)
            spec = _browser_ipc_probe_spec(phase) if phase is not None else None
            if spec is None:
                raise CleanupError("browser IPC one-shot probe name is unreviewed")
            kind = "probe"
            configured_caps = host.get("CapAdd")
            expected_caps = list(spec.capabilities)
            if (
                config.get("Image") != (browser_image if spec.image_is_browser else image)
                or config.get("User") != spec.user
                or config.get("Cmd") != list(spec.command)
                or config.get("Entrypoint") not in (None, [])
                or labels.get("com.docker.compose.service") is not None
                or labels.get(BROWSER_IPC_PROBE_PHASE_LABEL) != phase
                or host.get("NetworkMode") != "none"
                or host.get("PidMode") not in ("", "private")
                or host.get("IpcMode") != "private"
                or host.get("CgroupnsMode") != "private"
                or host.get("UsernsMode") != ""
                or host.get("UTSMode") != ""
                or (host.get("Init") is not None and host.get("Init") is not False)
                or host.get("AutoRemove") is not True
                or host.get("PortBindings") not in (None, {})
                or ports not in (None, {})
                or set(network["Networks"]) != {"none"}
                or host.get("CapDrop") != ["ALL"]
                or (
                    configured_caps not in (None, [])
                    if not expected_caps
                    else configured_caps != expected_caps
                )
                or host.get("SecurityOpt")
                not in (["no-new-privileges"], ["no-new-privileges:true"])
                or host.get("Devices") not in (None, [])
                or host.get("PublishAllPorts") is not False
                or host.get("PidsLimit") != spec.pids
                or host.get("Memory") != spec.memory
                or host.get("NanoCpus") != spec.nano_cpus
                or len(mounts) != len(spec.mounts)
                or actual_mounts != spec.mounts
                or any(m.get("Driver") != "local" for m in mounts)
            ):
                raise CleanupError("browser IPC one-shot probe isolation or phase differs")
            if phase in {"owner-check", "config-check", "data-init"}:
                entries = config.get("Env")
                if not isinstance(entries, list) or any(
                    type(entry) is not str for entry in entries
                ):
                    raise CleanupError("browser IPC probe simulation environment unavailable")
                environment: dict[str, str] = {}
                for entry in entries:
                    key, separator, value = entry.partition("=")
                    if separator != "=" or not key or key in environment:
                        raise CleanupError("browser IPC probe environment is ambiguous")
                    environment[key] = value
                required_env = {
                    "BOCA_ENVIRONMENT": "staging",
                    "BOCA_RUNTIME_MODE": "simulation",
                    "BOCA_ENGINE_MODE": "off",
                }
                if any(environment.get(key) != value for key, value in required_env.items()):
                    raise CleanupError("browser IPC probe lacks simulation-only gates")
        if kind in found:
            raise CleanupError("browser IPC service has multiple containers")
        found[kind] = container_id
    return found


def _browser_ipc_volumes(marker: dict[str, object] | None) -> frozenset[str]:
    names = frozenset(
        _run("volume", "ls", "--format", "{{.Name}}", "--filter", "name=^boca-socios_").splitlines()
    )
    if not names.issubset(BETA_VOLUMES | {BROWSER_IPC_VOLUME}):
        raise CleanupError("browser IPC volume inventory includes unknown state")
    if BROWSER_IPC_VOLUME in names:
        if marker is None or marker["ipc_volume_absent"] is not True:
            raise CleanupError("browser IPC volume lacks new-only provenance")
        try:
            record = json.loads(
                _run("volume", "inspect", "--format", "{{json .}}", BROWSER_IPC_VOLUME)
            )
            docker_root = _checked_docker_storage_dir()
        except (TypeError, ValueError, OSError) as exc:
            raise CleanupError("browser IPC volume metadata invalid") from exc
        mountpoint = docker_root / "volumes" / BROWSER_IPC_VOLUME / "_data"
        labels = record.get("Labels") if isinstance(record, dict) else None
        if (
            not isinstance(record, dict)
            or record.get("Name") != BROWSER_IPC_VOLUME
            or record.get("Driver") != "local"
            or record.get("Scope") != "local"
            or record.get("Options") not in (None, {})
            or record.get("Mountpoint") != str(mountpoint)
            or not isinstance(labels, dict)
            or labels.get("com.docker.compose.project") != "boca-socios"
            or labels.get("com.docker.compose.volume") != "boca_browser_ipc"
            or labels.get(BROWSER_IPC_ATTEMPT_LABEL) != marker["attempt_id"]
        ):
            raise CleanupError("browser IPC new-only volume identity unsafe")
        try:
            if (
                docker_root.resolve(strict=True) != docker_root
                or mountpoint.resolve(strict=True) != mountpoint
            ):
                raise CleanupError("browser IPC volume mountpoint redirected")
        except (OSError, RuntimeError) as exc:
            raise CleanupError("browser IPC volume mountpoint uncertain") from exc
    return names


def _browser_ipc_network(
    controller: str | None,
    marker: dict[str, object] | None,
) -> str | None:
    names = set(
        _run(
            "network", "ls", "--format", "{{.Name}}", "--filter", "name=^boca-socios_"
        ).splitlines()
    )
    if not names:
        return None
    if names != {BETA_NETWORK} or marker is None or marker["bridge_absent"] is not True:
        raise CleanupError("browser IPC bridge network lacks new-only provenance")
    try:
        record = json.loads(_run("network", "inspect", "--format", "{{json .}}", BETA_NETWORK))
    except (TypeError, ValueError) as exc:
        raise CleanupError("browser IPC bridge inspect invalid") from exc
    if not isinstance(record, dict):
        raise CleanupError("browser IPC bridge inspect invalid")
    labels, peers = record.get("Labels"), record.get("Containers")
    if (
        record.get("Name") != BETA_NETWORK
        or re.fullmatch(r"[0-9a-f]{64}", str(record.get("Id"))) is None
        or record.get("Driver") != "bridge"
        or record.get("Internal") is not False
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != "boca-socios"
        or labels.get("com.docker.compose.network") != "boca_private"
        or not isinstance(peers, dict)
        or set(peers) - ({controller} if controller else set())
    ):
        raise CleanupError("browser IPC bridge identity or peers uncertain")
    return str(record["Id"])


def _browser_ipc_image(image: str, source_sha: str) -> tuple[bool, int]:
    try:
        record = json.loads(_run("image", "inspect", "--format", "{{json .}}", image))
    except ImageAbsent:
        return False, 0
    except (TypeError, ValueError) as exc:
        raise CleanupError("browser IPC exact image inspect invalid") from exc
    return True, validate_image(record, image, source_sha)


def _browser_ipc_inventory(
    image: str,
    source_sha: str,
    beta_sha: str,
    browser_image: str,
    overlay_sha: str,
    seccomp_sha: str,
    attempt_id: str,
) -> tuple[
    dict[str, object] | None,
    dict[str, str],
    frozenset[str],
    str | None,
    dict[Path, bool],
    dict[Path, bool],
    tuple[bool, int],
    tuple[bool, int],
]:
    marker = _browser_ipc_attempt_marker(
        image, source_sha, beta_sha, browser_image, overlay_sha, seccomp_sha, attempt_id
    )
    files, partials = _browser_ipc_stages(marker, beta_sha, overlay_sha, seccomp_sha, attempt_id)
    containers = _browser_ipc_container_ids(image, source_sha, browser_image, attempt_id, marker)
    volumes = _browser_ipc_volumes(marker)
    bridge = _browser_ipc_network(containers.get("controller"), marker)
    if containers and (
        BROWSER_IPC_VOLUME not in volumes or ("controller" in containers and not bridge)
    ):
        raise CleanupError("browser IPC service attachments lack proven resources")
    # Both image references must be inspected even if preexisting. No deletion
    # is ever attempted without the creation-before-pull absence bit.
    controller_image = _browser_ipc_image(image, source_sha)
    worker_image = _browser_ipc_image(browser_image, source_sha)
    if marker is None and (containers or bridge or BROWSER_IPC_VOLUME in volumes):
        raise CleanupError("browser IPC attempt artifacts lack marker")
    if marker is not None:
        if "controller" in containers and not controller_image[0]:
            raise CleanupError("browser IPC running controller image unavailable")
        if "worker" in containers and not worker_image[0]:
            raise CleanupError("browser IPC running worker image unavailable")
        if "probe" in containers and (not controller_image[0] or not worker_image[0]):
            raise CleanupError("browser IPC one-shot probe image provenance unavailable")
    return marker, containers, volumes, bridge, files, partials, controller_image, worker_image


def clean_failed_browser_ipc_install(
    image: str,
    source_sha: str,
    beta_sha: str,
    browser_image: str,
    overlay_sha: str,
    seccomp_sha: str,
    attempt_id: str,
) -> BrowserIPCCleanupResult:
    """Rollback only a positively identified, new-only browser IPC attempt.

    The protected workflow must record absence *before* downloading an image or
    creating the bridge/IPC volume. Nothing here is permission to delete owner,
    key, data, previous images, pre-existing networks, or another application.
    Every Docker mutation is individually scoped and immediately verified.
    """
    _check_identity()
    _browser_ipc_coordinates(
        image, source_sha, beta_sha, browser_image, overlay_sha, seccomp_sha, attempt_id
    )
    _check_rootless_boundary()
    (marker, containers, volumes, bridge, files, partials, controller_image, worker_image) = (
        _browser_ipc_inventory(
            image, source_sha, beta_sha, browser_image, overlay_sha, seccomp_sha, attempt_id
        )
    )
    preserved_volumes = volumes - {BROWSER_IPC_VOLUME}
    before = _capacity()
    attempted = False

    # Exact, immutable attempt coordinates are carried through every recheck.
    def inspect_containers() -> dict[str, str]:
        return _browser_ipc_container_ids(image, source_sha, browser_image, attempt_id, marker)

    try:
        for service, stop_seconds in (("probe", "8"), ("worker", "8"), ("controller", "30")):
            container_id = containers.get(service)
            if container_id is None:
                continue
            current_id = inspect_containers().get(service)
            if service == "probe" and current_id is None:
                # docker run --rm may have finished and self-removed this
                # uniquely labeled one-shot between the two inventories.
                continue
            if current_id != container_id:
                raise CleanupError("browser IPC container changed before stop")
            try:
                inspected = json.loads(
                    _run("container", "inspect", "--format", "{{json .}}", container_id)
                )
            except CleanupError:
                if service == "probe" and inspect_containers().get(service) is None:
                    continue
                raise
            if not isinstance(inspected, dict) or not isinstance(inspected.get("State"), dict):
                raise CleanupError("browser IPC container state changed")
            if inspected["State"].get("Running") is True:
                attempted = True
                try:
                    _run("container", "stop", "--time", stop_seconds, container_id)
                except CleanupError:
                    if service == "probe" and inspect_containers().get(service) is None:
                        continue
                    raise
            current_id = inspect_containers().get(service)
            if service == "probe" and current_id is None:
                # --rm disposes the exact helper on successful stop; no
                # separate `docker rm` is possible or appropriate.
                continue
            if current_id != container_id:
                raise CleanupError("browser IPC container identity changed after stop")
            inspected = json.loads(
                _run("container", "inspect", "--format", "{{json .}}", container_id)
            )
            if (
                not isinstance(inspected, dict)
                or not isinstance(inspected.get("State"), dict)
                or inspected["State"].get("Running") is not False
                or inspected["State"].get("Restarting") is not False
            ):
                raise CleanupError("browser IPC container failed to stop safely")
            attempted = True
            try:
                _run("container", "rm", container_id)  # No --force or -v.
            except CleanupError:
                if service == "probe" and inspect_containers().get(service) is None:
                    continue
                raise
            if service in inspect_containers():
                raise CleanupError("browser IPC container remained after removal")

        if bridge:
            if _browser_ipc_network(None, marker) != bridge:
                raise CleanupError("browser IPC bridge ID changed before removal")
            attempted = True
            # Delete by its validated 64-hex ID, not a reusable network name.
            # A replacement Boca-named bridge cannot be targeted by accident.
            _run("network", "rm", bridge)
            if _browser_ipc_network(None, marker) is not None:
                raise CleanupError("browser IPC bridge remained after removal")

        image_status = (
            (image, controller_image, "controller_image_absent"),
            (browser_image, worker_image, "browser_image_absent"),
        )
        for reference, (present, _logical_size), absent_key in image_status:
            if not present or marker is None or marker[absent_key] is not True:
                continue
            if _run("ps", "-a", "-q", "--filter", f"ancestor={reference}"):
                raise CleanupError("browser IPC disposable image still referenced")
            if not _browser_ipc_image(reference, source_sha)[0]:
                raise CleanupError("browser IPC disposable image changed before removal")
            attempted = True
            _run("image", "rm", "--no-prune", reference)
            if _browser_ipc_image(reference, source_sha)[0]:
                raise CleanupError("browser IPC disposable image remained after removal")

        if BROWSER_IPC_VOLUME in volumes:
            if BROWSER_IPC_VOLUME not in _browser_ipc_volumes(marker):
                raise CleanupError("browser IPC volume changed before removal")
            if _run("ps", "-a", "-q", "--filter", f"volume={BROWSER_IPC_VOLUME}"):
                raise CleanupError("browser IPC volume is still attached")
            attempted = True
            _run("volume", "rm", BROWSER_IPC_VOLUME)
            if BROWSER_IPC_VOLUME in _browser_ipc_volumes(marker):
                raise CleanupError("browser IPC volume remained after removal")

        # A partial has no final content hash; exact name, attempt ID, owner,
        # link count, regular type, private mode and size are its only authority.
        pairs = {
            ROOT / f".browser-ipc-base-{attempt_id}.part": (BETA_COMPOSE, beta_sha),
            ROOT / f".browser-ipc-overlay-{attempt_id}.part": (BROWSER_IPC_OVERLAY, overlay_sha),
            ROOT / f".browser-ipc-seccomp-{attempt_id}.part": (BROWSER_IPC_SECCOMP, seccomp_sha),
        }
        for path, existed in sorted(partials.items()):
            if existed:
                paired = pairs[path]
                if not _browser_ipc_stage(path, None, partial=True, pair=paired):
                    raise CleanupError("browser IPC partial changed before removal")
                attempted = True
                _browser_ipc_unlink_stage(path, None, partial=True, pair=paired)
        for path, existed in sorted(files.items()):
            if existed:
                expected_sha = {
                    BETA_COMPOSE: beta_sha,
                    BROWSER_IPC_OVERLAY: overlay_sha,
                    BROWSER_IPC_SECCOMP: seccomp_sha,
                }[path]
                if not _browser_ipc_stage(path, expected_sha):
                    raise CleanupError("browser IPC staged artifact changed before removal")
                attempted = True
                _browser_ipc_unlink_stage(path, expected_sha)

        if marker is not None:
            if (
                _browser_ipc_attempt_marker(
                    image, source_sha, beta_sha, browser_image, overlay_sha, seccomp_sha, attempt_id
                )
                != marker
            ):
                raise CleanupError("browser IPC attempt marker changed before removal")
            attempted = True
            BROWSER_IPC_MARKER.unlink()

        (
            after_marker,
            after_containers,
            after_volumes,
            after_bridge,
            after_files,
            after_partials,
            _,
            _,
        ) = _browser_ipc_inventory(
            image, source_sha, beta_sha, browser_image, overlay_sha, seccomp_sha, attempt_id
        )
        after = _capacity()
        if (
            after_marker is not None
            or after_containers
            or after_volumes != preserved_volumes
            or after_bridge
            or any(after_files.values())
            or any(after_partials.values())
            or before.docker_root != after.docker_root
            or before.stage_device != after.stage_device
            or before.docker_device != after.docker_device
        ):
            raise CleanupError("browser IPC cleanup retained unproven state or topology changed")
    except (CleanupError, OSError, TypeError, ValueError, KeyError) as exc:
        if attempted:
            raise CleanupIndeterminate(
                "browser IPC cleanup outcome indeterminate; no retry"
            ) from exc
        raise CleanupError("browser IPC cleanup refused before deletion") from exc

    was_cleaned = bool(
        containers
        or bridge
        or BROWSER_IPC_VOLUME in volumes
        or (marker and marker["controller_image_absent"] and controller_image[0])
        or (marker and marker["browser_image_absent"] and worker_image[0])
        or any(files.values())
        or any(partials.values())
        or marker
    )
    result = BrowserIPCCleanupResult(
        removed_controller="controller" in containers,
        removed_worker="worker" in containers,
        removed_probe="probe" in containers,
        removed_network=bridge is not None,
        retained_network=False,
        removed_ipc_volume=BROWSER_IPC_VOLUME in volumes,
        removed_image=bool(marker and marker["controller_image_absent"] and controller_image[0]),
        retained_image=bool(
            marker and not marker["controller_image_absent"] and controller_image[0]
        ),
        removed_browser_image=bool(marker and marker["browser_image_absent"] and worker_image[0]),
        retained_browser_image=bool(
            marker and not marker["browser_image_absent"] and worker_image[0]
        ),
        removed_beta_stage=files[BETA_COMPOSE],
        removed_overlay_stage=files[BROWSER_IPC_OVERLAY],
        removed_seccomp_stage=files[BROWSER_IPC_SECCOMP],
        removed_partials=sum(partials.values()),
        removed_marker=marker is not None,
        before=before,
        after=after,
    )

    def tri_state(removed: bool, retained: bool = False) -> str:
        return "removed" if removed else "retained" if retained else "absent"

    print(
        "BOCA_BROWSER_IPC_CLEANUP"
        f" state={'CLEANED' if was_cleaned else 'ALREADY_CLEAN'}"
        f" controller={tri_state(result.removed_controller)}"
        f" worker={tri_state(result.removed_worker)}"
        f" network={tri_state(result.removed_network, result.retained_network)}"
        f" ipc_volume={tri_state(result.removed_ipc_volume)}"
        f" image={tri_state(result.removed_image, result.retained_image)}"
        f" browser_image={tri_state(result.removed_browser_image, result.retained_browser_image)}"
        f" beta_stage={tri_state(result.removed_beta_stage)}"
        f" overlay_stage={tri_state(result.removed_overlay_stage)}"
        " volumes=preserved"
        f" seccomp_stage={tri_state(result.removed_seccomp_stage)}"
        f" partials_removed={result.removed_partials}"
        f" marker={tri_state(result.removed_marker)}"
        f" image_logical_mib={controller_image[1] // 1024**2}"
        f" browser_image_logical_mib={worker_image[1] // 1024**2}"
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
    mode.add_argument("--browser-ipc-v2", action="store_true", help="new-only browser IPC cleanup")
    parser.add_argument("image")
    parser.add_argument("source_sha")
    parser.add_argument("compose_sha")
    parser.add_argument("browser_image", nargs="?")
    parser.add_argument("overlay_sha", nargs="?")
    parser.add_argument("seccomp_sha", nargs="?")
    parser.add_argument("attempt_id", nargs="?")
    args = parser.parse_args(argv)
    try:
        if args.browser_ipc_v2:
            if not all((args.browser_image, args.overlay_sha, args.seccomp_sha, args.attempt_id)):
                raise CleanupError("browser IPC cleanup requires seven exact coordinates")
            clean_failed_browser_ipc_install(
                args.image,
                args.source_sha,
                args.compose_sha,
                args.browser_image,
                args.overlay_sha,
                args.seccomp_sha,
                args.attempt_id,
            )
        elif any((args.browser_image, args.overlay_sha, args.seccomp_sha, args.attempt_id)):
            raise CleanupError("extra coordinates require protected browser IPC mode")
        elif args.enroll:
            clean_owner_enroll_artifacts(args.image, args.source_sha, args.compose_sha)
        elif args.beta:
            clean_failed_beta_install(args.image, args.source_sha, args.compose_sha)
        else:
            clean_failed_install(args.image, args.source_sha, args.compose_sha)
    except CleanupIndeterminate:
        if args.browser_ipc_v2:
            print(
                "BOCA_BROWSER_IPC_CLEANUP_INDETERMINATE: manual Boca-only inventory; "
                "do not retry automatically",
                file=sys.stderr,
            )
        else:
            print("BOCA_CLEANUP_INDETERMINADO: re-inventory Boca before retry", file=sys.stderr)
        return 1
    except (CleanupError, OSError, ValueError) as exc:
        print(f"BOCA_CLEANUP_NO_GO: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
