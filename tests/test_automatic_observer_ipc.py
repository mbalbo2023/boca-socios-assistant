"""Authenticated automatic observation frames; in-memory streams only."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from boca_socios.browser import ipc_client, ipc_protocol, ipc_server
from boca_socios.browser.ipc_client import UnixSyntheticBrowser
from boca_socios.browser.ipc_protocol import SyntheticIPCError, framed
from boca_socios.browser.queue_page_observation import (
    QueuePageObservation,
    parse_queue_page_observation,
)
from test_ipc_server_adapter import request_reader, wire_writer
from test_r177_fixture_probe_client import MemoryWriter

TARGET = "https://received.example.invalid/event?queueittoken=private-observed-value"


def observation():
    return parse_queue_page_observation(
        final_url=TARGET,
        queue_model={"eventId": "real-observed-event"},
        markers=frozenset(),
        observed_at=datetime(2026, 11, 14, 18, 0, tzinfo=UTC),
    )


def request():
    value = getattr(ipc_protocol, "OBSERVE_QUEUE", None)
    assert value is not None, "bounded automatic observation IPC is missing"
    return value


class Observer:
    def __init__(self):
        self.calls = 0
        self.closed = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    async def observe_queue(self):
        self.calls += 1
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            return observation()  # A swallowed STOP must still never publish its token.
        return observation()

    async def close(self):
        self.closed = True


def transport(monkeypatch, raw_reply):
    monkeypatch.setattr(ipc_client, "_check_controller_identity", lambda: None)
    monkeypatch.setattr(ipc_client, "socket_identity", lambda *_a, **_kw: (1, 2))
    monkeypatch.setattr(ipc_client, "verify_peer", lambda *_a, **_kw: None)
    writers = []

    class Writer(MemoryWriter):
        def write_eof(self):
            self.eof = True
            if raw_reply is not None:
                self.reader.feed_data(raw_reply)
                self.reader.feed_eof()

    async def connect(**_kwargs):
        reader = asyncio.StreamReader()
        writer = Writer(reader, lambda _: None)
        writers.append(writer)
        return reader, writer

    monkeypatch.setattr(ipc_client.asyncio, "open_unix_connection", connect)
    return writers


def test_queue_worker_returns_private_typed_payload_only_for_its_explicit_request(monkeypatch):
    async def exercise():
        uid = os.geteuid()
        monkeypatch.setattr(ipc_server, "CONTROLLER_UID", uid)
        observer = Observer()
        worker = ipc_server.UnixSyntheticWorker(
            queue_observer=observer, boundary_check=lambda: None
        )
        for value in (ipc_protocol.REQUEST, ipc_protocol.PROBE_FIXTURE, ipc_protocol.PROBE_SITE):
            record, writer = wire_writer(uid)
            await worker._handle(request_reader(framed(value)), writer)
            assert bytes(record.data) == framed(ipc_protocol.NO_GO)
        assert observer.calls == 0
        record, writer = wire_writer(uid)
        await worker._handle(request_reader(framed(request())), writer)
        raw = bytes(record.data)
        assert int.from_bytes(raw[:2], "big") == len(raw[2:])
        assert QueuePageObservation.from_payload(raw[2:]) == observation()
        assert ipc_protocol.SUCCESS not in raw
        assert observer.calls == 1
        await worker.close()
        assert observer.closed

    asyncio.run(exercise())


def test_queue_client_validates_observation_schema_and_never_promotes_it_to_reservation(
    monkeypatch,
):
    async def exercise():
        payload = observation().to_payload()
        writers = transport(monkeypatch, len(payload).to_bytes(2, "big") + payload)
        client = UnixSyntheticBrowser(socket_path=Path("/unused/synthetic.sock"))
        assert await client.observe_queue() == observation()
        assert writers[0].writes == [framed(request())]
        with pytest.raises(SyntheticIPCError, match="ipc_frame_unverified"):
            await client.simulate_general_reservation()
        assert all(writer.closed for writer in writers)
        await client.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "payload",
    [b"{}", b'{"target_url":"private-observed-value"}', ipc_protocol.SUCCESS, b"x" * 32769],
)
def test_bad_or_oversized_private_reply_never_reaches_monitor(monkeypatch, payload):
    async def exercise():
        transport(monkeypatch, len(payload).to_bytes(2, "big") + payload)
        client = UnixSyntheticBrowser()
        with pytest.raises(SyntheticIPCError) as error:
            await client.observe_queue()
        assert "private-observed-value" not in str(error.value)
        await client.close()

    asyncio.run(exercise())


def test_queue_worker_verifies_peer_before_reading_or_dispatching(monkeypatch):
    async def exercise():
        uid = os.geteuid()
        monkeypatch.setattr(ipc_server, "CONTROLLER_UID", uid)
        observer = Observer()
        worker = ipc_server.UnixSyntheticWorker(
            queue_observer=observer, boundary_check=lambda: None
        )
        record, writer = wire_writer(uid + 1)
        await worker._handle(request_reader(framed(request())), writer)
        assert bytes(record.data) == b"" and observer.calls == 0
        await worker.close()

    asyncio.run(exercise())


def test_stopping_queue_operation_discards_late_private_token(monkeypatch):
    async def exercise():
        uid = os.geteuid()
        monkeypatch.setattr(ipc_server, "CONTROLLER_UID", uid)
        observer = Observer()
        observer.release.clear()
        worker = ipc_server.UnixSyntheticWorker(
            queue_observer=observer, boundary_check=lambda: None
        )
        record, writer = wire_writer(uid)
        running = asyncio.create_task(worker._handle(request_reader(framed(request())), writer))
        await asyncio.wait_for(observer.entered.wait(), 1)
        await worker.close()
        await asyncio.wait_for(running, 1)
        assert bytes(record.data) == framed(ipc_protocol.NO_GO)
        assert observer.closed

    asyncio.run(exercise())


def test_default_worker_cannot_use_site_configuration_as_automatic_permission(monkeypatch):
    async def exercise():
        uid = os.geteuid()
        monkeypatch.setattr(ipc_server, "CONTROLLER_UID", uid)
        worker = ipc_server.UnixSyntheticWorker(boundary_check=lambda: None)
        record, writer = wire_writer(uid)
        await worker._handle(request_reader(framed(request())), writer)
        assert bytes(record.data) == framed(ipc_protocol.NO_GO)
        await worker.close()

    asyncio.run(exercise())


def test_automatic_worker_activation_is_explicit_and_inert_until_owner_command(monkeypatch):
    from boca_socios.browser import automatic_observer

    configured = []

    class Factory:
        def __init__(self, site_url):
            configured.append(site_url)

    async def serve(self, _stopping):
        assert isinstance(self._queue_observer, Factory)
        assert self._site_observer is None and self._fixture_only is False

    monkeypatch.setattr(
        ipc_server, "_read_worker_site_url", lambda: "https://owner.example.invalid/"
    )
    monkeypatch.setattr(automatic_observer, "AutomaticQueueObserver", Factory)
    monkeypatch.setattr(ipc_server.UnixSyntheticWorker, "serve_until", serve)
    monkeypatch.setenv("BOCA_BROWSER_EXECUTOR", "automatic-observation")
    monkeypatch.setenv("BOCA_RUNTIME_MODE", "simulation")
    monkeypatch.setenv("BOCA_BROWSER_OBSERVE_MODE", "off")
    asyncio.run(ipc_server._run_server())
    assert configured == ["https://owner.example.invalid/"]


def test_received_page_reaches_private_global_monitor_through_both_ipc_adapters(monkeypatch):
    from boca_socios.queue.private_pass_monitor import PrivateAutomaticObservationMonitor
    from test_automatic_observer import NOW, observer_for, snapshot

    async def exercise():
        uid = os.geteuid()
        monkeypatch.setattr(ipc_server, "CONTROLLER_UID", uid)
        observer, page, context, browser, _, _ = observer_for(
            [
                snapshot(model={"eventId": "received-event", "ticket": {"progress": 0}}),
                snapshot(model={"eventId": "received-event", "targetUrl": TARGET}),
            ]
        )
        worker = ipc_server.UnixSyntheticWorker(
            queue_observer=observer, boundary_check=lambda: None
        )
        client = UnixSyntheticBrowser()
        monitor = PrivateAutomaticObservationMonitor(configured=True, now=lambda: NOW)
        for expected in ("QUEUE_ACTIVE", "TARGET_OBSERVED"):
            monitor.mark_checking()
            record, writer = wire_writer(uid)
            await worker._handle(request_reader(framed(request())), writer)
            transport(monkeypatch, bytes(record.data))
            received = await client.observe_queue()
            monitor.observe_global(received)
            assert monitor.snapshot()["latest"]["outcome"] == expected
        assert monitor.owner_global_details(owner_authenticated=True).target_url == TARGET
        assert TARGET not in repr(monitor.snapshot())
        assert len(page.navigations) == context.pages == 1
        assert context.closed and browser.closed
        await client.close()
        await worker.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("runtime", "observe"),
    [("live", "off"), ("", "off"), ("simulation", "site-readonly")],
)
def test_automatic_mode_rejects_ambiguous_or_live_activation(monkeypatch, runtime, observe):
    monkeypatch.setattr(
        ipc_server, "_read_worker_site_url", lambda: "https://owner.example.invalid/"
    )
    monkeypatch.setenv("BOCA_BROWSER_EXECUTOR", "automatic-observation")
    monkeypatch.setenv("BOCA_RUNTIME_MODE", runtime)
    monkeypatch.setenv("BOCA_BROWSER_OBSERVE_MODE", observe)
    with pytest.raises(SyntheticIPCError, match="worker_executor_mode_unverified"):
        asyncio.run(ipc_server._run_server())
