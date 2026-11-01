"""Issue #227: real local AF_UNIX frames, no Chrome, network or host writes."""

from __future__ import annotations

import asyncio
import os
import socket
import tempfile
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

import pytest

from boca_socios.browser import ipc_client as client_module
from boca_socios.browser import ipc_worker as worker_module
from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.browser.ipc_client import UnixSyntheticBrowser
from boca_socios.browser.ipc_protocol import (
    BUSY,
    MAX_FRAME_BYTES,
    NO_GO,
    REQUEST,
    SUCCESS,
    SyntheticIPCError,
    framed,
    read_frame,
)
from boca_socios.browser.ipc_worker import UnixSyntheticWorker, validate_no_egress_namespace
from boca_socios.domain.policy import TicketIntent
from boca_socios.integration.beta import BetaCoordinator, CommandState
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from boca_socios.storage.database import Database


@pytest.fixture
def socket_path(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    # Real same-process SO_PEERCRED under the unprivileged test runner; these
    # test-only overrides are never read from a CLI/env/runtime setting.
    uid, gid = os.geteuid(), os.getegid()
    assert uid == gid
    monkeypatch.setattr(client_module, "CONTROLLER_UID", uid)
    monkeypatch.setattr(client_module, "WORKER_UID", uid)
    monkeypatch.setattr(worker_module, "CONTROLLER_UID", uid)
    monkeypatch.setattr(worker_module, "WORKER_UID", uid)
    with tempfile.TemporaryDirectory(prefix="boca-ipc-", dir="/tmp") as directory:  # noqa: S108
        path = Path(directory)
        path.chmod(0o711)
        yield path / "synthetic.sock"


class FakeBrowser:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.calls = 0
        self.closed = False
        self.cancelled = False
        self.outcome: SimulationOutcome | None = SimulationOutcome.RESERVED_IN_SIMULATOR

    async def simulate_general_reservation(self) -> SimulationOutcome:
        self.calls += 1
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if self.outcome is None:
            raise ValueError("synthetic failure text must not reach client")
        return self.outcome

    async def close(self) -> None:
        self.closed = True


def worker(fake: FakeBrowser, path: Path, **kwargs: float) -> UnixSyntheticWorker:
    return UnixSyntheticWorker(fake, socket_path=path, boundary_check=lambda: None, **kwargs)


def test_one_real_unix_round_trip_is_fixed_and_inert_until_command(socket_path: Path) -> None:
    async def exercise() -> None:
        fake = FakeBrowser()
        sidecar = worker(fake, socket_path)
        connector = UnixSyntheticBrowser(socket_path=socket_path)
        assert not socket_path.exists() and fake.calls == 0
        await sidecar.start()
        try:
            assert fake.calls == 0
            assert (
                await connector.simulate_general_reservation()
                is SimulationOutcome.RESERVED_IN_SIMULATOR
            )
            assert fake.calls == 1
        finally:
            await connector.close()
            await sidecar.close()
        assert fake.closed and not socket_path.exists()

    asyncio.run(exercise())


def test_server_global_single_flight_and_client_single_flight(socket_path: Path) -> None:
    async def exercise() -> None:
        fake = FakeBrowser()
        fake.release.clear()
        sidecar = worker(fake, socket_path)
        one = UnixSyntheticBrowser(socket_path=socket_path)
        two = UnixSyntheticBrowser(socket_path=socket_path)
        await sidecar.start()
        try:
            active = asyncio.create_task(one.simulate_general_reservation())
            await fake.started.wait()
            with pytest.raises(SyntheticIPCError, match="client_busy"):
                await one.simulate_general_reservation()
            with pytest.raises(SyntheticIPCError, match="worker_busy"):
                await two.simulate_general_reservation()
            assert fake.calls == 1
            fake.release.set()
            assert await active is SimulationOutcome.RESERVED_IN_SIMULATOR
        finally:
            await sidecar.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("payload", [b"", b"GET http://boca.invalid/", REQUEST + b"\x00"])
def test_invalid_or_extra_request_never_starts_browser(socket_path: Path, payload: bytes) -> None:
    async def exercise() -> None:
        fake = FakeBrowser()
        sidecar = worker(fake, socket_path)
        await sidecar.start()
        try:
            reader, writer = await asyncio.open_unix_connection(str(socket_path))
            writer.write(len(payload).to_bytes(2, "big") + payload)
            writer.write_eof()
            assert await asyncio.wait_for(read_frame(reader), 1) == NO_GO
            assert await reader.read(1) == b""
            writer.close()
            await writer.wait_closed()
            assert fake.calls == 0
        finally:
            await sidecar.close()

    asyncio.run(exercise())


def test_oversize_frame_refused_without_reading_body_or_page(socket_path: Path) -> None:
    async def exercise() -> None:
        fake = FakeBrowser()
        sidecar = worker(fake, socket_path)
        await sidecar.start()
        try:
            reader, writer = await asyncio.open_unix_connection(str(socket_path))
            writer.write((MAX_FRAME_BYTES + 1).to_bytes(2, "big"))
            writer.write_eof()
            assert await asyncio.wait_for(read_frame(reader), 1) == NO_GO
            assert fake.calls == 0
            writer.close()
            await writer.wait_closed()
        finally:
            await sidecar.close()

    asyncio.run(exercise())


def test_two_commands_in_one_connection_are_not_replayed(socket_path: Path) -> None:
    async def exercise() -> None:
        fake = FakeBrowser()
        sidecar = worker(fake, socket_path)
        await sidecar.start()
        try:
            reader, writer = await asyncio.open_unix_connection(str(socket_path))
            writer.write(framed(REQUEST) + framed(REQUEST))
            writer.write_eof()
            assert await asyncio.wait_for(read_frame(reader), 1) == NO_GO
            assert fake.calls == 0
            writer.close()
            await writer.wait_closed()
        finally:
            await sidecar.close()

    asyncio.run(exercise())


def test_non_authorized_controller_peer_rejected_before_frame(
    socket_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        fake = FakeBrowser()
        sidecar = worker(fake, socket_path)
        monkeypatch.setattr(worker_module, "CONTROLLER_UID", 10001 if os.geteuid() != 10001 else 0)
        await sidecar.start()
        try:
            reader, writer = await asyncio.open_unix_connection(str(socket_path))
            writer.write(framed(REQUEST))
            writer.write_eof()
            # Linux may reset a stream with unread bytes when the unauthorized
            # peer is closed immediately. EOF and RST both deny the request.
            with suppress(ConnectionResetError):
                assert await asyncio.wait_for(reader.read(1), 1) == b""
            assert fake.calls == 0
            writer.close()
            with suppress(ConnectionResetError):
                await writer.wait_closed()
        finally:
            await sidecar.close()

    asyncio.run(exercise())


def test_client_refuses_wrong_worker_credentials_even_with_valid_inode(
    socket_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        fake = FakeBrowser()
        sidecar = worker(fake, socket_path)
        await sidecar.start()
        try:
            # Leave file ownership validation truthful; tamper only the peer
            # identity proof to exercise the independent kernel credential gate.
            original = client_module.socket_identity
            monkeypatch.setattr(client_module, "WORKER_UID", 10002 if os.geteuid() != 10002 else 0)
            monkeypatch.setattr(
                client_module, "socket_identity", lambda path, uid: original(path, uid=os.geteuid())
            )
            with pytest.raises(SyntheticIPCError, match="ipc_peer_unverified"):
                await UnixSyntheticBrowser(socket_path=socket_path).simulate_general_reservation()
            assert fake.calls == 0
        finally:
            await sidecar.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("tamper", ["broad_directory", "symlink_directory", "foreign_entry"])
def test_unsafe_ipc_mount_preserved_and_never_bound(
    socket_path: Path, tamper: str, tmp_path: Path
) -> None:
    async def exercise() -> None:
        fake = FakeBrowser()
        path = socket_path
        if tamper == "broad_directory":
            path.parent.chmod(0o777)
        elif tamper == "symlink_directory":
            alias = tmp_path / "linked"
            alias.symlink_to(path.parent, target_is_directory=True)
            path = alias / "synthetic.sock"
        else:
            (path.parent / "unrelated").write_text("unrelated, preserve")
        sidecar = worker(fake, path)
        with pytest.raises(SyntheticIPCError):
            await sidecar.start()
        assert not path.exists() and fake.calls == 0
        if tamper == "foreign_entry":
            assert (path.parent / "unrelated").read_text() == "unrelated, preserve"

    asyncio.run(exercise())


def test_unverified_client_socket_mode_refuses_before_connection(socket_path: Path) -> None:
    async def exercise() -> None:
        fake = FakeBrowser()
        sidecar = worker(fake, socket_path)
        await sidecar.start()
        try:
            socket_path.chmod(0o666)
            with pytest.raises(SyntheticIPCError, match="ipc_socket_unverified"):
                await UnixSyntheticBrowser(socket_path=socket_path).simulate_general_reservation()
            assert fake.calls == 0
            socket_path.chmod(0o622)
        finally:
            await sidecar.close()

    asyncio.run(exercise())


def test_worker_timeout_cancels_call_and_never_reports_success(socket_path: Path) -> None:
    async def exercise() -> None:
        fake = FakeBrowser()
        fake.release.clear()
        sidecar = worker(fake, socket_path, operation_seconds=0.03, teardown_seconds=0.03)
        await sidecar.start()
        try:
            with pytest.raises(SyntheticIPCError, match="worker_no_go"):
                await UnixSyntheticBrowser(
                    socket_path=socket_path, timeout_seconds=1
                ).simulate_general_reservation()
            assert fake.calls == 1 and fake.cancelled
        finally:
            await sidecar.close()

    asyncio.run(exercise())


def test_failed_synthetic_journey_never_leaks_exception_text(socket_path: Path) -> None:
    async def exercise() -> None:
        fake = FakeBrowser()
        fake.outcome = None
        sidecar = worker(fake, socket_path)
        await sidecar.start()
        try:
            with pytest.raises(SyntheticIPCError, match="^worker_no_go$"):
                await UnixSyntheticBrowser(socket_path=socket_path).simulate_general_reservation()
            assert fake.calls == 1
        finally:
            await sidecar.close()

    asyncio.run(exercise())


def test_cancelled_client_releases_single_flight_without_false_success(socket_path: Path) -> None:
    async def exercise() -> None:
        fake = FakeBrowser()
        fake.release.clear()
        sidecar = worker(fake, socket_path)
        connector = UnixSyntheticBrowser(socket_path=socket_path)
        await sidecar.start()
        try:
            task = asyncio.create_task(connector.simulate_general_reservation())
            await fake.started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            # The worker's first fake page may finish, but a cancelled caller
            # can never observe it as a completed local command.
            fake.release.set()
            await asyncio.sleep(0.01)
            assert (
                await connector.simulate_general_reservation()
                is SimulationOutcome.RESERVED_IN_SIMULATOR
            )
            assert fake.calls == 2
        finally:
            await connector.close()
            await sidecar.close()

    asyncio.run(exercise())


def test_close_during_slow_socket_teardown_fences_late_success(
    socket_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        fake = FakeBrowser()
        sidecar = worker(fake, socket_path)
        connector = UnixSyntheticBrowser(socket_path=socket_path)
        reached_close = asyncio.Event()
        allow_close = asyncio.Event()
        original_open = asyncio.open_unix_connection

        class SlowWriter:
            def __init__(self, wrapped: asyncio.StreamWriter) -> None:
                self._wrapped = wrapped

            def __getattr__(self, name: str) -> object:
                return getattr(self._wrapped, name)

            async def wait_closed(self) -> None:
                reached_close.set()
                try:
                    await allow_close.wait()
                except asyncio.CancelledError:
                    await allow_close.wait()  # A hostile teardown swallows cancellation.
                await self._wrapped.wait_closed()

        async def slow_open(
            *args: object, **kwargs: object
        ) -> tuple[asyncio.StreamReader, SlowWriter]:
            reader, writer = await original_open(*args, **kwargs)  # type: ignore[arg-type]
            return reader, SlowWriter(writer)

        monkeypatch.setattr(client_module.asyncio, "open_unix_connection", slow_open)
        await sidecar.start()
        try:
            active = asyncio.create_task(connector.simulate_general_reservation())
            await asyncio.wait_for(reached_close.wait(), 1)
            assert not active.done()  # IPC success is not accepted yet.
            await connector.close()
            allow_close.set()
            with pytest.raises(asyncio.CancelledError):
                await active
            assert fake.calls == 1
        finally:
            allow_close.set()
            await sidecar.close()

    asyncio.run(exercise())


def test_worker_stop_between_fake_success_and_reply_sends_no_go(
    socket_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        fake = FakeBrowser()
        sidecar = worker(fake, socket_path)
        before_reply = asyncio.Event()
        continue_reply = asyncio.Event()
        original = sidecar._run_synthetic

        async def paused_reply() -> bytes:
            reply = await original()
            before_reply.set()
            await continue_reply.wait()
            return reply

        monkeypatch.setattr(sidecar, "_run_synthetic", paused_reply)
        await sidecar.start()
        try:
            invocation = asyncio.create_task(
                UnixSyntheticBrowser(socket_path=socket_path).simulate_general_reservation()
            )
            await asyncio.wait_for(before_reply.wait(), 1)
            assert not invocation.done() and fake.calls == 1
            closing = asyncio.create_task(sidecar.close())
            await asyncio.sleep(0)  # STOP has linearized before any reply.
            continue_reply.set()
            await closing
            with pytest.raises(SyntheticIPCError, match="worker_no_go"):
                await invocation
        finally:
            continue_reply.set()
            if sidecar._owned_socket is not None:
                await sidecar.close()

    asyncio.run(exercise())


def test_stop_during_partial_frame_never_starts_browser(
    socket_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        fake = FakeBrowser()
        sidecar = worker(fake, socket_path)
        reading = asyncio.Event()
        original_read = sidecar._read_request

        async def observed_read(reader: asyncio.StreamReader) -> None:
            reading.set()
            await original_read(reader)

        monkeypatch.setattr(sidecar, "_read_request", observed_read)
        await sidecar.start()
        reader, writer = await asyncio.open_unix_connection(str(socket_path))
        closing: asyncio.Task[None] | None = None
        try:
            await asyncio.wait_for(reading.wait(), 1)
            # A connected, authenticated peer sends no bytes until STOP.
            closing = asyncio.create_task(sidecar.close())
            await asyncio.sleep(0)
            assert sidecar._closed
            writer.write(framed(REQUEST))
            writer.write_eof()
            assert await asyncio.wait_for(read_frame(reader), 1) == NO_GO
            assert await asyncio.wait_for(reader.read(1), 1) == b""
            await asyncio.wait_for(closing, 2)
            assert fake.calls == 0 and fake.closed
        finally:
            writer.close()
            await writer.wait_closed()
            if closing is not None and not closing.done():
                await closing

    asyncio.run(exercise())


def test_success_written_before_drain_cannot_be_post_stop_commit(
    socket_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class PausedDrainWriter:
        def __init__(self) -> None:
            self.written: list[bytes] = []
            self.drain_started = asyncio.Event()
            self.release_drain = asyncio.Event()

        def write(self, data: bytes) -> None:
            self.written.append(data)

        async def drain(self) -> None:
            self.drain_started.set()
            await self.release_drain.wait()

        def close(self) -> None:
            return

        async def wait_closed(self) -> None:
            return

    async def exercise() -> None:
        fake = FakeBrowser()
        sidecar = worker(fake, socket_path)
        monkeypatch.setattr(worker_module, "verify_peer", lambda *args, **kwargs: None)
        reader = asyncio.StreamReader()
        reader.feed_data(framed(REQUEST))
        reader.feed_eof()
        writer = PausedDrainWriter()
        handler = asyncio.create_task(sidecar._handle(reader, writer))  # type: ignore[arg-type]
        try:
            await asyncio.wait_for(writer.drain_started.wait(), 1)
            # _respond writes synchronously before awaiting drain. The
            # response was committed while STOP had not yet happened.
            assert writer.written == [framed(SUCCESS)] and not sidecar._closed
            await sidecar.close()
            assert sidecar._closed and fake.closed
        finally:
            writer.release_drain.set()
            await asyncio.wait_for(handler, 1)
        assert writer.written == [framed(SUCCESS)] and fake.calls == 1

    asyncio.run(exercise())


def test_uncooperative_worker_is_poisoned_and_late_success_is_refused(socket_path: Path) -> None:
    class Stubborn(FakeBrowser):
        async def simulate_general_reservation(self) -> SimulationOutcome:
            self.calls += 1
            self.started.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                await self.release.wait()
            return SimulationOutcome.RESERVED_IN_SIMULATOR

    async def exercise() -> None:
        fake = Stubborn()
        fake.release.clear()
        sidecar = worker(fake, socket_path, operation_seconds=0.03, teardown_seconds=0.03)
        await sidecar.start()
        try:
            with pytest.raises(SyntheticIPCError, match="worker_no_go"):
                await UnixSyntheticBrowser(
                    socket_path=socket_path, timeout_seconds=1
                ).simulate_general_reservation()
            assert fake.calls == 1 and fake.cancelled
            assert sidecar._poisoned.is_set()  # No second request may create another page.
        finally:
            fake.release.set()
            await asyncio.sleep(0.01)
            await sidecar.close()
        assert fake.calls == 1

    asyncio.run(exercise())


def test_controller_rejects_synthetic_success_with_trailing_data(socket_path: Path) -> None:
    async def malicious(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        assert await read_frame(reader) == REQUEST
        assert await reader.read(1) == b""
        writer.write(framed(SUCCESS) + b"extra")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def exercise() -> None:
        server = await asyncio.start_unix_server(malicious, path=str(socket_path))
        socket_path.chmod(0o622)
        try:
            with pytest.raises(SyntheticIPCError, match="ipc_response_unverified"):
                await UnixSyntheticBrowser(socket_path=socket_path).simulate_general_reservation()
        finally:
            server.close()
            await server.wait_closed()
            socket_path.unlink()

    asyncio.run(exercise())


def test_client_deadline_is_bounded_when_worker_does_not_respond(socket_path: Path) -> None:
    async def exercise() -> None:
        fake = FakeBrowser()
        fake.release.clear()
        sidecar = worker(fake, socket_path)
        await sidecar.start()
        try:
            with pytest.raises(SyntheticIPCError, match="worker_timeout"):
                await UnixSyntheticBrowser(
                    socket_path=socket_path, timeout_seconds=0.03
                ).simulate_general_reservation()
            assert fake.calls == 1
        finally:
            fake.release.set()
            await sidecar.close()

    asyncio.run(exercise())


def test_no_egress_interface_guard_refuses_ethernet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "if_nameindex", lambda: [(1, "lo")])
    validate_no_egress_namespace()
    for interfaces in ([], [(1, "lo"), (2, "eth0")], [(2, "eth0")]):
        monkeypatch.setattr(socket, "if_nameindex", lambda values=interfaces: values)
        with pytest.raises(SyntheticIPCError, match="worker_network_unverified"):
            validate_no_egress_namespace()


def test_beta_coordinator_calls_one_ipc_command_and_retains_one_ticket(
    socket_path: Path, tmp_path: Path
) -> None:
    async def exercise() -> None:
        fake = FakeBrowser()
        sidecar = worker(fake, socket_path)
        connector = UnixSyntheticBrowser(socket_path=socket_path)
        db = Database(tmp_path / "ipc-beta.sqlite")
        outbox = SqliteNotificationOutbox(db)
        coordinator = BetaCoordinator(database=db, outbox=outbox, browser=connector)
        coordinator.prepare_storage()
        db.create_member("fixture-member", "member@example.invalid", "synthetic")
        db.create_event("fixture-event", "Fixture event")
        intent = TicketIntent("fixture-member", "fixture-event")
        await sidecar.start()
        try:
            key = str(uuid4())
            await coordinator.begin(key, intent)
            await coordinator.wait_idle()
            snapshot = coordinator.status(key, member_id=intent.member_id)
            assert snapshot is not None and snapshot.state is CommandState.COMPLETED
            assert snapshot.external_confirmation == "not_observed"
            alias = await coordinator.begin(str(uuid4()), intent)
            await coordinator.wait_idle()
            assert alias.command_id == key and alias.state is CommandState.COMPLETED
            assert fake.calls == 1
        finally:
            await coordinator.close()
            await connector.close()
            await sidecar.close()

    asyncio.run(exercise())


def test_constant_protocol_has_no_identity_url_or_secrets() -> None:
    for payload in (REQUEST, SUCCESS, BUSY, NO_GO):
        assert len(payload) <= MAX_FRAME_BYTES
        assert payload.isascii()
        assert b"http" not in payload and b"token" not in payload and b"member" not in payload
        assert len(framed(payload)) == len(payload) + 2
