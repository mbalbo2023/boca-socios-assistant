"""Authentication-only framing and peer checks, without network sockets."""

from __future__ import annotations

import asyncio
import os

import pytest

from boca_socios.browser import ipc_protocol as wire
from boca_socios.browser import ipc_server
from boca_socios.browser.boca_auth_protocol import BocaAuthReadiness, BocaAuthReply, BocaAuthRequest
from boca_socios.browser.ipc_client import UnixSyntheticBrowser
from test_automatic_observer_ipc import observation, transport
from test_boca_auth_continuation import OPERATION
from test_ipc_server_adapter import request_reader, wire_writer


class AuthObserver:
    def __init__(self):
        self.calls = []

    async def prepare_boca_login(self, operation):
        self.calls.append(operation)
        return BocaAuthReadiness(operation, observation(), "a" * 64, 15)

    async def login_boca(self, request):
        self.calls.append(request)
        return BocaAuthReply(request.operation_id, request.nonce, b"x" * 65536)

    async def close(self):
        pass


@pytest.mark.parametrize("login", [False, True])
def test_both_private_adapters_preserve_full_payload_and_correlation(monkeypatch, login):
    async def exercise():
        monkeypatch.setattr(ipc_server, "CONTROLLER_UID", os.geteuid())
        observer = AuthObserver()
        worker = ipc_server.UnixSyntheticWorker(
            queue_observer=observer, boundary_check=lambda: None
        )
        request = BocaAuthRequest(
            OPERATION, "a" * 64, "fixture@example.invalid", "private-password"
        )
        payload = (
            request.to_payload() if login else ('{"operation_id":"' + OPERATION + '"}').encode()
        )
        command = wire.LOGIN_BOCA if login else wire.PREPARE_BOCA_LOGIN
        record, writer = wire_writer(os.geteuid())
        await worker._handle(
            request_reader(wire.framed(command) + wire.framed_private_auth(payload)), writer
        )
        writers = transport(monkeypatch, bytes(record.data))
        client = UnixSyntheticBrowser()
        result = (
            await client.login_boca(request)
            if login
            else await client.prepare_boca_login(OPERATION)
        )
        assert result.operation_id == OPERATION
        if login:
            assert len(result.provider_payload) == 65536
        else:
            assert result.ready
        assert writers[0].writes == [wire.framed(command), wire.framed_private_auth(payload)]
        await client.close()
        await worker.close()

    asyncio.run(exercise())


def test_unauthorized_peer_cannot_even_read_private_frame(monkeypatch):
    async def exercise():
        monkeypatch.setattr(ipc_server, "CONTROLLER_UID", os.geteuid())
        observer = AuthObserver()
        worker = ipc_server.UnixSyntheticWorker(
            queue_observer=observer, boundary_check=lambda: None
        )

        class Unreadable:
            async def readexactly(self, count):
                pytest.fail("unverified peer must not read secrets")

        record, writer = wire_writer(os.geteuid() + 1)
        await worker._handle(Unreadable(), writer)
        assert record.data == b"" and observer.calls == []
        await worker.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("body", [b"{}", b'{"operation_id":"x","operation_id":"y"}', b"x" * 32769])
def test_private_requests_reject_invalid_schema_or_length(monkeypatch, body):
    async def exercise():
        monkeypatch.setattr(ipc_server, "CONTROLLER_UID", os.geteuid())
        observer = AuthObserver()
        worker = ipc_server.UnixSyntheticWorker(
            queue_observer=observer, boundary_check=lambda: None
        )
        record, writer = wire_writer(os.geteuid())
        await worker._handle(
            request_reader(
                wire.framed(wire.PREPARE_BOCA_LOGIN) + len(body).to_bytes(4, "big") + body
            ),
            writer,
        )
        assert observer.calls == []
        assert bytes(record.data).endswith(wire.NO_GO)
        await worker.close()

    asyncio.run(exercise())


def test_child_cleanup_uncertainty_poisons_worker(monkeypatch):
    async def exercise():
        observer = AuthObserver()

        async def fail(_request):
            raise wire.SyntheticIPCError("boca_login_teardown_unverified")

        observer.login_boca = fail
        worker = ipc_server.UnixSyntheticWorker(
            queue_observer=observer, boundary_check=lambda: None
        )
        request = BocaAuthRequest(OPERATION, "a" * 64, "fixture@example.invalid", "fixture")
        assert await worker._run_synthetic(auth_request=request) == wire.NO_GO
        assert worker._poisoned.is_set()
        await worker.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("guard", ["peer", "inode"])
def test_client_does_not_write_credentials_until_peer_and_inode_match(monkeypatch, guard):
    from boca_socios.browser import ipc_client

    async def exercise():
        writers = transport(monkeypatch, None)
        if guard == "peer":

            def fail(*_a, **_kw):
                raise wire.SyntheticIPCError("ipc_peer_unverified")

            monkeypatch.setattr(ipc_client, "verify_peer", fail)
        else:
            identities = iter([(1, 2), (1, 3)])
            monkeypatch.setattr(ipc_client, "socket_identity", lambda *_a, **_kw: next(identities))
        client = UnixSyntheticBrowser()
        with pytest.raises(wire.SyntheticIPCError):
            await client.login_boca(
                BocaAuthRequest(OPERATION, "a" * 64, "fixture@example.invalid", "private-password")
            )
        assert len(writers) == 1 and writers[0].writes == []
        await client.close()

    asyncio.run(exercise())
