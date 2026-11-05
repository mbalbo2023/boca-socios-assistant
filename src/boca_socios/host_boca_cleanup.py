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
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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
        "image": frozenset({"Id", "RepoTags", "RepoDigests", "Config.Labels"}),
        "network": frozenset({"Id", "Name", "Containers", "Labels"}),
        "volume": frozenset({"Name", "Labels"}),
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
