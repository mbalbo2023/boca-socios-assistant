"""Host-only Docker attestor for a parked legacy Boca controller.

No stop/start/rename/cleanup, no workflow dispatch and no container execution.
Call only inside a separately protected Boca cutover holding the SAME lease.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from boca_socios.panel.owner_session_upgrade import (
    ControllerStoppedEvidence,
    OwnerSessionUpgradeUnavailable,
)

DATA_VOLUME = "boca-socios_boca_data"
_ROOTLESS_SOCKET = Path("/run/user/10001/docker.sock")
# Shared across ALL protected Boca install/cutover/cleanup phases. A separate
# schema-specific flock would not serialize writers across the outer phases.
_LOCK = Path("/run/user/10001/boca-socios-protected-job.lock")
_UID = 10001
_CONTAINER = re.compile(r"[0-9a-f]{64}\Z")
_ATTEMPT = re.compile(r"[1-9][0-9]{0,19}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_IMAGE = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")


def _docker(*args: str) -> str:
    """Read-only Docker CLI against the exact Boca rootless daemon."""
    if os.path.lexists(_ROOTLESS_SOCKET):
        meta = _ROOTLESS_SOCKET.lstat()
        if not stat.S_ISSOCK(meta.st_mode) or meta.st_uid != _UID:
            raise OwnerSessionUpgradeUnavailable("rootless Boca endpoint unavailable")
    else:
        raise OwnerSessionUpgradeUnavailable("rootless Boca endpoint unavailable")
    env = dict(os.environ)
    for name in (
        "DOCKER_CONTEXT",
        "DOCKER_CONFIG",
        "DOCKER_TLS",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    ):
        env.pop(name, None)
    env["DOCKER_HOST"] = f"unix://{_ROOTLESS_SOCKET}"
    try:
        result = subprocess.run(  # noqa: S603 - static CLI/endpoint, no shell
            ("/usr/bin/docker", "--host", env["DOCKER_HOST"], *args),
            check=True,
            capture_output=True,
            text=True,
            timeout=4,
            env=env,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise OwnerSessionUpgradeUnavailable("Boca rootless inspection unavailable") from None
    if len(result.stdout) > 65536:
        raise OwnerSessionUpgradeUnavailable("Boca rootless inspection unavailable")
    return result.stdout.strip()


def _field(container: str, field: str) -> Any:
    try:
        return json.loads(_docker("inspect", "--format", f"{{{{json .{field}}}}}", container))
    except (TypeError, ValueError):
        raise OwnerSessionUpgradeUnavailable("Boca container inspection invalid") from None


def _volume() -> dict[str, Any]:
    try:
        result = json.loads(_docker("volume", "inspect", "--format", "{{json .}}", DATA_VOLUME))
    except (TypeError, ValueError):
        raise OwnerSessionUpgradeUnavailable("Boca data volume unavailable") from None
    if (
        not isinstance(result, dict)
        or result.get("Name") != DATA_VOLUME
        or result.get("Driver") != "local"
        or not isinstance(result.get("Labels"), dict)
        or result["Labels"].get("com.docker.compose.project") != "boca-socios"
        or result["Labels"].get("com.docker.compose.volume") != "boca_data"
        or type(result.get("Mountpoint")) is not str
        or result.get("Options") not in (None, {})
    ):
        raise OwnerSessionUpgradeUnavailable("Boca data volume identity invalid")
    return result


@dataclass(frozen=True, slots=True)
class DockerStoppedControllerEvidence(ControllerStoppedEvidence):
    """Fresh rootless Docker observations under a Boca-only exclusive host flock.

    This is a host-side capability, not serializable evidence. The protected
    caller must hold the same lock across park, upgrade, and candidate start;
    the lock alone does not prevent noncooperating Docker clients from starting.
    """

    original_id: str
    attempt_id: str
    legacy_sha: str
    legacy_image: str
    borrowed_lease_fd: int | None = None

    def __post_init__(self) -> None:
        if (
            not _CONTAINER.fullmatch(self.original_id)
            or not _ATTEMPT.fullmatch(self.attempt_id)
            or not _SHA.fullmatch(self.legacy_sha)
            or not _IMAGE.fullmatch(self.legacy_image)
            or (
                self.borrowed_lease_fd is not None
                and (type(self.borrowed_lease_fd) is not int or self.borrowed_lease_fd < 0)
            )
        ):
            raise OwnerSessionUpgradeUnavailable("Boca cutover coordinates invalid")

    def host_database_path(self) -> Path:
        """Resolve the Boca data volume via Docker, never via caller JSON."""
        root = Path(_volume()["Mountpoint"])
        if (
            not root.is_absolute()
            or root.parts[-3:] != ("volumes", DATA_VOLUME, "_data")
            or not root.is_dir()
            or any(part.is_symlink() for part in (root, *root.parents))
        ):
            raise OwnerSessionUpgradeUnavailable("Boca data mountpoint unavailable")
        return root / "boca.sqlite3"

    def _observe(self, *, path: Path, device: int, inode: int) -> None:
        try:
            security = json.loads(_docker("info", "--format", "{{json .SecurityOptions}}"))
        except (TypeError, ValueError):
            raise OwnerSessionUpgradeUnavailable("rootless Docker daemon invalid") from None
        if not isinstance(security, list) or "name=rootless" not in security:
            raise OwnerSessionUpgradeUnavailable("rootless Docker daemon invalid")
        if path != self.host_database_path():
            raise OwnerSessionUpgradeUnavailable("Boca database mountpoint changed")
        meta = path.lstat()
        if (
            not stat.S_ISREG(meta.st_mode)
            or (meta.st_dev, meta.st_ino) != (device, inode)
            or meta.st_uid != _UID
            or meta.st_gid != _UID
            or stat.S_IMODE(meta.st_mode) != 0o600
            or meta.st_nlink != 1
        ):
            raise OwnerSessionUpgradeUnavailable("Boca database inode/custody changed")
        listed = _docker(
            "ps",
            "-a",
            "--no-trunc",
            "--format",
            "{{.ID}}",
            "--filter",
            f"volume={DATA_VOLUME}",
        ).splitlines()
        if self.original_id not in listed or any(not _CONTAINER.fullmatch(cid) for cid in listed):
            raise OwnerSessionUpgradeUnavailable("Boca data volume container set invalid")
        controllers = _docker(
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
        if controllers != [self.original_id]:
            raise OwnerSessionUpgradeUnavailable("another Boca controller exists")
        for cid in listed:
            state = _field(cid, "State")
            mounts = _field(cid, "Mounts")
            if (
                not isinstance(state, dict)
                or type(state.get("Running")) is not bool
                or not isinstance(mounts, list)
            ):
                raise OwnerSessionUpgradeUnavailable("Boca volume user state unavailable")
            if (
                cid != self.original_id
                and state.get("Running") is True
                and any(
                    isinstance(mount, dict)
                    and mount.get("Name") == DATA_VOLUME
                    and mount.get("RW") is True
                    for mount in mounts
                )
            ):
                raise OwnerSessionUpgradeUnavailable("another Boca database writer is running")
            if cid != self.original_id:
                continue
            labels = _field(cid, "Config.Labels")
            name = _field(cid, "Name")
            restart = _field(cid, "HostConfig.RestartPolicy")
            image = _field(cid, "Config.Image")
            expected_mounts = {
                (DATA_VOLUME, "/data", True),
                ("boca-socios_boca_key", "/run/secrets", False),
                ("boca-socios_boca_owner", "/run/owner", False),
            }
            actual_mounts = {
                (m.get("Name"), m.get("Destination"), m.get("RW"))
                for m in mounts
                if isinstance(m, dict)
            }
            data_mount = next(
                (m for m in mounts if isinstance(m, dict) and m.get("Name") == DATA_VOLUME),
                None,
            )
            if (
                name != f"/boca-socios-controller-legacy-{self.attempt_id}"
                or not isinstance(labels, dict)
                or labels.get("com.docker.compose.project") != "boca-socios"
                or labels.get("com.docker.compose.service") != "controller"
                or labels.get("com.docker.compose.container-number") != "1"
                or labels.get("org.opencontainers.image.revision") != self.legacy_sha
                or image != self.legacy_image
                or state.get("Running") is not False
                or state.get("Status") != "exited"
                or state.get("Restarting") is not False
                or not isinstance(restart, dict)
                or restart.get("Name") != "no"
                or actual_mounts != expected_mounts
                or len(mounts) != 3
                or not isinstance(data_mount, dict)
                or data_mount.get("Source") != str(path.parent)
                or any(
                    not isinstance(m, dict)
                    or m.get("Type") != "volume"
                    or m.get("Driver") != "local"
                    for m in mounts
                )
            ):
                raise OwnerSessionUpgradeUnavailable("parked Boca controller identity invalid")

    @contextmanager
    def exclusive_stop(self, *, database_path: Path, device: int, inode: int) -> Iterator[None]:
        """Hold canonical Boca flock; borrowed FD shares the owner's OFD.

        For an outer cutover holding the global lease, `os.dup()` preserves the
        same open-file description (OFD). We prove it was *already locked* by
        testing an independent descriptor before reentrant flock, then keep
        the original owner's FD open and untouched across this nested scope.
        """
        if (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (_UID,) * 4:
            raise OwnerSessionUpgradeUnavailable("Boca host identity unavailable")
        runtime = _LOCK.parent.lstat()
        if (
            not stat.S_ISDIR(runtime.st_mode)
            or runtime.st_uid != _UID
            or (stat.S_IMODE(runtime.st_mode) != 0o700)
        ):
            raise OwnerSessionUpgradeUnavailable("Boca runtime lease directory unavailable")
        try:
            borrowed = self.borrowed_lease_fd is not None
            descriptor = (
                os.dup(self.borrowed_lease_fd)
                if self.borrowed_lease_fd is not None
                else os.open(_LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            )
            try:
                meta = os.fstat(descriptor)
                path_meta = _LOCK.lstat()
                if (
                    not stat.S_ISREG(meta.st_mode)
                    or meta.st_uid != _UID
                    or meta.st_gid != _UID
                    or stat.S_IMODE(meta.st_mode) != 0o600
                    or meta.st_nlink != 1
                    or (meta.st_dev, meta.st_ino) != (path_meta.st_dev, path_meta.st_ino)
                    or not stat.S_ISREG(path_meta.st_mode)
                ):
                    raise OwnerSessionUpgradeUnavailable("Boca stop lease identity invalid")
                if borrowed:
                    # An unlocked borrowed FD is NOT proof of an outer lease.
                    # An independent OFD must already be excluded before the
                    # dup-of-borrowed can reassert its pre-existing lock.
                    probe = os.open(_LOCK, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
                    try:
                        if (os.fstat(probe).st_dev, os.fstat(probe).st_ino) != (
                            meta.st_dev,
                            meta.st_ino,
                        ):
                            raise OwnerSessionUpgradeUnavailable("Boca stop lease changed")
                        try:
                            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            pass  # Some holder owns it; next call proves SAME OFD.
                        else:
                            raise OwnerSessionUpgradeUnavailable("borrowed Boca lease not held")
                    finally:
                        os.close(probe)
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._observe(path=database_path, device=device, inode=inode)
                try:
                    yield
                finally:
                    self._observe(path=database_path, device=device, inode=inode)
            finally:
                os.close(descriptor)
        except (OSError, BlockingIOError, ValueError, TypeError):
            raise OwnerSessionUpgradeUnavailable("Boca stop lease unavailable") from None
