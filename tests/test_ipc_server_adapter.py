"""R172 fake-stream IPC contract tests; no sockets, browser, or HTTP traffic.

Real cross-container AF_UNIX / SO_PEERCRED and socket inode acceptance remains
a separate protected Cutover gate, not something a fake stream can certify.
"""

from __future__ import annotations

import asyncio
import os
import struct
import sys
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

from boca_socios.browser import ipc_server as server_module
from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.browser.ipc_protocol import (
    FIXTURE_OBSERVED,
    NO_GO,
    PROBE_FIXTURE,
    REQUEST,
    SUCCESS,
    SyntheticIPCError,
    framed,
)


class FakePeer:
    def __init__(self, uid: int) -> None:
        self.uid = uid

    def getsockopt(self, level: int, option: int, size: int) -> bytes:
        return struct.pack("3i", 321, self.uid, self.uid)


class RecordingWriter:
    def __init__(self, uid: int) -> None:
        self.peer = FakePeer(uid)
        self.data = bytearray()
        self.closed = False

    def get_extra_info(self, name: str) -> FakePeer:
        assert name == "socket"
        return self.peer

    def write(self, data: bytes) -> None:
        self.data.extend(data)

    async def drain(self) -> None:
        return

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return


class FakeExecutor:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.calls = 0
        self.cancelled = False
        self.closed = False
        self.swallow_cancel = False

    async def simulate_general_reservation(self) -> SimulationOutcome:
        self.calls += 1
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            if not self.swallow_cancel:
                raise
        return SimulationOutcome.RESERVED_IN_SIMULATOR

    async def close(self) -> None:
        self.closed = True


class ObservingExecutor:
    """A fake observation has no simulator reservation or secret transport."""

    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.calls = 0
        self.closed = False

    async def simulate_general_reservation(self) -> object:
        self.calls += 1
        return self.outcome

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def controller_uid(monkeypatch: pytest.MonkeyPatch) -> int:
    uid = os.geteuid()
    assert uid == os.getegid()
    monkeypatch.setattr(server_module, "CONTROLLER_UID", uid)
    return uid


def request_reader(
    payload: bytes = framed(REQUEST), *, complete: bool = True
) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(payload)
    if complete:
        reader.feed_eof()
    return reader


def wire_writer(uid: int) -> tuple[RecordingWriter, asyncio.StreamWriter]:
    writer = RecordingWriter(uid)
    return writer, cast("asyncio.StreamWriter", writer)


def test_fixture_probe_is_separate_from_transactional_request(controller_uid: int) -> None:
    """A fixture-only worker never treats normal RUN as permission to launch Chromium."""

    async def exercise() -> None:
        fake = FakeExecutor()
        worker = server_module.UnixSyntheticWorker(
            fake, fixture_only=True, boundary_check=lambda: None
        )
        normal_record, normal_writer = wire_writer(controller_uid)
        await worker._handle(request_reader(), normal_writer)
        assert bytes(normal_record.data) == framed(NO_GO)
        assert fake.calls == 0

        probe_record, probe_writer = wire_writer(controller_uid)
        await worker._handle(request_reader(framed(PROBE_FIXTURE)), probe_writer)
        assert bytes(probe_record.data) == framed(FIXTURE_OBSERVED)
        assert fake.calls == 1
        await worker.close()
        assert fake.closed

    asyncio.run(exercise())


def test_default_worker_rejects_fixture_probe_without_running_executor(
    controller_uid: int,
) -> None:
    async def exercise() -> None:
        fake = FakeExecutor()
        worker = server_module.UnixSyntheticWorker(fake, boundary_check=lambda: None)
        record, writer = wire_writer(controller_uid)
        await worker._handle(request_reader(framed(PROBE_FIXTURE)), writer)
        assert bytes(record.data) == framed(NO_GO)
        assert fake.calls == 0
        await worker.close()

    asyncio.run(exercise())


def test_stopping_fixture_probe_cannot_emit_late_observed_result(controller_uid: int) -> None:
    async def exercise() -> None:
        fake = FakeExecutor()
        fake.release.clear()
        worker = server_module.UnixSyntheticWorker(
            fake, fixture_only=True, boundary_check=lambda: None
        )
        record, writer = wire_writer(controller_uid)
        active = asyncio.create_task(worker._handle(request_reader(framed(PROBE_FIXTURE)), writer))
        await asyncio.wait_for(fake.started.wait(), timeout=2)
        await asyncio.wait_for(worker.close(), timeout=2)
        await asyncio.wait_for(active, timeout=2)
        assert bytes(record.data) == framed(NO_GO)
        assert fake.cancelled and fake.closed

    asyncio.run(exercise())


def test_default_adapter_rejects_work_without_importing_navigation(controller_uid: int) -> None:
    async def exercise() -> None:
        server = server_module.UnixSyntheticWorker(boundary_check=lambda: None)
        for _ in range(2):
            record, writer = wire_writer(controller_uid)
            await server._handle(request_reader(), writer)
            assert record.closed
            assert bytes(record.data) == b"\x00\x17BOCA_SYNTHETIC_V1_NO_GO"
        await server.close()

    asyncio.run(exercise())


def test_unverified_fixture_teardown_poison_closes_admission_and_never_leaks_details(
    controller_uid: int,
) -> None:
    class FailedTeardownExecutor(FakeExecutor):
        async def simulate_general_reservation(self) -> SimulationOutcome:
            self.calls += 1
            raise SyntheticIPCError("offline_fixture_teardown_unverified")

    class TestListener:
        closed = False

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            return

    async def exercise() -> None:
        fake = FailedTeardownExecutor()
        server = server_module.UnixSyntheticWorker(fake, boundary_check=lambda: None)
        listener = TestListener()
        server._server = cast("asyncio.AbstractServer", listener)
        first_record, first_writer = wire_writer(controller_uid)
        await server._handle(request_reader(), first_writer)
        assert bytes(first_record.data) == framed(NO_GO)
        assert server._poisoned.is_set()
        assert listener.closed

        second_record, second_writer = wire_writer(controller_uid)
        await server._handle(request_reader(), second_writer)
        assert second_record.closed
        assert bytes(second_record.data) == b""
        assert fake.calls == 1
        await server.close()
        assert fake.closed

    asyncio.run(exercise())


def test_injected_offline_executor_returns_only_fixed_simulator_result(controller_uid: int) -> None:
    async def exercise() -> None:
        fake = FakeExecutor()
        server = server_module.UnixSyntheticWorker(fake, boundary_check=lambda: None)
        record, writer = wire_writer(controller_uid)
        await server._handle(request_reader(), writer)
        assert bytes(record.data) == framed(SUCCESS)
        assert fake.calls == 1
        await server.close()
        assert fake.closed

    asyncio.run(exercise())


@pytest.mark.parametrize("state", ["TOKEN_OBSERVED", "TOKEN_ABSENT", "OBSERVATION_FAILED"])
def test_observation_state_is_redacted_and_never_committed_as_simulated_reservation(
    controller_uid: int, state: str
) -> None:
    async def exercise() -> None:
        observation = getattr(server_module.ObservationStatus, state)
        fake = ObservingExecutor(observation)
        observed: list[server_module.ObservationStatus] = []
        server = server_module.UnixSyntheticWorker(
            fake, boundary_check=lambda: None, on_observation=observed.append
        )
        record, writer = wire_writer(controller_uid)
        await server._handle(request_reader(), writer)
        assert bytes(record.data) == framed(NO_GO)
        assert observed == [observation]
        assert fake.calls == 1
        await server.close()
        assert fake.closed

    asyncio.run(exercise())


def test_legacy_token_payload_cannot_be_interpreted_as_success(controller_uid: int) -> None:
    async def exercise() -> None:
        # The original owner engine labels successful observation of a page
        # "success" even with no Queue-it token. Neither case proves a booking.
        for token in (None, "fixture-do-not-publish"):
            fake = ObservingExecutor({"worker_id": 0, "status": "success", "token": token})
            server = server_module.UnixSyntheticWorker(fake, boundary_check=lambda: None)
            record, writer = wire_writer(controller_uid)
            await server._handle(request_reader(), writer)
            assert bytes(record.data) == framed(NO_GO)
            await server.close()
            assert fake.calls == 1

    asyncio.run(exercise())


def test_failed_observation_callback_leaks_no_details_into_ipc(controller_uid: int) -> None:
    async def exercise() -> None:
        observation = server_module.ObservationStatus.TOKEN_OBSERVED
        fake = ObservingExecutor(observation)

        def broken_sink(status: server_module.ObservationStatus) -> None:
            assert status is observation
            raise ValueError("fixture token and URL must never cross IPC")

        server = server_module.UnixSyntheticWorker(
            fake, boundary_check=lambda: None, on_observation=broken_sink
        )
        record, writer = wire_writer(controller_uid)
        await server._handle(request_reader(), writer)
        assert bytes(record.data) == framed(NO_GO)
        await server.close()

    asyncio.run(exercise())


def test_stop_fences_late_observation_and_never_emits_it(controller_uid: int) -> None:
    class SlowObserver(FakeExecutor):
        async def simulate_general_reservation(self) -> object:
            self.calls += 1
            self.started.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                return server_module.ObservationStatus.TOKEN_OBSERVED
            return server_module.ObservationStatus.TOKEN_OBSERVED

    async def exercise() -> None:
        fake = SlowObserver()
        fake.release.clear()
        observed: list[server_module.ObservationStatus] = []
        server = server_module.UnixSyntheticWorker(
            fake, boundary_check=lambda: None, on_observation=observed.append
        )
        record, writer = wire_writer(controller_uid)
        active = asyncio.create_task(server._handle(request_reader(), writer))
        await asyncio.wait_for(fake.started.wait(), timeout=2)
        await asyncio.wait_for(server.close(), timeout=2)
        await asyncio.wait_for(active, timeout=2)
        assert bytes(record.data) == framed(NO_GO)
        assert observed == []
        assert fake.cancelled and fake.closed

    asyncio.run(exercise())


def test_uncooperative_executor_poisoned_after_bounded_stop(controller_uid: int) -> None:
    class StubbornExecutor(FakeExecutor):
        async def simulate_general_reservation(self) -> SimulationOutcome:
            self.calls += 1
            self.started.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                await self.release.wait()  # Deliberately ignore cancellation.
            return SimulationOutcome.RESERVED_IN_SIMULATOR

    async def exercise() -> None:
        fake = StubbornExecutor()
        fake.release.clear()
        worker = server_module.UnixSyntheticWorker(
            fake, boundary_check=lambda: None, teardown_seconds=0.02
        )
        record, writer = wire_writer(controller_uid)
        active = asyncio.create_task(worker._handle(request_reader(), writer))
        await asyncio.wait_for(fake.started.wait(), 1)
        try:
            with pytest.raises(SyntheticIPCError, match="^worker_teardown_unverified$"):
                await asyncio.wait_for(worker.close(), 1)
            assert worker._poisoned.is_set()
            assert not fake.closed  # Not safe to claim a completed teardown.
        finally:
            fake.release.set()
            await asyncio.wait_for(active, 1)
        assert bytes(record.data) == framed(NO_GO)
        assert fake.calls == 1 and fake.cancelled

    asyncio.run(exercise())


def test_busy_does_not_dispatch_second_simulation(controller_uid: int) -> None:
    async def exercise() -> None:
        fake = FakeExecutor()
        fake.release.clear()
        server = server_module.UnixSyntheticWorker(fake, boundary_check=lambda: None)
        first_record, first_writer = wire_writer(controller_uid)
        first = asyncio.create_task(server._handle(request_reader(), first_writer))
        await asyncio.wait_for(fake.started.wait(), timeout=2)
        busy_record, busy_writer = wire_writer(controller_uid)
        await server._handle(request_reader(), busy_writer)
        assert bytes(busy_record.data) == b"\x00\x16BOCA_SYNTHETIC_V1_BUSY"
        assert fake.calls == 1
        fake.release.set()
        await asyncio.wait_for(first, timeout=2)
        assert bytes(first_record.data) == framed(SUCCESS)
        await server.close()

    asyncio.run(exercise())


def test_malformed_frame_returns_no_go_without_running_executor(controller_uid: int) -> None:
    async def exercise() -> None:
        fake = FakeExecutor()
        server = server_module.UnixSyntheticWorker(fake, boundary_check=lambda: None)
        record, writer = wire_writer(controller_uid)
        await server._handle(request_reader(b"\x00\x01X"), writer)
        assert bytes(record.data) == framed(NO_GO)
        assert fake.calls == 0
        await server.close()

    asyncio.run(exercise())


def test_unverified_peer_is_rejected_before_request_or_executor(controller_uid: int) -> None:
    async def exercise() -> None:
        fake = FakeExecutor()
        server = server_module.UnixSyntheticWorker(fake, boundary_check=lambda: None)
        record, writer = wire_writer(controller_uid + 1)
        await server._handle(request_reader(), writer)
        assert bytes(record.data) == b""
        assert record.closed and fake.calls == 0
        await server.close()

    asyncio.run(exercise())


def test_stop_during_partial_request_never_starts_job(controller_uid: int) -> None:
    async def exercise() -> None:
        fake = FakeExecutor()
        server = server_module.UnixSyntheticWorker(fake, boundary_check=lambda: None)
        reader = request_reader(b"\x00\x15", complete=False)
        record, writer = wire_writer(controller_uid)
        active = asyncio.create_task(server._handle(reader, writer))
        await asyncio.sleep(0)
        await server.close()
        reader.feed_data(REQUEST)
        reader.feed_eof()
        await asyncio.wait_for(active, timeout=2)
        assert bytes(record.data) == framed(NO_GO)
        assert fake.calls == 0

    asyncio.run(exercise())


def test_pre_requested_stop_never_opens_worker_listener() -> None:
    async def exercise() -> None:
        fake = FakeExecutor()
        worker = server_module.UnixSyntheticWorker(fake, boundary_check=lambda: None)
        stopping = asyncio.Event()
        stopping.set()
        starts = 0

        async def fake_start() -> None:
            nonlocal starts
            starts += 1

        worker.start = fake_start  # type: ignore[method-assign]
        await worker.serve_until(stopping)
        assert starts == 0 and fake.calls == 0 and fake.closed

    asyncio.run(exercise())


def test_demand_stop_fences_request_even_before_async_close(controller_uid: int) -> None:
    async def exercise() -> None:
        fake = FakeExecutor()
        worker = server_module.UnixSyntheticWorker(fake, boundary_check=lambda: None)
        stopping = asyncio.Event()
        started = asyncio.Event()

        async def fake_start() -> None:
            started.set()

        worker.start = fake_start  # type: ignore[method-assign]
        serving = asyncio.create_task(worker.serve_until(stopping))
        await asyncio.wait_for(started.wait(), 1)
        stopping.set()
        record, writer = wire_writer(controller_uid)
        # The STOP flag is already raised; its teardown task may not have run
        # yet, but a new completed frame must never start a simulation.
        await worker._handle(request_reader(), writer)
        await asyncio.wait_for(serving, 1)
        assert bytes(record.data) == framed(NO_GO)
        assert fake.calls == 0 and fake.closed

    asyncio.run(exercise())


@pytest.mark.parametrize("swallow_cancel", [False, True])
def test_stop_does_not_upgrade_cancelled_or_late_fake_success(
    controller_uid: int, swallow_cancel: bool
) -> None:
    async def exercise() -> None:
        fake = FakeExecutor()
        fake.release.clear()
        fake.swallow_cancel = swallow_cancel
        server = server_module.UnixSyntheticWorker(fake, boundary_check=lambda: None)
        record, writer = wire_writer(controller_uid)
        active = asyncio.create_task(server._handle(request_reader(), writer))
        await asyncio.wait_for(fake.started.wait(), timeout=2)
        await asyncio.wait_for(server.close(), timeout=2)
        await asyncio.wait_for(active, timeout=2)
        assert bytes(record.data) == framed(NO_GO)
        assert fake.cancelled and fake.closed

    asyncio.run(exercise())


def test_cold_start_reads_verified_site_url_without_exposing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = ModuleType("boca_socios.browser.site_url_runtime")
    destination = "https://ensayo.boca.internal/prueba"
    runtime_path = Path("/run/boca-site-config/boca-site-url.runtime.json")
    runtime.RUNTIME_SITE_URL_PATH = runtime_path  # type: ignore[attr-defined]

    def read_site_url(path: Path) -> str:
        assert path == runtime_path
        return destination

    runtime.read_site_url = read_site_url  # type: ignore[attr-defined]
    runtime.RuntimeSiteUrlUnavailable = RuntimeError  # type: ignore[attr-defined]
    runtime.SiteUrlInvalid = ValueError  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, runtime.__name__, runtime)
    assert server_module._read_worker_site_url() == destination


def test_absent_runtime_config_is_fail_closed_without_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = ModuleType("boca_socios.browser.site_url_runtime")
    runtime.RUNTIME_SITE_URL_PATH = Path(  # type: ignore[attr-defined]
        "/run/boca-site-config/boca-site-url.runtime.json"
    )

    def unavailable(path: Path) -> str:
        raise RuntimeError("discard this private detail")

    runtime.read_site_url = unavailable  # type: ignore[attr-defined]
    runtime.RuntimeSiteUrlUnavailable = RuntimeError  # type: ignore[attr-defined]
    runtime.SiteUrlInvalid = ValueError  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, runtime.__name__, runtime)
    with pytest.raises(SyntheticIPCError, match="^site_url_not_ready$"):
        server_module._read_worker_site_url()


def test_untyped_runtime_site_url_cannot_reach_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = ModuleType("boca_socios.browser.site_url_runtime")
    runtime.RUNTIME_SITE_URL_PATH = Path(  # type: ignore[attr-defined]
        "/run/boca-site-config/boca-site-url.runtime.json"
    )
    runtime.read_site_url = lambda path: {"SITE_URL": "https://test.invalid/"}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, runtime.__name__, runtime)
    with pytest.raises(SyntheticIPCError, match="^site_url_not_ready$"):
        server_module._read_worker_site_url()


def test_cold_start_injects_only_the_verified_url_into_explicit_offline_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        destination = "https://ensayo.boca.internal/prueba"
        monkeypatch.setattr(server_module, "_read_worker_site_url", lambda: destination)
        fake = FakeExecutor()
        received: list[str] = []

        def factory(site_url: str) -> FakeExecutor:
            received.append(site_url)
            return fake

        async def fake_serve(self: server_module.UnixSyntheticWorker, stop: asyncio.Event) -> None:
            assert self._executor is fake
            assert not stop.is_set()

        monkeypatch.setattr(server_module.UnixSyntheticWorker, "serve_until", fake_serve)
        await server_module._run_server(factory)
        assert received == [destination]
        assert fake.calls == 0

    asyncio.run(exercise())


def test_default_cold_start_is_transport_only_and_does_not_load_owner_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        monkeypatch.setattr(
            server_module, "_read_worker_site_url", lambda: "https://fixture.invalid/"
        )
        invoked = False

        async def fake_serve(self: server_module.UnixSyntheticWorker, stop: asyncio.Event) -> None:
            nonlocal invoked
            invoked = True
            assert isinstance(self._executor, server_module.OfflineNoGoExecutor)
            assert not stop.is_set()

        monkeypatch.setattr(server_module.UnixSyntheticWorker, "serve_until", fake_serve)
        await server_module._run_server()
        assert invoked
        assert "boca_socios.browser.synthetic" not in sys.modules
        assert "boca_socios.browser.ipc_worker" not in sys.modules

    asyncio.run(exercise())


def test_fixture_probe_is_enabled_only_by_explicit_offline_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        monkeypatch.setenv("BOCA_BROWSER_OBSERVE_MODE", "offline-fixture")
        monkeypatch.setattr(
            server_module, "_read_worker_site_url", lambda: "https://sandbox.invalid"
        )
        started = False

        async def fake_serve(self: server_module.UnixSyntheticWorker, stop: asyncio.Event) -> None:
            nonlocal started
            started = True
            assert self._fixture_only is True
            assert type(self._executor).__name__ == "OfflineFixtureExecutor"
            assert not stop.is_set()

        monkeypatch.setattr(server_module.UnixSyntheticWorker, "serve_until", fake_serve)
        await server_module._run_server()
        assert started
        assert "boca_socios.browser.ipc_worker" not in sys.modules

    asyncio.run(exercise())


def test_unknown_observation_mode_refuses_cold_start_without_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        monkeypatch.setenv("BOCA_BROWSER_OBSERVE_MODE", "site-observe")
        monkeypatch.setattr(
            server_module, "_read_worker_site_url", lambda: "https://sandbox.invalid"
        )
        started = False

        async def fake_serve(self: server_module.UnixSyntheticWorker, stop: asyncio.Event) -> None:
            nonlocal started
            started = True

        monkeypatch.setattr(server_module.UnixSyntheticWorker, "serve_until", fake_serve)
        with pytest.raises(SyntheticIPCError, match="^worker_observe_mode_unverified$"):
            await server_module._run_server()
        assert not started

    asyncio.run(exercise())
