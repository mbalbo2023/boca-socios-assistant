"""V2 uses the existing authenticated socket with per-session independence."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import os
from dataclasses import replace

import pytest

from boca_socios.browser import ipc_client, ipc_server
from boca_socios.browser import ipc_protocol as wire
from boca_socios.browser.boca_auth_protocol import BocaAuthRequest
from test_engine_sessions import identity, modules, registry
from test_ipc_server_adapter import request_reader, wire_writer
from test_r177_fixture_probe_client import MemoryWriter


def client_module():
    assert importlib.util.find_spec("boca_socios.browser.engine_client") is not None, (
        "independent authenticated engine client is missing"
    )
    return importlib.import_module("boca_socios.browser.engine_client")


def encoded_request(request):
    command = getattr(wire, "ENGINE_SESSION", None)
    assert command is not None, "scoped V2 command missing on existing listener"
    payload = request.to_payload()
    return wire.framed(command) + wire.framed_private_auth(payload, maximum=33792)


def decoded_reply(protocol, record):
    data = bytes(record.data)
    assert int.from_bytes(data[:4], "big") == len(data[4:])
    return protocol.EngineReply.from_payload(data[4:])


def test_scoped_worker_bypasses_only_legacy_global_gate_and_echoes_full_identity(monkeypatch):
    async def exercise():
        protocol, sessions = modules()
        monkeypatch.setattr(ipc_server, "CONTROLLER_UID", os.geteuid())
        observers = {}
        worker = ipc_server.UnixSyntheticWorker(
            engine_sessions=registry(sessions, observers), boundary_check=lambda: None
        )
        ident = identity(protocol)
        record, writer = wire_writer(os.geteuid())
        await worker._handle(
            request_reader(encoded_request(protocol.EngineRequest(ident, "observe"))), writer
        )
        reply = decoded_reply(protocol, record)
        assert reply.status == "OK" and reply.identity == ident
        assert wire.SUCCESS not in record.data
        await worker.close()

    asyncio.run(exercise())


def test_worker_accepts_stop_while_other_engine_request_is_blocked(monkeypatch):
    async def exercise():
        protocol, sessions = modules()
        monkeypatch.setattr(ipc_server, "CONTROLLER_UID", os.geteuid())
        observers = {}
        reg = registry(sessions, observers)
        worker = ipc_server.UnixSyntheticWorker(engine_sessions=reg, boundary_check=lambda: None)
        first = identity(protocol)
        second = identity(protocol, engine="browsers_members")
        await reg.execute(protocol.EngineRequest(first, "observe"))
        await reg.execute(protocol.EngineRequest(second, "observe"))
        obs = observers[first.session_id]
        obs.release.clear()
        obs.entered.clear()
        record, writer = wire_writer(os.geteuid())
        blocked = asyncio.create_task(
            worker._handle(
                request_reader(encoded_request(protocol.EngineRequest(first, "observe"))), writer
            )
        )
        await obs.entered.wait()
        close_record, close_writer = wire_writer(os.geteuid())
        await asyncio.wait_for(
            worker._handle(
                request_reader(
                    encoded_request(
                        protocol.EngineRequest(second, "close", close_scope="activation")
                    )
                ),
                close_writer,
            ),
            0.2,
        )
        assert decoded_reply(protocol, close_record).status == "CLOSED"
        assert not blocked.done() and not obs.closed
        obs.release.set()
        await blocked
        await worker.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("legacy_first", [True, False])
def test_legacy_and_v2_observers_cannot_coexist_outside_global_cap(monkeypatch, legacy_first):
    from test_engine_sessions import Observer

    async def exercise():
        protocol, sessions = modules()
        monkeypatch.setattr(ipc_server, "CONTROLLER_UID", os.geteuid())
        observers = {}
        legacy = Observer()
        worker = ipc_server.UnixSyntheticWorker(
            queue_observer=legacy,
            engine_sessions=registry(sessions, observers),
            boundary_check=lambda: None,
        )
        ident = identity(protocol)
        legacy_record, legacy_writer = wire_writer(os.geteuid())
        scoped_record, scoped_writer = wire_writer(os.geteuid())

        async def old():
            await worker._handle(request_reader(wire.framed(wire.OBSERVE_QUEUE)), legacy_writer)

        async def new():
            await worker._handle(
                request_reader(encoded_request(protocol.EngineRequest(ident, "observe"))),
                scoped_writer,
            )

        await (old() if legacy_first else new())
        await (new() if legacy_first else old())
        if legacy_first:
            assert decoded_reply(protocol, scoped_record).status == "BUSY" and observers == {}
        else:
            assert bytes(legacy_record.data) == wire.framed(wire.BUSY)
            assert not legacy.entered.is_set()
        await worker.close()

    asyncio.run(exercise())


def transport(monkeypatch, responder):
    module = client_module()
    monkeypatch.setattr(ipc_client, "_check_controller_identity", lambda: None)
    monkeypatch.setattr(ipc_client, "socket_identity", lambda *_a, **_kw: (1, 2))
    monkeypatch.setattr(ipc_client, "verify_peer", lambda *_a, **_kw: None)
    writers = []

    class Writer(MemoryWriter):
        def write_eof(self):
            self.eof = True
            payload = self.writes[1][4:]
            result = responder(payload)
            if result is not None:
                self.reader.feed_data(wire.framed_private_auth(result, maximum=98304))
                self.reader.feed_eof()

    async def connect(**_kwargs):
        reader = asyncio.StreamReader()
        writer = Writer(reader, lambda _: None)
        writers.append(writer)
        return reader, writer

    monkeypatch.setattr(ipc_client.asyncio, "open_unix_connection", connect)
    return module, writers


def test_client_close_uses_separate_connection_and_fences_pending_result(monkeypatch):
    async def exercise():
        protocol, _ = modules()
        ident = identity(protocol)

        def responder(payload):
            request = protocol.EngineRequest.from_payload(payload)
            if request.command == "close":
                return protocol.EngineReply(
                    ident, "close", "CLOSED", close_scope=request.close_scope
                ).to_payload()
            return None

        module, writers = transport(monkeypatch, responder)
        client = module.UnixEngineSession(ident)
        running = asyncio.create_task(client.observe_queue())
        while not writers:
            await asyncio.sleep(0)
        await asyncio.wait_for(client.close_activation(), 0.2)
        with pytest.raises((wire.SyntheticIPCError, asyncio.CancelledError)):
            await running
        assert len(writers) == 2 and all(writer.closed for writer in writers)
        with pytest.raises(wire.SyntheticIPCError, match="client_closed"):
            await client.observe_queue()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "mismatch", ["engine", "activation_id", "generation", "session_id", "browser", "nonce"]
)
def test_client_rejects_full_correlation_mismatch(monkeypatch, mismatch):
    from uuid import uuid4

    from boca_socios.browser.boca_auth_protocol import BocaAuthReply
    from test_automatic_observer_ipc import observation

    async def exercise():
        protocol, _ = modules()
        ident = identity(protocol, engine="browsers_members")
        changed = {
            "engine": "queues_tokens",
            "activation_id": str(uuid4()),
            "generation": 2,
            "session_id": str(uuid4()),
            "browser": "webkit",
        }
        altered = replace(ident, **{mismatch: changed[mismatch]}) if mismatch != "nonce" else ident
        if mismatch == "nonce":
            result = BocaAuthReply(ident.activation_id, "b" * 64, b"fixture")
            reply = protocol.EngineReply(altered, "login", "OK", result)
        else:
            reply = protocol.EngineReply(altered, "observe", "OK", observation())
        module, writers = transport(monkeypatch, lambda _: reply.to_payload())
        client = module.UnixEngineSession(ident)
        with pytest.raises(wire.SyntheticIPCError, match="correlation_unverified"):
            if mismatch == "nonce":
                await client.login_boca(
                    BocaAuthRequest(
                        ident.activation_id, "a" * 64, "fixture@example.invalid", "fixture"
                    )
                )
            else:
                await client.observe_queue()
        assert writers[0].closed

    asyncio.run(exercise())


@pytest.mark.parametrize("guard", ["peer", "inode"])
def test_client_does_not_write_private_request_before_peer_and_inode_checks(monkeypatch, guard):
    async def exercise():
        protocol, _ = modules()
        module, writers = transport(monkeypatch, lambda _: None)
        if guard == "peer":

            def fail(*_a, **_kw):
                raise wire.SyntheticIPCError("ipc_peer_unverified")

            monkeypatch.setattr(ipc_client, "verify_peer", fail)
        else:
            values = iter([(1, 2), (1, 3)])
            monkeypatch.setattr(ipc_client, "socket_identity", lambda *_a, **_kw: next(values))
        client = module.UnixEngineSession(identity(protocol))
        with pytest.raises(wire.SyntheticIPCError):
            await client.observe_queue()
        assert len(writers) == 1 and writers[0].writes == [] and writers[0].closed

    asyncio.run(exercise())


def test_login_on_another_thread_loop_is_cancelled_by_owner_loop_stop(monkeypatch):
    from threading import Event

    async def exercise():
        protocol, _ = modules()
        ident = identity(protocol, engine="browsers_members")
        login_entered = Event()

        def responder(payload):
            request = protocol.EngineRequest.from_payload(payload)
            if request.command == "close":
                return protocol.EngineReply(
                    ident, "close", "CLOSED", close_scope=request.close_scope
                ).to_payload()
            login_entered.set()
            return None

        module, writers = transport(monkeypatch, responder)
        client = module.UnixEngineSession(ident)

        def background():
            try:
                asyncio.run(
                    client.login_boca(
                        BocaAuthRequest(
                            ident.activation_id, "a" * 64, "fixture@example.invalid", "fixture"
                        )
                    )
                )
            except (asyncio.CancelledError, wire.SyntheticIPCError):
                return "discarded"
            return "unexpected success"

        running = asyncio.create_task(asyncio.to_thread(background))
        async with asyncio.timeout(1):
            while not login_entered.is_set():
                await asyncio.sleep(0.001)
        await asyncio.wait_for(client.close_activation(), 1)
        assert await running == "discarded"
        assert len(writers) == 2 and all(writer.closed for writer in writers)

    asyncio.run(exercise())


def test_scoped_request_requires_eof_and_never_dispatches_an_appended_command(monkeypatch):
    async def exercise():
        protocol, sessions = modules()
        monkeypatch.setattr(ipc_server, "CONTROLLER_UID", os.geteuid())
        observers = {}
        worker = ipc_server.UnixSyntheticWorker(
            engine_sessions=registry(sessions, observers), boundary_check=lambda: None
        )
        ident = identity(protocol)
        record, writer = wire_writer(os.geteuid())
        await worker._handle(
            request_reader(
                encoded_request(protocol.EngineRequest(ident, "observe"))
                + wire.framed(wire.REQUEST)
            ),
            writer,
        )
        assert observers == {} and bytes(record.data).endswith(wire.NO_GO)
        await worker.close()

    asyncio.run(exercise())


def test_scoped_private_reply_supports_full_existing_provider_payload(monkeypatch):
    from boca_socios.browser.boca_auth_protocol import BocaAuthReply

    async def exercise():
        protocol, _ = modules()
        ident = identity(protocol, engine="browsers_members")
        request = BocaAuthRequest(
            ident.activation_id, "a" * 64, "fixture@example.invalid", "fixture"
        )
        reply = protocol.EngineReply(
            ident, "login", "OK", BocaAuthReply(ident.activation_id, request.nonce, b"x" * 65536)
        )
        module, writers = transport(monkeypatch, lambda _: reply.to_payload())
        client = module.UnixEngineSession(ident)
        result = await client.login_boca(request)
        assert result.provider_payload == b"x" * 65536 and writers[0].closed

    asyncio.run(exercise())


def test_scoped_client_rejects_trailing_response_bytes(monkeypatch):
    from test_automatic_observer_ipc import observation

    async def exercise():
        protocol, _ = modules()
        ident = identity(protocol)
        reply = protocol.EngineReply(ident, "observe", "OK", observation()).to_payload()
        module, writers = transport(monkeypatch, lambda _: None)
        original = ipc_client.asyncio.open_unix_connection

        async def connect(**kwargs):
            reader, writer = await original(**kwargs)

            def eof():
                reader.feed_data(wire.framed_private_auth(reply, maximum=98304) + b"x")
                reader.feed_eof()

            writer.write_eof = eof
            return reader, writer

        monkeypatch.setattr(ipc_client.asyncio, "open_unix_connection", connect)
        client = module.UnixEngineSession(ident)
        with pytest.raises(wire.SyntheticIPCError, match="ipc_response_unverified"):
            await client.observe_queue()
        assert writers[0].closed

    asyncio.run(exercise())


def test_worker_shutdown_fences_scoped_requests_before_waiting_for_live_connections(monkeypatch):
    from asyncio.base_events import Server

    async def exercise():
        protocol, sessions = modules()
        monkeypatch.setattr(ipc_server, "CONTROLLER_UID", os.geteuid())
        observers = {}
        reg = registry(sessions, observers, teardown_seconds=0.02)
        ident = identity(protocol)
        await reg.execute(protocol.EngineRequest(ident, "observe"))
        observer = observers[ident.session_id]
        observer.entered.clear()
        observer.release.clear()
        worker = ipc_server.UnixSyntheticWorker(
            engine_sessions=reg, boundary_check=lambda: None, teardown_seconds=0.1
        )
        # Use real 3.12 Server connection bookkeeping without requiring AF_UNIX
        # access. wait_closed must wait for this attached peer to detach.
        server = Server(asyncio.get_running_loop(), [], None, None, None, None)
        server._attach()
        worker._server = server
        record, writer = wire_writer(os.geteuid())
        original_close = writer.close
        detached = False

        def detach():
            nonlocal detached
            original_close()
            if not detached:
                detached = True
                server._detach()

        writer.close = detach
        handling = asyncio.create_task(
            worker._handle(
                request_reader(encoded_request(protocol.EngineRequest(ident, "observe"))), writer
            )
        )
        await observer.entered.wait()
        await worker.close()
        await handling
        assert observer.closed and reg.live_contexts == 0 and detached
        assert decoded_reply(protocol, record).status == "NO_GO"

    asyncio.run(exercise())


@pytest.mark.parametrize("retry_method", ["close", "close_activation"])
def test_failed_close_ack_can_be_retried_without_reopening_or_duplicate_concurrent_exchange(
    monkeypatch, retry_method
):
    async def exercise():
        protocol, _ = modules()
        ident = identity(protocol)
        calls = []

        def responder(payload):
            request = protocol.EngineRequest.from_payload(payload)
            calls.append(request)
            return protocol.EngineReply(
                ident,
                "close",
                "NO_GO" if len(calls) == 1 else "CLOSED",
                close_scope="activation",
            ).to_payload()

        module, writers = transport(monkeypatch, responder)
        client = module.UnixEngineSession(ident)
        with pytest.raises(wire.SyntheticIPCError, match="worker_no_go"):
            await client.close_activation()
        with pytest.raises(wire.SyntheticIPCError, match="client_closed"):
            await client.observe_queue()
        retry = getattr(client, retry_method)
        await asyncio.gather(retry(), retry())
        assert len(writers) == len(calls) == 2
        assert all(
            request.identity == ident
            and request.command == "close"
            and request.close_scope == "activation"
            for request in calls
        )
        await client.close_activation()
        assert len(writers) == 2, "successful close remains cached"

    asyncio.run(exercise())
