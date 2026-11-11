"""Cutover A singleton inventory, READ_ONLY on Boca's dedicated rootless daemon.

This module cannot perform a cutover, discover a release run ID, stage files,
write SQLite or contact Boca/Telegram. It only emits bounded observed Docker
coordinates for a future authenticated GitHub Actions PREPARE receipt.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from boca_socios import host_boca_cleanup as cleanup
from boca_socios.host_boca_cleanup import (
    BocaJobLease,
    Container,
    Inventory,
    protected_boca_job_lease,
    verify_protected_boca_job_lease,
)

_VERSION = "boca-cutover-inventory-observe-v1"
_OFFICIAL_VERSION = "boca-official-inventory-observe-v1"
_INPUT_FIELDS = frozenset(
    {
        "version",
        "target_source_sha",
        "target_controller_image",
        "target_browser_image",
        "target_release_run_id",
        "observe_run_id",
    }
)
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_B64 = re.compile(r"[A-Za-z0-9_-]{1,2750}\Z")
_CONTROLLER = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
_BROWSER = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant-browser@sha256:[0-9a-f]{64}\Z")
_PROJECT = "boca-socios"
_SOURCE = "https://github.com/mbalbo2023/boca-socios-assistant"
_BRIDGE = "boca-socios_boca_private"
_DATA = "boca-socios_boca_data"
_KEY = "boca-socios_boca_key"
_OWNER = "boca-socios_boca_owner"
_TELEGRAM = "boca-socios_boca_telegram"
_EXPECTED_VOLUMES = frozenset({_DATA, _KEY, _OWNER})
_PORT_BINDING = {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
_MOUNTS = frozenset(
    {
        (_DATA, "/data", True),
        (_KEY, "/run/secrets", False),
        (_OWNER, "/run/owner", False),
    }
)


class CutoverInventoryNoGo(ValueError):
    """Legacy singleton could not be uniquely observed under the Boca lease."""


# Public diagnostics are intentionally *not* raw exception messages. Only
# exact hard-coded reasons may cross the SSH/GitHub runner boundary; paths,
# labels, credentials, Docker stderr and arbitrary Python exceptions cannot.
_CUTOVER_PUBLIC_REASONS = {
    "Boca bounded Docker field unavailable": "DOCKER_FIELD",
    "Boca dedicated network boundary missing": "NETWORK_BOUNDARY",
    "Boca historical Compose labels unavailable": "COMPOSE_LABELS",
    "Boca historical GHCR image not uniquely attested": "IMAGE_DIGEST",
    "Boca historical image provenance unavailable": "IMAGE_PROVENANCE",
    "Boca host UTC observation clock unverified": "HOST_CLOCK",
    "Boca legacy mounts changed": "MOUNTS",
    "Boca legacy secret/data mounts changed": "MOUNTS",
    "Boca legacy service isolation or health drifted": "SERVICE_HEALTH",
    "Boca legacy singleton absent or ambiguous": "LEGACY_SINGLETON",
    "Boca legacy singleton changed during observation": "SINGLETON_DRIFT",
    "Boca legacy volume mount unverified": "MOUNTS",
    "Boca named legacy data volume mount unavailable": "DATA_VOLUME",
    "Boca observer not running under dedicated rootless UID": "ROOTLESS_UID",
    "Boca original rootless network/volumes changed": "NETWORK_VOLUMES",
    "Boca owner volume identity unverified": "VOLUME_PROVENANCE",
    "Boca protected inventory context invalid": "INPUT_CONTEXT",
    "Boca rootless inventory observation unverified": "ROOTLESS_INVENTORY",
    "Boca running legacy controller identity unverified": "LEGACY_IDENTITY",
    "Boca legacy gained privileges": "PRIVILEGES",
    "Boca inventory Docker field unapproved": "DOCKER_FIELD_DENIED",
    "Boca public inventory receipt too large": "RECEIPT_BOUNDS",
    "reviewed Boca target release pins unavailable": "INPUT_RELEASE",
}
_CUTOVER_NO_GO_OTHER = "OBSERVER_UNVERIFIED"
_CUTOVER_NO_GO_TRANSPORT = "TRANSPORT_OR_BOOTSTRAP"
_CUTOVER_NO_GO_ALLOWED = frozenset(_CUTOVER_PUBLIC_REASONS.values()) | {
    _CUTOVER_NO_GO_OTHER,
}
_PUBLIC_NO_GO_LINE = re.compile(
    r"BOCA_CUTOVER_INVENTORY_OBSERVE state=NO_GO reason=([A-Z][A-Z0-9_]{2,63})\Z"
)


def _cutover_public_reason(error: Exception) -> str:
    """Map a genuine known source error to one enum; never expose error text."""
    if type(error) is CutoverInventoryNoGo:
        return _CUTOVER_PUBLIC_REASONS.get(str(error), _CUTOVER_NO_GO_OTHER)
    return _CUTOVER_NO_GO_OTHER


def parse_cutover_no_go_stderr(stderr: bytes) -> str:
    """Runner parser for a single bounded Boca-generated reason, not raw stderr."""
    if type(stderr) is not bytes or len(stderr) > 4096:
        return _CUTOVER_NO_GO_TRANSPORT
    try:
        lines = stderr.decode("ascii").splitlines()
    except UnicodeError:
        return _CUTOVER_NO_GO_TRANSPORT
    matches = [
        found.group(1)
        for line in lines
        if (found := _PUBLIC_NO_GO_LINE.fullmatch(line)) is not None
    ]
    if len(matches) != 1 or matches[0] not in _CUTOVER_NO_GO_ALLOWED:
        return _CUTOVER_NO_GO_TRANSPORT
    return matches[0]


@dataclass(frozen=True, slots=True)
class ReviewedTargetRelease:
    """Target pins authenticated by Actions, never supplied by Chrome."""

    target_source_sha: str
    target_controller_image: str
    target_browser_image: str
    target_release_run_id: str
    observe_run_id: str

    def require(self) -> None:
        if (
            any(
                type(value) is not str
                for value in (
                    self.target_source_sha,
                    self.target_controller_image,
                    self.target_browser_image,
                    self.target_release_run_id,
                    self.observe_run_id,
                )
            )
            or not _SHA.fullmatch(self.target_source_sha)
            or not _CONTROLLER.fullmatch(self.target_controller_image)
            or not _BROWSER.fullmatch(self.target_browser_image)
            or not _RUN.fullmatch(self.target_release_run_id)
            or not _RUN.fullmatch(self.observe_run_id)
            or self.target_release_run_id == self.observe_run_id
        ):
            raise CutoverInventoryNoGo("reviewed Boca target release pins unavailable")


class CutoverInventoryIO(Protocol):
    """Only bounded Boca Docker read methods; tests inject inert fixtures."""

    @property
    def uid(self) -> int: ...

    @property
    def gid(self) -> int: ...

    def inventory(self) -> Inventory: ...

    def field(self, kind: str, ident: str, field: str) -> object: ...


class ProductionCutoverInventoryIO:
    """Exact field-only Docker inspection under the dedicated Boca user."""

    @property
    def uid(self) -> int:
        return os.geteuid()

    @property
    def gid(self) -> int:
        return os.getegid()

    def inventory(self) -> Inventory:
        # This aborts if the rootless daemon contains ANY non-Boca workload.
        return cleanup.capture_inventory()

    def field(self, kind: str, ident: str, field: str) -> object:
        # The cleanup-only reader intentionally has a narrower allowlist:
        # Config.Image, HostConfig.*, State.Health and Mountpoint are NOT
        # permitted there. Cutover/official need a separate fixed read-only
        # projection, never a full inspect or Config.Env.
        container_fields = frozenset(
            {
                "Config.Image",
                "Config.User",
                "Config.Cmd",
                "HostConfig.NetworkMode",
                "HostConfig.RestartPolicy",
                "HostConfig.ReadonlyRootfs",
                "HostConfig.Privileged",
                "HostConfig.PublishAllPorts",
                "HostConfig.Init",
                "HostConfig.CapDrop",
                "HostConfig.CapAdd",
                "HostConfig.NanoCpus",
                "HostConfig.Memory",
                "HostConfig.PidsLimit",
                "HostConfig.PortBindings",
                "NetworkSettings.Ports",
                "NetworkSettings.Networks",
                "State.Running",
                "State.Restarting",
                "State.Health.Status",
                "RestartCount",
                "Mounts",
            }
        )
        if kind == "container" and _HASH.fullmatch(ident) and field in container_fields:
            argv: tuple[str, ...] = ("inspect",)
        elif kind == "volume" and ident == _DATA and field == "Mountpoint":
            argv = ("volume", "inspect")
        else:
            raise CutoverInventoryNoGo("Boca inventory Docker field unapproved")
        try:
            return json.loads(
                cleanup._docker(  # noqa: SLF001 - guarded dedicated Boca rootless CLI
                    *argv, "--format", "{{json ." + field + "}}", ident
                )
            )
        except (cleanup.CleanupError, ValueError, TypeError):
            raise CutoverInventoryNoGo("Boca bounded Docker field unavailable") from None


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CutoverInventoryNoGo("duplicate Boca inventory input key")
        result[key] = value
    return result


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    ).encode("ascii")


def decode_observe_input(
    encoded: str, *, expected_version: str = _VERSION
) -> ReviewedTargetRelease:
    """Reject any browser-generated, ambiguous or noncanonical context."""
    if expected_version not in (_VERSION, _OFFICIAL_VERSION):
        raise CutoverInventoryNoGo("Boca observer operation unsupported")
    if type(encoded) is not str or not _B64.fullmatch(encoded):
        raise CutoverInventoryNoGo("Boca inventory context encoding invalid")
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        if (
            not 0 < len(raw) <= 2048
            or base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != encoded
        ):
            raise ValueError("Boca inventory input noncanonical base64")
        data = json.loads(raw.decode("ascii"), object_pairs_hook=_unique)
        if (
            type(data) is not dict
            or set(data) != _INPUT_FIELDS
            or any(type(v) is not str for v in data.values())
            or _canonical(data) != raw
            or data["version"] != expected_version
        ):
            raise ValueError("Boca inventory schema noncanonical")
        release = ReviewedTargetRelease(
            target_source_sha=data["target_source_sha"],
            target_controller_image=data["target_controller_image"],
            target_browser_image=data["target_browser_image"],
            target_release_run_id=data["target_release_run_id"],
            observe_run_id=data["observe_run_id"],
        )
        release.require()
        return release
    except (
        ValueError,
        TypeError,
        KeyError,
        UnicodeError,
        binascii.Error,
        OverflowError,
    ):
        raise CutoverInventoryNoGo("Boca protected inventory context invalid") from None


def _labels(container: Container) -> dict[str, str]:
    labels = dict(container.labels)
    if len(labels) != len(container.labels) or any(
        type(key) is not str or type(value) is not str for key, value in container.labels
    ):
        raise CutoverInventoryNoGo("Boca installed legacy labels duplicated")
    return labels


def _mounts(value: object) -> frozenset[tuple[str, str, bool]]:
    if not isinstance(value, list) or len(value) != 3:
        raise CutoverInventoryNoGo("Boca legacy mounts changed")
    result: set[tuple[str, str, bool]] = set()
    for raw in value:
        if (
            type(raw) is not dict
            or raw.get("Type") != "volume"
            or raw.get("Driver") != "local"
            or type(raw.get("Name")) is not str
            or type(raw.get("Destination")) is not str
            or type(raw.get("RW")) is not bool
        ):
            raise CutoverInventoryNoGo("Boca legacy volume mount unverified")
        item = (raw["Name"], raw["Destination"], raw["RW"])
        if item in result:
            raise CutoverInventoryNoGo("Boca duplicate legacy mount")
        result.add(item)
    return frozenset(result)


def _observation(io: CutoverInventoryIO, release: ReviewedTargetRelease) -> dict[str, str]:
    inventory = io.inventory()
    if not isinstance(inventory, Inventory) or len(inventory.containers) != 1:
        raise CutoverInventoryNoGo("Boca legacy singleton absent or ambiguous")
    controller = inventory.containers[0]
    if (
        not isinstance(controller, Container)
        or not _HASH.fullmatch(controller.ident)
        or controller.name != "/boca-socios-controller-1"
        or not controller.running
        or not _DIGEST.fullmatch(controller.image_id)
        or controller.networks != (_BRIDGE,)
        or controller.volumes != tuple(sorted(_EXPECTED_VOLUMES))
    ):
        raise CutoverInventoryNoGo("Boca running legacy controller identity unverified")
    labels = _labels(controller)
    legacy_sha = labels.get("org.opencontainers.image.revision", "")
    config_hash = labels.get("com.docker.compose.config-hash", "")
    if (
        labels.get("com.docker.compose.project") != _PROJECT
        or labels.get("com.docker.compose.service") != "controller"
        or labels.get("com.docker.compose.container-number") != "1"
        or "boca.socios.browser-ipc-attempt" in labels
        or not _SHA.fullmatch(legacy_sha)
        or legacy_sha == release.target_source_sha
        or not _HASH.fullmatch(config_hash)
    ):
        raise CutoverInventoryNoGo("Boca historical Compose labels unavailable")
    images = [image for image in inventory.images if image.ident == controller.image_id]
    # Historical #41893887078 builds had the OCI revision label but not the
    # OCI *source* label. The generic cleanup inventory correctly marks those
    # images as unverified, and its trust/deletion policy MUST NOT be changed.
    # Cutover may instead observe the exact already-running container's image
    # ID and pinned GHCR Config.Image; the runner independently authenticates
    # its original source and immutable release manifest BEFORE PREPARE/GO/APPLY.
    if len(images) > 1 or (images and images[0].source not in (_SOURCE, None)):
        raise CutoverInventoryNoGo("Boca historical image provenance unavailable")
    if (
        not images or images[0].source is None
    ) and controller.image_id not in inventory.global_image_ids:
        raise CutoverInventoryNoGo("Boca historical image provenance unavailable")
    if (
        images
        and images[0].source is None
        and images[0].references != ("ghcr.io/mbalbo2023/boca-socios-assistant:unverified",)
    ):
        raise CutoverInventoryNoGo("Boca historical image provenance unavailable")
    ident = controller.ident
    image_ref = io.field("container", ident, "Config.Image")
    if (
        type(image_ref) is not str
        or not _CONTROLLER.fullmatch(image_ref)
        or image_ref == release.target_controller_image
        or images
        and images[0].source == _SOURCE
        and image_ref not in images[0].references
    ):
        raise CutoverInventoryNoGo("Boca historical GHCR image not uniquely attested")
    if (
        len(inventory.networks) != 1
        or inventory.networks[0].name != _BRIDGE
        or inventory.networks[0].attached_ids != (ident,)
        or set(x.name for x in inventory.volumes)
        not in (_EXPECTED_VOLUMES, _EXPECTED_VOLUMES | {_TELEGRAM})
    ):
        raise CutoverInventoryNoGo("Boca original rootless network/volumes changed")
    for volume in inventory.volumes:
        found = dict(volume.labels)
        if len(found) != len(volume.labels) or found.get("com.docker.compose.project") != _PROJECT:
            raise CutoverInventoryNoGo("Boca owner volume identity unverified")
    mount = io.field("volume", _DATA, "Mountpoint")
    if (
        type(mount) is not str
        or not Path(mount).is_absolute()
        or Path(mount) == Path("/")
        or ".." in Path(mount).parts
    ):
        raise CutoverInventoryNoGo("Boca named legacy data volume mount unavailable")
    # Read only allowlisted fixed Docker fields, never Config.Env or credentials.
    expected = {
        "Config.User": "10001:10001",
        "Config.Cmd": ["python", "-m", "boca_socios.runtime", "serve-beta"],
        "HostConfig.NetworkMode": _BRIDGE,
        "HostConfig.RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0},
        "HostConfig.ReadonlyRootfs": True,
        "HostConfig.Privileged": False,
        "HostConfig.PublishAllPorts": False,
        "HostConfig.Init": True,
        "HostConfig.CapDrop": ["ALL"],
        "HostConfig.NanoCpus": 500_000_000,
        "HostConfig.Memory": 268_435_456,
        "HostConfig.PidsLimit": 64,
        "HostConfig.PortBindings": _PORT_BINDING,
        "NetworkSettings.Ports": _PORT_BINDING,
        "State.Running": True,
        "State.Restarting": False,
        "State.Health.Status": "healthy",
        "RestartCount": 0,
    }
    for field, want in expected.items():
        if io.field("container", ident, field) != want:
            raise CutoverInventoryNoGo("Boca legacy service isolation or health drifted")
    if io.field("container", ident, "HostConfig.CapAdd") not in (None, []):
        raise CutoverInventoryNoGo("Boca legacy gained privileges")
    connected = io.field("container", ident, "NetworkSettings.Networks")
    if type(connected) is not dict or set(connected) != {_BRIDGE}:
        raise CutoverInventoryNoGo("Boca dedicated network boundary missing")
    if _mounts(io.field("container", ident, "Mounts")) != _MOUNTS:
        raise CutoverInventoryNoGo("Boca legacy secret/data mounts changed")
    return {
        "version": _VERSION,
        "kind": "cutover-inventory",
        "observe_run_id": release.observe_run_id,
        "target_source_sha": release.target_source_sha,
        "target_release_run_id": release.target_release_run_id,
        "legacy_controller_id": ident,
        "legacy_source_sha": legacy_sha,
        "legacy_image_ref": image_ref,
        "legacy_image_id": controller.image_id,
        "legacy_compose_config_hash": config_hash,
        "compose_project": _PROJECT,
        "compose_service": "controller",
        "port": "127.0.0.1:8443",
        "data_volume": _DATA,
        "key_volume": _KEY,
        "owner_volume": _OWNER,
        "controller_health": "healthy",
    }


def observe_cutover_inventory(
    release: ReviewedTargetRelease,
    *,
    lease: BocaJobLease,
    io: CutoverInventoryIO | None = None,
    observed_at: datetime | None = None,
) -> dict[str, str]:
    """Prove one unchanged original controller twice; never issue physical GO."""
    if not isinstance(release, ReviewedTargetRelease):
        raise CutoverInventoryNoGo("Boca reviewed target pins required")
    release.require()
    verify_protected_boca_job_lease(lease, release.observe_run_id)
    transport = ProductionCutoverInventoryIO() if io is None else io
    if transport.uid != cleanup.EXPECTED_UID or transport.gid != cleanup.EXPECTED_GID:
        raise CutoverInventoryNoGo("Boca observer not running under dedicated rootless UID")
    try:
        first = _observation(transport, release)
        second = _observation(transport, release)
        if first != second:
            raise CutoverInventoryNoGo("Boca legacy singleton changed during observation")
        verify_protected_boca_job_lease(lease, release.observe_run_id)
        timestamp = datetime.now(UTC) if observed_at is None else observed_at
        offset = timestamp.utcoffset() if isinstance(timestamp, datetime) else None
        if (
            not isinstance(timestamp, datetime)
            or timestamp.tzinfo is None
            or offset is None
            or offset.total_seconds() != 0
        ):
            raise CutoverInventoryNoGo("Boca host UTC observation clock unverified")
        first["observed_at_utc"] = (
            timestamp.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )
        if not 0 < len(_canonical(first)) <= 2048:
            raise CutoverInventoryNoGo("Boca public inventory receipt too large")
        return first
    except CutoverInventoryNoGo:
        raise
    except (cleanup.CleanupError, OSError, KeyError, TypeError, ValueError, RuntimeError):
        raise CutoverInventoryNoGo("Boca rootless inventory observation unverified") from None


def main(argv: list[str] | None = None) -> int:
    """Return one canonical JSON line on PASS, stderr NO_GO without host data."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("BOCA_CUTOVER_INVENTORY_OBSERVE state=NO_GO", file=sys.stderr)
        return 3
    try:
        release = decode_observe_input(args[0])
        with protected_boca_job_lease(release.observe_run_id) as lease:
            public = observe_cutover_inventory(release, lease=lease)
        print(_canonical(public).decode("ascii"))
        return 0
    except Exception as exc:
        print(
            f"BOCA_CUTOVER_INVENTORY_OBSERVE state=NO_GO reason={_cutover_public_reason(exc)}",
            file=sys.stderr,
        )
        return 3


def selftest_main() -> int:
    """Memfd/Python -S smoke without Docker, SQLite or network."""
    ReviewedTargetRelease(
        target_source_sha="a" * 40,
        target_controller_image="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64,
        target_browser_image="ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "c" * 64,
        target_release_run_id="1001",
        observe_run_id="1002",
    ).require()
    print("BOCA_CUTOVER_INVENTORY_MEMFD state=PASS host=untouched blackbox=excluded")
    return 0


def _official_observation(io: CutoverInventoryIO, release: ReviewedTargetRelease) -> dict[str, str]:
    """Read the installed dual/tri-service Boca topology, without REQUESTED or exec."""
    from boca_socios import host_lifecycle_observe as lifecycle_observe
    from boca_socios import host_lifecycle_rootless_adapter as adapter

    reviewed = lifecycle_observe.ReviewedObserveRelease(
        source_sha=release.target_source_sha,
        controller_image=release.target_controller_image,
        worker_image=release.target_browser_image,
        release_run_id=release.target_release_run_id,
        observe_run_id=release.observe_run_id,
    )
    reviewed.require()
    inventory = io.inventory()
    controller, worker, sender, pair = lifecycle_observe._selected_services(  # noqa: SLF001
        inventory, reviewed
    )
    image_map = {item.ident: item for item in inventory.images}
    if len(image_map) != len(inventory.images):
        raise CutoverInventoryNoGo("Boca official image inventory duplicated")
    services = [
        (controller, "controller", release.target_controller_image),
        (worker, "browser-worker", release.target_browser_image),
    ]
    if sender is not None:
        services.append((sender, "telegram", release.target_controller_image))
    probe = adapter.RootlessLifecycleProbe(pair, cast(adapter.LifecycleDockerIO, io))
    for container, service, reference in services:
        image = image_map.get(container.image_id)
        if (
            image is None
            or image.source != _SOURCE
            or reference not in image.references
            or not _DIGEST.fullmatch(container.image_id)
        ):
            raise CutoverInventoryNoGo("Boca official installed GHCR image drifted")
        probe._service_boundary(container.ident, service, reference)  # noqa: SLF001
    if (
        controller.networks != (_BRIDGE,)
        or worker.networks not in ((), ("boca-socios_boca_browser_egress",))
        or worker.running
        and worker.networks != ("boca-socios_boca_browser_egress",)
        or controller.volumes
        != tuple(
            sorted(
                {
                    _DATA,
                    _KEY,
                    _OWNER,
                    "boca-socios_boca_browser_ipc",
                    "boca-socios_boca_site_config",
                }
            )
        )
        or worker.volumes
        != tuple(sorted(("boca-socios_boca_browser_ipc", "boca-socios_boca_site_config")))
        or not controller.running
        or io.field("container", controller.ident, "State.Running") is not True
        or io.field("container", controller.ident, "State.Health.Status") != "healthy"
        or io.field("container", worker.ident, "State.Running") is not worker.running
        or worker.running
        and io.field("container", worker.ident, "State.Health.Status") != "healthy"
        or sender is not None
        and io.field("container", sender.ident, "State.Running") is not sender.running
    ):
        raise CutoverInventoryNoGo("Boca official dual runtime not verified")
    egress = "boca-socios_boca_telegram_egress"
    expected_volumes = {
        _DATA,
        _KEY,
        _OWNER,
        "boca-socios_boca_browser_ipc",
        "boca-socios_boca_site_config",
    }
    if sender is not None:
        expected_volumes.add(_TELEGRAM)
        if sender.networks not in ((), (egress,)) or (
            sender.running and sender.networks != (egress,)
        ):
            raise CutoverInventoryNoGo("Boca official Telegram egress boundary unavailable")
    if {item.name for item in inventory.volumes} != expected_volumes:
        raise CutoverInventoryNoGo("Boca official persistent volumes changed")
    for volume in inventory.volumes:
        labels = dict(volume.labels)
        if (
            len(labels) != len(volume.labels)
            or labels.get("com.docker.compose.project") != _PROJECT
        ):
            raise CutoverInventoryNoGo("Boca official volume label provenance unavailable")
    browser_egress = "boca-socios_boca_browser_egress"
    if any(network.name not in (_BRIDGE, browser_egress, egress) for network in inventory.networks):
        raise CutoverInventoryNoGo("Boca official network outside project")
    by_name = {network.name: network for network in inventory.networks}
    if (
        len(by_name) != len(inventory.networks)
        or _BRIDGE not in by_name
        or by_name[_BRIDGE].attached_ids != (controller.ident,)
        or browser_egress not in by_name
        or by_name[browser_egress].attached_ids != ((worker.ident,) if worker.running else ())
        or sender is not None
        and sender.running
        and egress not in by_name
        or egress in by_name
        and by_name[egress].attached_ids
        != ((sender.ident,) if sender is not None and sender.running else ())
    ):
        raise CutoverInventoryNoGo("Boca official network attachments ambiguous")
    data_mount = io.field("volume", _DATA, "Mountpoint")
    if (
        type(data_mount) is not str
        or not Path(data_mount).is_absolute()
        or Path(data_mount) == Path("/")
        or ".." in Path(data_mount).parts
    ):
        raise CutoverInventoryNoGo("Boca official data mount unavailable")
    result = {
        "version": _OFFICIAL_VERSION,
        "kind": "official-inventory",
        "observe_run_id": release.observe_run_id,
        "source_sha": release.target_source_sha,
        "release_run_id": release.target_release_run_id,
        "controller_id": controller.ident,
        "controller_image": release.target_controller_image,
        "worker_id": worker.ident,
        "worker_image": release.target_browser_image,
        "browser_attempt": pair.original_browser_attempt,
        "controller_config_hash": pair.controller_config_hash,
        "worker_config_hash": pair.worker_config_hash,
        "port": "127.0.0.1:8443",
        "data_volume": _DATA,
    }
    if sender is not None:
        result.update(
            {
                "sender_id": pair.sender_id,
                "sender_config_hash": pair.sender_config_hash,
                "sender_attempt_id": pair.sender_attempt_id,
                "sender_state": "on" if sender.running else "off",
            }
        )
    return result


def observe_official_inventory(
    release: ReviewedTargetRelease,
    *,
    lease: BocaJobLease,
    io: CutoverInventoryIO | None = None,
    observed_at: datetime | None = None,
) -> dict[str, str]:
    """Observe CURRENT main controller and worker twice, no lifecycle REQUESTED."""
    if not isinstance(release, ReviewedTargetRelease):
        raise CutoverInventoryNoGo("Boca reviewed current release required")
    release.require()
    verify_protected_boca_job_lease(lease, release.observe_run_id)
    transport = ProductionCutoverInventoryIO() if io is None else io
    if transport.uid != cleanup.EXPECTED_UID or transport.gid != cleanup.EXPECTED_GID:
        raise CutoverInventoryNoGo("Boca official observer not rootless owner")
    try:
        first = _official_observation(transport, release)
        if first != _official_observation(transport, release):
            raise CutoverInventoryNoGo("Boca official controller changed during observation")
        verify_protected_boca_job_lease(lease, release.observe_run_id)
        timestamp = datetime.now(UTC) if observed_at is None else observed_at
        offset = timestamp.utcoffset() if isinstance(timestamp, datetime) else None
        if (
            not isinstance(timestamp, datetime)
            or timestamp.tzinfo is None
            or offset is None
            or offset.total_seconds() != 0
        ):
            raise CutoverInventoryNoGo("Boca official UTC host clock invalid")
        first["observed_at_utc"] = (
            timestamp.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )
        if not 0 < len(_canonical(first)) <= 2048:
            raise CutoverInventoryNoGo("Boca official inventory receipt oversized")
        return first
    except CutoverInventoryNoGo:
        raise
    except (
        cleanup.CleanupError,
        RuntimeError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
    ):
        raise CutoverInventoryNoGo("Boca official rootless observation unverified") from None


def official_main(argv: list[str] | None = None) -> int:
    """One public canonical JSON line only on PASS; invalid context is inert."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("BOCA_OFFICIAL_INVENTORY_OBSERVE state=NO_GO", file=sys.stderr)
        return 3
    try:
        release = decode_observe_input(args[0], expected_version=_OFFICIAL_VERSION)
        with protected_boca_job_lease(release.observe_run_id) as lease:
            public = observe_official_inventory(release, lease=lease)
        print(_canonical(public).decode("ascii"))
        return 0
    except Exception:
        print("BOCA_OFFICIAL_INVENTORY_OBSERVE state=NO_GO", file=sys.stderr)
        return 3


def official_selftest_main() -> int:
    """Stdlib-only ZIP smoke; does not enter the Docker inspector."""
    ReviewedTargetRelease(
        target_source_sha="a" * 40,
        target_controller_image="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64,
        target_browser_image="ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "c" * 64,
        target_release_run_id="1001",
        observe_run_id="1002",
    ).require()
    print("BOCA_OFFICIAL_INVENTORY_MEMFD state=PASS host=untouched blackbox=excluded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
