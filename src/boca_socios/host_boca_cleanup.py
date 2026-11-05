"""Fail-closed, Boca-only post-install cleanup contract (issue #323).

This module is intentionally *not* connected to any live workflow. A future
single protected job must call it on both SUCCESS and FAILURE, use the same
lease as its installer, and publish only the redacted receipt. It accepts an
independent Docker inventory before *each* deletion; no global prune, fuzzy
name lookup or guess about a dangling image can authorize removal.
"""

from __future__ import annotations

import fcntl
import json
import os
import pwd
import re
import stat
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

KIND = Literal["container", "volume", "network", "image"]
OUTCOME = Literal["SUCCESS", "FAILURE"]
BOCA_PROJECT = "boca-socios"
BOCA_IMAGE_PREFIXES = (
    "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:",
    "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:",
    "ghcr.io/mbalbo2023/boca-socios-assistant:",
    "ghcr.io/mbalbo2023/boca-socios-assistant-browser:",
)
BOCA_SOURCE = "https://github.com/mbalbo2023/boca-socios-assistant"
BOCA_PUBLIC_SHA_TAG = re.compile(
    r"ghcr\.io/mbalbo2023/boca-socios-assistant(?:-browser)?:sha-[0-9a-f]{40}\Z"
)
BOCA_PUBLIC_DIGEST = re.compile(
    r"ghcr\.io/mbalbo2023/boca-socios-assistant(?:-browser)?@sha256:[0-9a-f]{64}\Z"
)
ATTEMPT_LABELS = (
    "boca.socios.install-attempt",
    "boca.socios.beta-install-attempt",
    "boca.socios.update-attempt",
    "boca.socios.browser-ipc-attempt",
    "boca.socios.telegram-runtime-attempt",
    "boca.socios.cutover-a-attempt",
)
PERSISTENT_VOLUMES = frozenset(
    {
        "boca-socios_boca_data",
        "boca-socios_boca_key",
        "boca-socios_boca_owner",
        "boca-socios_boca_telegram",
    }
)
HEX_ID = re.compile(r"(?:sha256:)?[0-9a-f]{64}\Z")
ATTEMPT_ID = re.compile(r"[1-9][0-9]{0,19}\Z")
DOCKER_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}\Z")
MAX_OBJECTS = 256
MAX_DELETIONS = 32
RUN_LIMIT = 2_000_000
EXPECTED_UID = 10001
EXPECTED_GID = 10001
DOCKER_SOCKET = f"unix:///run/user/{EXPECTED_UID}/docker.sock"
LEASE_DIR = Path(f"/run/user/{EXPECTED_UID}")
LEASE_FILE = "boca-socios-protected-job.lock"
DISK_ROOT = Path("/srv")


class CleanupError(ValueError):
    """Known residue or unverifiable Docker state prohibits acceptance."""


@dataclass(frozen=True)
class DiskInodes:
    bytes_free: int
    inodes_free: int
    # Optional fields preserve old synthetic fixture/facade construction.
    # A real host inventory MUST fill all six to attest both filesystems.
    docker_bytes_free: int | None = None
    docker_inodes_free: int | None = None
    stage_device: int | None = None
    stage_inode: int | None = None
    docker_device: int | None = None
    docker_inode: int | None = None

    def __post_init__(self) -> None:
        extra = (
            self.docker_bytes_free,
            self.docker_inodes_free,
            self.stage_device,
            self.stage_inode,
            self.docker_device,
            self.docker_inode,
        )
        if (
            self.bytes_free < 0
            or self.inodes_free < 0
            or (any(value is None for value in extra) and any(value is not None for value in extra))
            or any(value is not None and value < 0 for value in extra)
        ):
            raise CleanupError("disk/inode inventory invalid")


def _storage_topology_changed(before: DiskInodes, after: DiskInodes) -> bool:
    """Reject storage swaps across the same lease; capacity may legitimately change."""
    old = (before.stage_device, before.stage_inode, before.docker_device, before.docker_inode)
    new = (after.stage_device, after.stage_inode, after.docker_device, after.docker_inode)
    return old != new or (before.docker_bytes_free is None) != (after.docker_bytes_free is None)


@dataclass(frozen=True)
class Container:
    ident: str
    name: str
    image_id: str
    running: bool
    labels: tuple[tuple[str, str], ...]
    volumes: tuple[str, ...] = ()
    networks: tuple[str, ...] = ()


@dataclass(frozen=True)
class Image:
    ident: str
    references: tuple[str, ...]
    source: str | None
    # A singular historical controller image may lack OCI source (release #41893887078).
    # True is set only by the narrow, exact-digest/revision host attestor below.
    historical_legacy_attested: bool = False


@dataclass(frozen=True)
class LegacyImageProof:
    """Exact, previously running Boca controller image; never an arbitrary tag."""

    ident: str
    reference: str
    revision: str


@dataclass(frozen=True)
class Network:
    name: str
    ident: str
    attached_ids: tuple[str, ...]
    labels: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Volume:
    name: str
    labels: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Inventory:
    containers: tuple[Container, ...]
    images: tuple[Image, ...]
    networks: tuple[Network, ...]
    volumes: tuple[Volume, ...]
    disk: DiskInodes
    global_image_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Target:
    kind: KIND
    ident: str


@dataclass(frozen=True)
class CleanupPlan:
    targets: tuple[Target, ...]
    uncertain: tuple[str, ...]


@dataclass(frozen=True)
class CleanupReceipt:
    outcome: OUTCOME
    attempt_id: str
    status: Literal["ACCEPT", "INDETERMINATE", "NO_GO"]
    before: DiskInodes
    after: DiskInodes
    removed: tuple[Target, ...]
    retained_uncertain: tuple[str, ...]
    known_residue: tuple[Target, ...]

    def redacted_json(self) -> str:
        """Bounded exact-ID host receipt, free of labels, env, secrets or foreign paths.

        The trusted Boca-only inventorier established resource provenance before
        each removal. This projection does NOT infer ownership from an ID alone.
        Missing rootless disk/inode metrics cannot be represented as an ACCEPT.
        """
        if (
            self.outcome not in ("SUCCESS", "FAILURE")
            or type(self.attempt_id) is not str
            or not ATTEMPT_ID.fullmatch(self.attempt_id)
            or self.status not in ("ACCEPT", "NO_GO", "INDETERMINATE")
            or not isinstance(self.before, DiskInodes)
            or not isinstance(self.after, DiskInodes)
            or len(self.removed) > MAX_DELETIONS
            or len(self.known_residue) > MAX_DELETIONS
            or len(self.retained_uncertain) > MAX_OBJECTS
            or (self.status == "ACCEPT" and (self.retained_uncertain or self.known_residue))
        ):
            raise CleanupError("Boca cleanup exact receipt evidence invalid")

        def disk(snapshot: DiskInodes) -> dict[str, int]:
            values = {
                "stage_bytes_free": snapshot.bytes_free,
                "stage_inodes_free": snapshot.inodes_free,
                "docker_bytes_free": snapshot.docker_bytes_free,
                "docker_inodes_free": snapshot.docker_inodes_free,
                "stage_device": snapshot.stage_device,
                "stage_inode": snapshot.stage_inode,
                "docker_device": snapshot.docker_device,
                "docker_inode": snapshot.docker_inode,
            }
            if any(type(value) is not int or value < 0 for value in values.values()):
                raise CleanupError("Boca cleanup physical disk/inodes unproven")
            return {key: value for key, value in values.items() if isinstance(value, int)}

        before = disk(self.before)
        after = disk(self.after)
        if any(
            before[key] != after[key]
            for key in ("stage_device", "stage_inode", "docker_device", "docker_inode")
        ):
            raise CleanupError("Boca cleanup storage identity changed")

        def resources(items: tuple[Target, ...]) -> list[dict[str, str]]:
            seen: set[tuple[str, str]] = set()
            result: list[dict[str, str]] = []
            for item in items:
                if not isinstance(item, Target) or item.kind not in (
                    "container",
                    "image",
                    "network",
                    "volume",
                ):
                    raise CleanupError("Boca cleanup receipt target kind invalid")
                valid = (
                    item.kind != "volume"
                    and type(item.ident) is str
                    and HEX_ID.fullmatch(item.ident) is not None
                    or item.kind == "volume"
                    and type(item.ident) is str
                    and DOCKER_NAME.fullmatch(item.ident) is not None
                    and item.ident.startswith("boca-socios_")
                    and item.ident not in PERSISTENT_VOLUMES
                )
                key = (item.kind, item.ident)
                if not valid or key in seen:
                    raise CleanupError("Boca cleanup receipt resource identity unproven")
                seen.add(key)
                result.append({"kind": item.kind, "id": item.ident})
            return result

        if any(
            type(reason) is not str or re.fullmatch(r"[A-Za-z0-9:_.-]{1,220}", reason) is None
            for reason in self.retained_uncertain
        ):
            raise CleanupError("Boca cleanup receipt uncertainty contains unsafe text")
        body = {
            "version": 1,
            "scope": "boca-postdeploy",
            "outcome": self.outcome,
            "attempt_id": self.attempt_id,
            "status": self.status,
            "before": before,
            "after": after,
            "removed": resources(self.removed),
            "retained_uncertain": list(self.retained_uncertain),
            "known_residue": resources(self.known_residue),
        }
        encoded = json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        )
        if not 0 < len(encoded.encode("ascii")) <= 8192:
            raise CleanupError("Boca cleanup public receipt unbounded")
        return encoded


@dataclass
class BocaJobLease:
    """Opaque in-process handle to an actively held, Boca-only flock."""

    attempt_id: str
    fd: int
    owner_pid: int
    active: bool


def verify_protected_boca_job_lease(lease: BocaJobLease, attempt_id: str) -> None:
    """Prove a *held canonical flock*, not just a plausible fd or boolean.

    The independent open must be blocked while a duplicate of the caller's
    original open-file description remains able to retain the same lock.
    Never release the caller's fd: it protects install through finalizer.
    """
    if (
        not isinstance(lease, BocaJobLease)
        or not lease.active
        or lease.owner_pid != os.getpid()
        or lease.attempt_id != attempt_id
        or not ATTEMPT_ID.fullmatch(attempt_id)
        or os.geteuid() != EXPECTED_UID
        or os.getegid() != EXPECTED_UID
    ):
        raise CleanupError("postdeploy cleanup requires one protected Boca job lease")
    folder: int | None = None
    contender: int | None = None
    borrowed: int | None = None
    try:
        fd_meta = os.fstat(lease.fd)
        folder = os.open(LEASE_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        root = os.fstat(folder)
        if (
            not stat.S_ISDIR(root.st_mode)
            or root.st_uid != EXPECTED_UID
            or root.st_gid != EXPECTED_UID
            or stat.S_IMODE(root.st_mode) != 0o700
        ):
            raise CleanupError("Boca protected job lease parent unsafe")
        contender = os.open(LEASE_FILE, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=folder)
        path_meta = os.fstat(contender)
        if (
            (fd_meta.st_dev, fd_meta.st_ino) != (path_meta.st_dev, path_meta.st_ino)
            or not stat.S_ISREG(fd_meta.st_mode)
            or fd_meta.st_uid != EXPECTED_UID
            or fd_meta.st_gid != EXPECTED_UID
            or fd_meta.st_nlink != 1
            or stat.S_IMODE(fd_meta.st_mode) != 0o600
            or fd_meta.st_size != 0
        ):
            raise CleanupError("Boca protected job lease file identity changed")
        try:
            fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass  # At least one *other* OFD holds the canonical lock.
        else:
            raise CleanupError("Boca job lease appears unlocked")
        borrowed = os.dup(lease.fd)
        try:
            fcntl.flock(borrowed, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CleanupError("Boca job lease is held by a different file description") from exc
    except OSError as exc:
        raise CleanupError("Boca job lease cannot be verified") from exc
    finally:
        if borrowed is not None:
            os.close(borrowed)
        if contender is not None:
            os.close(contender)
        if folder is not None:
            os.close(folder)


@contextmanager
def protected_boca_job_lease(attempt_id: str) -> Iterator[BocaJobLease]:
    """Exclusive job-scoped flock, including first-install before ROOT exists.

    This is an additional cooperative barrier, not proof that unreviewed old
    workflows respect it. The live workflow is not yet wired to this module.
    """
    if (
        not ATTEMPT_ID.fullmatch(attempt_id)
        or os.geteuid() != EXPECTED_UID
        or os.getegid() != EXPECTED_UID
    ):
        raise CleanupError("Boca job lease owner/attempt invalid")
    directory: int | None = None
    handle: int | None = None
    lease: BocaJobLease | None = None
    try:
        directory = os.open(LEASE_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        root = os.fstat(directory)
        if (
            not stat.S_ISDIR(root.st_mode)
            or root.st_uid != EXPECTED_UID
            or root.st_gid != EXPECTED_UID
            or stat.S_IMODE(root.st_mode) != 0o700
        ):
            raise CleanupError("Boca lease owner directory unsafe")
        handle = os.open(
            LEASE_FILE,
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=directory,
        )
        item = os.fstat(handle)
        if (
            not stat.S_ISREG(item.st_mode)
            or item.st_uid != EXPECTED_UID
            or item.st_gid != EXPECTED_UID
            or item.st_nlink != 1
            or stat.S_IMODE(item.st_mode) != 0o600
            or item.st_size != 0
        ):
            raise CleanupError("Boca lease inode or mode unsafe")
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lease = BocaJobLease(attempt_id, handle, os.getpid(), True)
        yield lease
    except (OSError, BlockingIOError) as exc:
        raise CleanupError("Boca protected job lease held or unavailable") from exc
    finally:
        if lease is not None:
            lease.active = False
        if handle is not None:
            os.close(handle)
        if directory is not None:
            os.close(directory)


def _labels(entries: tuple[tuple[str, str], ...]) -> dict[str, str]:
    labels = dict(entries)
    if len(labels) != len(entries) or any(not k or not isinstance(v, str) for k, v in entries):
        raise CleanupError("duplicate or malformed Docker labels")
    return labels


def _attempt_owner(labels: dict[str, str], attempt_id: str) -> bool:
    present = [(key, labels[key]) for key in ATTEMPT_LABELS if key in labels]
    return len(present) == 1 and present[0][1] == attempt_id


def _known_boca_image(image: Image) -> bool:
    return (image.source == BOCA_SOURCE or image.historical_legacy_attested) and all(
        any(ref.startswith(prefix) for prefix in BOCA_IMAGE_PREFIXES) for ref in image.references
    )


def _boca_image_signal(image: Image) -> bool:
    return image.source == BOCA_SOURCE or any(
        ref.startswith(prefix) for ref in image.references for prefix in BOCA_IMAGE_PREFIXES
    )


def _validate_inventory(value: Inventory) -> None:
    all_containers = [x.ident for x in value.containers]
    all_images = [x.ident for x in value.images]
    all_networks = [x.ident for x in value.networks]
    all_volumes = [x.name for x in value.volumes]
    if (
        sum(map(len, (all_containers, all_images, all_networks, all_volumes))) > MAX_OBJECTS
        or any(
            len(items) != len(set(items))
            for items in (all_containers, all_images, all_networks, all_volumes)
        )
        or any(not HEX_ID.fullmatch(x) for x in all_containers + all_images + all_networks)
        or any(not DOCKER_NAME.fullmatch(x) for x in all_volumes)
        or any(not HEX_ID.fullmatch(x) for x in value.global_image_ids)
        or (value.global_image_ids and not set(all_images) <= value.global_image_ids)
    ):
        raise CleanupError("Docker inventory incomplete, duplicate or outside bounded limits")
    for c in value.containers:
        if (
            not DOCKER_NAME.fullmatch(c.name.removeprefix("/"))
            or not HEX_ID.fullmatch(c.image_id)
            or type(c.running) is not bool
            or len(c.volumes) > 16
            or len(c.networks) > 16
        ):
            raise CleanupError("Docker container snapshot cannot be authenticated")
        _labels(c.labels)
    for network in value.networks:
        if not DOCKER_NAME.fullmatch(network.name) or len(network.attached_ids) > MAX_OBJECTS:
            raise CleanupError("Docker network snapshot malformed")
        _labels(network.labels)
    for volume in value.volumes:
        _labels(volume.labels)
    for image in value.images:
        if (
            len(image.references) > 32
            or any(not ref or len(ref) > 256 for ref in image.references)
            or type(image.historical_legacy_attested) is not bool
            or (
                image.historical_legacy_attested
                and (
                    not image.references
                    or image.source not in (None, BOCA_SOURCE)
                    or any(
                        not ref.startswith("ghcr.io/mbalbo2023/boca-socios-assistant:")
                        and not ref.startswith("ghcr.io/mbalbo2023/boca-socios-assistant@sha256:")
                        for ref in image.references
                    )
                )
            )
        ):
            raise CleanupError("Docker image references or historical attestation malformed")


def plan(
    inventory: Inventory,
    attempt_id: str,
    *,
    preserve_images: frozenset[str],
    preserve_containers: frozenset[str],
    retire_containers: frozenset[str],
) -> CleanupPlan:
    """Find only demonstrably Boca, attempt-owned, unused stale resources.

    The physical inventory first checks global ID-only census for exclusivity:
    any foreign container/network/volume aborts before inspect. This pure
    policy function may also receive synthetic foreign fixtures to verify
    image references are never misclassified as deletion authorization.
    """
    if (
        not ATTEMPT_ID.fullmatch(attempt_id)
        or any(not HEX_ID.fullmatch(image) for image in preserve_images)
        or any(not HEX_ID.fullmatch(ident) for ident in preserve_containers | retire_containers)
        or preserve_containers & retire_containers
    ):
        raise CleanupError("postdeploy exact attempt or protected image invalid")
    _validate_inventory(inventory)
    all_ids = {c.ident for c in inventory.containers}
    if not preserve_containers <= all_ids:
        raise CleanupError("protected installed/parked container missing from inventory")
    referenced_images = {c.image_id for c in inventory.containers} | set(preserve_images)
    referenced_volumes = {v for c in inventory.containers for v in c.volumes}
    referenced_networks = {n for c in inventory.containers for n in c.networks}
    targets: list[Target] = []
    uncertain: list[str] = []
    for c in inventory.containers:
        labels = _labels(c.labels)
        positive = (
            labels.get("com.docker.compose.project") == BOCA_PROJECT
            and c.name.removeprefix("/").startswith("boca-socios-")
            and _attempt_owner(labels, attempt_id)
        )
        if c.ident in preserve_containers:
            continue
        if c.ident in retire_containers:
            if not positive or c.running:
                raise CleanupError("retirement receipt does not match stopped Boca attempt")
            targets.append(Target("container", c.ident))
        elif c.name.removeprefix("/").startswith("boca-socios-") and not c.running and not positive:
            uncertain.append(f"container:{c.ident}:missing-or-unproven-attempt-NO_GO")
        elif positive and not c.running:
            uncertain.append(f"container:{c.ident}:stopped-not-authorized-for-retirement")
    for volume in inventory.volumes:
        labels = _labels(volume.labels)
        if volume.name in PERSISTENT_VOLUMES:
            continue
        if volume.name.startswith("boca-socios_"):
            if (
                _attempt_owner(labels, attempt_id)
                and labels.get("com.docker.compose.project") == BOCA_PROJECT
                and volume.name not in referenced_volumes
            ):
                targets.append(Target("volume", volume.name))
            elif volume.name not in referenced_volumes:
                uncertain.append(f"volume:{volume.name}:unproven-or-unknown-reference")
    for network in inventory.networks:
        labels = _labels(network.labels)
        if network.name.startswith("boca-socios_"):
            if (
                _attempt_owner(labels, attempt_id)
                and labels.get("com.docker.compose.project") == BOCA_PROJECT
                and not network.attached_ids
                and network.name not in referenced_networks
            ):
                targets.append(Target("network", network.ident))
            elif not network.attached_ids and network.name not in referenced_networks:
                uncertain.append(f"network:{network.ident}:unproven-or-unknown-reference")
    for image in inventory.images:
        if image.ident in referenced_images:
            continue
        if _known_boca_image(image):
            targets.append(Target("image", image.ident))
        elif _boca_image_signal(image):
            uncertain.append(f"image:{image.ident}:unverified-provenance-or-shared-reference")
    if len(targets) > MAX_DELETIONS:
        raise CleanupError("Boca cleanup exceeds explicit bounded deletion budget")
    targets.sort(
        key=lambda target: (
            ("container", "volume", "network", "image").index(target.kind),
            target.ident,
        )
    )
    return CleanupPlan(tuple(targets), tuple(sorted(uncertain)))


def execute(
    outcome: OUTCOME,
    attempt_id: str,
    *,
    preserve_images: frozenset[str],
    preserve_containers: frozenset[str],
    retire_containers: frozenset[str],
    probe: Callable[[], Inventory],
    delete_exact: Callable[[Target], None],
) -> CleanupReceipt:
    """Same obligatory cleanup finalizer for *every* Boca install outcome.

    A caller must hold the single protected Boca job lease for the complete
    probe/delete/postflight section. No retry is done if a receipt is lost.
    """
    if outcome not in ("SUCCESS", "FAILURE"):
        raise CleanupError("postdeploy status is not a reviewed outcome")
    before = probe()
    plan(
        before,
        attempt_id,
        preserve_images=preserve_images,
        preserve_containers=preserve_containers,
        retire_containers=retire_containers,
    )
    removed: list[Target] = []
    try:
        # A stopped attempt container can be the sole remaining reference to
        # its obsolete image or ephemeral volume. Recompute the complete plan
        # after each successful exact-ID deletion until no known residue
        # remains; never assume the initial graph is the final graph.
        for _ in range(MAX_DELETIONS):
            fresh = probe()
            if _storage_topology_changed(before.disk, fresh.disk):
                raise CleanupError("Boca postdeploy storage topology changed")
            candidates = plan(
                fresh,
                attempt_id,
                preserve_images=preserve_images,
                preserve_containers=preserve_containers,
                retire_containers=retire_containers,
            ).targets
            if not candidates:
                break
            target = candidates[0]
            if target in removed:
                raise CleanupError("target reappeared after verified selective removal")
            delete_exact(target)
            after_delete = probe()
            if _storage_topology_changed(before.disk, after_delete.disk):
                raise CleanupError("Boca postdeploy storage topology changed")
            # An object that merely became ineligible is NOT proof it was
            # deleted: its labels, live attachments or running status could
            # have drifted while Docker returned a misleading receipt. Prove
            # exact absence for *all four kinds* before accepting a deletion.
            surviving = {
                "container": {item.ident for item in after_delete.containers},
                "network": {item.ident for item in after_delete.networks},
                "volume": {item.name for item in after_delete.volumes},
                "image": (
                    after_delete.global_image_ids
                    if after_delete.global_image_ids
                    else {item.ident for item in after_delete.images}
                ),
            }[target.kind]
            if target.ident in surviving:
                raise CleanupError(
                    "Boca exact deletion target remains present by immutable identity"
                )
            if (
                target
                in plan(
                    after_delete,
                    attempt_id,
                    preserve_images=preserve_images,
                    preserve_containers=preserve_containers,
                    retire_containers=retire_containers,
                ).targets
            ):
                raise CleanupError("known removable Boca Docker residue survived delete")
            removed.append(target)
        else:
            raise CleanupError("bounded postdeploy deletion budget exhausted")
    except (CleanupError, OSError, ValueError):
        # No blind retry. A lost Docker receipt may have succeeded or failed.
        # The final inventory exposes any known residue but never runs prune.
        after = probe()
        try:
            final = plan(
                after,
                attempt_id,
                preserve_images=preserve_images,
                preserve_containers=preserve_containers,
                retire_containers=retire_containers,
            )
        except (CleanupError, ValueError):
            # A drifted retired ID may no longer pass positive-label policy.
            # That is itself NO_GO; do not let a second classification error
            # suppress the stable failure receipt or authorize a new delete.
            return CleanupReceipt(
                outcome,
                attempt_id,
                "NO_GO",
                before.disk,
                after.disk,
                tuple(removed),
                (
                    "postdelete-inventory-reconciliation-untrusted",
                    *(
                        ("Boca-storage-topology-changed",)
                        if _storage_topology_changed(before.disk, after.disk)
                        else ()
                    ),
                ),
                (),
            )
        return CleanupReceipt(
            outcome,
            attempt_id,
            "NO_GO",
            before.disk,
            after.disk,
            tuple(removed),
            (
                *final.uncertain,
                *(
                    ("Boca-storage-topology-changed",)
                    if _storage_topology_changed(before.disk, after.disk)
                    else ()
                ),
            ),
            final.targets,
        )
    after = probe()
    storage_drift = (
        ("Boca-storage-topology-changed",)
        if _storage_topology_changed(before.disk, after.disk)
        else ()
    )
    final = plan(
        after,
        attempt_id,
        preserve_images=preserve_images,
        preserve_containers=preserve_containers,
        retire_containers=retire_containers,
    )
    before_ids = (
        {("container", c.ident) for c in before.containers}
        | {("image", i.ident) for i in before.images}
        | {("network", n.ident) for n in before.networks}
        | {("volume", v.name) for v in before.volumes}
    )
    after_ids = (
        {("container", c.ident) for c in after.containers}
        | {("image", i.ident) for i in after.images}
        | {("network", n.ident) for n in after.networks}
        | {("volume", v.name) for v in after.volumes}
    )
    removed_ids = {(r.kind, r.ident) for r in removed}
    unexpected_deletions = before_ids - after_ids - removed_ids
    unexpected_creations = after_ids - before_ids
    drift_reasons = tuple(
        sorted(
            [f"unexpected-deletion:{kind}:{ident}" for kind, ident in unexpected_deletions]
            + [f"unexpected-creation:{kind}:{ident}" for kind, ident in unexpected_creations]
        )
    )
    if (
        final.targets
        or drift_reasons
        or storage_drift
        or any("NO_GO" in reason for reason in final.uncertain)
    ):
        status: Literal["ACCEPT", "INDETERMINATE", "NO_GO"] = "NO_GO"
    elif final.uncertain:
        status = "INDETERMINATE"
    else:
        status = "ACCEPT"
    return CleanupReceipt(
        outcome,
        attempt_id,
        status,
        before.disk,
        after.disk,
        tuple(removed),
        (*final.uncertain, *drift_reasons, *storage_drift),
        final.targets,
    )


def _docker(*args: str) -> str:
    """Dedicated rootless Docker CLI, never a shell or host-wide prune."""
    if os.geteuid() != EXPECTED_UID or os.getegid() != EXPECTED_UID:
        raise CleanupError("Boca cleanup requires its exact rootless owner")
    if os.environ.get("DOCKER_HOST", DOCKER_SOCKET) != DOCKER_SOCKET or any(
        key in os.environ
        for key in (
            "DOCKER_CONTEXT",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
            "DOCKER_TLS",
            "DOCKER_CONFIG",
        )
    ):
        raise CleanupError("Boca Docker context/TLS overrides are forbidden")
    # Never inherit deployment secrets or a different Docker daemon context.
    env = {
        "DOCKER_HOST": DOCKER_SOCKET,
        "XDG_RUNTIME_DIR": f"/run/user/{EXPECTED_UID}",
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
    }
    try:
        response = subprocess.run(  # noqa: S603 - exact Docker args; never shell
            ["/usr/bin/docker", "--host", DOCKER_SOCKET, *args],
            capture_output=True,
            check=False,
            text=True,
            timeout=45,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CleanupError("Boca Docker CLI unavailable or transport uncertain") from exc
    if response.returncode or len(response.stdout) > RUN_LIMIT or len(response.stderr) > RUN_LIMIT:
        # Docker output can contain host paths/ENV, so never include it in the
        # outward receipt or an exception.
        raise CleanupError("Boca Docker CLI failed or bounded receipt invalid")
    return response.stdout


def _json(raw: str) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise CleanupError("Docker inspected JSON malformed") from exc
    if not isinstance(value, dict):
        raise CleanupError("Docker inspect root is not an object")
    return value


def _dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        raise CleanupError("Docker inspected field malformed")
    return value


def _docker_labels(value: object) -> tuple[tuple[str, str], ...]:
    raw = _dict(value) if value is not None else {}
    if not all(isinstance(v, str) for v in raw.values()):
        raise CleanupError("Docker labels not a string map")
    return tuple(sorted((k, str(v)) for k, v in raw.items()))


def _ids(command: str, *args: str, dedupe: bool = False) -> list[str]:
    result = [line.strip() for line in _docker(command, *args).splitlines()]
    if (
        len(result) > MAX_OBJECTS
        or any(not HEX_ID.fullmatch(x) for x in result)
        or (not dedupe and len(result) != len(set(result)))
    ):
        raise CleanupError("Docker ID listing unsafe, truncated or duplicate")
    # 'docker image ls -a -q' lists an image ID once for *each* tag. Dedup the
    # ID inventory but keep all RepoTags/RepoDigests from image inspect.
    return sorted(set(result)) if dedupe else result


def _names(command: str, *args: str) -> list[str]:
    result = [line.strip() for line in _docker(command, *args).splitlines()]
    if (
        len(result) > MAX_OBJECTS
        or any(not DOCKER_NAME.fullmatch(x) for x in result)
        or len(result) != len(set(result))
    ):
        raise CleanupError("Docker resource names unsafe, truncated or duplicate")
    return result


def _inspect_field(kind: KIND, ident: str, field: str) -> object:
    """Read only one allowlisted Docker field, never full Config/Env."""
    fields = {
        "container": frozenset(
            {
                "Id",
                "Name",
                "Image",
                "State.Running",
                "Config.Labels",
                "Mounts",
                "NetworkSettings.Networks",
            }
        ),
        "image": frozenset({"Id", "RepoTags", "RepoDigests", "Config.Labels", "Size"}),
        "network": frozenset({"Id", "Name", "Containers", "Labels"}),
        "volume": frozenset({"Name", "Labels", "Mountpoint"}),
    }
    if field not in fields[kind]:
        raise CleanupError("Docker field outside narrowly reviewed allowlist")
    prefix = {
        "container": ("inspect",),
        "image": ("image", "inspect"),
        "network": ("network", "inspect"),
        "volume": ("volume", "inspect"),
    }[kind]
    try:
        return json.loads(_docker(*prefix, "--format", "{{json ." + field + "}}", ident))
    except (ValueError, TypeError) as exc:
        raise CleanupError("Docker narrow inspected field JSON malformed") from exc


def _inspect_image_public_oci_label(ident: str, field: str) -> str | None:
    """Only two exact OCI labels; never expose Config.Env or the full labels map."""
    if field not in ("org.opencontainers.image.source", "org.opencontainers.image.revision"):
        raise CleanupError("image provenance label outside minimal allowlist")
    if HEX_ID.fullmatch(ident) is None:
        raise CleanupError("image provenance exact ID invalid")
    template = (
        '{{if .Config.Labels}}{{json (index .Config.Labels "' + field + '")}}{{else}}null{{end}}'
    )
    try:
        value = json.loads(_docker("image", "inspect", "--format", template, ident))
    except (ValueError, TypeError) as exc:
        raise CleanupError("minimal OCI provenance field malformed") from exc
    if value is not None and not isinstance(value, str):
        raise CleanupError("minimal OCI provenance value malformed")
    return value


def _verify_historical_legacy_image(
    proof: LegacyImageProof,
) -> tuple[tuple[str, ...], str | None]:
    """Exact previously attested Boca image only; never inspect unknown image data.

    The only admitted OCI-source exception is the old controller whose Docker
    container was authenticated against the historical GH release SHA/digest.
    Re-verify narrowly on every cleanup probe, including all aliases. Docker
    Config.Env and foreign containers/images are never read.
    """
    if (
        type(proof) is not LegacyImageProof
        or not HEX_ID.fullmatch(proof.ident)
        or not re.fullmatch(
            r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z",
            proof.reference,
        )
        or re.fullmatch(r"[0-9a-f]{40}\Z", proof.revision) is None
    ):
        raise CleanupError("historical Boca image proof coordinates untrusted")
    if _inspect_field("image", proof.ident, "Id") != proof.ident:
        raise CleanupError("historical Boca image exact ID drifted")
    labels = _dict(_inspect_field("image", proof.ident, "Config.Labels") or {})
    tags = _inspect_field("image", proof.ident, "RepoTags") or []
    digests = _inspect_field("image", proof.ident, "RepoDigests") or []
    if (
        not isinstance(tags, list)
        or not isinstance(digests, list)
        or not all(isinstance(value, str) for value in tags + digests)
        or digests != [proof.reference]
        or len(tags) > 1
        or labels.get("org.opencontainers.image.revision") != proof.revision
        or labels.get("org.opencontainers.image.source") not in (None, BOCA_SOURCE)
    ):
        raise CleanupError("historical Boca image revision/digest/source unproven")
    references = tuple(
        sorted({ref for ref in tags + digests if isinstance(ref, str) and ref != "<none>:<none>"})
    )
    controller_prefixes = (
        "ghcr.io/mbalbo2023/boca-socios-assistant:",
        "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:",
    )
    if (
        not references
        or len(references) > 32
        or any(
            not any(ref.startswith(prefix) for prefix in controller_prefixes) or len(ref) > 256
            for ref in references
        )
    ):
        raise CleanupError("historical Boca image has foreign/ambiguous alias")
    source = labels.get("org.opencontainers.image.source")
    return references, source if isinstance(source, str) else None


def attest_historical_legacy_image(ident: str, reference: str, revision: str) -> LegacyImageProof:
    """Precommit, exact ID from positively authenticated installed controller."""
    proof = LegacyImageProof(ident, reference, revision)
    _verify_historical_legacy_image(proof)
    return proof


def _rootless_docker_disk_inodes() -> tuple[int, int, int, int]:
    """Measure only the verified data root of Boca's dedicated Docker daemon.

    Never assume /srv and Docker share a filesystem.  The socket and child
    environment are already pinned by `_docker`; Docker's own rootless/info
    identity must agree with the private UID home before following its path.
    """
    directory_fd: int | None = None
    try:
        info = _json(_docker("info", "--format", "{{json .}}"))
        status = info.get("DriverStatus")
        options = info.get("SecurityOptions")
        if (
            not isinstance(options, list)
            or "name=rootless" not in options
            or str(info.get("CgroupVersion")) != "2"
            or info.get("CgroupDriver") != "systemd"
            or info.get("Driver") not in {"overlay2", "fuse-overlayfs", "vfs"}
            or not isinstance(status, list)
            or any(
                not isinstance(item, list)
                or len(item) != 2
                or not all(isinstance(value, str) for value in item)
                or item[0] == "driver-type"
                for item in status
            )
        ):
            raise CleanupError("rootless Docker storage backend untrusted")
        reported = info.get("DockerRootDir")
        if not isinstance(reported, str) or not 0 < len(reported) <= 4096:
            raise CleanupError("rootless Docker storage root path untrusted")
        home = Path(pwd.getpwuid(EXPECTED_UID).pw_dir)
        storage = Path(reported)
        if (
            not home.is_absolute()
            or home == Path("/")
            or home.resolve(strict=True) != home
            or not storage.is_absolute()
            or str(storage) != reported
            or ".." in storage.parts
        ):
            raise CleanupError("rootless Docker storage root path untrusted")
        try:
            relative = storage.relative_to(home)
        except ValueError:
            raise CleanupError("rootless Docker storage outside Boca owner home") from None
        if not relative.parts:
            raise CleanupError("rootless Docker storage root equals Boca owner home")

        directory_fd = os.open(
            home,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        root = os.fstat(directory_fd)
        if (
            not stat.S_ISDIR(root.st_mode)
            or root.st_uid != EXPECTED_UID
            or root.st_gid != EXPECTED_GID
            or stat.S_IMODE(root.st_mode) != 0o700
        ):
            raise CleanupError("rootless Docker storage owner home untrusted")

        for part in relative.parts:
            child = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = child
            detail = os.fstat(child)
            if (
                not stat.S_ISDIR(detail.st_mode)
                or detail.st_uid != EXPECTED_UID
                or detail.st_gid != EXPECTED_GID
                or stat.S_IMODE(detail.st_mode) & 0o022
            ):
                raise CleanupError("rootless Docker storage child path untrusted")
        assert directory_fd is not None
        actual = os.fstat(directory_fd)
        path = os.lstat(storage)
        if (path.st_dev, path.st_ino) != (actual.st_dev, actual.st_ino) or not stat.S_ISDIR(
            path.st_mode
        ):
            raise CleanupError("rootless Docker storage inode changed during inventory")
        stats = os.fstatvfs(directory_fd)
        return stats.f_bavail * stats.f_frsize, stats.f_favail, actual.st_dev, actual.st_ino
    except CleanupError:
        raise
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        raise CleanupError("rootless Docker storage identity or capacity unavailable") from exc
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def _disk_inodes() -> DiskInodes:
    """Record both Boca staging and authenticated rootless Docker filesystems."""
    root_fd: int | None = None
    child_fd: int | None = None
    try:
        root_fd = os.open(DISK_ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            child_fd = os.open(
                "boca-socios",
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=root_fd,
            )
        except FileNotFoundError:
            # Fresh-install FAILURE before root creation; /srv is the same
            # persistent filesystem and this probe creates no placeholder.
            pass
        if child_fd is not None:
            details = os.fstat(child_fd)
            if (
                not stat.S_ISDIR(details.st_mode)
                or details.st_uid != EXPECTED_UID
                or details.st_gid != EXPECTED_UID
                or stat.S_IMODE(details.st_mode) != 0o700
            ):
                raise CleanupError("Boca root owner/mode/inode unsafe")
        measured_fd = child_fd if child_fd is not None else root_fd
        assert measured_fd is not None
        stats = os.fstatvfs(measured_fd)
        identity = os.fstat(measured_fd)
        docker_bytes, docker_inodes, docker_device, docker_inode = _rootless_docker_disk_inodes()
        return DiskInodes(
            stats.f_bavail * stats.f_frsize,
            stats.f_favail,
            docker_bytes_free=docker_bytes,
            docker_inodes_free=docker_inodes,
            stage_device=identity.st_dev,
            stage_inode=identity.st_ino,
            docker_device=docker_device,
            docker_inode=docker_inode,
        )
    except OSError as exc:
        raise CleanupError("Boca disk/inode measurement unsafe") from exc
    finally:
        if child_fd is not None:
            os.close(child_fd)
        if root_fd is not None:
            os.close(root_fd)


def capture_inventory(*, historical_legacy: LegacyImageProof | None = None) -> Inventory:
    """Read-only Docker graph + disk/inodes before and after cleanup.

    Never inspect foreign work: ID-only global presence checks must prove this
    particular rootless daemon has no foreign containers/networks/volumes.
    Config.Env and every other unallowlisted inspected field are never read.
    """
    project_filter = f"label=com.docker.compose.project={BOCA_PROJECT}"
    every_container = set(_ids("ps", "-a", "-q", "--no-trunc"))
    boca_containers = set(_ids("ps", "-a", "-q", "--no-trunc", "--filter", project_filter))
    if every_container != boca_containers:
        raise CleanupError("rootless Docker daemon has foreign containers; NO_GO without inspect")
    every_network = set(_ids("network", "ls", "-q", "--no-trunc"))
    builtin_networks = set(_ids("network", "ls", "-q", "--no-trunc", "--filter", "type=builtin"))
    boca_networks = set(_ids("network", "ls", "-q", "--no-trunc", "--filter", project_filter))
    if every_network - builtin_networks != boca_networks:
        raise CleanupError("rootless Docker daemon has unproven networks; NO_GO")
    every_volume = set(_names("volume", "ls", "-q"))
    boca_volumes = set(_names("volume", "ls", "-q", "--filter", project_filter))
    if every_volume != boca_volumes:
        raise CleanupError("rootless Docker daemon has foreign volumes; NO_GO")
    containers: list[Container] = []
    for ident in sorted(boca_containers):
        if _inspect_field("container", ident, "Id") != ident:
            raise CleanupError("Docker container ID changed during inventory")
        running = _inspect_field("container", ident, "State.Running")
        connected_networks = _dict(
            _inspect_field("container", ident, "NetworkSettings.Networks") or {}
        )
        mounts = _inspect_field("container", ident, "Mounts")
        if type(running) is not bool or not isinstance(mounts, list) or len(mounts) > 32:
            raise CleanupError("Docker container running/mount state malformed")
        mounted_volumes: list[str] = []
        for mount in mounts:
            mount = _dict(mount)
            if mount.get("Type") == "volume":
                name = mount.get("Name")
                if not isinstance(name, str) or not DOCKER_NAME.fullmatch(name):
                    raise CleanupError("Docker volume attachment invalid")
                mounted_volumes.append(name)
        name = _inspect_field("container", ident, "Name")
        image = _inspect_field("container", ident, "Image")
        if not isinstance(name, str) or not isinstance(image, str):
            raise CleanupError("Docker container name/image unavailable")
        containers.append(
            Container(
                ident,
                name,
                image,
                running,
                _docker_labels(_inspect_field("container", ident, "Config.Labels")),
                tuple(sorted(mounted_volumes)),
                tuple(sorted(connected_networks)),
            )
        )
    images: list[Image] = []
    all_image_ids = frozenset(_ids("image", "ls", "-a", "-q", "--no-trunc", dedupe=True))
    label_images = set(
        _ids(
            "image",
            "ls",
            "-a",
            "-q",
            "--no-trunc",
            "--filter",
            f"label=org.opencontainers.image.source={BOCA_SOURCE}",
            dedupe=True,
        )
    )
    reference_images = set(
        _ids(
            "image",
            "ls",
            "-a",
            "-q",
            "--no-trunc",
            "--filter",
            "reference=ghcr.io/mbalbo2023/boca-socios-assistant*",
            dedupe=True,
        )
    )
    known = label_images | reference_images
    if historical_legacy is not None and historical_legacy.ident in all_image_ids:
        # Only this precommitted old container's exact image ID may be inspected
        # without an OCI source label; its immutable digest and revision are
        # checked before exposing it as a cleanup target.
        known.add(historical_legacy.ident)
    for ident in sorted(known):
        if historical_legacy is not None and ident == historical_legacy.ident:
            refs, source = _verify_historical_legacy_image(historical_legacy)
            images.append(Image(ident, refs, source, historical_legacy_attested=True))
            continue
        if ident not in label_images:
            # Other Boca-like tags remain uncertain: no foreign Config/Env read
            # and no delete authorization from a name or tag alone.
            images.append(
                Image(ident, ("ghcr.io/mbalbo2023/boca-socios-assistant:unverified",), None)
            )
            continue
        if _inspect_field("image", ident, "Id") != ident:
            raise CleanupError("Docker image ID changed during inventory")
        labels = _dict(_inspect_field("image", ident, "Config.Labels") or {})
        tags = _inspect_field("image", ident, "RepoTags") or []
        digests = _inspect_field("image", ident, "RepoDigests") or []
        if not isinstance(tags, list) or not isinstance(digests, list):
            raise CleanupError("Docker image references malformed")
        refs = tuple(
            sorted(
                {
                    ref
                    for ref in tags + digests
                    if isinstance(ref, str) and not ref.startswith("<none>")
                }
            )
        )
        raw_source = labels.get("org.opencontainers.image.source")
        images.append(Image(ident, refs, raw_source if isinstance(raw_source, str) else None))
    networks: list[Network] = []
    for ident in sorted(boca_networks):
        if _inspect_field("network", ident, "Id") != ident:
            raise CleanupError("Docker network ID changed during inventory")
        name = _inspect_field("network", ident, "Name")
        attached = _dict(_inspect_field("network", ident, "Containers") or {})
        if not isinstance(name, str) or any(not HEX_ID.fullmatch(x) for x in attached):
            raise CleanupError("Docker network connection map invalid")
        networks.append(
            Network(
                name,
                ident,
                tuple(sorted(attached)),
                _docker_labels(_inspect_field("network", ident, "Labels")),
            )
        )
    volumes: list[Volume] = []
    for name in sorted(boca_volumes):
        if _inspect_field("volume", name, "Name") != name:
            raise CleanupError("Docker volume identity changed during inventory")
        volumes.append(Volume(name, _docker_labels(_inspect_field("volume", name, "Labels"))))
    result = Inventory(
        tuple(containers),
        tuple(images),
        tuple(networks),
        tuple(volumes),
        _disk_inodes(),
        all_image_ids,
    )
    _validate_inventory(result)
    return result


def delete_exact(target: Target) -> None:
    """Never pass tags, short IDs, globs or -f to Docker removal."""
    if target.kind in ("container", "image", "network") and not HEX_ID.fullmatch(target.ident):
        raise CleanupError("unsafe Docker deletion ID")
    if target.kind == "volume" and not DOCKER_NAME.fullmatch(target.ident):
        raise CleanupError("unsafe Docker deletion name")
    command = {
        "container": ("rm",),
        "image": ("image", "rm"),
        "network": ("network", "rm"),
        "volume": ("volume", "rm"),
    }[target.kind]
    _docker(*command, target.ident)


def execute_protected(
    outcome: OUTCOME,
    attempt_id: str,
    *,
    preserve_images: frozenset[str],
    preserve_containers: frozenset[str],
    retire_containers: frozenset[str],
    lease: BocaJobLease,
    historical_legacy: LegacyImageProof | None = None,
) -> CleanupReceipt:
    """Future *unwired* generic finalizer for first/beta/cutover install.

    This callable is NOT exposed by any CLI/workflow and refuses to proceed
    without the active exclusive Boca-only flock from the protected job.
    Today physical use is hard NO_GO until all installers honor this lease.
    """
    verify_protected_boca_job_lease(lease, attempt_id)
    if historical_legacy is not None:
        # An image that vanished or changed since the precommit attestation is
        # not proof of a successful cleanup. Abort before any other removal.
        _verify_historical_legacy_image(historical_legacy)
    return execute(
        outcome,
        attempt_id,
        preserve_images=preserve_images,
        preserve_containers=preserve_containers,
        retire_containers=retire_containers,
        probe=(
            capture_inventory
            if historical_legacy is None
            else lambda: capture_inventory(historical_legacy=historical_legacy)
        ),
        delete_exact=delete_exact,
    )


# The Cutover A post-APPLY diagnostic intentionally has no relationship to the
# mutation/lease entrypoint above. Its sole dependency is the already reviewed
# read-only inventory and pure positive-identity plan; the protected GitHub
# workflow streams this module by stdin to the Boca-only rootless account.
READONLY_CLEANUP_VERSION = "boca-cutover-cleanup-readonly-v4"
READONLY_CLEANUP_MAX_JSON = 8192
READONLY_PROVENANCE_LIMIT = 8
SYSTEM_DF_KINDS = frozenset({"Images", "Containers", "Local Volumes", "Build Cache"})
SAFE_SIZE_DISPLAY = re.compile(r"[0-9]+(?:\.[0-9]+)?\s*(?:B|kB|MB|GB|TB|PB)\Z")
SAFE_RECLAIMABLE_DISPLAY = re.compile(
    r"[0-9]+(?:\.[0-9]+)?\s*(?:B|kB|MB|GB|TB|PB)(?:\s*\([0-9]{1,3}%\))?\Z"
)

# R28: fixed third-party-verifiable coordinates from physical #42116760086
# and successful GitHub release #41559973013. This can NEVER accept another
# image via CLI args, a name prefix, a moving tag, or a runtime environment.
HISTORICAL_RETIRE_INCIDENT = "42096941815"
HISTORICAL_RETIRE_CONTAINER = "27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793"
HISTORICAL_RETIRE_KEEP_IMAGE = (
    "sha256:12d492da545566a13ba4faec6afd99a3d6fe1990657d2e0981420c429c36d5c1"
)
HISTORICAL_RETIRE_TARGET = "sha256:a44453ab30cb17fa42f71723cf64b1097dabdf0e56369186077c47bc8224f90b"
HISTORICAL_RETIRE_DIGEST = (
    "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:"
    "7afe5429e34bd39b289e9d1da700fd5cd436cd2bdd413a2c4f8039829f1d034e"
)
HISTORICAL_RETIRE_REVISION = "0e830e3eed941de1da70cef8b42bda9f20258b65"
HISTORICAL_RETIRE_SIZE = 66_021_451


def _check_exact_historical_retire_snapshot(
    snapshot: Inventory,
    provenance: dict[str, object],
) -> Container:
    """Single candidate and exact original, never Boca-prefix as delete authority."""
    _validate_inventory(snapshot)
    original = _readonly_original(snapshot, HISTORICAL_RETIRE_CONTAINER)
    candidates = plan(
        snapshot,
        HISTORICAL_RETIRE_INCIDENT,
        preserve_images=frozenset({HISTORICAL_RETIRE_KEEP_IMAGE}),
        preserve_containers=frozenset({HISTORICAL_RETIRE_CONTAINER}),
        retire_containers=frozenset(),
    )
    expected_unknown = (
        f"image:{HISTORICAL_RETIRE_TARGET}:unverified-provenance-or-shared-reference",
    )
    expected_volumes = {"boca-socios_boca_data", "boca-socios_boca_key", "boca-socios_boca_owner"}
    if (
        original.image_id != HISTORICAL_RETIRE_KEEP_IMAGE
        or len(snapshot.containers) != 1
        or len(snapshot.networks) != 1
        or snapshot.networks[0].name != "boca-socios_boca_private"
        or snapshot.networks[0].attached_ids != (HISTORICAL_RETIRE_CONTAINER,)
        or original.networks != ("boca-socios_boca_private",)
        or set(original.volumes) != expected_volumes
        or {vol.name for vol in snapshot.volumes} != expected_volumes
        or {img.ident for img in snapshot.images}
        != {HISTORICAL_RETIRE_KEEP_IMAGE, HISTORICAL_RETIRE_TARGET}
        or snapshot.global_image_ids != {HISTORICAL_RETIRE_KEEP_IMAGE, HISTORICAL_RETIRE_TARGET}
        or candidates.targets
        or candidates.uncertain != expected_unknown
        or provenance
        != {
            "id": HISTORICAL_RETIRE_TARGET,
            "repo_tags": [],
            "repo_digests": [HISTORICAL_RETIRE_DIGEST],
            "untrusted_alias_count": 0,
            "oci_source_status": "ABSENT",
            "oci_revision": HISTORICAL_RETIRE_REVISION,
            "logical_size_bytes": HISTORICAL_RETIRE_SIZE,
            "container_ref_count": 0,
            "deletion_authorized": False,
        }
    ):
        raise CleanupError("historical Boca image retirement exact proof does not match")
    metrics = _readonly_disk(snapshot.disk)
    if (
        min(metrics["stage_bytes_free"], metrics["docker_bytes_free"]) < 4 * 1024**3
        or min(metrics["stage_inodes_free"], metrics["docker_inodes_free"]) < 50_000
    ):
        raise CleanupError("historical retirement storage reserve unavailable")
    return original


def retire_single_attested_historical_image(
    lease: BocaJobLease,
    *,
    probe: Callable[[], Inventory] = capture_inventory,
    provenance_probe: Callable[[str, Inventory], dict[str, object]] | None = None,
    remove: Callable[[str], None] | None = None,
) -> CleanupReceipt:
    """CODE_ONLY, UNWIRED exact one-image retire under Boca lease.

    This callable is NOT a CLI route or a GitHub Action. Before a future
    protected caller may use it, that caller must pin main/release/actor and
    acquire the single UID10001 Boca-only lease. No built-in retry or purge.
    """
    verify_protected_boca_job_lease(lease, HISTORICAL_RETIRE_INCIDENT)
    inspect_provenance = provenance_probe or _observe_boca_reference_image

    def snapshot_and_proof() -> tuple[Inventory, dict[str, object]]:
        snapshot = probe()
        proof = inspect_provenance(HISTORICAL_RETIRE_TARGET, snapshot)
        _check_exact_historical_retire_snapshot(snapshot, proof)
        return snapshot, proof

    before, proof = snapshot_and_proof()
    stable, repeated = snapshot_and_proof()
    if (
        (before.containers, before.images, before.networks, before.volumes, before.global_image_ids)
        != (
            stable.containers,
            stable.images,
            stable.networks,
            stable.volumes,
            stable.global_image_ids,
        )
        or _storage_topology_changed(before.disk, stable.disk)
        or proof != repeated
    ):
        raise CleanupError("historical image retirement preflight drifted before deletion")
    # Revalidate the exact immutable release proof immediately before the one
    # possible write; never remove by tag/digest or user-selected coordinate.
    last, proof_last = snapshot_and_proof()
    if (
        (stable.containers, stable.images, stable.networks, stable.volumes, stable.global_image_ids)
        != (last.containers, last.images, last.networks, last.volumes, last.global_image_ids)
        or _storage_topology_changed(stable.disk, last.disk)
        or repeated != proof_last
    ):
        raise CleanupError("historical image retirement proof changed before deletion")

    try:
        if remove is None:
            _docker("image", "rm", "--no-prune", HISTORICAL_RETIRE_TARGET)
        else:
            remove(HISTORICAL_RETIRE_TARGET)
        after = probe()
        original = _readonly_original(after, HISTORICAL_RETIRE_CONTAINER)
        if (
            original.image_id != HISTORICAL_RETIRE_KEEP_IMAGE
            or after.containers != before.containers
            or after.networks != before.networks
            or after.volumes != before.volumes
            or after.images
            != tuple(img for img in before.images if img.ident != HISTORICAL_RETIRE_TARGET)
            or after.global_image_ids != {HISTORICAL_RETIRE_KEEP_IMAGE}
            or _storage_topology_changed(before.disk, after.disk)
            or min(after.disk.bytes_free, after.disk.docker_bytes_free or 0) < 4 * 1024**3
            or min(after.disk.inodes_free, after.disk.docker_inodes_free or 0) < 50_000
        ):
            raise CleanupError("historical image retirement postflight identity unverified")
        return CleanupReceipt(
            "SUCCESS",
            HISTORICAL_RETIRE_INCIDENT,
            "ACCEPT",
            before.disk,
            after.disk,
            (Target("image", HISTORICAL_RETIRE_TARGET),),
            (),
            (),
        )
    except (CleanupError, OSError, ValueError):
        # Docker may have removed it even if the ACK was lost: never retry.
        # Keep the attempted identity in an uncertain receipt, not `removed`.
        return CleanupReceipt(
            "FAILURE",
            HISTORICAL_RETIRE_INCIDENT,
            "INDETERMINATE",
            before.disk,
            before.disk,
            (),
            ("historical-exact-image-removal-ack-unverified",),
            (),
        )


def _empty_rootless_disk_accounting() -> dict[str, object]:
    return {
        "scope": "BOCA_ROOTLESS_DAEMON_ONLY",
        "system_df_status": "NOT_OBSERVED",
        "system_df": [],
        "buildx_status": "NOT_OBSERVED",
        "buildx": {
            "records": 0,
            "total_record_bytes": 0,
            "reclaimable_record_bytes": 0,
            "shared_record_bytes": 0,
            "mutable_records": 0,
        },
        "deletion_authorized": False,
    }


def _empty_host_python_crypto() -> dict[str, object]:
    return {
        "scope": "HOST_PYTHON_UID10001",
        "status": "NOT_OBSERVED",
        "version": None,
        "probe_writes": 0,
    }


def _probe_host_python_crypto() -> dict[str, object]:
    """Prove an isolated host-Python import as Boca UID; never inspect secrets.

    This is NOT a test of the controller image or a request to execute inside
    its container. Python's -I/-B makes this bounded subprocess independent
    of PYTHONPATH, user site and .pyc writes, with no inherited credentials.
    """
    if os.geteuid() != EXPECTED_UID or os.getegid() != EXPECTED_GID:
        raise CleanupError("host crypto proof requires Boca rootless identity")
    result = _empty_host_python_crypto()
    try:
        completed = subprocess.run(  # noqa: S603 - fixed read-only Python probe
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                "import cryptography; print(cryptography.__version__)",
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if completed.returncode:
            result["status"] = "IMPORT_FAILED"
        elif (
            len(completed.stdout) <= 64
            and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,4}(?:[a-z0-9.]{0,15})\n?", completed.stdout)
            is not None
        ):
            result["status"] = "AVAILABLE"
            result["version"] = completed.stdout.strip()
        else:
            result["status"] = "UNAVAILABLE"
    except (OSError, subprocess.TimeoutExpired):
        result["status"] = "UNAVAILABLE"
    return result


def _validate_host_python_crypto(value: object) -> None:
    if (
        type(value) is not dict
        or set(value) != {"scope", "status", "version", "probe_writes"}
        or value["scope"] != "HOST_PYTHON_UID10001"
        or value["status"] not in ("NOT_OBSERVED", "AVAILABLE", "IMPORT_FAILED", "UNAVAILABLE")
        or value["probe_writes"] != 0
        or type(value["probe_writes"]) is not int
        or (
            value["status"] == "AVAILABLE"
            and (
                type(value["version"]) is not str
                or re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,4}(?:[a-z0-9.]{0,15})", value["version"])
                is None
            )
        )
        or (value["status"] != "AVAILABLE" and value["version"] is not None)
    ):
        raise CleanupError("host Python read-only crypto proof invalid")


OWNER_VOLUME = "boca-socios_boca_owner"
OWNER_PUBLIC_FILES = ("credential_id", "public_key.der")


def _empty_owner_metadata() -> dict[str, object]:
    return {
        "scope": "BOCA_ROOTLESS_OWNER_VOLUME_METADATA_ONLY",
        "status": "NOT_OBSERVED",
        "owner_directory": None,
        "public_files": {name: None for name in OWNER_PUBLIC_FILES},
        "host_process_uid_map": [],
        "deletion_authorized": False,
    }


def _safe_public_file_stat(directory_fd: int, name: str) -> dict[str, int | str]:
    """Only lstat allowlisted *public* credential metadata, never contents."""
    if name not in OWNER_PUBLIC_FILES:
        raise CleanupError("owner public file outside exact allowlist")
    try:
        item = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return {"status": "MISSING"}
    except OSError:
        return {"status": "UNAVAILABLE"}
    if not stat.S_ISREG(item.st_mode):
        return {"status": "NOT_REGULAR"}
    return {
        "status": "PRESENT",
        "uid": item.st_uid,
        "gid": item.st_gid,
        "mode": stat.S_IMODE(item.st_mode),
        "size": item.st_size,
        "nlink": item.st_nlink,
    }


def _read_host_process_uid_map() -> list[list[int]]:
    """Current observer process map only; NOT a container's UID mapping."""
    try:
        with open("/proc/self/uid_map", encoding="ascii") as handle:
            raw = handle.read(512)
        lines = raw.splitlines()
        if not 1 <= len(lines) <= 8:
            raise CleanupError("host process UID map unreadable")
        ranges = [[int(value) for value in line.split()] for line in lines]
        if any(
            len(row) != 3 or any(not 0 <= value <= 2**32 for value in row) or row[2] == 0
            for row in ranges
        ):
            raise CleanupError("host process UID map invalid")
        return ranges
    except (OSError, UnicodeError, ValueError, CleanupError):
        return []


def _read_owner_public_metadata(snapshot: Inventory) -> dict[str, object]:
    """No file opens: only positive Boca volume mount and public stat metadata.

    A subordinate UID may block host traversal. In that case retain directory
    uid/gid/mode and mark file metadata unavailable; no Docker exec or secrets.
    """
    result = _empty_owner_metadata()
    result["host_process_uid_map"] = _read_host_process_uid_map()
    if not any(
        volume.name == OWNER_VOLUME
        and _labels(volume.labels).get("com.docker.compose.project") == BOCA_PROJECT
        for volume in snapshot.volumes
    ):
        result["status"] = "VOLUME_MISSING"
        return result

    opened: list[int] = []
    try:
        if os.geteuid() != EXPECTED_UID or os.getegid() != EXPECTED_GID:
            raise CleanupError("owner volume metadata requires Boca rootless UID")
        raw_root = _json(_docker("info", "--format", "{{json .}}"))
        root_name = raw_root.get("DockerRootDir")
        mount_name = _inspect_field("volume", OWNER_VOLUME, "Mountpoint")
        home = Path(pwd.getpwuid(EXPECTED_UID).pw_dir)
        if (
            not isinstance(root_name, str)
            or not isinstance(mount_name, str)
            or not root_name.startswith(str(home) + "/")
            or ".." in Path(root_name).parts
            or Path(mount_name) != Path(root_name) / "volumes" / OWNER_VOLUME / "_data"
        ):
            raise CleanupError("rootless owner volume mountpoint is not exact Boca path")
        # capture_inventory() already attested this Docker storage root under
        # owned Boca home. Recheck dev/inode against that bounded snapshot.
        root_fd = os.open(root_name, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        opened.append(root_fd)
        root_stat = os.fstat(root_fd)
        if (root_stat.st_dev, root_stat.st_ino) != (
            snapshot.disk.docker_device,
            snapshot.disk.docker_inode,
        ):
            raise CleanupError("rootless owner volume storage root changed")
        parent_fd = root_fd
        for part in ("volumes", OWNER_VOLUME):
            parent_fd = os.open(
                part,
                os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent_fd,
            )
            opened.append(parent_fd)
        directory_stat = os.stat("_data", dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise CleanupError("owner volume data directory is not a directory")
        result["owner_directory"] = {
            "uid": directory_stat.st_uid,
            "gid": directory_stat.st_gid,
            "mode": stat.S_IMODE(directory_stat.st_mode),
        }
        try:
            data_fd = os.open(
                "_data",
                os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent_fd,
            )
        except OSError:
            result["status"] = "FILES_INACCESSIBLE"
            return result
        opened.append(data_fd)
        public_files = {name: _safe_public_file_stat(data_fd, name) for name in OWNER_PUBLIC_FILES}
        result["public_files"] = public_files
        result["status"] = (
            "FILES_INACCESSIBLE"
            if any(row["status"] == "UNAVAILABLE" for row in public_files.values())
            else "OBSERVED"
        )
    except (CleanupError, OSError, ValueError, KeyError, TypeError):
        result["status"] = "UNAVAILABLE"
        result["owner_directory"] = None
    finally:
        for fd in reversed(opened):
            os.close(fd)
    return result


def _validate_owner_metadata(value: object) -> None:
    if (
        type(value) is not dict
        or set(value)
        != {
            "scope",
            "status",
            "owner_directory",
            "public_files",
            "host_process_uid_map",
            "deletion_authorized",
        }
        or value["scope"] != "BOCA_ROOTLESS_OWNER_VOLUME_METADATA_ONLY"
        or value["status"]
        not in ("NOT_OBSERVED", "OBSERVED", "FILES_INACCESSIBLE", "VOLUME_MISSING", "UNAVAILABLE")
        or value["deletion_authorized"] is not False
        or type(value["host_process_uid_map"]) is not list
        or len(value["host_process_uid_map"]) > 8
        or any(
            type(row) is not list
            or len(row) != 3
            or any(type(number) is not int or not 0 <= number <= 2**32 for number in row)
            or row[2] == 0
            for row in value["host_process_uid_map"]
        )
    ):
        raise CleanupError("rootless owner volume metadata receipt invalid")
    directory = value["owner_directory"]
    if directory is not None and (
        type(directory) is not dict
        or set(directory) != {"uid", "gid", "mode"}
        or any(type(item) is not int or not 0 <= item <= 2**32 for item in directory.values())
        or directory["mode"] > 0o7777
    ):
        raise CleanupError("rootless owner directory metadata invalid")
    if (value["status"] in ("NOT_OBSERVED", "VOLUME_MISSING", "UNAVAILABLE")) != (
        directory is None
    ):
        raise CleanupError("rootless owner volume directory/status contradictory")
    files = value["public_files"]
    if type(files) is not dict or set(files) != set(OWNER_PUBLIC_FILES):
        raise CleanupError("rootless owner public files allowlist invalid")
    for name in OWNER_PUBLIC_FILES:
        row = files[name]
        if row is None:
            if value["status"] == "OBSERVED":
                raise CleanupError("owner public file metadata absent on observed directory")
            continue
        if (
            value["status"] not in ("OBSERVED", "FILES_INACCESSIBLE")
            or type(row) is not dict
            or row.get("status") not in ("PRESENT", "MISSING", "NOT_REGULAR", "UNAVAILABLE")
            or (row["status"] != "PRESENT" and set(row) != {"status"})
            or (
                row["status"] == "PRESENT"
                and (
                    set(row) != {"status", "uid", "gid", "mode", "size", "nlink"}
                    or any(
                        type(row[key]) is not int or not 0 <= row[key] <= 2**32
                        for key in ("uid", "gid", "mode", "size", "nlink")
                    )
                    or row["mode"] > 0o7777
                )
            )
        ):
            raise CleanupError("owner public file metadata forged")
    if value["status"] == "OBSERVED" and any(
        row is None or row["status"] == "UNAVAILABLE" for row in files.values()
    ):
        raise CleanupError("owner public file visibility unverified")
    if (
        value["status"] == "FILES_INACCESSIBLE"
        and any(row is not None for row in files.values())
        and not any(row is not None and row["status"] == "UNAVAILABLE" for row in files.values())
    ):
        raise CleanupError("owner file inaccessibility claim not supported")


def _read_rootless_storage_usage() -> dict[str, object]:
    """Read aggregate daemon cache/volume pressure; never reveal cache descriptions.

    The caller first established that this UID10001 rootless daemon contains
    exclusively Boca containers/networks/volumes. Buildx probes ONLY its local
    `default` driver=docker builder, not a selected/remote builder. This is an
    accounting hint, never proof a `prune` would safely reclaim these bytes.
    """
    report = _empty_rootless_disk_accounting()
    try:
        raw = _docker("system", "df", "--format", "{{json .}}")
        lines = [line for line in raw.splitlines() if line.strip()]
        rows: list[dict[str, object]] = []
        seen: set[str] = set()
        if not 1 <= len(lines) <= 4:
            raise CleanupError("rootless Docker disk summary incomplete")
        for line in lines:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise CleanupError("Docker disk summary row malformed")
            kind = value.get("Type")
            if kind not in SYSTEM_DF_KINDS or kind in seen:
                raise CleanupError("Docker disk summary type unsupported")
            seen.add(kind)
            total, active = value.get("TotalCount"), value.get("Active")
            if type(total) is str and total.isdecimal():
                total = int(total)
            if type(active) is str and active.isdecimal():
                active = int(active)
            size, reclaimable = value.get("Size"), value.get("Reclaimable")
            if (
                type(total) is not int
                or type(active) is not int
                or not 0 <= active <= total <= 1_000_000
                or type(size) is not str
                or SAFE_SIZE_DISPLAY.fullmatch(size.strip()) is None
                or type(reclaimable) is not str
                or SAFE_RECLAIMABLE_DISPLAY.fullmatch(reclaimable.strip()) is None
            ):
                raise CleanupError("Docker disk accounting numbers malformed")
            rows.append(
                {
                    "kind": kind,
                    "total": total,
                    "active": active,
                    "size_display": size.strip(),
                    "reclaimable_display": reclaimable.strip(),
                }
            )
        report["system_df_status"] = "OBSERVED"
        report["system_df"] = sorted(rows, key=lambda row: str(row["kind"]))
    except (CleanupError, ValueError, TypeError):
        report["system_df_status"] = "UNAVAILABLE"
        report["system_df"] = []

    try:
        builders = _docker("buildx", "ls", "--format", "{{.Builder.Name}}:{{.DriverEndpoint}}")
        normalized = {line.strip().replace(": ", ":") for line in builders.splitlines()}
        if not {"default:docker", "default:default"} <= normalized:
            raise CleanupError("buildx local default driver cannot be proved")
        raw = _docker("buildx", "du", "--builder", "default", "--format=json")
        lines = [line for line in raw.splitlines() if line.strip()]
        if len(lines) > 1024:
            raise CleanupError("Buildx read-only cache record limit exceeded")
        total_bytes = reclaimable_bytes = shared_bytes = mutable_records = 0
        for line in lines:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise CleanupError("Buildx cache row malformed")
            size = value.get("Size")
            if (
                type(size) is not str
                or re.fullmatch(r"[0-9]{1,16}", size) is None
                or type(value.get("Reclaimable")) is not bool
                or type(value.get("Shared")) is not bool
                or type(value.get("Mutable")) is not bool
            ):
                raise CleanupError("Buildx cache numeric evidence malformed")
            size_bytes = int(size)
            total_bytes += size_bytes
            reclaimable_bytes += size_bytes if value["Reclaimable"] else 0
            shared_bytes += size_bytes if value["Shared"] else 0
            mutable_records += int(value["Mutable"])
        report["buildx_status"] = "OBSERVED"
        report["buildx"] = {
            "records": len(lines),
            "total_record_bytes": total_bytes,
            "reclaimable_record_bytes": reclaimable_bytes,
            "shared_record_bytes": shared_bytes,
            "mutable_records": mutable_records,
        }
    except (CleanupError, ValueError, TypeError):
        report["buildx_status"] = "UNAVAILABLE"
    return report


def _validate_rootless_disk_accounting(value: object) -> None:
    if (
        type(value) is not dict
        or set(value)
        != {
            "scope",
            "system_df_status",
            "system_df",
            "buildx_status",
            "buildx",
            "deletion_authorized",
        }
        or value["scope"] != "BOCA_ROOTLESS_DAEMON_ONLY"
        or value["deletion_authorized"] is not False
        or value["system_df_status"] not in ("OBSERVED", "UNAVAILABLE", "NOT_OBSERVED")
        or value["buildx_status"] not in ("OBSERVED", "UNAVAILABLE", "NOT_OBSERVED")
    ):
        raise CleanupError("rootless read-only disk accounting envelope invalid")
    rows = value["system_df"]
    if type(rows) is not list or len(rows) > 4:
        raise CleanupError("rootless disk accounting rows invalid")
    seen: set[str] = set()
    for row in rows:
        if type(row) is not dict or set(row) != {
            "kind",
            "total",
            "active",
            "size_display",
            "reclaimable_display",
        }:
            raise CleanupError("rootless disk accounting row fields invalid")
        kind = row["kind"]
        if (
            type(kind) is not str
            or kind not in SYSTEM_DF_KINDS
            or kind in seen
            or type(row["total"]) is not int
            or type(row["active"]) is not int
            or not 0 <= row["active"] <= row["total"] <= 1_000_000
            or type(row["size_display"]) is not str
            or SAFE_SIZE_DISPLAY.fullmatch(row["size_display"]) is None
            or type(row["reclaimable_display"]) is not str
            or SAFE_RECLAIMABLE_DISPLAY.fullmatch(row["reclaimable_display"]) is None
        ):
            raise CleanupError("rootless disk accounting row evidence invalid")
        seen.add(kind)
    if (value["system_df_status"] == "OBSERVED") != bool(rows):
        raise CleanupError("rootless disk accounting status contradictory")
    if rows != sorted(rows, key=lambda row: row["kind"]):
        raise CleanupError("rootless disk accounting rows unsorted")
    buildx = value["buildx"]
    if (
        type(buildx) is not dict
        or set(buildx)
        != {
            "records",
            "total_record_bytes",
            "reclaimable_record_bytes",
            "shared_record_bytes",
            "mutable_records",
        }
        or any(type(entry) is not int or not 0 <= entry <= 2**54 for entry in buildx.values())
        or not 0 <= buildx["mutable_records"] <= buildx["records"] <= 1024
        or not 0 <= buildx["reclaimable_record_bytes"] <= buildx["total_record_bytes"]
        or not 0 <= buildx["shared_record_bytes"] <= buildx["total_record_bytes"]
        or (value["buildx_status"] != "OBSERVED" and any(buildx.values()))
    ):
        raise CleanupError("rootless Buildx aggregate accounting invalid")


def _observe_boca_reference_image(ident: str, snapshot: Inventory) -> dict[str, object]:
    """Bounded public provenance of one Boca-*referenced* rootless image, no writes.

    A repository-prefix match is only permission to read a tiny fixed metadata
    subset, never proof that the image is Boca-owned or safe to delete. Images
    appearing only in the global ID census and arbitrary foreign references
    are not probed; non-Boca aliases are counted, never echoed.
    """
    if (
        HEX_ID.fullmatch(ident) is None
        or ident not in {item.ident for item in snapshot.images}
        or ident not in snapshot.global_image_ids
        or ident in {item.image_id for item in snapshot.containers}
    ):
        raise CleanupError("reference-only image provenance identity unproven")
    reference_filter = "reference=ghcr.io/mbalbo2023/boca-socios-assistant*"
    if ident not in _ids(
        "image", "ls", "-a", "-q", "--no-trunc", "--filter", reference_filter, dedupe=True
    ):
        raise CleanupError("reference-only image no longer has Boca repository signal")
    if _inspect_field("image", ident, "Id") != ident:
        raise CleanupError("reference-only image changed ID during provenance read")
    raw_tags = _inspect_field("image", ident, "RepoTags") or []
    raw_digests = _inspect_field("image", ident, "RepoDigests") or []
    image_size = _inspect_field("image", ident, "Size")
    if (
        not isinstance(raw_tags, list)
        or not isinstance(raw_digests, list)
        or len(raw_tags) + len(raw_digests) > 32
        or any(type(ref) is not str or not 0 < len(ref) <= 256 for ref in raw_tags + raw_digests)
        or type(image_size) is not int
        or not 0 <= image_size <= 16 * 1024**3
    ):
        raise CleanupError("reference-only image metadata malformed")
    public_tags = sorted({tag for tag in raw_tags if BOCA_PUBLIC_SHA_TAG.fullmatch(tag)})
    public_digests = sorted(
        {digest for digest in raw_digests if BOCA_PUBLIC_DIGEST.fullmatch(digest)}
    )
    untrusted_alias_count = (
        len(raw_tags) + len(raw_digests) - len(public_tags) - len(public_digests)
    )
    source = _inspect_image_public_oci_label(ident, "org.opencontainers.image.source")
    revision = _inspect_image_public_oci_label(ident, "org.opencontainers.image.revision")
    source_status = "BOCA" if source == BOCA_SOURCE else "ABSENT" if not source else "UNVERIFIED"
    valid_revision = (
        revision if isinstance(revision, str) and re.fullmatch(r"[0-9a-f]{40}", revision) else None
    )
    # Reconfirm the positive Boca reference filter after the individual reads.
    if ident not in _ids(
        "image", "ls", "-a", "-q", "--no-trunc", "--filter", reference_filter, dedupe=True
    ):
        raise CleanupError("reference-only image provenance raced with Docker tag change")
    return {
        "id": ident,
        "repo_tags": public_tags,
        "repo_digests": public_digests,
        "untrusted_alias_count": untrusted_alias_count,
        "oci_source_status": source_status,
        "oci_revision": valid_revision,
        "logical_size_bytes": image_size,
        "container_ref_count": sum(c.image_id == ident for c in snapshot.containers),
        "deletion_authorized": False,
    }


def _readonly_disk(snapshot: DiskInodes) -> dict[str, int]:
    fields = {
        "stage_bytes_free": snapshot.bytes_free,
        "stage_inodes_free": snapshot.inodes_free,
        "docker_bytes_free": snapshot.docker_bytes_free,
        "docker_inodes_free": snapshot.docker_inodes_free,
        "stage_device": snapshot.stage_device,
        "stage_inode": snapshot.stage_inode,
        "docker_device": snapshot.docker_device,
        "docker_inode": snapshot.docker_inode,
    }
    if any(type(value) is not int or value < 0 for value in fields.values()):
        raise CleanupError("Boca physical cleanup inventory metrics absent")
    return {name: value for name, value in fields.items() if isinstance(value, int)}


def _readonly_original(snapshot: Inventory, legacy_id: str) -> Container:
    if (
        any(
            _labels(item.labels).get("com.docker.compose.project") != BOCA_PROJECT
            for item in snapshot.containers
        )
        or any(
            _labels(item.labels).get("com.docker.compose.project") != BOCA_PROJECT
            for item in snapshot.networks
        )
        or any(
            _labels(item.labels).get("com.docker.compose.project") != BOCA_PROJECT
            for item in snapshot.volumes
        )
    ):
        raise CleanupError("foreign resources cannot be part of Boca-only read-only plan")
    matches = [container for container in snapshot.containers if container.ident == legacy_id]
    if len(matches) != 1:
        raise CleanupError("original Boca controller missing from exact inventory")
    original = matches[0]
    labels = _labels(original.labels)
    if (
        original.name != "/boca-socios-controller-1"
        or not original.running
        or labels.get("com.docker.compose.project") != BOCA_PROJECT
        or labels.get("com.docker.compose.service") != "controller"
        or not PERSISTENT_VOLUMES.difference({"boca-socios_boca_telegram"}) <= set(original.volumes)
        or len([item for item in snapshot.containers if item.running]) != 1
        or not HEX_ID.fullmatch(original.image_id)
        or original.image_id not in snapshot.global_image_ids
    ):
        raise CleanupError("original Boca controller not positively preserved")
    return original


def observe_postapply_cleanup(
    incident_run_id: str,
    legacy_id: str,
    *,
    probe: Callable[[], Inventory] = capture_inventory,
    probe_provenance: Callable[[str, Inventory], dict[str, object]] | None = None,
    probe_storage: Callable[[], dict[str, object]] | None = None,
    probe_host_crypto: Callable[[], dict[str, object]] | None = None,
    probe_owner_metadata: Callable[[Inventory], dict[str, object]] | None = None,
) -> dict[str, object]:
    """Two stable, Boca-only READ_ONLY snapshots and a *nonexecuted* cleanup plan.

    A reported clean inventory does not retroactively certify the failed APPLY;
    this API NEVER calls delete_exact/execute/execute_protected or returns GO.
    """
    if (
        type(incident_run_id) is not str
        or ATTEMPT_ID.fullmatch(incident_run_id) is None
        or type(legacy_id) is not str
        or HEX_ID.fullmatch(legacy_id) is None
    ):
        raise CleanupError("Boca post-APPLY cleanup observation IDs invalid")
    first = probe()
    second = probe()
    _validate_inventory(first)
    _validate_inventory(second)
    if (
        first.containers,
        first.images,
        first.networks,
        first.volumes,
        first.global_image_ids,
    ) != (
        second.containers,
        second.images,
        second.networks,
        second.volumes,
        second.global_image_ids,
    ) or _storage_topology_changed(first.disk, second.disk):
        raise CleanupError("Boca Docker inventory drifted during read-only observation")
    original = _readonly_original(first, legacy_id)
    _readonly_original(second, legacy_id)
    proposed = plan(
        second,
        incident_run_id,
        preserve_images=frozenset({original.image_id}),
        preserve_containers=frozenset({legacy_id}),
        retire_containers=frozenset(),
    )
    # The image-ID census may contain untagged images with no reviewed Boca
    # signal. Never inspect or publish those unknown exact IDs; their mere
    # presence precludes a declaration that the inventory is fully clean.
    unknown_image_ids = second.global_image_ids - {image.ident for image in second.images}
    unknown_reasons = (
        *proposed.uncertain,
        *(("rootless-unclassified-image-ids-present",) if unknown_image_ids else ()),
    )
    provenance_ids = sorted(
        image.ident
        for image in second.images
        if any(reason.startswith(f"image:{image.ident}:") for reason in proposed.uncertain)
    )
    if len(provenance_ids) > READONLY_PROVENANCE_LIMIT:
        raise CleanupError("reference-only image provenance exceeds protected bound")
    provenance: list[dict[str, object]] = []
    if probe_provenance is not None:
        for ident in provenance_ids:
            earlier = probe_provenance(ident, first)
            later = probe_provenance(ident, second)
            if earlier != later:
                raise CleanupError("reference-only image provenance drifted")
            provenance.append(later)
    classification = (
        "INDETERMINATE"
        if unknown_reasons
        else "BOCA_REMNANTS_IDENTIFIED"
        if proposed.targets
        else "NO_CONFIRMED_REMNANTS"
    )
    result: dict[str, object] = {
        "version": READONLY_CLEANUP_VERSION,
        "incident_run_id": incident_run_id,
        "legacy_id": legacy_id,
        "protected_image_id": original.image_id,
        "scope": "BOCA_ROOTLESS_ONLY",
        "status": "READ_ONLY_NO_GO",
        "classification": classification,
        "container_count": len(second.containers),
        "image_count": len(second.images),
        "rootless_image_id_count": len(second.global_image_ids),
        "unclassified_image_id_count": len(unknown_image_ids),
        "network_count": len(second.networks),
        "volume_count": len(second.volumes),
        "known_remnants": [
            {"kind": target.kind, "id": target.ident} for target in proposed.targets
        ],
        "retained_uncertain": list(unknown_reasons),
        "image_provenance": provenance,
        "storage_accounting": probe_storage()
        if probe_storage is not None
        else _empty_rootless_disk_accounting(),
        "host_python_crypto": probe_host_crypto()
        if probe_host_crypto is not None
        else _empty_host_python_crypto(),
        "owner_volume_metadata": probe_owner_metadata(second)
        if probe_owner_metadata is not None
        else _empty_owner_metadata(),
        "before": _readonly_disk(first.disk),
        "after": _readonly_disk(second.disk),
        "original_preserved": True,
        "cleanup_executed": False,
        "observer_writes": 0,
        "go_for_retry": False,
    }
    verify_readonly_cleanup_receipt(
        canonical_readonly_cleanup_receipt(result), incident_run_id, legacy_id
    )
    return result


def canonical_readonly_cleanup_receipt(receipt: dict[str, object]) -> bytes:
    """Canonical bounded ASCII, never raw Docker or host environment output."""
    try:
        encoded = (
            json.dumps(
                receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
            ).encode("ascii")
            + b"\n"
        )
    except (TypeError, ValueError) as exc:
        raise CleanupError("Boca read-only receipt cannot be encoded") from exc
    if not 0 < len(encoded) <= READONLY_CLEANUP_MAX_JSON:
        raise CleanupError("Boca read-only cleanup receipt exceeds bound")
    return encoded


def verify_readonly_cleanup_receipt(
    raw: bytes, incident_run_id: str, legacy_id: str
) -> dict[str, object]:
    """Runner-side exact read-only contract; never converts diagnosis to GO."""
    if (
        not 0 < len(raw) <= READONLY_CLEANUP_MAX_JSON
        or not raw.endswith(b"\n")
        or raw.count(b"\n") != 1
        or ATTEMPT_ID.fullmatch(incident_run_id) is None
        or HEX_ID.fullmatch(legacy_id) is None
    ):
        raise CleanupError("Boca read-only cleanup receipt envelope invalid")
    try:

        def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
            value: dict[str, object] = {}
            for key, item in pairs:
                if key in value:
                    raise CleanupError("duplicate Boca cleanup receipt field")
                value[key] = item
            return value

        obj = json.loads(raw.decode("ascii"), object_pairs_hook=reject_duplicates)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise CleanupError("Boca read-only cleanup receipt JSON untrusted") from exc
    fields = {
        "version",
        "incident_run_id",
        "legacy_id",
        "protected_image_id",
        "scope",
        "status",
        "classification",
        "container_count",
        "image_count",
        "rootless_image_id_count",
        "unclassified_image_id_count",
        "network_count",
        "volume_count",
        "known_remnants",
        "retained_uncertain",
        "image_provenance",
        "storage_accounting",
        "host_python_crypto",
        "owner_volume_metadata",
        "before",
        "after",
        "original_preserved",
        "cleanup_executed",
        "observer_writes",
        "go_for_retry",
    }
    if (
        type(obj) is not dict
        or set(obj) != fields
        or obj.get("version") != READONLY_CLEANUP_VERSION
        or obj.get("incident_run_id") != incident_run_id
        or obj.get("legacy_id") != legacy_id
        or obj.get("scope") != "BOCA_ROOTLESS_ONLY"
        or obj.get("status") != "READ_ONLY_NO_GO"
        or obj.get("original_preserved") is not True
        or obj.get("cleanup_executed") is not False
        or obj.get("observer_writes") != 0
        or type(obj.get("observer_writes")) is not int
        or obj.get("go_for_retry") is not False
        or type(obj.get("protected_image_id")) is not str
        or HEX_ID.fullmatch(obj["protected_image_id"]) is None
        or any(
            type(obj.get(name)) is not int or not 0 <= obj[name] <= MAX_OBJECTS
            for name in (
                "container_count",
                "image_count",
                "rootless_image_id_count",
                "unclassified_image_id_count",
                "network_count",
                "volume_count",
            )
        )
        or obj.get("container_count", 0) < 1
        or obj["image_count"] + obj["unclassified_image_id_count"] != obj["rootless_image_id_count"]
    ):
        raise CleanupError("Boca read-only cleanup status or identity invalid")
    before, after = obj["before"], obj["after"]
    expected_disk = {
        "stage_bytes_free",
        "stage_inodes_free",
        "docker_bytes_free",
        "docker_inodes_free",
        "stage_device",
        "stage_inode",
        "docker_device",
        "docker_inode",
    }
    if any(
        type(disk) is not dict
        or set(disk) != expected_disk
        or any(type(value) is not int or value < 0 for value in disk.values())
        for disk in (before, after)
    ) or any(
        before[field] != after[field]
        for field in ("stage_device", "stage_inode", "docker_device", "docker_inode")
    ):
        raise CleanupError("Boca read-only cleanup disk/inodes unverified")
    remnants, unknown = obj["known_remnants"], obj["retained_uncertain"]
    if (
        type(remnants) is not list
        or len(remnants) > MAX_DELETIONS
        or type(unknown) is not list
        or len(unknown) > MAX_OBJECTS
        or any(
            type(row) is not dict
            or set(row) != {"kind", "id"}
            or row["kind"] not in ("container", "image", "volume", "network")
            or type(row["id"]) is not str
            or not (
                row["kind"] == "volume"
                and DOCKER_NAME.fullmatch(row["id"]) is not None
                and row["id"].startswith("boca-socios_")
                and row["id"] not in PERSISTENT_VOLUMES
                or row["kind"] != "volume"
                and HEX_ID.fullmatch(row["id"]) is not None
            )
            for row in remnants
        )
        or any(
            type(reason) is not str or re.fullmatch(r"[A-Za-z0-9:_.-]{1,220}", reason) is None
            for reason in unknown
        )
        or len({(row["kind"], row["id"]) for row in remnants}) != len(remnants)
        or any(row["id"] in (legacy_id, obj["protected_image_id"]) for row in remnants)
    ):
        raise CleanupError("Boca cleanup candidate classifications untrusted")
    provenance = obj["image_provenance"]
    if (
        type(provenance) is not list
        or len(provenance) > READONLY_PROVENANCE_LIMIT
        or any(
            type(row) is not dict
            or set(row)
            != {
                "id",
                "repo_tags",
                "repo_digests",
                "untrusted_alias_count",
                "oci_source_status",
                "oci_revision",
                "logical_size_bytes",
                "container_ref_count",
                "deletion_authorized",
            }
            or type(row["id"]) is not str
            or HEX_ID.fullmatch(row["id"]) is None
            or row["id"] == obj["protected_image_id"]
            or f"image:{row['id']}:unverified-provenance-or-shared-reference" not in unknown
            or type(row["repo_tags"]) is not list
            or any(
                type(ref) is not str or BOCA_PUBLIC_SHA_TAG.fullmatch(ref) is None
                for ref in row["repo_tags"]
            )
            or row["repo_tags"] != sorted(set(row["repo_tags"]))
            or type(row["repo_digests"]) is not list
            or any(
                type(ref) is not str or BOCA_PUBLIC_DIGEST.fullmatch(ref) is None
                for ref in row["repo_digests"]
            )
            or row["repo_digests"] != sorted(set(row["repo_digests"]))
            or type(row["untrusted_alias_count"]) is not int
            or not 0 <= row["untrusted_alias_count"] <= 32
            or row["oci_source_status"] not in ("BOCA", "ABSENT", "UNVERIFIED")
            or (
                row["oci_revision"] is not None
                and (
                    type(row["oci_revision"]) is not str
                    or re.fullmatch(r"[0-9a-f]{40}", row["oci_revision"]) is None
                )
            )
            or type(row["logical_size_bytes"]) is not int
            or not 0 <= row["logical_size_bytes"] <= 16 * 1024**3
            or type(row["container_ref_count"]) is not int
            or row["container_ref_count"] != 0
            or row["deletion_authorized"] is not False
            for row in provenance
        )
        or len({row["id"] for row in provenance}) != len(provenance)
        or provenance != sorted(provenance, key=lambda row: row["id"])
    ):
        raise CleanupError("Boca public image provenance receipt untrusted")
    _validate_rootless_disk_accounting(obj["storage_accounting"])
    _validate_host_python_crypto(obj["host_python_crypto"])
    _validate_owner_metadata(obj["owner_volume_metadata"])
    expected_classification = (
        "INDETERMINATE"
        if unknown
        else "BOCA_REMNANTS_IDENTIFIED"
        if remnants
        else "NO_CONFIRMED_REMNANTS"
    )
    if (
        obj.get("classification") != expected_classification
        or canonical_readonly_cleanup_receipt(obj) != raw
    ):
        raise CleanupError("Boca read-only cleanup receipt classification or bytes invalid")
    return obj


def _readonly_main(args: list[str]) -> int:
    if len(args) != 3 or args[0] not in ("host", "verify"):
        print("BOCA_CLEANUP_RECONCILE state=NO_GO reason=INPUT", file=sys.stderr)
        return 3
    mode, incident_run_id, legacy_id = args
    try:
        if mode == "host":
            if os.geteuid() != EXPECTED_UID or os.getegid() != EXPECTED_GID:
                raise CleanupError("read-only cleanup requires exact Boca rootless identity")
            receipt = observe_postapply_cleanup(
                incident_run_id,
                legacy_id,
                probe_provenance=_observe_boca_reference_image,
                probe_storage=_read_rootless_storage_usage,
                probe_host_crypto=_probe_host_python_crypto,
                probe_owner_metadata=_read_owner_public_metadata,
            )
            sys.stdout.buffer.write(canonical_readonly_cleanup_receipt(receipt))
        else:
            receipt = verify_readonly_cleanup_receipt(
                sys.stdin.buffer.read(READONLY_CLEANUP_MAX_JSON + 1), incident_run_id, legacy_id
            )
            print(
                "BOCA_CLEANUP_RECONCILE state=READ_ONLY_NO_GO"
                f" classification={receipt['classification']}"
                f" known={len(cast(list[object], receipt['known_remnants']))}"
                f" uncertain={len(cast(list[object], receipt['retained_uncertain']))}"
                " original=preserved cleanup_executed=false"
                " observer_writes=0 retry=NO_GO"
            )
        return 0
    except (CleanupError, OSError, TypeError, ValueError):
        print("BOCA_CLEANUP_RECONCILE state=NO_GO reason=UNVERIFIED", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(_readonly_main(sys.argv[1:]))
