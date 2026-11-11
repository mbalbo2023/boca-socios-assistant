"""The private owner control, host actuator and disposable restart contract."""

import hashlib
import os
import socket
import struct
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import test_host_lifecycle_rootless_adapter as docker_fixture
import test_private_beta_panel as panel_fixture
from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_lifecycle_rootless_adapter as adapter
from boca_socios import host_on_demand_lifecycle as lifecycle
from boca_socios import host_on_demand_service as service
from boca_socios.panel import bot_control, owner_sessions
from boca_socios.panel.lifecycle_intents import LifecycleIntentStore
from boca_socios.panel.private_http import PrivatePanelApplication
from boca_socios.security.credential_vault import CredentialVault
from boca_socios.security.enrollment import MemberEnrollmentService
from test_private_lifecycle_controls import _bot_fields
from test_worker_start_lab import lab


class WorkerFixture(docker_fixture.FakeIO):
    """Real host attestor over an in-memory inventory, with inert worker and engine effects."""

    def __init__(self, root: Path):
        super().__init__(root, worker_running=False)
        self.state = "created"
        self.starts_from = []
        self.after_start = lambda: None
        self.peers = []
        self.stops = 0
        self.fields["container", docker_fixture.CONTROLLER, "HostConfig.RestartPolicy"] = {
            "Name": "unless-stopped",
            "MaximumRetryCount": 0,
        }
        self.fields["container", docker_fixture.CONTROLLER, "Mounts"].append(
            {
                "Type": "bind",
                "Source": str(root / "control"),
                "Destination": "/run/boca-bot-control",
                "RW": False,
                "Propagation": "rprivate",
            }
        )
        self.fields["container", docker_fixture.WORKER, "HostConfig.PortBindings"] = {}
        self.fields["container", docker_fixture.WORKER, "NetworkSettings.Networks"] = {
            "boca-socios_boca_browser_egress": {"IPAddress": "", "GlobalIPv6Address": ""}
        }
        self.probe = adapter.RootlessLifecycleProbe(docker_fixture._binding(), self, on_demand=True)

    def observe(self, coordinates, lease):
        return self.probe.observe(coordinates, lease)

    def worker_state(self, worker_id):
        assert worker_id == docker_fixture.WORKER
        return self.state

    def stopped_token(self, worker_id):
        assert self.worker_state(worker_id) == "exited"
        return hashlib.sha256(f"{worker_id}/{self.stops}".encode()).hexdigest()

    def start_worker(self, installation, state, before_start):
        assert installation.worker_id == docker_fixture.WORKER
        assert state == self.state and state in ("created", "exited")
        before_start()
        self.starts_from.append(state)
        self.worker_action(installation.worker_id, "start")
        self.state = "running"
        self.after_start()

    def verify_peer(self, controller_id):
        assert controller_id == docker_fixture.CONTROLLER and self.state == "running"
        self.peers.append(controller_id)

    def stop_worker(self, worker_id):
        assert not self.engine_running and self.worker_state(worker_id) == "running"
        self.worker_action(worker_id, "stop")
        self.state = "exited"
        self.stops += 1


class ControlSocket:
    """Use the named Unix endpoint whenever permitted, including every Actions run."""

    def __init__(self, stack, path):
        self.pending = deque()
        self.stack = stack
        try:
            self.listener = stack.enter_context(socket.socket(socket.AF_UNIX, socket.SOCK_STREAM))
            self.listener.bind(path)
        except PermissionError:
            if os.environ.get("GITHUB_ACTIONS") == "true":
                raise
            # Sandboxes that forbid creating named sockets still allow AF_UNIX socketpair.
            self.listener = None
        else:
            self.listener.listen(4)
            self.listener.settimeout(2)

    def wake(self, operation):
        if self.listener is not None:
            bot_control.wake_bot_control(operation)
            return
        client, server = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.pending.append(self.stack.enter_context(server))

        class ConnectedSocket(socket.socket):
            def connect(self, path):
                assert path == bot_control.CONTROL_SOCKET

        def connected(family, kind):
            assert (family, kind) == (socket.AF_UNIX, socket.SOCK_STREAM)
            return ConnectedSocket(family, kind, fileno=client.detach())

        transport = SimpleNamespace(
            socket=connected, AF_UNIX=socket.AF_UNIX, SOCK_STREAM=socket.SOCK_STREAM
        )
        with client, patch.object(bot_control, "socket", transport):
            bot_control.wake_bot_control(operation)

    def accept(self):
        return self.listener.accept()[0] if self.listener is not None else self.pending.popleft()


class OwnerJourney:
    def __init__(self, path, channel, clock):
        self.path = path
        self.channel = channel
        self.clock = clock
        self.io = WorkerFixture(path.parent)
        self.provider, key, credential_id = panel_fixture._passkey([0.0])
        self.commands = panel_fixture.FakeHost()
        self.app, self.db = panel_fixture._app(
            path,
            self.provider,
            self.commands,
            bot_control=channel.wake,
        )
        migrations = files("boca_socios.storage.migrations")
        for version, name in (
            (3, "0003_reservation_guard.sql"),
            (5, "0005_simulation_outcomes.sql"),
        ):
            raw = migrations.joinpath(name).read_bytes()
            with self.db.connection() as connection, connection:
                connection.executescript(raw.decode())
                connection.execute(
                    "INSERT INTO schema_migrations(version,checksum) VALUES (?,?)",
                    (version, hashlib.sha256(raw).hexdigest()),
                )
        self.cookie = panel_fixture._login(self.app, key, credential_id)
        self.installation = lifecycle.OnDemandInstallation(
            docker_fixture.INSTALLED,
            docker_fixture.SOURCE,
            docker_fixture.CONTROLLER,
            docker_fixture.CONTROLLER_REF,
            docker_fixture.WORKER,
            docker_fixture.WORKER_REF,
            path,
            docker_fixture._binding(),
        )

    def control(self):
        assert panel_fixture._request(self.app, "/", cookie=self.cookie)[0] == 200
        status, _, body = panel_fixture._request(self.app, "/control", cookie=self.cookie)
        assert status == 200
        assert (
            self.io.field("container", docker_fixture.CONTROLLER, "State.Health.Status")
            == "healthy"
        )
        assert self.commands.calls == []
        return body

    def click(self, action, *, advance_clock=True):
        if advance_clock:
            self.clock[0] += 2
        fields = _bot_fields(self.control(), action)
        response = self.post(action, fields)
        assert response[0] == 303 and response[1]["Location"] == "/control"
        assert self.intent(fields["operation_id"]).status == "REQUESTED"
        return fields

    def post(self, action, fields):
        return panel_fixture._request(
            self.app, f"/control/bot/{action}", cookie=self.cookie, method="POST", payload=fields
        )

    def intent(self, operation):
        with self.db.connection() as connection:
            return LifecycleIntentStore.for_operation(connection, operation)

    def deliver(self, *, authorized=True, entered=None):
        result = []

        def peer(conn, installation):
            assert installation == self.installation
            cred = struct.unpack("3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            return authorized and cred == (os.getpid(), os.geteuid(), os.getegid())

        def apply(operation, installation):
            assert self.intent(operation) is not None
            if entered is not None:
                entered.set()
            receipt = lifecycle.apply_panel_request(operation, installation, io=self.io)
            result.append(receipt)
            return receipt

        with self.channel.accept() as connection:
            accepted = service.handle_connection(
                connection, self.installation, peer_check=peer, apply=apply
            )
        assert accepted is authorized
        if authorized:
            assert len(result) == 1
            return result[0]
        assert not result

    def restart_panel(self):
        self.app = PrivatePanelApplication(
            origin=panel_fixture.ORIGIN,
            database_path=self.path,
            owner_subject="owner",
            passkey=self.provider,
            members=MemberEnrollmentService(self.db, CredentialVault(os.urandom(32))),
            commands=self.commands,
            events={},
            bot_control=self.channel.wake,
        )


@pytest.fixture
def journey(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())
    monkeypatch.setattr(cleanup, "LEASE_DIR", tmp_path)
    monkeypatch.setattr(adapter, "panel_control_mount", lambda: str(tmp_path / "control"))
    clock = [100.0]
    monkeypatch.setattr(owner_sessions, "monotonic", lambda: clock[0])
    with ExitStack() as stack:
        # sun_path has a small limit; xdist per-test directories can be much longer.
        directory = stack.enter_context(TemporaryDirectory(prefix="boca-on-demand-"))
        path = os.path.join(directory, "control.sock")
        monkeypatch.setattr(bot_control, "CONTROL_SOCKET", path)
        yield OwnerJourney(tmp_path / "boca.sqlite3", ControlSocket(stack, path), clock)


def test_authenticated_clicks_reach_exact_worker_and_publish_durable_ack(journey):
    j = journey
    assert j.io.state == "created" and not j.io.engine_running
    start = j.click("iniciar")
    assert b"Pendiente" in j.control() and not j.io.effects
    assert j.deliver().status == j.intent(start["operation_id"]).status == "APPLIED"
    assert j.io.state == "running" and j.io.engine_running
    assert "confirmó".encode() in j.control()
    effects = list(j.io.effects)
    assert j.post("iniciar", start)[0] == 303
    j.channel.wake(start["operation_id"])
    assert j.deliver().status == "APPLIED" and j.io.effects == effects

    stop = j.click("detener")
    assert j.deliver().status == j.intent(stop["operation_id"]).status == "APPLIED"
    assert j.io.state == "exited" and not j.io.engine_running
    j.restart_panel()
    assert "confirmó".encode() in j.control()
    second = j.click("iniciar")
    assert second["operation_id"] != start["operation_id"]
    assert j.deliver().status == "APPLIED" and j.io.starts_from == ["created", "exited"]
    assert j.io.peers == [docker_fixture.CONTROLLER] * 2
    assert j.io.effects == [
        ("worker", docker_fixture.WORKER, "start"),
        ("engine", docker_fixture.CONTROLLER, "start"),
        ("engine", docker_fixture.CONTROLLER, "stop"),
        ("worker", docker_fixture.WORKER, "stop"),
        ("worker", docker_fixture.WORKER, "start"),
        ("engine", docker_fixture.CONTROLLER, "start"),
    ]


def test_an_unapproved_peer_cannot_ack_a_valid_durable_operation(journey):
    j = journey
    start = j.click("iniciar")
    j.deliver(authorized=False)
    assert j.intent(start["operation_id"]).status == "REQUESTED" and not j.io.effects
    assert b"Pendiente" in j.control()


def test_owner_stop_while_start_is_claimed_never_enables_the_engine(journey):
    j = journey
    start = j.click("iniciar")
    entered, release = Event(), Event()
    stopping = Event()

    def pause():
        entered.set()
        assert release.wait(10)

    j.io.after_start = pause
    with ThreadPoolExecutor(max_workers=2) as pool:
        applying = pool.submit(j.deliver)
        try:
            assert entered.wait(5)
            assert j.intent(start["operation_id"]).status == "CLAIMED"
            stop = j.click("detener", advance_clock=False)
            # Two independently accepted Unix connections, as with systemd Accept=yes.
            stopping_result = pool.submit(j.deliver, entered=stopping)
            assert stopping.wait(5) and not stopping_result.done()
            assert (
                j.intent(stop["operation_id"]).status == "REQUESTED" and b"Pendiente" in j.control()
            )
        finally:
            release.set()
        assert applying.result(timeout=5).status == "FAILED"
        assert (
            stopping_result.result(timeout=5).status
            == j.intent(stop["operation_id"]).status
            == "APPLIED"
        )
    assert j.intent(start["operation_id"]).status == "FAILED"
    assert j.io.effects == [
        ("worker", docker_fixture.WORKER, "start"),
        ("worker", docker_fixture.WORKER, "stop"),
    ]
    assert j.io.state == "exited" and not j.io.engine_running and "confirmó".encode() in j.control()


def test_worker_failure_keeps_owner_session_and_panel_after_recreation(journey, monkeypatch):
    j = journey
    start = j.click("iniciar")

    def fail():
        j.io.set_state(docker_fixture.WORKER, False)
        j.io.state = "exited"
        raise lifecycle.WorkerStartFailure("MODULE_NOT_FOUND_ERROR", exit_code=1, oom=False)

    j.io.after_start = fail
    receipt = j.deliver()
    assert receipt.status == j.intent(start["operation_id"]).status == "FAILED"
    assert receipt.cause == "MODULE_NOT_FOUND_ERROR" and receipt.exit_code == 1
    assert b"Fallo confirmado" in j.control() and not j.io.engine_running
    j.restart_panel()
    assert b"Fallo confirmado" in j.control()
    j.channel.wake(start["operation_id"])
    assert j.deliver() == receipt
    assert j.io.effects == [("worker", docker_fixture.WORKER, "start")]

    # Cross the independent Actions readback boundary against this same real file.
    # Only the container exec is substituted. The SELECTs use production read-only SQL.
    def in_controller(cid, action, fingerprint):
        assert cid == j.installation.controller_id and action == "status"
        assert fingerprint == j.installation.fingerprint()
        return lifecycle._status_wire(j.path, fingerprint) + "\n"

    monkeypatch.setattr(lifecycle, "_controller_command", in_controller)
    with j.db.connection() as db:
        before = db.execute("SELECT count(*) FROM audit_events").fetchone()
        readback = lifecycle.read_panel_status(j.installation)
        assert readback.operation_id == start["operation_id"] and readback.target == "start"
        assert (readback.status, readback.cause, readback.exit_code, readback.oom) == (
            "FAILED",
            "MODULE_NOT_FOUND_ERROR",
            1,
            False,
        )
        assert db.execute("SELECT count(*) FROM audit_events").fetchone() == before


@pytest.mark.parametrize("fault", [None, "replayed-stream", "replayed-start-time"])
def test_same_cid_restart_requires_fresh_stream_and_later_start(monkeypatch, fault) -> None:
    cid = "a" * 64
    image = "sha256:" + "b" * 64
    events = []
    starts = 0
    running = False

    def inspect(ident, key):
        assert ident == cid
        if key == ".State.Status":
            return "running" if running else "exited" if starts else "created"
        if key == ".State.StartedAt":
            second = 1 if fault == "replayed-start-time" else 2 * starts - 1
            return f"2026-11-10T00:00:0{second}Z"
        return {
            ".Id": cid,
            ".State.OOMKilled": False,
            ".State.FinishedAt": f"2026-11-10T00:00:0{2 * starts}Z",
        }[key]

    def start(ident):
        nonlocal starts, running
        assert ident == cid and not running
        starts += 1
        running = True
        events.append("start")

    @contextmanager
    def attach(_socket, ident):
        assert ident == cid and not running
        events.append("attach")

        class Stream:
            def finish(self):
                nonlocal running
                running = False
                events.append("finish")
                if starts == 1 or fault == "replayed-stream":
                    return lab.CaptureResult.PERMISSION_ERROR
                return lab.CaptureResult.RUNTIME_ERROR

        yield Stream()

    def docker(*args):
        if args == ("stop", "-t", "2", cid):
            events.append("stop")
            return cid
        assert args == ("wait", cid)
        return "1"

    monkeypatch.setattr(lab, "create_fixture", lambda *args: cid)
    monkeypatch.setattr(lab, "verify_fixture", lambda *args: None)
    monkeypatch.setattr(lab, "field", inspect)
    monkeypatch.setattr(lab, "start_fixture", start)
    monkeypatch.setattr(lab, "attach_output", attach)
    monkeypatch.setattr(lab, "wait_healthy", lambda ident: events.append("ready"))
    monkeypatch.setattr(lab, "docker", docker)

    def remove(ident, key, checked_image):
        assert (ident, key, checked_image) == (cid, "123-restart-exited", image)
        events.append("remove")

    monkeypatch.setattr(lab, "remove_fixture", remove)
    case = (image, "123", "restart-exited", lab.RESTART_FIXTURE, "RESTART_VERIFIED", 1)
    if fault:
        with pytest.raises(lab.LabError, match="RESTART_"):
            lab.exercise(*case)
    else:
        lab.exercise(*case)
    assert events == [
        "attach",
        "start",
        "ready",
        "stop",
        "finish",
        "attach",
        "start",
        "finish",
        "remove",
    ]
