"""Proposed Boca-only rootless lifecycle adapter for a future protected job.

This module has NO HTTP endpoint, CLI entrypoint, scheduler or deployment hook.
Only the canonical, independently authorized Boca Actions operation may use
``execute_requested_lifecycle`` after obtaining a held BocaJobLease and exact
installed-release coordinates.  Local/CI fixtures inject an inert IO adapter.

The real adapter reads ONLY Boca's dedicated UID10001 rootless Docker daemon;
it does not inspect or mutate a foreign daemon, host stack, backup or socket.
No blackbox navigation module is imported or executed by these tests.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from time import monotonic, sleep
from typing import Literal, Protocol, cast

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_lifecycle as lifecycle
from boca_socios.host_boca_cleanup import BocaJobLease, Inventory, verify_protected_boca_job_lease
from boca_socios.integration.engine_socket import (
    ControlState,
    EngineReceipt,
    LocalEngineUnavailable,
    _unique_object,
)

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ATTEMPT = re.compile(r"[1-9][0-9]{0,19}\Z")
_ENGINE_COMMAND = "boca_socios.integration.engine_socket"
_SOURCE_URL = "https://github.com/mbalbo2023/boca-socios-assistant"
_PROJECT = "boca-socios"
_DATA_VOLUME = "boca-socios_boca_data"
_IPC_VOLUME = "boca-socios_boca_browser_ipc"
_SITE_CONFIG_VOLUME = "boca-socios_boca_site_config"
_CONTROLLER_VOLUMES = frozenset(
    {
        _DATA_VOLUME,
        "boca-socios_boca_key",
        "boca-socios_boca_owner",
        _IPC_VOLUME,
        _SITE_CONFIG_VOLUME,
    }
)
_APPROVED_VOLUMES = _CONTROLLER_VOLUMES | {"boca-socios_boca_telegram"}
_PRIVATE_NETWORK = "boca-socios_boca_private"
_TELEGRAM_NETWORK = "boca-socios_boca_telegram_egress"
_BROWSER_EGRESS_NETWORK = "boca-socios_boca_browser_egress"
_ATTEMPT_LABEL = "boca.socios.browser-ipc-attempt"
_CONFIG_HASH_LABEL = "com.docker.compose.config-hash"
_REVISION_LABEL = "org.opencontainers.image.revision"
_CONTROLLER_PORT = {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
# Only discrete public fields needed by the lifecycle attestor; no Env, Args,
# raw health output, State.Error, or arbitrary templates cross this boundary.
_LIFECYCLE_FIELDS = frozenset(
    {
        "Config.Image",
        "Config.User",
        "HostConfig.RestartPolicy",
        "HostConfig.ReadonlyRootfs",
        "HostConfig.Privileged",
        "HostConfig.PublishAllPorts",
        "HostConfig.Init",
        "HostConfig.NetworkMode",
        "HostConfig.PortBindings",
        "NetworkSettings.Ports",
        "NetworkSettings.Networks",
        "RestartCount",
        "State.Restarting",
        "State.Health.Status",
        "State.Status",
        "State.StartedAt",
        "State.FinishedAt",
        "State.ExitCode",
        "State.OOMKilled",
        "State.Pid",
        "State.Running",
        "Mounts",
    }
)


def panel_control_mount() -> str:
    from boca_socios.host_on_demand_service import control_directory

    return str(control_directory())


class LifecycleAdapterNoGo(RuntimeError):
    """The owned resource or requested prestate is not independently proven."""


class LifecycleEffectUncertain(LifecycleAdapterNoGo):
    """An effect may have reached Docker/IPC, but a positive result is absent."""


@dataclass(frozen=True, slots=True)
class ReviewedInstalledPair:
    """Coordinates taken from the approved immutable release, never a Docker label."""

    original_browser_attempt: str
    controller_config_hash: str
    worker_config_hash: str
    # Optional, independently reviewed Telegram sender topology. Its identity
    # does not prove Bot API delivery or consent; controls never act on sender.
    sender_id: str = ""
    sender_config_hash: str = ""
    sender_attempt_id: str = ""
    sender_running: bool = False

    def require(self) -> None:
        if (
            type(self.original_browser_attempt) is not str
            or not _ATTEMPT.fullmatch(self.original_browser_attempt)
            or type(self.controller_config_hash) is not str
            or not _HASH.fullmatch(self.controller_config_hash)
            or type(self.worker_config_hash) is not str
            or not _HASH.fullmatch(self.worker_config_hash)
            or self.controller_config_hash == self.worker_config_hash
            or any(
                type(value) is not str
                for value in (self.sender_id, self.sender_config_hash, self.sender_attempt_id)
            )
            or type(self.sender_running) is not bool
            or bool(self.sender_id) != bool(self.sender_config_hash)
            or bool(self.sender_id) != bool(self.sender_attempt_id)
            or self.sender_id != ""
            and (
                not re.fullmatch(r"[0-9a-f]{64}", self.sender_id)
                or not _HASH.fullmatch(self.sender_config_hash)
                or not _ATTEMPT.fullmatch(self.sender_attempt_id)
                or self.sender_config_hash in (self.controller_config_hash, self.worker_config_hash)
            )
            or self.sender_id == ""
            and self.sender_running
        ):
            raise LifecycleAdapterNoGo("reviewed Boca installed pair is unavailable")


class LifecycleDockerIO(Protocol):
    """Small, injected Docker boundary; only ProductionRootlessDockerIO is real."""

    @property
    def uid(self) -> int: ...

    @property
    def gid(self) -> int: ...

    def inventory(self) -> Inventory: ...

    def field(self, kind: str, ident: str, field: str) -> object: ...

    def engine_request(self, controller_id: str, operation: str) -> EngineReceipt: ...

    def worker_action(self, worker_id: str, operation: str) -> None: ...


class ProductionRootlessDockerIO:
    """Host-only fixed Docker argv on the isolated Boca UID10001 socket."""

    @property
    def uid(self) -> int:
        return os.geteuid()

    @property
    def gid(self) -> int:
        return os.getegid()

    def inventory(self) -> Inventory:
        # This helper proves the daemon contains only positively identified
        # Boca objects before inspecting even the narrow Config/State fields.
        return cleanup.capture_inventory()

    def field(self, kind: str, ident: str, field: str) -> object:
        if kind == "volume" and ident == _DATA_VOLUME and field == "Mountpoint":
            return cleanup._inspect_field("volume", ident, field)
        if (
            kind != "container"
            or type(ident) is not str
            or not _HASH.fullmatch(ident)
            or field not in _LIFECYCLE_FIELDS
        ):
            raise LifecycleAdapterNoGo("exact Boca lifecycle inspection field required")
        try:
            return json.loads(
                cleanup._docker("inspect", "--format", "{{json ." + field + "}}", ident)
            )
        except (TypeError, ValueError):
            raise LifecycleAdapterNoGo("Boca lifecycle field receipt invalid") from None

    def engine_request(self, controller_id: str, operation: str) -> EngineReceipt:
        if (
            type(controller_id) is not str
            or not _HASH.fullmatch(controller_id)
            or operation
            not in (
                "status",
                "start",
                "stop",
            )
        ):
            raise LifecycleAdapterNoGo("Boca engine invocation coordinates invalid")
        # In-container UID10001 through the exact pre-attested controller ID,
        # with no Docker socket in the controller and no extra host TCP port.
        output = cleanup._docker(
            "exec",
            "--user",
            "10001:10001",
            controller_id,
            "python",
            "-m",
            _ENGINE_COMMAND,
            operation,
        )
        if len(output) > 256:
            raise LifecycleEffectUncertain("Boca engine control response uncertain")
        try:
            parsed = _unique_object(output.encode("ascii"))
        except (UnicodeError, LocalEngineUnavailable):
            raise LifecycleEffectUncertain("Boca engine control response uncertain") from None
        if (
            set(parsed) != {"version", "state", "changed", "pid"}
            or type(parsed["version"]) is not int
            or parsed["version"] != 1
            or type(parsed["state"]) is not str
            or parsed["state"] not in ("RUNNING", "STOPPED")
            or type(parsed["changed"]) is not bool
            or type(parsed["pid"]) is not int
            or not 1 <= parsed["pid"] <= 2**31 - 1
            or operation == "status"
            and parsed["changed"]
        ):
            raise LifecycleEffectUncertain("Boca engine control response unverified")
        return EngineReceipt(cast(ControlState, parsed["state"]), parsed["changed"], parsed["pid"])

    def worker_action(self, worker_id: str, operation: str) -> None:
        if (
            type(worker_id) is not str
            or not _HASH.fullmatch(worker_id)
            or operation not in ("start", "stop")
        ):
            raise LifecycleAdapterNoGo("Boca worker invocation coordinates invalid")
        if operation == "stop":
            output = cleanup._docker("stop", "-t", "8", worker_id)
        else:
            output = cleanup._docker("start", worker_id)
        if output not in (worker_id, worker_id + "\n"):
            raise LifecycleEffectUncertain("Boca exact worker Docker ACK uncertain")
        # A Docker CLI acknowledgement alone is not a verified service state.
        # Loopback/controller health and all resource identities are rechecked
        # independently by RootlessLifecycleProbe after this finite observation.
        deadline = monotonic() + 40
        while monotonic() < deadline:
            running = self.field("container", worker_id, "State.Running")
            if type(running) is not bool:
                raise LifecycleEffectUncertain("Boca worker runtime state unavailable")
            if operation == "stop" and not running:
                return
            if operation == "start":
                health = self.field("container", worker_id, "State.Health.Status")
                if running and health == "healthy":
                    return
                if health not in ("starting", "healthy") or not running:
                    raise LifecycleEffectUncertain("Boca worker start did not become healthy")
            sleep(0.5)
        raise LifecycleEffectUncertain("Boca worker host health deadline expired")


def _typed_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise LifecycleAdapterNoGo(f"Boca {label} witness unavailable")
    return value


def _labels(container: cleanup.Container) -> dict[str, str]:
    labels = dict(container.labels)
    if len(labels) != len(container.labels):
        raise LifecycleAdapterNoGo("Boca Compose labels duplicated")
    return labels


def _mounts(
    value: object, *, control_source: str | None = None
) -> frozenset[tuple[str, str, bool]]:
    if not isinstance(value, list) or len(value) > 6:
        raise LifecycleAdapterNoGo("Boca service mount list unavailable")
    observed: set[tuple[str, str, bool]] = set()
    for entry in value:
        if (
            isinstance(entry, dict)
            and control_source is not None
            and entry.get("Type") == "bind"
            and entry.get("Source") == control_source
            and entry.get("Destination") == "/run/boca-bot-control"
            and entry.get("RW") is False
            and entry.get("Propagation") == "rprivate"
        ):
            item = (control_source, "/run/boca-bot-control", False)
            if item in observed:
                raise LifecycleAdapterNoGo("Boca duplicate service mount")
            observed.add(item)
            continue
        if (
            not isinstance(entry, dict)
            or entry.get("Type") != "volume"
            or entry.get("Driver") != "local"
            or type(entry.get("Name")) is not str
            or type(entry.get("Destination")) is not str
            or type(entry.get("RW")) is not bool
        ):
            raise LifecycleAdapterNoGo("Boca service mount identity unavailable")
        item = (entry["Name"], entry["Destination"], entry["RW"])
        if item in observed:
            raise LifecycleAdapterNoGo("Boca duplicate service mount")
        observed.add(item)
    return frozenset(observed)


class RootlessLifecycleProbe:
    """Read-only independently observed Docker + in-controller engine state."""

    def __init__(
        self, binding: ReviewedInstalledPair, io: LifecycleDockerIO, *, on_demand: bool = False
    ) -> None:
        binding.require()
        self._on_demand = on_demand
        self._binding = binding
        self._io = io

    def observe(
        self, coordinates: lifecycle.LifecycleHostCoordinates, lease: BocaJobLease
    ) -> lifecycle.LifecycleHostSnapshot:
        coordinates.validate()
        verify_protected_boca_job_lease(lease, coordinates.attempt_id)
        if self._io.uid != 10001 or self._io.gid != 10001:
            raise LifecycleAdapterNoGo("dedicated Boca rootless identity absent")
        try:
            snapshot = self._observe(coordinates)
        except LifecycleAdapterNoGo:
            raise
        except Exception:
            # Never reflect Docker inspection text: it can include host or
            # application metadata unrelated to the requested receipt.
            raise LifecycleAdapterNoGo("Boca physical lifecycle attestation unavailable") from None
        verify_protected_boca_job_lease(lease, coordinates.attempt_id)
        try:
            snapshot.require(coordinates)
        except lifecycle.LifecycleHostUnavailable:
            raise LifecycleAdapterNoGo("Boca physical component readiness not proven") from None
        return snapshot

    def _observe(
        self, coordinates: lifecycle.LifecycleHostCoordinates
    ) -> lifecycle.LifecycleHostSnapshot:
        inventory = self._io.inventory()
        if not isinstance(inventory, Inventory) or len(inventory.containers) != (
            3 if self._binding.sender_id else 2
        ):
            # Sender state is permitted only with independent exact reviewed
            # binding. A stale controller or arbitrary third service is NO_GO.
            raise LifecycleAdapterNoGo("Boca reviewed service topology not proven")
        by_id = {item.ident: item for item in inventory.containers}
        expected_ids = {coordinates.controller_id, coordinates.worker_id}
        if self._binding.sender_id:
            expected_ids.add(self._binding.sender_id)
        if len(expected_ids) != (3 if self._binding.sender_id else 2) or set(by_id) != expected_ids:
            raise LifecycleAdapterNoGo("Boca installed service IDs differ")
        image_map = {item.ident: item for item in inventory.images}
        if len(image_map) != len(inventory.images):
            raise LifecycleAdapterNoGo("Boca image inventory duplicated")
        controller = by_id[coordinates.controller_id]
        worker = by_id[coordinates.worker_id]
        sender = by_id[self._binding.sender_id] if self._binding.sender_id else None
        reviewed = [
            (
                controller,
                "controller",
                coordinates.controller_image,
                self._binding.controller_config_hash,
            ),
            (
                worker,
                "browser-worker",
                coordinates.worker_image,
                self._binding.worker_config_hash,
            ),
        ]
        if sender is not None:
            reviewed.append(
                (sender, "telegram", coordinates.controller_image, self._binding.sender_config_hash)
            )
        for item, service, digest, config_hash in reviewed:
            image = image_map.get(item.image_id)
            labels = _labels(item)
            if (
                item.name != f"/{_PROJECT}-{service}-1"
                or labels.get("com.docker.compose.project") != _PROJECT
                or labels.get("com.docker.compose.service") != service
                or labels.get(_ATTEMPT_LABEL) != self._binding.original_browser_attempt
                or service == "telegram"
                and labels.get("boca.socios.telegram-runtime-attempt")
                != self._binding.sender_attempt_id
                or labels.get(_CONFIG_HASH_LABEL) != config_hash
                or labels.get(_REVISION_LABEL) != coordinates.source_sha
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", item.image_id)
                or image is None
                or digest not in image.references
                or image.source != _SOURCE_URL
            ):
                raise LifecycleAdapterNoGo("Boca installed Compose/image identity changed")
            self._service_boundary(item.ident, service, digest)
        egresses = [network for network in inventory.networks if network.name == _TELEGRAM_NETWORK]
        browser_egresses = [
            network for network in inventory.networks if network.name == _BROWSER_EGRESS_NETWORK
        ]
        browser_egress_valid = len(browser_egresses) == 1 and browser_egresses[0].attached_ids == (
            (worker.ident,) if worker.running else ()
        )
        egress_valid = (
            len(egresses) == 1
            and egresses[0].attached_ids
            == ((sender.ident,) if self._binding.sender_running else ())
            if sender is not None
            else all(not network.attached_ids for network in egresses)
        )
        if sender is None:
            sender_network_valid = True
        elif self._binding.sender_running:
            sender_network_valid = sender.networks == (_TELEGRAM_NETWORK,)
        else:
            # Docker may retain the stopped service's network in its static
            # object while removing the live endpoint. Both are safe because
            # HostConfig.NetworkMode remains pinned to Boca egress.
            sender_network_valid = sender.networks in ((), (_TELEGRAM_NETWORK,))
        if (
            controller.networks != (_PRIVATE_NETWORK,)
            or not browser_egress_valid
            or worker.networks not in ((), (_BROWSER_EGRESS_NETWORK,))
            or worker.running
            and worker.networks != (_BROWSER_EGRESS_NETWORK,)
            or controller.volumes != tuple(sorted(_CONTROLLER_VOLUMES))
            or worker.volumes != tuple(sorted((_IPC_VOLUME, _SITE_CONFIG_VOLUME)))
            or sender is not None
            and (
                not sender_network_valid
                or sender.volumes != tuple(sorted((_DATA_VOLUME, "boca-socios_boca_telegram")))
            )
            or set(v.name for v in inventory.volumes) - _APPROVED_VOLUMES
            or {v.name for v in inventory.volumes} < _CONTROLLER_VOLUMES
            or sender is not None
            and "boca-socios_boca_telegram" not in {v.name for v in inventory.volumes}
            or any(
                n.name not in (_PRIVATE_NETWORK, _TELEGRAM_NETWORK, _BROWSER_EGRESS_NETWORK)
                for n in inventory.networks
            )
            or not any(
                n.name == _PRIVATE_NETWORK and n.attached_ids == (coordinates.controller_id,)
                for n in inventory.networks
            )
            or not egress_valid
        ):
            raise LifecycleAdapterNoGo("Boca volume or network isolation differs")
        data_mountpoint = self._io.field("volume", _DATA_VOLUME, "Mountpoint")
        if (
            type(data_mountpoint) is not str
            or data_mountpoint != str(coordinates.database_path.parent)
            or not coordinates.database_path.is_absolute()
        ):
            raise LifecycleAdapterNoGo("Boca data volume cannot be bound to host ledger")
        engine = self._io.engine_request(coordinates.controller_id, "status")
        if (
            not isinstance(engine, EngineReceipt)
            or engine.state not in ("RUNNING", "STOPPED")
            or engine.changed
            or type(engine.pid) is not int
            or engine.pid <= 0
        ):
            raise LifecycleAdapterNoGo("Boca synthetic motor status is unverified")
        controller_running = _typed_bool(
            self._io.field("container", coordinates.controller_id, "State.Running"), "controller"
        )
        worker_running = _typed_bool(
            self._io.field("container", coordinates.worker_id, "State.Running"), "worker"
        )
        if sender is not None:
            sender_running = _typed_bool(
                self._io.field("container", sender.ident, "State.Running"), "Telegram sender"
            )
            if sender_running != sender.running or sender_running != self._binding.sender_running:
                raise LifecycleAdapterNoGo("Boca Telegram sender state changed")
        controller_healthy = (
            self._io.field("container", coordinates.controller_id, "State.Health.Status")
            == "healthy"
        )
        worker_healthy = worker_running and (
            self._io.field("container", coordinates.worker_id, "State.Health.Status") == "healthy"
        )
        if (
            not controller_running
            or not controller_healthy
            or worker_running != worker.running
            or controller_running != controller.running
            # STOP must remain possible for an unhealthy but RUNNING worker;
            # Chromium START and bot START keep the healthy-readiness gate.
            or worker_running
            and not worker_healthy
            and coordinates.component == "chromium"
            and coordinates.target == "start"
        ):
            raise LifecycleAdapterNoGo("Boca controller/worker liveness is not authentic")
        return lifecycle.LifecycleHostSnapshot(
            controller_id=coordinates.controller_id,
            controller_project=_PROJECT,
            controller_service="controller",
            controller_image=coordinates.controller_image,
            controller_sha=coordinates.source_sha,
            worker_id=coordinates.worker_id,
            worker_project=_PROJECT,
            worker_service="browser-worker",
            worker_image=coordinates.worker_image,
            worker_sha=coordinates.source_sha,
            controller_running=controller_running,
            controller_healthy=controller_healthy,
            worker_running=worker_running,
            worker_healthy=worker_healthy,
            bot_engine_running=engine.state == "RUNNING",
            worker_network_mode=_BROWSER_EGRESS_NETWORK,
            published_controller_port="127.0.0.1:8443",
            rootless_uid=10001,
            controller_data_volume=_DATA_VOLUME,
            controller_data_mountpoint=coordinates.database_path.parent,
            controller_data_volume_exclusive=True,
            single_boca_project_verified=True,
            rootless_boca_uid_verified=True,
        )

    def _service_boundary(self, ident: str, service: str, reference: str) -> None:
        if service == "controller":
            expected_mounts = frozenset(
                {
                    (_DATA_VOLUME, "/data", True),
                    ("boca-socios_boca_key", "/run/secrets", False),
                    ("boca-socios_boca_owner", "/run/owner", False),
                    (_IPC_VOLUME, "/run/boca-browser-ipc", False),
                    (_SITE_CONFIG_VOLUME, "/run/boca-site-config", True),
                }
            )
        elif service == "browser-worker":
            expected_mounts = frozenset(
                {
                    (_IPC_VOLUME, "/run/boca-browser-ipc", True),
                    (_SITE_CONFIG_VOLUME, "/run/boca-site-config", False),
                }
            )
        elif service == "telegram":
            expected_mounts = frozenset(
                {
                    (_DATA_VOLUME, "/data", True),
                    ("boca-socios_boca_telegram", "/run/telegram", False),
                }
            )
        else:
            raise LifecycleAdapterNoGo("Boca service not authorized")
        expected_user = "10002:10002" if service == "browser-worker" else "10001:10001"
        expected_network = (
            _BROWSER_EGRESS_NETWORK
            if service == "browser-worker"
            else _TELEGRAM_NETWORK
            if service == "telegram"
            else _PRIVATE_NETWORK
        )
        expected_ports = _CONTROLLER_PORT if service == "controller" else {}
        persistent = self._on_demand and service == "controller"
        source = panel_control_mount() if persistent else None
        if source is not None:
            expected_mounts |= {(source, "/run/boca-bot-control", False)}
        restart = self._io.field("container", ident, "HostConfig.RestartPolicy")
        restart_count = self._io.field("container", ident, "RestartCount")
        ports = self._io.field("container", ident, "NetworkSettings.Ports")
        if self._on_demand and service == "browser-worker":
            from boca_socios.host_first_deploy import _browser_worker_egress_network

            _browser_worker_egress_network(
                self._io.field("container", ident, "NetworkSettings.Networks"),
                running=_typed_bool(self._io.field("container", ident, "State.Running"), "worker"),
            )
            if self._io.field("container", ident, "HostConfig.PortBindings") not in ({}, None):
                raise LifecycleAdapterNoGo("Boca worker gained host ports")
            # Docker serializes an empty port map as null on a never-started CID.
            if ports is None:
                ports = {}
        if (
            self._io.field("container", ident, "Config.Image") != reference
            or self._io.field("container", ident, "Config.User") != expected_user
            or restart != {"Name": "unless-stopped" if persistent else "no", "MaximumRetryCount": 0}
            or self._io.field("container", ident, "HostConfig.ReadonlyRootfs") is not True
            or self._io.field("container", ident, "HostConfig.Privileged") is not False
            or self._io.field("container", ident, "HostConfig.PublishAllPorts") is not False
            or self._io.field("container", ident, "HostConfig.Init") is not True
            or type(restart_count) is not int
            or restart_count < 0
            or not persistent
            and restart_count != 0
            or self._io.field("container", ident, "HostConfig.NetworkMode") != expected_network
            or ports != expected_ports
            or _mounts(self._io.field("container", ident, "Mounts"), control_source=source)
            != expected_mounts
            or self._io.field("container", ident, "State.Restarting") is not False
        ):
            raise LifecycleAdapterNoGo("Boca service exact isolation changed")


def apply_exact_effect(
    claim: lifecycle.HostLifecycleClaim,
    *,
    lease: BocaJobLease,
    probe: RootlessLifecycleProbe,
    io: LifecycleDockerIO,
) -> None:
    """One physical effect after durable CLAIMED, never a direct panel call."""
    if not isinstance(claim, lifecycle.HostLifecycleClaim):
        raise LifecycleAdapterNoGo("Boca lifecycle host CLAIMED receipt absent")
    coordinates = claim.coordinates
    coordinates.validate()
    verify_protected_boca_job_lease(lease, coordinates.attempt_id)
    before = probe.observe(coordinates, lease)
    current = before.require(coordinates)
    desired = coordinates.target == "start"
    if current != claim.was_running or current == desired:
        raise LifecycleAdapterNoGo("Boca lifecycle claim prestate changed or already satisfied")
    if coordinates.component == "chromium" and coordinates.target == "stop":
        if before.bot_engine_running is not False:
            raise LifecycleAdapterNoGo("stop bot first before stopping Chromium")
    # No action is allowed on the controller itself. Its identity and HTTP
    # health must remain unchanged while only the engine thread or exact
    # worker ID is controlled.
    try:
        if coordinates.component == "bot":
            receipt = io.engine_request(coordinates.controller_id, coordinates.target)
            if (
                receipt.state != ("RUNNING" if desired else "STOPPED")
                or receipt.changed is not True
            ):
                raise LifecycleEffectUncertain("Boca motor result uncertain")
        else:
            io.worker_action(coordinates.worker_id, coordinates.target)
        after = probe.observe(coordinates, lease)
        if after.require(coordinates) != desired or not after.controller_healthy:
            raise LifecycleEffectUncertain("Boca host lifecycle poststate uncertain")
    except Exception:
        # The effect may have occurred before Docker/IPC or the postflight
        # receipt failed. Never retry it, ACK success, or touch foreign IDs.
        raise LifecycleEffectUncertain("Boca host lifecycle effect uncertain") from None


def execute_requested_lifecycle(
    coordinates: lifecycle.LifecycleHostCoordinates,
    *,
    binding: ReviewedInstalledPair,
    lease: BocaJobLease,
    io: LifecycleDockerIO | None = None,
) -> Literal["APPLIED", "REFUSED"]:
    """Single-lease CLAIM/effect/postflight/ACK; NOT wired to any workflow.

    A protected caller must prove the release and operation-specific GO before
    invoking this API. An absent or indeterminate receipt is always NO_GO.
    """
    coordinates.validate()
    binding.require()
    transport = ProductionRootlessDockerIO() if io is None else io
    probe = RootlessLifecycleProbe(binding, transport)
    claim = lifecycle.claim_requested(coordinates, lease=lease, probe=probe)
    if claim.was_running == (coordinates.target == "start"):
        lifecycle.acknowledge(
            claim, lease=lease, probe=probe, result="REFUSED", effect_attempted=False
        )
        return "REFUSED"
    try:
        apply_exact_effect(claim, lease=lease, probe=probe, io=transport)
    except LifecycleEffectUncertain:
        try:
            lifecycle.mark_uncertain(claim, lease=lease)
        except lifecycle.LifecycleHostUnavailable:
            pass
        raise
    except LifecycleAdapterNoGo:
        # No effect occurred, but REFUSED still requires an unchanged
        # independently observed poststate under the same Boca lease.
        lifecycle.acknowledge(
            claim, lease=lease, probe=probe, result="REFUSED", effect_attempted=False
        )
        raise
    try:
        lifecycle.acknowledge(
            claim, lease=lease, probe=probe, result="APPLIED", effect_attempted=True
        )
    except lifecycle.LifecycleHostUnavailable:
        try:
            lifecycle.mark_uncertain(claim, lease=lease)
        except lifecycle.LifecycleHostUnavailable:
            pass
        raise LifecycleEffectUncertain("Boca host lifecycle final ACK uncertain") from None
    return "APPLIED"
