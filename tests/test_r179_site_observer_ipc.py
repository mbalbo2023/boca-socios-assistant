"""R179: site observation has no transactional IPC path or live network."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from boca_socios.browser import ipc_protocol, ipc_server
from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.browser.ipc_client import UnixSyntheticBrowser
from boca_socios.browser.ipc_protocol import SyntheticIPCError, framed
from test_ipc_server_adapter import request_reader, wire_writer
from test_r177_fixture_probe_client import in_memory_transport


class FakeSiteObserver:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0
        self.closed = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.cancelled = False

    async def observe_site(self) -> object:
        self.calls += 1
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            return self.result  # Even a swallowed cancellation must NOT succeed.
        return self.result

    async def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("category", "frame"),
    [("HTTP_OK", "SITE_HTTP_OK"), ("HTTP_NON_OK", "SITE_HTTP_NON_OK")],
)
def test_site_observer_ipc_only_answers_explicit_probe(
    monkeypatch: pytest.MonkeyPatch, category: str, frame: str
) -> None:
    async def exercise() -> None:
        uid = os.geteuid()
        monkeypatch.setattr(ipc_server, "CONTROLLER_UID", uid)
        result = getattr(ipc_server.SiteObservationStatus, category)
        observer = FakeSiteObserver(result)
        worker = ipc_server.UnixSyntheticWorker(site_observer=observer, boundary_check=lambda: None)

        for request in (ipc_protocol.REQUEST, ipc_protocol.PROBE_FIXTURE):
            record, writer = wire_writer(uid)
            await worker._handle(request_reader(framed(request)), writer)
            assert bytes(record.data) == framed(ipc_protocol.NO_GO)
        assert observer.calls == 0

        record, writer = wire_writer(uid)
        await worker._handle(request_reader(framed(ipc_protocol.PROBE_SITE)), writer)
        assert bytes(record.data) == framed(getattr(ipc_protocol, frame))
        assert observer.calls == 1
        await worker.close()
        assert observer.closed

    asyncio.run(exercise())


def test_default_worker_rejects_site_probe_without_navigating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        uid = os.geteuid()
        monkeypatch.setattr(ipc_server, "CONTROLLER_UID", uid)
        worker = ipc_server.UnixSyntheticWorker(boundary_check=lambda: None)
        record, writer = wire_writer(uid)
        await worker._handle(request_reader(framed(ipc_protocol.PROBE_SITE)), writer)
        assert bytes(record.data) == framed(ipc_protocol.NO_GO)
        await worker.close()

    asyncio.run(exercise())


def test_injected_transactional_engine_never_runs_for_site_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OldSimulator:
        calls = 0

        async def simulate_general_reservation(self) -> SimulationOutcome:
            self.calls += 1
            return SimulationOutcome.RESERVED_IN_SIMULATOR

        async def close(self) -> None:
            return

    async def exercise() -> None:
        uid = os.geteuid()
        monkeypatch.setattr(ipc_server, "CONTROLLER_UID", uid)
        simulator = OldSimulator()
        worker = ipc_server.UnixSyntheticWorker(simulator, boundary_check=lambda: None)
        record, writer = wire_writer(uid)
        await worker._handle(request_reader(framed(ipc_protocol.PROBE_SITE)), writer)
        assert bytes(record.data) == framed(ipc_protocol.NO_GO)
        assert simulator.calls == 0
        await worker.close()
        with pytest.raises(ValueError, match="observer modes must be exclusive"):
            ipc_server.UnixSyntheticWorker(
                simulator, site_observer=FakeSiteObserver(ipc_server.SiteObservationStatus.HTTP_OK)
            )

    asyncio.run(exercise())


def test_stop_cannot_turn_late_site_reply_into_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        uid = os.geteuid()
        monkeypatch.setattr(ipc_server, "CONTROLLER_UID", uid)
        observer = FakeSiteObserver(ipc_server.SiteObservationStatus.HTTP_OK)
        observer.release.clear()
        worker = ipc_server.UnixSyntheticWorker(site_observer=observer, boundary_check=lambda: None)
        record, writer = wire_writer(uid)
        active = asyncio.create_task(
            worker._handle(request_reader(framed(ipc_protocol.PROBE_SITE)), writer)
        )
        await asyncio.wait_for(observer.entered.wait(), 1)
        await asyncio.wait_for(worker.close(), 2)
        await asyncio.wait_for(active, 2)
        assert bytes(record.data) == framed(ipc_protocol.NO_GO)
        assert observer.cancelled and observer.closed

    asyncio.run(exercise())


def test_unverified_site_teardown_poisoned_without_positive_ipc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenObserver(FakeSiteObserver):
        async def observe_site(self) -> object:
            self.calls += 1
            raise SyntheticIPCError("site_observer_teardown_unverified")

    class FakeListener:
        closed = False

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            return

    async def exercise() -> None:
        uid = os.geteuid()
        monkeypatch.setattr(ipc_server, "CONTROLLER_UID", uid)
        observer = BrokenObserver(ipc_server.SiteObservationStatus.HTTP_OK)
        worker = ipc_server.UnixSyntheticWorker(site_observer=observer, boundary_check=lambda: None)
        listener = FakeListener()
        worker._server = listener
        first, writer = wire_writer(uid)
        await worker._handle(request_reader(framed(ipc_protocol.PROBE_SITE)), writer)
        assert bytes(first.data) == framed(ipc_protocol.NO_GO)
        assert worker._poisoned.is_set() and listener.closed
        second, another_writer = wire_writer(uid)
        await worker._handle(request_reader(framed(ipc_protocol.PROBE_SITE)), another_writer)
        assert bytes(second.data) == b""
        assert observer.calls == 1
        await worker.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("frame", "outcome"),
    [("SITE_HTTP_OK", "site_http_ok"), ("SITE_HTTP_NON_OK", "site_http_non_ok")],
)
def test_client_site_probe_returns_only_categorical_status(
    monkeypatch: pytest.MonkeyPatch, frame: str, outcome: str
) -> None:
    async def exercise() -> None:
        response = getattr(ipc_protocol, frame)
        seen = in_memory_transport(monkeypatch, lambda _request: response)
        client = UnixSyntheticBrowser(socket_path=Path("/ignored/synthetic.sock"))
        try:
            assert await client.probe_site_readonly() == outcome
            with pytest.raises(SyntheticIPCError, match="^ipc_response_unverified$"):
                await client.simulate_general_reservation()
        finally:
            await client.close()
        assert [writer.writes for writer in seen] == [
            [framed(ipc_protocol.PROBE_SITE)],
            [framed(ipc_protocol.REQUEST)],
        ]

    asyncio.run(exercise())


def test_site_mode_requires_explicit_opt_in_and_rejects_injected_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from boca_socios.browser import site_observer

    class FakeWorker:
        def __init__(self, executor: object, *, site_observer: object = None, **_: object) -> None:
            assert executor is None
            assert isinstance(site_observer, site_observer_module.SiteReadOnlyExecutor)

        async def serve_until(self, _stop: asyncio.Event) -> None:
            return

    site_observer_module = site_observer
    monkeypatch.setattr(
        ipc_server, "_read_worker_site_url", lambda: "https://sandbox.example.test/"
    )
    monkeypatch.setattr(ipc_server, "UnixSyntheticWorker", FakeWorker)
    monkeypatch.setenv("BOCA_BROWSER_OBSERVE_MODE", "site-readonly")
    asyncio.run(ipc_server._run_server())
    with pytest.raises(SyntheticIPCError, match="worker_observe_mode_unverified"):
        asyncio.run(ipc_server._run_server(executor_factory=lambda _url: object()))


def test_browser_probe_frame_never_accepts_raw_url_or_tokens() -> None:
    for value in (
        b"BOCA_SYNTHETIC_V1_PROBE_SITE https://sandbox.example.test/",
        b"SITE_HTTP_OK_TOKEN=opaque",
    ):
        with pytest.raises(SyntheticIPCError, match="ipc_frame_unverified"):
            framed(value)
