"""R177: offline fixture observation has a separate, nontransactional IPC path.

Most transport tests use in-memory asyncio streams; no socket or network opens.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest

from boca_socios.browser import ipc_client
from boca_socios.browser.ipc_client import UnixSyntheticBrowser
from boca_socios.browser.ipc_protocol import (
    FIXTURE_OBSERVED,
    NO_GO,
    PROBE_FIXTURE,
    REQUEST,
    SUCCESS,
    SyntheticIPCError,
    framed,
)


class MemoryWriter:
    def __init__(
        self,
        reader: asyncio.StreamReader,
        response: Callable[[bytes], bytes | None],
    ) -> None:
        self.reader = reader
        self.response = response
        self.writes: list[bytes] = []
        self.eof = False
        self.closed = False

    def write(self, payload: bytes) -> None:
        self.writes.append(payload)

    async def drain(self) -> None:
        return

    def can_write_eof(self) -> bool:
        return True

    def write_eof(self) -> None:
        self.eof = True
        assert len(self.writes) == 1
        reply = self.response(self.writes[0])
        if reply is not None:
            self.reader.feed_data(framed(reply))
            self.reader.feed_eof()

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return


def in_memory_transport(
    monkeypatch: pytest.MonkeyPatch, response: Callable[[bytes], bytes | None]
) -> list[MemoryWriter]:
    # Production still uses exact SO_PEERCRED/socket checks; only this test
    # replaces transport to avoid AF_UNIX creation under restricted CI hosts.
    monkeypatch.setattr(ipc_client, "_check_controller_identity", lambda: None)
    monkeypatch.setattr(ipc_client, "socket_identity", lambda *_a, **_kw: (1, 2))
    monkeypatch.setattr(ipc_client, "verify_peer", lambda *_a, **_kw: None)
    seen: list[MemoryWriter] = []

    async def connect(
        *_args: object, **_kwargs: object
    ) -> tuple[asyncio.StreamReader, MemoryWriter]:
        reader = asyncio.StreamReader()
        writer = MemoryWriter(reader, response)
        seen.append(writer)
        return reader, writer

    monkeypatch.setattr(ipc_client.asyncio, "open_unix_connection", connect)
    return seen


def test_probe_observes_fixture_only_via_distinct_ipc_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        seen = in_memory_transport(
            monkeypatch,
            lambda frame: FIXTURE_OBSERVED if frame == framed(PROBE_FIXTURE) else NO_GO,
        )
        client = UnixSyntheticBrowser(socket_path=Path("/ignored/synthetic.sock"))
        try:
            assert await client.probe_offline_fixture() == "fixture_observed"
            with pytest.raises(SyntheticIPCError, match="^worker_no_go$"):
                await client.simulate_general_reservation()
        finally:
            await client.close()
        assert [writer.writes for writer in seen] == [
            [framed(PROBE_FIXTURE)],
            [framed(REQUEST)],
        ]
        assert all(writer.eof and writer.closed for writer in seen)

    asyncio.run(exercise())


def test_probe_never_interprets_transactional_success_as_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        seen = in_memory_transport(monkeypatch, lambda _frame: SUCCESS)
        with pytest.raises(SyntheticIPCError, match="^ipc_response_unverified$"):
            await UnixSyntheticBrowser().probe_offline_fixture()
        assert seen[0].writes == [framed(PROBE_FIXTURE)]

    asyncio.run(exercise())


def test_reservation_never_interprets_fixture_observation_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fixture acknowledgement must never become a reservation outcome."""

    async def exercise() -> None:
        seen = in_memory_transport(monkeypatch, lambda _frame: FIXTURE_OBSERVED)
        client = UnixSyntheticBrowser()
        try:
            with pytest.raises(SyntheticIPCError, match="^ipc_response_unverified$"):
                await client.simulate_general_reservation()
        finally:
            await client.close()
        assert seen[0].writes == [framed(REQUEST)]
        assert seen[0].eof and seen[0].closed

    asyncio.run(exercise())


def test_stopped_fixture_probe_cannot_turn_late_reply_into_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        pending = asyncio.Event()

        def response(frame: bytes) -> None:
            assert frame == framed(PROBE_FIXTURE)
            pending.set()
            return None

        seen = in_memory_transport(monkeypatch, response)
        client = UnixSyntheticBrowser()
        active = asyncio.create_task(client.probe_offline_fixture())
        await asyncio.wait_for(pending.wait(), 1.0)
        await client.close()
        # A late frame cannot convert an interrupted probe to observed status.
        seen[0].reader.feed_data(framed(FIXTURE_OBSERVED))
        seen[0].reader.feed_eof()
        with pytest.raises(asyncio.CancelledError):
            await active
        with pytest.raises(SyntheticIPCError, match="^client_closed$"):
            await client.probe_offline_fixture()

    asyncio.run(exercise())


def test_fixture_probe_has_bounded_timeout_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        seen = in_memory_transport(monkeypatch, lambda _frame: None)
        client = UnixSyntheticBrowser(timeout_seconds=0.05)
        try:
            with pytest.raises(SyntheticIPCError, match="^worker_timeout$"):
                await client.probe_offline_fixture()
        finally:
            await client.close()
        assert seen[0].writes == [framed(PROBE_FIXTURE)]
        assert seen[0].closed

    asyncio.run(exercise())
