"""Hosted-Linux-only AF_UNIX smoke with a fake Boca browser and no network.

This script is deliberately separate from ordinary pytest because the
development executor denies socket(AF_UNIX) at the kernel boundary. GitHub's
ephemeral Linux CI runner must prove the actual listener/client handshake.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.integration.beta import BetaCoordinator
from boca_socios.integration.command_host import BetaCommandHost
from boca_socios.integration.engine_socket import LocalEngineSocket, request_local_engine
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from boca_socios.storage.database import Database


class _OfflineBrowser:
    async def simulate_general_reservation(self) -> SimulationOutcome:
        await asyncio.sleep(0)
        return SimulationOutcome.RESERVED_IN_SIMULATOR


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="boca-engine-ci-") as directory:
        root = Path(directory)
        db = Database(root / "boca.sqlite3")
        outbox = SqliteNotificationOutbox(db)
        browser = _OfflineBrowser()

        def coordinator() -> BetaCoordinator:
            return BetaCoordinator(database=db, outbox=outbox, browser=browser)

        first = coordinator()
        first.prepare_storage()
        commands = BetaCommandHost.start(first, coordinator_factory=coordinator)
        path = root / "engine.sock"
        server = LocalEngineSocket(commands, path=path)
        try:
            server.start()
            first_receipt = request_local_engine("status", path=path)
            assert first_receipt.state == "RUNNING" and not first_receipt.changed
            assert first_receipt.pid == os.getpid()
            stopped = request_local_engine("stop", path=path)
            assert stopped.state == "STOPPED" and stopped.changed
            assert commands.engine_stopped and not commands._thread.is_alive()
            assert not request_local_engine("stop", path=path).changed
            started = request_local_engine("start", path=path)
            assert started.state == "RUNNING" and started.changed
            assert commands.engine_running
            assert not request_local_engine("start", path=path).changed
            assert request_local_engine("status", path=path).state == "RUNNING"
        finally:
            server.close()
            commands.close()
        assert not path.exists(), "controller-private AF_UNIX residue"
    print("BOCA_ENGINE_UDS_OFFLINE state=PASS protocol=v1 start_stop=verified port=none")


if __name__ == "__main__":
    main()
