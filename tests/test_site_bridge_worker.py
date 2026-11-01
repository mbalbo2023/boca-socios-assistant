"""D1 redelivery is reconciled through durable local command identity only."""

from __future__ import annotations

import asyncio
import base64
import time
from pathlib import Path

import pytest

from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.integration.bridge_client import (
    BridgeLease,
    BridgeUnavailable,
    SiteBridgeWorker,
)
from boca_socios.integration.command_host import CommandResultUnknown
from boca_socios.integration.command_store import CommandSnapshot, CommandState
from boca_socios.integration.operational import LocalBetaRuntime

MEMBER_ID = "ec6d7503-f92b-4094-9f24-b7483e9b82e1"
COMMAND_ID = "ba1e7e37-5e4a-4be9-b31b-3379027e4b0c"
EVENT_ID = "00000000-0000-4000-8000-000000000001"
LEASE = BridgeLease(
    operation_id="5387eb20-c962-42f5-933e-d5f681ab0877",
    command_id=COMMAND_ID,
    operation="synthetic_begin",
    member_id=MEMBER_ID,
    event_id=EVENT_ID,
    lease_id="c0ae377c-d477-4a46-8e69-266c4ea7eac0",
    attempts=1,
)


class SyntheticBrowser:
    calls = 0

    async def simulate_general_reservation(self) -> SimulationOutcome:
        self.calls += 1
        await asyncio.sleep(0)
        return SimulationOutcome.RESERVED_IN_SIMULATOR


class FakeTransport:
    def __init__(self, leases: list[BridgeLease | None]) -> None:
        self.leases = leases
        self.acks: list[tuple[str, str]] = []
        self.heartbeats: list[tuple[str, str, dict[str, object]]] = []
        self.fail_first_ack = False

    def lease(self) -> BridgeLease | None:
        return self.leases.pop(0)

    def ack(self, lease: BridgeLease, state: str) -> None:
        if self.fail_first_ack:
            self.fail_first_ack = False
            raise BridgeUnavailable("synthetic ack loss")
        self.acks.append((lease.operation_id, state))

    def heartbeat(self, source_sha: str, runtime_state: str, snapshot: dict[str, object]) -> None:
        self.heartbeats.append((source_sha, runtime_state, snapshot))


@pytest.fixture
def local(tmp_path: Path) -> tuple[LocalBetaRuntime, SyntheticBrowser]:
    key = tmp_path / "master"
    key.write_bytes(base64.b64encode(b"k" * 32) + b"\n")
    key.chmod(0o400)
    browser = SyntheticBrowser()
    runtime = LocalBetaRuntime.start(
        database_path=tmp_path / "boca.sqlite3",
        key_file=key,
        browser=browser,
        initialize_new=True,
    )
    runtime.database.create_member(MEMBER_ID, "synthetic@example.invalid", "synthetic")
    runtime.database.create_event(EVENT_ID, "Evento de prueba local")
    try:
        yield runtime, browser
    finally:
        runtime.close()


def _worker(
    local: tuple[LocalBetaRuntime, SyntheticBrowser], transport: FakeTransport
) -> SiteBridgeWorker:
    runtime, _ = local
    return SiteBridgeWorker(
        transport=transport,
        commands=runtime.commands,
        database_path=runtime.database.path,
        source_sha="a" * 40,
        clock=lambda: 100.0,
    )


def test_ack_loss_redelivery_preserves_one_local_command_and_no_credentials(
    local: tuple[LocalBetaRuntime, SyntheticBrowser],
) -> None:
    runtime, browser = local
    transport = FakeTransport([LEASE, LEASE])
    transport.fail_first_ack = True
    worker = _worker(local, transport)
    with pytest.raises(BridgeUnavailable):
        worker.tick()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        status = runtime.commands.status(COMMAND_ID, member_id=MEMBER_ID)
        if status and status.state is CommandState.COMPLETED:
            break
        time.sleep(0.01)
    else:
        pytest.fail("synthetic command did not settle")
    worker.tick()
    assert browser.calls == 1
    assert transport.acks == [(LEASE.operation_id, "completed")]
    assert len(transport.heartbeats) == 1
    heartbeat = transport.heartbeats[0]
    assert heartbeat[:2] == ("a" * 40, "ready")
    assert heartbeat[2]["external_confirmation"] == "not_observed"
    assert "synthetic@example.invalid" not in str(heartbeat)
    assert heartbeat[2]["counts"]["local_result_recorded_unverified"] in {0, 1}


def test_unknown_member_and_wrong_event_never_start_command(
    local: tuple[LocalBetaRuntime, SyntheticBrowser],
) -> None:
    _, browser = local
    unknown = BridgeLease(
        LEASE.operation_id,
        LEASE.command_id,
        LEASE.operation,
        "8c75125e-8cf0-4f9e-a2af-2cc16d39db5f",
        EVENT_ID,
        LEASE.lease_id,
        1,
    )
    transport = FakeTransport([unknown])
    _worker(local, transport).tick()
    assert transport.acks == [(LEASE.operation_id, "not_found")]
    wrong = BridgeLease(
        LEASE.operation_id,
        LEASE.command_id,
        LEASE.operation,
        MEMBER_ID,
        "13dfb6d0-a3a3-46a3-9e04-b4a971d8e1ca",
        LEASE.lease_id,
        1,
    )
    transport = FakeTransport([wrong])
    with pytest.raises(BridgeUnavailable):
        _worker(local, transport).tick()
    assert transport.acks == [] and browser.calls == 0


def test_stop_reuses_command_identity_after_completion(
    local: tuple[LocalBetaRuntime, SyntheticBrowser],
) -> None:
    runtime, browser = local
    begin = FakeTransport([LEASE])
    _worker(local, begin).tick()
    stop = BridgeLease(
        "d0945755-f7ce-4d83-9f44-dd93a1e842c5",
        COMMAND_ID,
        "synthetic_stop",
        MEMBER_ID,
        None,
        "90ea3df3-074c-4528-a8d3-14b23758472b",
        1,
    )
    transport = FakeTransport([stop, stop])
    worker = _worker(local, transport)
    worker.tick()
    worker.tick()
    assert [operation for operation, _ in transport.acks] == [stop.operation_id] * 2
    assert runtime.commands.status(COMMAND_ID, member_id=MEMBER_ID) is not None
    assert browser.calls <= 1


def test_unknown_local_commit_is_not_acknowledged_until_same_id_is_reinspected(
    local: tuple[LocalBetaRuntime, SyntheticBrowser],
) -> None:
    runtime, _ = local

    class AmbiguousCommands:
        calls = 0
        failed = False

        def status(self, command_id: str, *, member_id: str) -> CommandSnapshot | None:
            assert command_id == COMMAND_ID and member_id == MEMBER_ID
            if self.calls == 0:
                return None
            return CommandSnapshot(COMMAND_ID, "local-request", CommandState.ACCEPTED, 1, 1, False)

        def begin(self, command_id: str, *, member_id: str, event_id: str) -> CommandSnapshot:
            assert command_id == COMMAND_ID and member_id == MEMBER_ID and event_id == EVENT_ID
            self.calls += 1
            raise CommandResultUnknown("ambiguous synthetic commit")

        def stop(self, command_id: str, *, member_id: str) -> CommandSnapshot | None:
            raise AssertionError("stop was not requested")

    transport = FakeTransport([LEASE, LEASE])
    commands = AmbiguousCommands()
    worker = SiteBridgeWorker(
        transport=transport,
        commands=commands,
        database_path=runtime.database.path,
        source_sha="a" * 40,
        clock=lambda: 100.0,
    )
    worker.tick()
    assert transport.acks == []
    worker.tick()
    assert commands.calls == 1
    assert transport.acks == [(LEASE.operation_id, "accepted")]
