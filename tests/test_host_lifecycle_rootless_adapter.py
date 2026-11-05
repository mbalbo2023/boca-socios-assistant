"""Code-only rootless host lifecycle adapter; no real Docker or Boca calls."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

import pytest

from boca_socios import host_lifecycle_rootless_adapter as adapter
from boca_socios.host_boca_cleanup import (
    BocaJobLease,
    Container,
    DiskInodes,
    Image,
    Inventory,
    Network,
    Volume,
)
from boca_socios.host_boca_lifecycle import HostLifecycleClaim, LifecycleHostCoordinates
from boca_socios.integration.engine_socket import EngineReceipt
from boca_socios.panel.lifecycle_intents import LifecycleIntentStore
from boca_socios.storage.database import Database

SOURCE = "a" * 40
CONTROLLER = "b" * 64
WORKER = "c" * 64
SENDER = "8" * 64
# Registry manifest RepoDigest and Docker image config ID differ by design.
CI = "sha256:" + "6" * 64
WI = "sha256:" + "7" * 64
CONTROLLER_REF = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "d" * 64
WORKER_REF = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "e" * 64
RUN = "3456789012"
INSTALLED = "12345678"
CONFIG_CONTROLLER = "f" * 64
CONFIG_WORKER = "1" * 64
CONFIG_SENDER = "9" * 64
SENDER_ATTEMPT = "777777"
IPC_ATTEMPT = "boca.socios.browser-ipc-attempt"


def _coordinates(
    path: Path, component: str = "bot", target: str = "start"
) -> LifecycleHostCoordinates:
    return LifecycleHostCoordinates(
        attempt_id=RUN,
        request_id=str(uuid4()),
        component=component,  # type: ignore[arg-type]
        target=target,  # type: ignore[arg-type]
        source_sha=SOURCE,
        controller_id=CONTROLLER,
        controller_image=CONTROLLER_REF,
        worker_id=WORKER,
        worker_image=WORKER_REF,
        database_path=path,
    )


def _binding(*, sender_running: bool | None = None) -> adapter.ReviewedInstalledPair:
    return adapter.ReviewedInstalledPair(
        original_browser_attempt=INSTALLED,
        controller_config_hash=CONFIG_CONTROLLER,
        worker_config_hash=CONFIG_WORKER,
        sender_id=SENDER if sender_running is not None else "",
        sender_config_hash=CONFIG_SENDER if sender_running is not None else "",
        sender_attempt_id=SENDER_ATTEMPT if sender_running is not None else "",
        sender_running=bool(sender_running),
    )


def _labels(service: str, hash_value: str) -> tuple[tuple[str, str], ...]:
    labels = {
        "com.docker.compose.project": "boca-socios",
        "com.docker.compose.service": service,
        "com.docker.compose.config-hash": hash_value,
        "org.opencontainers.image.revision": SOURCE,
        IPC_ATTEMPT: INSTALLED,
    }
    if service == "telegram":
        labels["boca.socios.telegram-runtime-attempt"] = SENDER_ATTEMPT
    return tuple(sorted(labels.items()))


def _container(ident: str, service: str, image_id: str, *, running: bool) -> Container:
    controller = service == "controller"
    sender = service == "telegram"
    return Container(
        ident=ident,
        name=f"/boca-socios-{service}-1",
        image_id=image_id,
        running=running,
        labels=_labels(
            service, CONFIG_CONTROLLER if controller else CONFIG_SENDER if sender else CONFIG_WORKER
        ),
        volumes=(
            (
                "boca-socios_boca_browser_ipc",
                "boca-socios_boca_data",
                "boca-socios_boca_key",
                "boca-socios_boca_owner",
            )
            if controller
            else ("boca-socios_boca_data", "boca-socios_boca_telegram")
            if sender
            else ("boca-socios_boca_browser_ipc",)
        ),
        networks=(
            ("boca-socios_boca_private",)
            if controller
            else ("boca-socios_boca_telegram_egress",)
            if sender
            else ()
        ),
    )


def _mount(name: str, path: str, writable: bool) -> dict[str, object]:
    return {"Type": "volume", "Driver": "local", "Name": name, "Destination": path, "RW": writable}


class FakeIO:
    """Injected fake; production IO must use the dedicated Boca rootless socket."""

    def __init__(
        self,
        data_parent: Path,
        *,
        worker_running: bool = True,
        engine: bool = False,
        sender_running: bool | None = None,
    ):
        self.uid = self.gid = 10001
        self.engine_running = engine
        self.effects: list[tuple[str, str, str]] = []
        self.fail_next_effect = False
        self.inventory_value = Inventory(
            containers=(
                _container(CONTROLLER, "controller", CI, running=True),
                _container(WORKER, "browser-worker", WI, running=worker_running),
            )
            + (
                (_container(SENDER, "telegram", CI, running=sender_running),)
                if sender_running is not None
                else ()
            ),
            images=(
                Image(CI, (CONTROLLER_REF,), "https://github.com/mbalbo2023/boca-socios-assistant"),
                Image(WI, (WORKER_REF,), "https://github.com/mbalbo2023/boca-socios-assistant"),
            ),
            networks=(Network("boca-socios_boca_private", "2" * 64, (CONTROLLER,), ()),)
            + (
                (
                    Network(
                        "boca-socios_boca_telegram_egress",
                        "3" * 64,
                        (SENDER,) if sender_running else (),
                        (),
                    ),
                )
                if sender_running is not None
                else ()
            ),
            volumes=tuple(
                Volume(name, ())
                for name in (
                    "boca-socios_boca_data",
                    "boca-socios_boca_key",
                    "boca-socios_boca_owner",
                    "boca-socios_boca_browser_ipc",
                )
                + (("boca-socios_boca_telegram",) if sender_running is not None else ())
            ),
            disk=DiskInodes(100, 10),
        )
        self.fields: dict[tuple[str, str, str], object] = {}
        self.fields[("volume", "boca-socios_boca_data", "Mountpoint")] = str(data_parent)
        for ident, image, user, service in (
            (
                (CONTROLLER, CONTROLLER_REF, "10001:10001", "controller"),
                (WORKER, WORKER_REF, "10002:10002", "browser-worker"),
            )
            + ((SENDER, CONTROLLER_REF, "10001:10001", "telegram"),)
            if sender_running is not None
            else (
                (CONTROLLER, CONTROLLER_REF, "10001:10001", "controller"),
                (WORKER, WORKER_REF, "10002:10002", "browser-worker"),
            )
        ):
            self.fields[("container", ident, "Config.Image")] = image
            self.fields[("container", ident, "Config.User")] = user
            self.fields[("container", ident, "HostConfig.RestartPolicy")] = {
                "Name": "no",
                "MaximumRetryCount": 0,
            }
            self.fields[("container", ident, "HostConfig.ReadonlyRootfs")] = True
            self.fields[("container", ident, "HostConfig.Privileged")] = False
            self.fields[("container", ident, "HostConfig.Init")] = True
            self.fields[("container", ident, "HostConfig.PublishAllPorts")] = False
            self.fields[("container", ident, "RestartCount")] = 0
            self.fields[("container", ident, "HostConfig.NetworkMode")] = (
                "none"
                if service == "browser-worker"
                else "boca-socios_boca_telegram_egress"
                if service == "telegram"
                else "boca-socios_boca_private"
            )
            self.fields[("container", ident, "NetworkSettings.Ports")] = (
                {}
                if service != "controller"
                else {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
            )
            self.fields[("container", ident, "Mounts")] = (
                [_mount("boca-socios_boca_browser_ipc", "/run/boca-browser-ipc", True)]
                if service == "browser-worker"
                else [
                    _mount("boca-socios_boca_data", "/data", True),
                    _mount("boca-socios_boca_telegram", "/run/telegram", False),
                ]
                if service == "telegram"
                else [
                    _mount("boca-socios_boca_data", "/data", True),
                    _mount("boca-socios_boca_key", "/run/secrets", False),
                    _mount("boca-socios_boca_owner", "/run/owner", False),
                    _mount("boca-socios_boca_browser_ipc", "/run/boca-browser-ipc", False),
                ]
            )
        self.set_state(CONTROLLER, True)
        self.set_state(WORKER, worker_running)
        if sender_running is not None:
            self.set_state(SENDER, sender_running)

    def set_state(self, ident: str, running: bool) -> None:
        self.fields[("container", ident, "State.Running")] = running
        self.fields[("container", ident, "State.Restarting")] = False
        self.fields[("container", ident, "State.Health.Status")] = "healthy" if running else None
        self.inventory_value = replace(
            self.inventory_value,
            containers=tuple(
                replace(c, running=running) if c.ident == ident else c
                for c in self.inventory_value.containers
            ),
        )

    def inventory(self) -> Inventory:
        return self.inventory_value

    def field(self, kind: str, ident: str, field: str) -> object:
        return self.fields[(kind, ident, field)]

    def engine_request(self, controller_id: str, operation: str) -> EngineReceipt:
        assert controller_id == CONTROLLER
        if operation != "status":
            self.effects.append(("engine", controller_id, operation))
            if self.fail_next_effect:
                raise RuntimeError("injected uncertain transport")
            self.engine_running = operation == "start"
        return EngineReceipt(
            "RUNNING" if self.engine_running else "STOPPED", operation != "status", 27
        )

    def worker_action(self, worker_id: str, operation: str) -> None:
        assert worker_id == WORKER
        self.effects.append(("worker", worker_id, operation))
        if self.fail_next_effect:
            raise RuntimeError("injected uncertain transport")
        self.set_state(WORKER, operation == "start")


@pytest.fixture(autouse=True)
def fake_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    def held(lease: BocaJobLease, attempt: str) -> None:
        assert lease.active and lease.attempt_id == attempt

    monkeypatch.setattr(adapter, "verify_protected_boca_job_lease", held)
    monkeypatch.setattr(adapter.lifecycle, "verify_protected_boca_job_lease", held)


def _request_with_real_ledger(
    path: Path, component: str = "bot", target: str = "start"
) -> tuple[LifecycleHostCoordinates, LifecycleIntentStore]:
    """True SQLite legacy audit rows; never add the forbidden 0008 migration."""
    database = Database(path)
    database.migrate()
    migrations = files("boca_socios.storage.migrations")
    for version, name in (
        (2, "0002_notification_outbox.sql"),
        (3, "0003_reservation_guard.sql"),
        (5, "0005_simulation_outcomes.sql"),
        (6, "0006_beta_commands.sql"),
    ):
        sql = migrations.joinpath(name).read_bytes()
        with database.connection() as connection:
            connection.executescript(sql.decode("utf-8"))
            connection.execute(
                "INSERT INTO schema_migrations(version,checksum) VALUES (?,?)",
                (version, hashlib.sha256(sql).hexdigest()),
            )
            connection.commit()
    ledger = LifecycleIntentStore(database)
    coords = _coordinates(path, component, target)
    ledger.request(component, target, coords.request_id)
    return coords, ledger


def test_probes_exact_rootless_pair_without_contacting_foreign_work(tmp_path: Path) -> None:
    coords = _coordinates(tmp_path / "boca.sqlite3")
    io = FakeIO(tmp_path)
    probe = adapter.RootlessLifecycleProbe(_binding(), io)
    snap = probe.observe(coords, BocaJobLease(RUN, 12, 123, True))
    assert snap.require(coords) is False
    assert snap.controller_running and snap.controller_healthy
    assert snap.worker_running and snap.worker_healthy
    assert snap.bot_engine_running is False
    assert io.effects == []


@pytest.mark.parametrize(
    "mutation",
    [
        "foreign_container",
        "wrong_controller",
        "wrong_config_hash",
        "wrong_source",
        "wrong_image",
        "wrong_image_config_id",
        "foreign_network",
        "wrong_host_port",
        "extra_mount",
        "bad_rootless_uid",
        "missing_worker_health",
        "unexpected_restart_policy",
        "changed_data_volume",
    ],
)
def test_rejects_unverified_host_identity_and_boundary(tmp_path: Path, mutation: str) -> None:
    coords = _coordinates(tmp_path / "boca.sqlite3")
    io = FakeIO(tmp_path)
    if mutation == "foreign_container":
        io.inventory_value = replace(
            io.inventory_value,
            containers=io.inventory_value.containers
            + (_container("9" * 64, "other", CI, running=True),),
        )
    elif mutation == "wrong_controller":
        io.inventory_value = replace(
            io.inventory_value,
            containers=(
                replace(io.inventory_value.containers[0], name="/porota"),
                io.inventory_value.containers[1],
            ),
        )
    elif mutation == "wrong_config_hash":
        first = io.inventory_value.containers[0]
        io.inventory_value = replace(
            io.inventory_value,
            containers=(
                replace(
                    first,
                    labels=tuple(
                        (k, "0" * 64 if k == "com.docker.compose.config-hash" else v)
                        for k, v in first.labels
                    ),
                ),
                io.inventory_value.containers[1],
            ),
        )
    elif mutation == "wrong_source":
        first = io.inventory_value.containers[0]
        io.inventory_value = replace(
            io.inventory_value,
            containers=(
                replace(
                    first,
                    labels=tuple(
                        (k, "0" * 40 if k == "org.opencontainers.image.revision" else v)
                        for k, v in first.labels
                    ),
                ),
                io.inventory_value.containers[1],
            ),
        )
    elif mutation == "wrong_image":
        io.inventory_value = replace(
            io.inventory_value,
            images=(
                replace(io.inventory_value.images[0], source=None),
                io.inventory_value.images[1],
            ),
        )
    elif mutation == "wrong_image_config_id":
        controller = io.inventory_value.containers[0]
        io.inventory_value = replace(
            io.inventory_value,
            containers=(
                replace(controller, image_id="sha256:" + "0" * 64),
                io.inventory_value.containers[1],
            ),
        )
    elif mutation == "foreign_network":
        first = io.inventory_value.containers[0]
        io.inventory_value = replace(
            io.inventory_value,
            containers=(
                replace(first, networks=("porota_private",)),
                io.inventory_value.containers[1],
            ),
        )
    elif mutation == "wrong_host_port":
        io.fields[("container", CONTROLLER, "NetworkSettings.Ports")] = {
            "8443/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8443"}]  # noqa: S104 - rejected negative fixture
        }
    elif mutation == "extra_mount":
        io.fields[("container", WORKER, "Mounts")] = io.fields[("container", WORKER, "Mounts")] + [
            _mount("foreign", "/root", True)
        ]  # type: ignore[operator]
    elif mutation == "bad_rootless_uid":
        io.uid = 0
    elif mutation == "missing_worker_health":
        io.fields[("container", WORKER, "State.Health.Status")] = "starting"
    elif mutation == "unexpected_restart_policy":
        io.fields[("container", CONTROLLER, "HostConfig.RestartPolicy")] = {
            "Name": "always",
            "MaximumRetryCount": 0,
        }
    elif mutation == "changed_data_volume":
        io.fields[("volume", "boca-socios_boca_data", "Mountpoint")] = "/foreign"
    with pytest.raises(adapter.LifecycleAdapterNoGo):
        adapter.RootlessLifecycleProbe(_binding(), io).observe(
            coords, BocaJobLease(RUN, 12, 123, True)
        )


def test_separate_chromium_stop_keeps_controller_and_http_healthy(tmp_path: Path) -> None:
    coords = _coordinates(tmp_path / "boca.sqlite3", "chromium", "stop")
    io = FakeIO(tmp_path, engine=False)
    receipt = adapter.RootlessLifecycleProbe(_binding(), io)
    claim = HostLifecycleClaim(coords, True)
    adapter.apply_exact_effect(claim, lease=BocaJobLease(RUN, 12, 123, True), probe=receipt, io=io)
    assert io.effects == [("worker", WORKER, "stop")]
    snap = receipt.observe(coords, BocaJobLease(RUN, 12, 123, True))
    assert not snap.worker_running
    assert snap.controller_running and snap.controller_healthy
    assert snap.bot_engine_running is False


def test_unhealthy_running_chromium_stop_physically_applies_and_acks_legacy(tmp_path: Path) -> None:
    coords, ledger = _request_with_real_ledger(tmp_path / "boca.sqlite3", "chromium", "stop")
    io = FakeIO(tmp_path, engine=False, worker_running=True)
    io.fields[("container", WORKER, "State.Health.Status")] = "unhealthy"
    assert (
        adapter.execute_requested_lifecycle(
            coords,
            binding=_binding(),
            lease=BocaJobLease(RUN, 12, 123, True),
            io=io,
        )
        == "APPLIED"
    )
    assert ledger.current().status == "APPLIED"
    assert io.effects == [("worker", WORKER, "stop")]
    assert io.fields[("container", WORKER, "State.Running")] is False
    assert io.fields[("container", CONTROLLER, "State.Health.Status")] == "healthy"


def test_unhealthy_running_chromium_cannot_restart_or_claim(tmp_path: Path) -> None:
    coords, ledger = _request_with_real_ledger(tmp_path / "boca.sqlite3", "chromium", "start")
    io = FakeIO(tmp_path, engine=False, worker_running=True)
    io.fields[("container", WORKER, "State.Health.Status")] = "unhealthy"
    with pytest.raises(adapter.lifecycle.LifecycleHostUnavailable):
        adapter.execute_requested_lifecycle(
            coords,
            binding=_binding(),
            lease=BocaJobLease(RUN, 12, 123, True),
            io=io,
        )
    assert ledger.current().status == "REQUESTED"
    assert io.effects == []


def test_unhealthy_running_chromium_stop_cannot_bypass_controller_health(tmp_path: Path) -> None:
    coords, ledger = _request_with_real_ledger(tmp_path / "boca.sqlite3", "chromium", "stop")
    io = FakeIO(tmp_path, engine=False, worker_running=True)
    io.fields[("container", WORKER, "State.Health.Status")] = "unhealthy"
    io.fields[("container", CONTROLLER, "State.Health.Status")] = "unhealthy"
    with pytest.raises(adapter.lifecycle.LifecycleHostUnavailable):
        adapter.execute_requested_lifecycle(
            coords,
            binding=_binding(),
            lease=BocaJobLease(RUN, 12, 123, True),
            io=io,
        )
    assert ledger.current().status == "REQUESTED"
    assert io.effects == []


def test_running_bot_blocks_chromium_stop_before_docker_effect(tmp_path: Path) -> None:
    coords = _coordinates(tmp_path / "boca.sqlite3", "chromium", "stop")
    io = FakeIO(tmp_path, engine=True)
    with pytest.raises(adapter.LifecycleAdapterNoGo, match="stop bot first"):
        adapter.apply_exact_effect(
            HostLifecycleClaim(coords, True),
            lease=BocaJobLease(RUN, 12, 123, True),
            probe=adapter.RootlessLifecycleProbe(_binding(), io),
            io=io,
        )
    assert io.effects == []


def test_exact_controller_engine_start_stop_no_docker_container_restarts(tmp_path: Path) -> None:
    io = FakeIO(tmp_path, engine=False)
    probe = adapter.RootlessLifecycleProbe(_binding(), io)
    lease = BocaJobLease(RUN, 12, 123, True)
    start = _coordinates(tmp_path / "boca.sqlite3", "bot", "start")
    adapter.apply_exact_effect(HostLifecycleClaim(start, False), lease=lease, probe=probe, io=io)
    assert probe.observe(start, lease).bot_engine_running is True
    stop = _coordinates(tmp_path / "boca.sqlite3", "bot", "stop")
    adapter.apply_exact_effect(HostLifecycleClaim(stop, True), lease=lease, probe=probe, io=io)
    assert io.effects == [("engine", CONTROLLER, "start"), ("engine", CONTROLLER, "stop")]
    assert probe.observe(stop, lease).bot_engine_running is False


@pytest.mark.parametrize("worker_running", [True, False])
def test_bot_stop_remains_available_if_chromium_failed_or_stopped(
    tmp_path: Path, worker_running: bool
) -> None:
    coords = _coordinates(tmp_path / "boca.sqlite3", "bot", "stop")
    io = FakeIO(tmp_path, engine=True, worker_running=worker_running)
    if worker_running:
        io.fields[("container", WORKER, "State.Health.Status")] = "unhealthy"
    probe = adapter.RootlessLifecycleProbe(_binding(), io)
    adapter.apply_exact_effect(
        HostLifecycleClaim(coords, True),
        lease=BocaJobLease(RUN, 12, 123, True),
        probe=probe,
        io=io,
    )
    assert io.effects == [("engine", CONTROLLER, "stop")]
    assert probe.observe(coords, BocaJobLease(RUN, 12, 123, True)).bot_engine_running is False


@pytest.mark.parametrize("sender_running", [True, False])
@pytest.mark.parametrize("component,target", [("bot", "start"), ("chromium", "stop")])
def test_controls_preserve_exact_sender_off_or_on_unchanged(
    tmp_path: Path, sender_running: bool, component: str, target: str
) -> None:
    coords = _coordinates(tmp_path / "boca.sqlite3", component, target)
    io = FakeIO(tmp_path, engine=False, sender_running=sender_running)
    binding = _binding(sender_running=sender_running)
    probe = adapter.RootlessLifecycleProbe(binding, io)
    before = probe.observe(coords, BocaJobLease(RUN, 12, 123, True))
    assert before.controller_running and before.controller_healthy
    adapter.apply_exact_effect(
        HostLifecycleClaim(coords, component == "chromium"),
        lease=BocaJobLease(RUN, 12, 123, True),
        probe=probe,
        io=io,
    )
    assert io.fields[("container", SENDER, "State.Running")] is sender_running
    assert not any(effect[1] == SENDER for effect in io.effects)
    assert probe.observe(coords, BocaJobLease(RUN, 12, 123, True)).controller_healthy


def test_stopped_sender_may_have_no_live_network_endpoint(tmp_path: Path) -> None:
    io = FakeIO(tmp_path, sender_running=False)
    sender = io.inventory_value.containers[2]
    io.inventory_value = replace(
        io.inventory_value,
        containers=io.inventory_value.containers[:2] + (replace(sender, networks=()),),
    )
    coords = _coordinates(tmp_path / "boca.sqlite3", "bot", "start")
    assert (
        adapter.RootlessLifecycleProbe(_binding(sender_running=False), io)
        .observe(coords, BocaJobLease(RUN, 12, 123, True))
        .bot_engine_running
        is False
    )


@pytest.mark.parametrize("sender_running", [True, False])
def test_real_legacy_claim_ack_preserves_telegram_sender_variant(
    tmp_path: Path, sender_running: bool
) -> None:
    coords, ledger = _request_with_real_ledger(tmp_path / "boca.sqlite3")
    io = FakeIO(tmp_path, sender_running=sender_running)
    assert (
        adapter.execute_requested_lifecycle(
            coords,
            binding=_binding(sender_running=sender_running),
            lease=BocaJobLease(RUN, 12, 123, True),
            io=io,
        )
        == "APPLIED"
    )
    assert ledger.current().status == "APPLIED"
    assert io.fields[("container", SENDER, "State.Running")] is sender_running
    assert io.effects == [("engine", CONTROLLER, "start")]


@pytest.mark.parametrize(
    "mutation",
    [
        "absent_binding",
        "different_sender_id",
        "sender_image",
        "sender_runtime_attempt",
        "sender_network",
        "sender_mount",
        "sender_running_drift",
        "sender_source",
        "sender_config_hash",
    ],
)
def test_sender_presence_requires_independent_exact_binding(tmp_path: Path, mutation: str) -> None:
    coords = _coordinates(tmp_path / "boca.sqlite3")
    io = FakeIO(tmp_path, sender_running=True)
    binding = _binding(sender_running=True)
    if mutation == "absent_binding":
        binding = _binding()
    elif mutation == "different_sender_id":
        binding = replace(binding, sender_id="0" * 64)
    elif mutation == "sender_image":
        sender = io.inventory_value.containers[2]
        io.inventory_value = replace(
            io.inventory_value,
            containers=io.inventory_value.containers[:2] + (replace(sender, image_id=WI),),
        )
    elif mutation == "sender_runtime_attempt":
        sender = io.inventory_value.containers[2]
        io.inventory_value = replace(
            io.inventory_value,
            containers=io.inventory_value.containers[:2]
            + (
                replace(
                    sender,
                    labels=tuple(
                        (key, "0" if key == "boca.socios.telegram-runtime-attempt" else value)
                        for key, value in sender.labels
                    ),
                ),
            ),
        )
    elif mutation == "sender_network":
        sender = io.inventory_value.containers[2]
        io.inventory_value = replace(
            io.inventory_value,
            containers=io.inventory_value.containers[:2]
            + (replace(sender, networks=("porota_network",)),),
        )
    elif mutation == "sender_mount":
        io.fields[("container", SENDER, "Mounts")] = [
            _mount("boca-socios_boca_data", "/data", True),
            _mount("foreign", "/secret", True),
        ]
    elif mutation == "sender_running_drift":
        io.fields[("container", SENDER, "State.Running")] = False
    elif mutation == "sender_source":
        sender = io.inventory_value.containers[2]
        io.inventory_value = replace(
            io.inventory_value,
            containers=io.inventory_value.containers[:2]
            + (
                replace(
                    sender,
                    labels=tuple(
                        (key, "0" * 40 if key == "org.opencontainers.image.revision" else value)
                        for key, value in sender.labels
                    ),
                ),
            ),
        )
    elif mutation == "sender_config_hash":
        binding = replace(binding, sender_config_hash=CONFIG_WORKER)
    with pytest.raises(adapter.LifecycleAdapterNoGo):
        adapter.RootlessLifecycleProbe(binding, io).observe(
            coords, BocaJobLease(RUN, 12, 123, True)
        )


def test_uncertain_effect_never_becomes_false_applied_or_retry(tmp_path: Path) -> None:
    coords = _coordinates(tmp_path / "boca.sqlite3")
    io = FakeIO(tmp_path, engine=False)
    io.fail_next_effect = True
    with pytest.raises(adapter.LifecycleAdapterNoGo, match="uncertain"):
        adapter.apply_exact_effect(
            HostLifecycleClaim(coords, False),
            lease=BocaJobLease(RUN, 12, 123, True),
            probe=adapter.RootlessLifecycleProbe(_binding(), io),
            io=io,
        )
    assert io.effects == [("engine", CONTROLLER, "start")]


@pytest.mark.parametrize(
    ("start_engine_running", "inject_uncertainty", "result", "actions"),
    [
        (False, False, "APPLIED", 1),
        (True, False, "REFUSED", 0),
        (False, True, "UNCERTAIN", 1),
    ],
)
def test_durable_legacy_ledger_claim_ack_and_uncertainty(
    tmp_path: Path,
    start_engine_running: bool,
    inject_uncertainty: bool,
    result: str,
    actions: int,
) -> None:
    coords, ledger = _request_with_real_ledger(tmp_path / "boca.sqlite3")
    io = FakeIO(tmp_path, engine=start_engine_running)
    io.fail_next_effect = inject_uncertainty
    if inject_uncertainty:
        with pytest.raises(adapter.LifecycleEffectUncertain):
            adapter.execute_requested_lifecycle(
                coords,
                binding=_binding(),
                lease=BocaJobLease(RUN, 12, 123, True),
                io=io,
            )
    else:
        returned = adapter.execute_requested_lifecycle(
            coords,
            binding=_binding(),
            lease=BocaJobLease(RUN, 12, 123, True),
            io=io,
        )
        assert returned == result
    assert ledger.current().status == result
    assert len(io.effects) == actions
    # Durable terminal/uncertain record remains visible without starting the
    # physical motor or consulting any unrelated controller.
    assert ledger.current().operation_id == coords.request_id


def test_real_ledger_refuses_chromium_stop_when_bot_is_running(tmp_path: Path) -> None:
    coords, ledger = _request_with_real_ledger(tmp_path / "boca.sqlite3", "chromium", "stop")
    io = FakeIO(tmp_path, engine=True)
    with pytest.raises(adapter.LifecycleAdapterNoGo, match="stop bot first"):
        adapter.execute_requested_lifecycle(
            coords,
            binding=_binding(),
            lease=BocaJobLease(RUN, 12, 123, True),
            io=io,
        )
    assert ledger.current().status == "REFUSED"
    assert io.effects == []


def test_production_engine_command_uses_only_exact_boca_container_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def docker(*args: str) -> str:
        calls.append(args)
        return '{"version":1,"state":"RUNNING","changed":true,"pid":27}'

    monkeypatch.setattr(adapter.cleanup, "_docker", docker)
    transport = adapter.ProductionRootlessDockerIO()
    receipt = transport.engine_request(CONTROLLER, "start")
    assert receipt.state == "RUNNING" and receipt.changed
    assert calls == [
        (
            "exec",
            "--user",
            "10001:10001",
            CONTROLLER,
            "python",
            "-m",
            "boca_socios.integration.engine_socket",
            "start",
        )
    ]
    with pytest.raises(adapter.LifecycleAdapterNoGo):
        transport.engine_request("/porota", "start")
    with pytest.raises(adapter.LifecycleAdapterNoGo):
        transport.engine_request(CONTROLLER, "restart")
    assert len(calls) == 1


def test_production_engine_rejects_ambiguous_duplicate_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        adapter.cleanup,
        "_docker",
        lambda *args: '{"version":1,"state":"RUNNING","changed":true,"pid":27,"pid":28}',
    )
    with pytest.raises(adapter.LifecycleAdapterNoGo):
        adapter.ProductionRootlessDockerIO().engine_request(CONTROLLER, "start")


def test_production_worker_command_has_no_compose_or_other_service_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def docker(*args: str) -> str:
        calls.append(args)
        return WORKER

    monkeypatch.setattr(adapter.cleanup, "_docker", docker)
    transport = adapter.ProductionRootlessDockerIO()
    monkeypatch.setattr(
        transport,
        "field",
        lambda kind, ident, field: (
            True
            if field == "State.Running" and len(calls) == 1
            else "healthy"
            if field == "State.Health.Status"
            else False
        ),
    )
    transport.worker_action(WORKER, "start")
    transport.worker_action(WORKER, "stop")
    assert calls == [("start", WORKER), ("stop", "--time", "8", WORKER)]
    with pytest.raises(adapter.LifecycleAdapterNoGo):
        transport.worker_action("porota-1", "stop")


def test_release_binding_requires_independently_pinned_config_hashes() -> None:
    with pytest.raises(adapter.LifecycleAdapterNoGo):
        adapter.ReviewedInstalledPair(INSTALLED, CONFIG_CONTROLLER, CONFIG_CONTROLLER).require()
    with pytest.raises(adapter.LifecycleAdapterNoGo):
        adapter.ReviewedInstalledPair("", CONFIG_CONTROLLER, CONFIG_WORKER).require()
