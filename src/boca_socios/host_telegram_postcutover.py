"""Read-only Boca Telegram post-cutover topology witness (ADR0160, #357).

This is NOT an activation caller. It deliberately has no CLI, token, Bot API,
crypto key, Docker mutations or protected GO surface. A successful observation
cannot stand in for fresh passkey/HMAC owner authority, staged ciphertext
verification, same-lease four Telegram GETs or signed custody commitment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from boca_socios.host_boca_cleanup import (
    BocaJobLease,
    Container,
    Image,
    Inventory,
    verify_protected_boca_job_lease,
)
from boca_socios.host_lifecycle_rootless_adapter import (
    LifecycleDockerIO,
    ProductionRootlessDockerIO,
    ReviewedInstalledPair,
    RootlessLifecycleProbe,
    _mounts,
)

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_ID = re.compile(r"[0-9a-f]{64}\Z")
_DECIMAL = re.compile(r"[1-9][0-9]{0,19}\Z")
_IMAGE = re.compile(r"ghcr[.]io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
_WORKER_IMAGE = re.compile(
    r"ghcr[.]io/mbalbo2023/boca-socios-assistant-browser@sha256:[0-9a-f]{64}\Z"
)
_SOURCE = "https://github.com/mbalbo2023/boca-socios-assistant"
_PROJECT = "boca-socios"
_DATA = "boca-socios_boca_data"
_IPC = "boca-socios_boca_browser_ipc"
_TELEGRAM = "boca-socios_boca_telegram"
_PRIVATE = "boca-socios_boca_private"
_EGRESS = "boca-socios_boca_telegram_egress"
_VOLUMES = {_DATA, _IPC, _TELEGRAM, "boca-socios_boca_key", "boca-socios_boca_owner"}
_ATTEMPT = "boca.socios.browser-ipc-attempt"
_REVISION = "org.opencontainers.image.revision"
_CONFIG = "com.docker.compose.config-hash"


class TelegramHostNoGo(ValueError):
    """Only static non-secret NO_GO diagnostics may cross the workflow boundary."""


@dataclass(frozen=True, slots=True)
class TelegramHostPins:
    """Nonsecret, UNTRUSTED workflow pins; every field needs independent proof."""

    version: str
    kind: str
    attempt_id: str
    source_sha: str
    controller_id: str
    controller_image: str
    worker_id: str
    worker_image: str
    browser_attempt: str
    controller_config_hash: str
    worker_config_hash: str
    data_mountpoint: str
    cutover_attempt: str
    cutover_receipt_sha256: str
    owner_digest: str
    recipient_fingerprint: str
    sender_expected_state: Literal["absent", "stopped"]
    sender_id: str = ""
    sender_image: str = ""
    sender_config_hash: str = ""
    sender_attempt: str = ""

    def require(self) -> None:
        if (
            self.version != "boca-protected-action-v1"
            or self.kind != "telegram"
            or any(
                not isinstance(value, str)
                for value in (
                    self.attempt_id,
                    self.source_sha,
                    self.controller_id,
                    self.controller_image,
                    self.worker_id,
                    self.worker_image,
                    self.browser_attempt,
                    self.controller_config_hash,
                    self.worker_config_hash,
                    self.data_mountpoint,
                    self.cutover_attempt,
                    self.cutover_receipt_sha256,
                    self.owner_digest,
                    self.recipient_fingerprint,
                    self.sender_id,
                    self.sender_image,
                    self.sender_config_hash,
                    self.sender_attempt,
                )
            )
            or not _DECIMAL.fullmatch(self.attempt_id)
            or not _DECIMAL.fullmatch(self.browser_attempt)
            or not _DECIMAL.fullmatch(self.cutover_attempt)
            or not _SHA.fullmatch(self.source_sha)
            or not _ID.fullmatch(self.controller_id)
            or not _ID.fullmatch(self.worker_id)
            or self.controller_id == self.worker_id
            or not _IMAGE.fullmatch(self.controller_image)
            or not _WORKER_IMAGE.fullmatch(self.worker_image)
            or not _ID.fullmatch(self.controller_config_hash)
            or not _ID.fullmatch(self.worker_config_hash)
            or self.controller_config_hash == self.worker_config_hash
            or self.data_mountpoint != "/data"
            or not _ID.fullmatch(self.cutover_receipt_sha256)
            or not _ID.fullmatch(self.owner_digest)
            or not _ID.fullmatch(self.recipient_fingerprint)
            or self.sender_expected_state not in ("absent", "stopped")
        ):
            raise TelegramHostNoGo("boca_telegram_public_coordinates_unverified")
        sender_values = (
            self.sender_id,
            self.sender_image,
            self.sender_config_hash,
            self.sender_attempt,
        )
        if self.sender_expected_state == "absent":
            if any(sender_values):
                raise TelegramHostNoGo("boca_telegram_sender_identity_unverified")
        elif (
            not _ID.fullmatch(self.sender_id)
            or self.sender_id in (self.controller_id, self.worker_id)
            or self.sender_image != self.controller_image
            or not _ID.fullmatch(self.sender_config_hash)
            or self.sender_config_hash in (self.controller_config_hash, self.worker_config_hash)
            or not _DECIMAL.fullmatch(self.sender_attempt)
        ):
            raise TelegramHostNoGo("boca_telegram_sender_identity_unverified")


@dataclass(frozen=True, slots=True)
class TelegramTopologyWitness:
    """Read-only diagnostic; no owner proof and NO activation authority."""

    attempt_id: str
    source_sha: str
    controller_id: str
    worker_id: str
    sender_state: Literal["OFF"]
    phase: Literal["TOPOLOGY_OBSERVED_NOT_AUTHORIZED"]
    authorized: Literal[False]
    host_effects: Literal[False]
    human_receipt: Literal["UNVERIFIED"]


def _labels(value: tuple[tuple[str, str], ...]) -> dict[str, str]:
    result = dict(value)
    if len(result) != len(value):
        raise TelegramHostNoGo("boca_telegram_duplicate_docker_labels")
    return result


def _service(
    item: Container,
    *,
    source_sha: str,
    browser_attempt: str,
    image_ref: str,
    config_hash: str,
    service: str,
    images: dict[str, Image],
) -> None:
    labels = _labels(item.labels)
    image = images.get(item.image_id)
    if (
        item.name != f"/boca-socios-{service}-1"
        or labels.get("com.docker.compose.project") != _PROJECT
        or labels.get("com.docker.compose.service") != service
        or labels.get(_ATTEMPT) != browser_attempt
        or labels.get(_REVISION) != source_sha
        or labels.get(_CONFIG) != config_hash
        or image is None
        or getattr(image, "source", None) != _SOURCE
        or image_ref not in getattr(image, "references", ())
        or item.running
    ):
        raise TelegramHostNoGo("boca_telegram_installed_release_unverified")


def _stopped_controller_boundary(reader: LifecycleDockerIO, pins: TelegramHostPins) -> None:
    """Stopped Docker releases lose runtime NetworkSettings.Ports.

    Verify the persistent approved loopback PortBindings instead. All other
    service invariants are the same as the running-only lifecycle probe.
    """
    cid = pins.controller_id
    expected_mounts = frozenset(
        {
            (_DATA, "/data", True),
            ("boca-socios_boca_key", "/run/secrets", False),
            ("boca-socios_boca_owner", "/run/owner", False),
            (_IPC, "/run/boca-browser-ipc", False),
        }
    )
    if (
        reader.field("container", cid, "Config.Image") != pins.controller_image
        or reader.field("container", cid, "Config.User") != "10001:10001"
        or reader.field("container", cid, "Config.Cmd")
        != ["python", "-m", "boca_socios.runtime", "serve-beta"]
        or reader.field("container", cid, "HostConfig.RestartPolicy")
        != {"Name": "no", "MaximumRetryCount": 0}
        or reader.field("container", cid, "HostConfig.ReadonlyRootfs") is not True
        or reader.field("container", cid, "HostConfig.Privileged") is not False
        or reader.field("container", cid, "HostConfig.Init") is not True
        or reader.field("container", cid, "HostConfig.PublishAllPorts") is not False
        or reader.field("container", cid, "RestartCount") != 0
        or reader.field("container", cid, "HostConfig.NetworkMode") != _PRIVATE
        or reader.field("container", cid, "HostConfig.PortBindings")
        != {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
        or _mounts(reader.field("container", cid, "Mounts")) != expected_mounts
        or reader.field("container", cid, "State.Restarting") is not False
    ):
        raise TelegramHostNoGo("boca_telegram_stopped_controller_boundary_unverified")


def observe_telegram_host(
    pins: TelegramHostPins,
    *,
    lease: BocaJobLease,
    io: LifecycleDockerIO | None = None,
) -> TelegramTopologyWitness:
    """Observe only dedicated Boca rootless topology under its EXISTING lease.

    The default reader uses UID10001 rootless Docker and the existing adapter
    for exact mount/network/port/restart checks. Injection exists for CI only:
    an injected object is NEVER a credential or physical authorization.
    """
    pins.require()
    verify_protected_boca_job_lease(lease, pins.attempt_id)
    reader = ProductionRootlessDockerIO() if io is None else io
    if reader.uid != 10001 or reader.gid != 10001:
        raise TelegramHostNoGo("boca_telegram_rootless_owner_unverified")
    try:
        inventory = reader.inventory()
        if not isinstance(inventory, Inventory):
            raise TelegramHostNoGo("boca_telegram_docker_inventory_unverified")
        expected = {pins.controller_id, pins.worker_id}
        if pins.sender_expected_state == "stopped":
            expected.add(pins.sender_id)
        containers = {container.ident: container for container in inventory.containers}
        if (
            len(containers) != len(expected)
            or set(containers) != expected
            or len(inventory.containers) != len(expected)
        ):
            raise TelegramHostNoGo("boca_telegram_docker_inventory_unverified")
        images = {item.ident: item for item in inventory.images}
        if len(images) != len(inventory.images):
            raise TelegramHostNoGo("boca_telegram_image_inventory_unverified")
        controller = containers[pins.controller_id]
        worker = containers[pins.worker_id]
        _service(
            controller,
            source_sha=pins.source_sha,
            browser_attempt=pins.browser_attempt,
            image_ref=pins.controller_image,
            config_hash=pins.controller_config_hash,
            service="controller",
            images=images,
        )
        _service(
            worker,
            source_sha=pins.source_sha,
            browser_attempt=pins.browser_attempt,
            image_ref=pins.worker_image,
            config_hash=pins.worker_config_hash,
            service="browser-worker",
            images=images,
        )
        if (
            controller.volumes
            != tuple(sorted({_DATA, _IPC, "boca-socios_boca_key", "boca-socios_boca_owner"}))
            or worker.volumes != (_IPC,)
            or controller.networks not in ((), (_PRIVATE,))
            or worker.networks
        ):
            raise TelegramHostNoGo("boca_telegram_controller_isolation_unverified")
        if pins.sender_expected_state == "stopped":
            sender = containers[pins.sender_id]
            _service(
                sender,
                source_sha=pins.source_sha,
                browser_attempt=pins.browser_attempt,
                image_ref=pins.sender_image,
                config_hash=pins.sender_config_hash,
                service="telegram",
                images=images,
            )
            if (
                _labels(sender.labels).get("boca.socios.telegram-runtime-attempt")
                != pins.sender_attempt
                or sender.volumes != tuple(sorted({_DATA, _TELEGRAM}))
                or sender.networks not in ((), (_EGRESS,))
            ):
                raise TelegramHostNoGo("boca_telegram_sender_state_unverified")
        volume_names = {item.name for item in inventory.volumes}
        if len(inventory.volumes) != len(_VOLUMES) or volume_names != _VOLUMES:
            raise TelegramHostNoGo("boca_telegram_volume_inventory_unverified")
        for volume in inventory.volumes:
            labels = _labels(volume.labels)
            if labels.get("com.docker.compose.project") != _PROJECT:
                raise TelegramHostNoGo("boca_telegram_volume_ownership_unverified")
            if labels.get("com.docker.compose.volume") != volume.name.removeprefix("boca-socios_"):
                raise TelegramHostNoGo("boca_telegram_volume_ownership_unverified")
        networks = {item.name: item for item in inventory.networks}
        if set(networks) != {_PRIVATE, _EGRESS} or len(inventory.networks) != 2:
            raise TelegramHostNoGo("boca_telegram_network_inventory_unverified")
        if networks[_EGRESS].attached_ids:
            raise TelegramHostNoGo("boca_telegram_competing_poller_unverified")
        for name, suffix in ((_PRIVATE, "boca_private"), (_EGRESS, "telegram_egress")):
            labels = _labels(networks[name].labels)
            if (
                labels.get("com.docker.compose.project") != _PROJECT
                or labels.get("com.docker.compose.network") != suffix
            ):
                raise TelegramHostNoGo("boca_telegram_network_ownership_unverified")
        binding = ReviewedInstalledPair(
            original_browser_attempt=pins.browser_attempt,
            controller_config_hash=pins.controller_config_hash,
            worker_config_hash=pins.worker_config_hash,
            sender_id=pins.sender_id,
            sender_config_hash=pins.sender_config_hash,
            sender_attempt_id=pins.sender_attempt,
            sender_running=False,
        )
        probe = RootlessLifecycleProbe(binding, reader)
        _stopped_controller_boundary(reader, pins)
        probe._service_boundary(pins.worker_id, "browser-worker", pins.worker_image)
        if pins.sender_expected_state == "stopped":
            probe._service_boundary(pins.sender_id, "telegram", pins.sender_image)
        for volume_name in (_DATA, _TELEGRAM):
            mountpoint = reader.field("volume", volume_name, "Mountpoint")
            if not isinstance(mountpoint, str) or not mountpoint.startswith("/"):
                raise TelegramHostNoGo("boca_telegram_volume_mount_unverified")
        verify_protected_boca_job_lease(lease, pins.attempt_id)
    except TelegramHostNoGo:
        raise
    except Exception:
        # Never reflect Docker paths, stderr, credentials or foreign metadata.
        raise TelegramHostNoGo("boca_telegram_host_observation_unavailable") from None
    return TelegramTopologyWitness(
        attempt_id=pins.attempt_id,
        source_sha=pins.source_sha,
        controller_id=pins.controller_id,
        worker_id=pins.worker_id,
        sender_state="OFF",
        phase="TOPOLOGY_OBSERVED_NOT_AUTHORIZED",
        authorized=False,
        host_effects=False,
        human_receipt="UNVERIFIED",
    )
