"""Controller-internal AF_UNIX engine control; no host, TCP or Boca traffic."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest

from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.integration import engine_socket
from boca_socios.integration.beta import BetaCoordinator, CommandState
from boca_socios.integration.command_host import BetaCommandHost
from boca_socios.integration.engine_socket import LocalEngineSocket, LocalEngineUnavailable
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from boca_socios.storage.database import Database


class SyntheticBrowser:
    def __init__(self) -> None:
        self.calls = 0
        self.started = Event()
        self.release = Event()
        self.release.set()
        self.cancelled = False

    async def simulate_general_reservation(self) -> SimulationOutcome:
        self.calls += 1
        self.started.set()
        try:
            while not self.release.is_set():
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return SimulationOutcome.RESERVED_IN_SIMULATOR


@pytest.fixture
def engine(tmp_path: Path):
    db = Database(tmp_path / "synthetic.sqlite3")
    outbox = SqliteNotificationOutbox(db)
    browser = SyntheticBrowser()

    def factory() -> BetaCoordinator:
        return BetaCoordinator(database=db, outbox=outbox, browser=browser)

    first = factory()
    first.prepare_storage()
    db.create_member("member", "member@example.invalid", "synthetic")
    db.create_event("event", "synthetic")
    commands = BetaCommandHost.start(first, coordinator_factory=factory)
    socket_server = LocalEngineSocket(commands, path=tmp_path / "engine.sock")
    try:
        yield socket_server, commands, browser
    finally:
        socket_server.close()
        commands.close()


def test_real_bot_loop_stops_and_restarts_via_private_socket(engine) -> None:
    server, commands, browser = engine
    # The sandbox prohibits *all* socket() syscalls; exercise the exact
    # request dispatcher and wire framing offline. Hosted runner integration
    # must independently prove the AF_UNIX transport before physical GO.
    before = server._dispatch("status")
    assert before.state == "RUNNING"
    assert before.changed is False
    assert before.pid == os.getpid()

    stopped = server._dispatch("stop")
    assert stopped.state == "STOPPED"
    assert stopped.changed is True
    assert commands.engine_stopped and not commands._thread.is_alive()
    assert server._dispatch("stop").changed is False
    with pytest.raises(RuntimeError, match="stopped"):
        commands.begin(str(uuid4()), member_id="member", event_id="event")

    started = server._dispatch("start")
    assert started.state == "RUNNING" and started.changed is True
    assert server._dispatch("start").changed is False
    assert commands.engine_running
    assert browser.calls == 0

    key = str(uuid4())
    commands.begin(key, member_id="member", event_id="event")
    assert commands.status(key, member_id="member").state in {
        CommandState.ACCEPTED,
        CommandState.RUNNING,
        CommandState.COMPLETED,
    }


def test_real_bot_stop_cancels_inflight_and_returns_actual_state(engine) -> None:
    server, commands, browser = engine
    browser.release.clear()
    key = str(uuid4())
    commands.begin(key, member_id="member", event_id="event")
    assert browser.started.wait(2)
    receipt = server._dispatch("stop")
    assert receipt.state == "STOPPED" and receipt.changed
    assert browser.cancelled
    assert commands.engine_stopped


def test_unknown_socket_operation_and_path_fail_without_engine_effect(
    engine, tmp_path: Path
) -> None:
    server, commands, _ = engine
    with pytest.raises(LocalEngineUnavailable):
        server._dispatch("delete-all")  # type: ignore[arg-type]
    with pytest.raises(LocalEngineUnavailable):
        engine_socket.request_local_engine("stop", path=tmp_path / "absent.sock")
    assert commands.engine_running


def test_control_framing_and_duplicate_json_keys_are_rejected(engine) -> None:
    server, _, _ = engine
    payload = server._dispatch("status")._as_bytes()
    assert payload.startswith(b'{"version":1,"state":"RUNNING"')
    assert engine_socket._unique_object(payload[:-1])["state"] == "RUNNING"
    with pytest.raises(LocalEngineUnavailable):
        engine_socket._unique_object(b'{"version":1,"version":1}')
    with pytest.raises(LocalEngineUnavailable):
        engine_socket._unique_object(b'{"version":null,}')


def test_engine_socket_never_makes_a_tcp_listener() -> None:
    import inspect

    from boca_socios.integration import engine_socket

    source = inspect.getsource(engine_socket)
    assert "AF_UNIX" in source
    assert "AF_INET" not in source
    assert "socket.AF_UNIX" in source
