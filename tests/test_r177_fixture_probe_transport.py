"""Optional real AF_UNIX interoperability test of the R177 probe protocol.

CI Linux with AF_UNIX permitted executes the real socket exchange. Restricted
local sandboxes report an explicit skip, not a claimed physical pass.
"""

from __future__ import annotations

import asyncio
import errno
import os
import tempfile
from pathlib import Path

import pytest

from boca_socios.browser import ipc_client, ipc_server
from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.browser.ipc_client import UnixSyntheticBrowser
from boca_socios.browser.ipc_protocol import SyntheticIPCError
from boca_socios.browser.ipc_server import UnixSyntheticWorker


class FakeFixture:
    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    async def simulate_general_reservation(self) -> SimulationOutcome:
        self.calls += 1
        return SimulationOutcome.RESERVED_IN_SIMULATOR

    async def close(self) -> None:
        self.closed = True


def test_real_local_af_unix_fixture_probe_isolated_from_reservations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        uid, gid = os.geteuid(), os.getegid()
        if uid != gid:
            pytest.skip("AF_UNIX requires matching test fixture UID/GID")
        monkeypatch.setattr(ipc_client, "CONTROLLER_UID", uid)
        monkeypatch.setattr(ipc_client, "WORKER_UID", uid)
        monkeypatch.setattr(ipc_server, "CONTROLLER_UID", uid)
        monkeypatch.setattr(ipc_server, "WORKER_UID", uid)
        # The activity function's default owner UID was bound at definition.
        reset = ipc_server.reset_chromium_activity
        monkeypatch.setattr(
            ipc_server,
            "reset_chromium_activity",
            lambda *, path: reset(path=path, owner_uid=uid),
        )
        with tempfile.TemporaryDirectory(prefix="boca-r177-", dir="/tmp") as directory:  # noqa: S108
            folder = Path(directory)
            folder.chmod(0o711)
            path = folder / "synthetic.sock"
            fixture = FakeFixture()
            worker = UnixSyntheticWorker(
                fixture,
                socket_path=path,
                boundary_check=lambda: None,
                fixture_only=True,
            )
            client = UnixSyntheticBrowser(socket_path=path)
            try:
                try:
                    await worker.start()
                except OSError as exc:
                    if exc.errno == errno.EPERM:
                        pytest.skip("AF_UNIX kernel creation denied by sandbox (EPERM)")
                    raise
                assert await client.probe_offline_fixture() == "fixture_observed"
                with pytest.raises(SyntheticIPCError, match="^worker_no_go$"):
                    await client.simulate_general_reservation()
                assert fixture.calls == 1
            finally:
                await client.close()
                await worker.close()
            assert fixture.closed
            assert not path.exists()

    asyncio.run(exercise())
