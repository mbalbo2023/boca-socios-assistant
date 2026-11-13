"""R253 Boca-only postflight data/key/owner mount attestor (read-only).

This is a callable for R247's ``volume_attestor=`` slot, NOT an installation
command, a synthetic witness, or evidence that physical postflight passed.
Only its caller's currently held protected Boca lease may enter Docker. The
R177 pair attestor checks exact controller/worker mounts and systemd custody;
the dedicated rootless inventory excludes all foreign Docker resources.
The inspected volume fields reproduce the narrow, previously reviewed first-
install data/key/owner validation without importing that mutation-capable CLI.
No database/key/session contents are read, printed or opened here.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_upgrade_postflight as postflight
from boca_socios import host_boca_upgrade_postflight_runtime as runtime

_VOLUME_NAMES = (
    "boca-socios_boca_data",
    "boca-socios_boca_key",
    "boca-socios_boca_owner",
)
_DIR_FLAGS = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class BocaVolumeAttestorNoGo(ValueError):
    """Constant redacted NO_GO; no Docker, filesystem or private paths leak."""


def _fail() -> BocaVolumeAttestorNoGo:
    return BocaVolumeAttestorNoGo("BOCA_POSTFLIGHT_VOLUME_ATTESTOR_V2 NO_GO")


def _root_from_authenticated_inventory(inventory: cleanup.Inventory) -> Path:
    """Bind Docker's exact root path to census's already-attested dev/inode."""
    try:
        raw = json.loads(cleanup._docker("info", "--format", "{{json .DockerRootDir}}"))
        if (
            type(raw) is not str
            or raw != str(runtime._ROOT)
            or not runtime._ROOT.is_absolute()
            or runtime._ROOT == Path("/")
            or ".." in runtime._ROOT.parts
            or inventory.disk.docker_device is None
            or inventory.disk.docker_inode is None
        ):
            raise _fail()
        return runtime._ROOT
    except Exception:
        raise _fail() from None


def _attest_directory_tree(root: Path, name: str, *, device: int, inode: int) -> None:
    """Never follow symlinks, including in ancestor/volume/mountpoint paths.

    Root custody has already been proved by ``cleanup.capture_inventory()``;
    this re-opens every component and pins its dev/inode against that census.
    Only directory metadata is opened, never the files within ``_data``.
    """
    current = -1
    try:
        current = os.open("/", _DIR_FLAGS)
        for part in root.parts[1:]:
            next_fd = os.open(part, _DIR_FLAGS, dir_fd=current)
            os.close(current)
            current = next_fd
        authentic_root = os.fstat(current)
        if not stat.S_ISDIR(authentic_root.st_mode) or (
            authentic_root.st_dev,
            authentic_root.st_ino,
        ) != (device, inode):
            raise _fail()
        for part in ("volumes", name, "_data"):
            next_fd = os.open(part, _DIR_FLAGS, dir_fd=current)
            os.close(current)
            current = next_fd
            detail = os.fstat(current)
            if (
                not stat.S_ISDIR(detail.st_mode)
                or detail.st_dev != device
                or stat.S_IMODE(detail.st_mode) & 0o022
            ):
                raise _fail()
        expected = root / "volumes" / name / "_data"
        named = os.lstat(expected)
        opened = os.fstat(current)
        if (opened.st_dev, opened.st_ino, opened.st_mode) != (
            named.st_dev,
            named.st_ino,
            named.st_mode,
        ) or not stat.S_ISDIR(named.st_mode):
            raise _fail()
    except Exception:
        raise _fail() from None
    finally:
        if current >= 0:
            os.close(current)


def _attest_exact_volume(name: str, root: Path, inventory: cleanup.Inventory) -> None:
    """Check first-install's reviewed local-volume identity, with no mutation."""
    try:
        named = [row for row in inventory.volumes if row.name == name]
        if len(named) != 1:
            raise _fail()
        expected_label = name.removeprefix("boca-socios_")
        listed_labels = dict(named[0].labels)
        if (
            listed_labels.get("com.docker.compose.project") != cleanup.BOCA_PROJECT
            or listed_labels.get("com.docker.compose.volume") != expected_label
        ):
            raise _fail()
        # This exact Docker volume-inspect projection and predicate are already
        # reviewed in host_first_deploy._validate_*_volume. The CLI itself is
        # the read-only dedicated UID10001 Docker wrapper from cleanup.
        observed = json.loads(cleanup._docker("volume", "inspect", "--format", "{{json .}}", name))
        if type(observed) is not dict:
            raise _fail()
        labels = cleanup._docker_labels(observed.get("Labels"))
        if (
            observed.get("Name") != name
            or observed.get("Driver") != "local"
            or observed.get("Scope") != "local"
            or observed.get("Options") not in (None, {})
            or observed.get("Mountpoint") != str(root / "volumes" / name / "_data")
            or labels != named[0].labels
        ):
            raise _fail()
        root_device = inventory.disk.docker_device
        root_inode = inventory.disk.docker_inode
        if root_device is None or root_inode is None:
            raise _fail()
        _attest_directory_tree(root, name, device=root_device, inode=root_inode)
    except Exception:
        raise _fail() from None


@dataclass(frozen=True, slots=True)
class ProductionBocaVolumeAttestor:
    """Purely read-only, SAME-LEASE metadata boundary for three Boca volumes.

    Constructing the callback is inert. Calling it fails closed if any proof
    is missing. It does not attest database file ownership: rootless Docker
    subuid remapping may make the *separate* structural inode reader NO_GO.
    """

    expected: postflight.PostflightExpected
    lease: cleanup.BocaJobLease

    def __call__(self) -> None:
        try:
            cleanup.verify_protected_boca_job_lease(self.lease, self.expected.plan.attempt_id)
            runtime._attest_live_pair(self.expected, self.lease)
            if runtime._read_rootless_identity() != (
                cleanup.EXPECTED_UID,
                cleanup.EXPECTED_GID,
            ):
                raise _fail()
            # Foreign resources abort *before* inspecting any volume. Census
            # also validates DockerRootDir with no-follow ancestry + dev/inode.
            inventory = cleanup.capture_inventory()
            root = _root_from_authenticated_inventory(inventory)
            for name in _VOLUME_NAMES:
                _attest_exact_volume(name, root, inventory)
            runtime._attest_live_pair(self.expected, self.lease)
            cleanup.verify_protected_boca_job_lease(self.lease, self.expected.plan.attempt_id)
        except Exception:
            raise _fail() from None
