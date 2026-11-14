"""Authenticate the installed Boca binding before deriving Telegram coordinates."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_on_demand_service as service
from boca_socios.host_lifecycle_rootless_adapter import LifecycleDockerIO, RootlessLifecycleProbe
from boca_socios.host_telegram_postcutover import TelegramHostPins, observe_telegram_host
from boca_socios.host_telegram_production_reader import TelegramProductionDockerIO
from boca_socios.telegram_pairing_cutover import CutoverCoordinates

if TYPE_CHECKING:
    from boca_socios.host_on_demand_lifecycle import OnDemandInstallation
    from boca_socios.telegram_bootstrap import RecipientReceipt


class TelegramContextError(ValueError):
    """Fixed diagnostic, without host coordinates or credential material."""


@dataclass
class InstalledTelegramContext:
    attempt_id: str
    lease: cleanup.BocaJobLease
    reader: LifecycleDockerIO
    installation: OnDemandInstallation
    binding_digest: str
    volumes: tuple[tuple[str, str], ...]
    workflow_sha: str
    pins: TelegramHostPins | None = None
    coordinates: CutoverCoordinates | None = None

    def check_binding(self) -> None:
        cleanup.verify_protected_boca_job_lease(self.lease, self.attempt_id)
        if service.read_installed_binding(self.lease) != self.installation:
            raise TelegramContextError("telegram_installed_binding_changed")
        for name, path in self.volumes:
            if name == "boca-socios_boca_telegram":
                from boca_socios.host_first_deploy import _telegram_volume

                _telegram_volume()
            if self.reader.field("volume", name, "Mountpoint") != path:
                raise TelegramContextError("telegram_volume_changed")

    def healthy(self) -> None:
        self.check_binding()
        item = self.installation
        if (
            self.reader.field("container", item.worker_id, "State.Running") is not False
            or self.reader.field("container", item.worker_id, "State.Restarting") is not False
        ):
            raise TelegramContextError("telegram_worker_must_be_stopped")
        coords = item.coordinates(str(uuid4()))
        probe = RootlessLifecycleProbe(item.pair, self.reader, on_demand=True)
        snapshot = probe._observe(coords)
        snapshot.require(coords)
        if self.reader.engine_request(item.controller_id, "status").state != "STOPPED":
            raise TelegramContextError("telegram_engine_must_be_stopped")
        self.check_binding()

    def stopped(self, *, active_helper: bool = False) -> None:
        self.check_binding()
        for ident in (self.installation.controller_id, self.installation.worker_id):
            if (
                self.reader.field("container", ident, "State.Running") is not False
                or self.reader.field("container", ident, "State.Restarting") is not False
            ):
                raise TelegramContextError("telegram_services_not_stopped")
        if self.pins is not None and not active_helper:
            observe_telegram_host(self.pins, lease=self.lease, io=self.reader)
        self.check_binding()

    def bind(self, recipient: RecipientReceipt, owner_digest: str) -> None:
        item = self.installation
        pair = item.pair
        if pair.sender_running:
            raise TelegramContextError("telegram_sender_must_be_off")
        self.pins = TelegramHostPins(
            "boca-protected-action-v1",
            "telegram",
            self.attempt_id,
            item.source_sha,
            item.controller_id,
            item.controller_image,
            item.worker_id,
            item.worker_image,
            item.installation_run_id,
            pair.controller_config_hash,
            pair.worker_config_hash,
            "/data",
            item.installation_run_id,
            self.binding_digest,
            owner_digest,
            recipient.fingerprint,
            "stopped" if pair.sender_id else "absent",
            pair.sender_id,
            item.controller_image if pair.sender_id else "",
            pair.sender_config_hash,
            pair.sender_attempt_id,
        )
        self.pins.require()
        lease_digest = hashlib.sha256(
            (self.attempt_id + ":" + self.workflow_sha + ":" + self.binding_digest).encode("ascii")
        ).hexdigest()
        self.coordinates = CutoverCoordinates(
            self.attempt_id,
            item.source_sha,
            item.controller_image,
            owner_digest,
            lease_digest,
            item.controller_id,
            recipient.fingerprint,
        )

    def stop(self) -> None:
        self.healthy()
        ident = self.installation.controller_id
        if cleanup._docker("stop", "--time", "10", ident).strip() != ident:
            raise TelegramContextError("telegram_controller_stop_uncertain")
        self.stopped()

    def restore(self) -> None:
        self.check_binding()
        ident = self.installation.controller_id
        if self.reader.field("container", ident, "State.Running") is False:
            if cleanup._docker("start", ident).strip() != ident:
                raise TelegramContextError("telegram_controller_restore_uncertain")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            self.check_binding()
            if self.reader.field("container", ident, "State.Health.Status") == "healthy":
                self.healthy()
                return
            time.sleep(0.2)
        raise TelegramContextError("telegram_controller_restore_unverified")


def resolve_installed_context(
    attempt_id: str,
    *,
    lease: cleanup.BocaJobLease,
    reader: LifecycleDockerIO | None = None,
    expected_source_sha: str,
    workflow_sha: str,
    allow_registered_sender: bool = False,
) -> InstalledTelegramContext:
    if (
        not re.fullmatch(r"[1-9][0-9]{0,19}", attempt_id)
        or not re.fullmatch(r"[a-f0-9]{40}", expected_source_sha)
        or not re.fullmatch(r"[a-f0-9]{40}", workflow_sha)
    ):
        raise TelegramContextError("telegram_source_required")
    cleanup.verify_protected_boca_job_lease(lease, attempt_id)
    io = TelegramProductionDockerIO() if reader is None else reader
    if (io.uid, io.gid) != (10001, 10001):
        raise TelegramContextError("telegram_rootless_identity_required")
    installed = service.read_installed_binding(lease)
    if installed.source_sha != expected_source_sha or (
        installed.pair.sender_running and not allow_registered_sender
    ):
        raise TelegramContextError("telegram_installed_source_mismatch")
    root = service._home() / service._ROOT
    digest = hashlib.sha256(service._read(root / service._BINDING, service._MAX_PLAN)).hexdigest()
    volumes = []
    existing = {volume.name for volume in io.inventory().volumes}
    for suffix in ("boca_data", "boca_owner", "boca_telegram"):
        name = "boca-socios_" + suffix
        if suffix == "boca_telegram" and name not in existing:
            continue
        path = io.field("volume", name, "Mountpoint")
        if (
            type(path) is not str
            or not path.startswith("/home/boca-deploy/.local/share/docker/volumes/")
            or not path.endswith("/" + name + "/_data")
        ):
            raise TelegramContextError("telegram_named_volume_required")
        volumes.append((name, path))
    context = InstalledTelegramContext(
        attempt_id, lease, io, installed, digest, tuple(volumes), workflow_sha
    )
    context.healthy()
    return context
