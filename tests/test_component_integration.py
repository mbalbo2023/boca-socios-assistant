"""Cross-module internal contract; no HTTP route or real Boca reservation."""

from __future__ import annotations

import asyncio
import base64
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.domain.policy import TicketIntent
from boca_socios.integration import OfflineSimulation
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from boca_socios.panel import PanelEntry, PanelStatus, render_panel
from boca_socios.queue import InvalidStateTransition, OfflineQueueSimulator, SimulatorConfig
from boca_socios.security.credential_vault import CredentialVault
from boca_socios.security.enrollment import EnrollmentConflict, MemberEnrollmentService
from boca_socios.storage.database import Database

START = datetime(2026, 10, 28, 18, tzinfo=UTC)


class BrowserDouble:
    calls = 0

    async def simulate_general_reservation(self) -> SimulationOutcome:
        self.calls += 1
        return SimulationOutcome.RESERVED_IN_SIMULATOR


def test_enrollment_intent_durable_notice_and_private_panel(tmp_path: Path) -> None:
    key_dir = tmp_path / "key-source"
    key_dir.mkdir(mode=0o700)
    key_path = key_dir / "master"
    key_path.write_bytes(base64.b64encode(os.urandom(32)))
    key_path.chmod(0o600)
    db_path = tmp_path / "data" / "boca.sqlite3"
    database = Database(db_path)
    database.migrate()
    service = MemberEnrollmentService(database, CredentialVault.from_secret_file(key_path))
    member_id = service.enroll(
        email="synthetic@invalid.test",
        password="test-only-credential",
        consent_recorded_at=START,
    )
    with pytest.raises(EnrollmentConflict):
        service.enroll(
            email="SYNTHETIC@invalid.test",
            password="another-test-value",
            consent_recorded_at=START,
        )
    database.create_event("event-1", "Partido ficticio")
    queue = OfflineQueueSimulator(
        SimulatorConfig(event_id="event-1", opens_at=START, closes_at=START + timedelta(hours=1))
    )
    queue.create_session(member_id, "session-1", START)
    queue.create_session(member_id, "session-2", START)
    queue.join("session-1", START)
    assert queue.admit_next(START) is not None
    outbox = SqliteNotificationOutbox(db_path)
    outbox.migrate()
    browser = BrowserDouble()
    lab = OfflineSimulation(database=database, queue=queue, outbox=outbox, browser=browser)
    intent = TicketIntent(member_id, "event-1")
    receipt = asyncio.run(
        lab.run_admitted(
            intent,
            session_id="session-2",
            at=START,
            notification_at_seconds=START.timestamp(),
        )
    )

    assert receipt.outcome is SimulationOutcome.RESERVED_IN_SIMULATOR
    assert browser.calls == 1
    assert queue.request_count == 1 and queue.session_count == 2
    with pytest.raises(InvalidStateTransition):
        asyncio.run(
            lab.run_admitted(
                intent,
                session_id="session-1",
                at=START,
                notification_at_seconds=START.timestamp() + 1,
            )
        )
    assert database.request_ticket(intent) == receipt.request_id
    with database.connection() as connection:
        assert connection.execute("SELECT quantity, status FROM ticket_requests").fetchall() == [
            (1, "planned")
        ]
        assert connection.execute("SELECT count(*) FROM members").fetchone() == (1,)

    restarted = SqliteNotificationOutbox(db_path)
    restarted.migrate()
    claims = restarted.claim_ready(now=START.timestamp() + 1)
    assert len(claims) == 1
    assert claims[0].message.startswith("Simulación:")
    assert all(value not in claims[0].message for value in (member_id, "synthetic@invalid.test"))
    restarted.accept(claims[0], now=START.timestamp() + 2)
    assert SqliteNotificationOutbox(db_path).claim_ready(now=START.timestamp() + 3) == ()

    html = render_panel([PanelEntry(member_id, "event-1", PanelStatus.SIMULATED_RESERVED, START)])
    assert "SIMULACIÓN SIN RESERVAS REALES" in html
    assert "1 entrada ficticia" in html
    for private_value in (
        member_id,
        receipt.request_id,
        "synthetic@invalid.test",
        "test-only-credential",
    ):
        assert private_value not in html
