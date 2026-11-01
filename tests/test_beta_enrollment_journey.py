"""Own application's request-to-storage journey, never a fake Boca website.

Authentication proof and the browser port are synthetic. Everything between
the private form request, encryption, command ledger and outbox is real code.
"""

import io
import json
import os
import re
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlencode
from uuid import uuid4

from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.domain.policy import TicketIntent
from boca_socios.integration.beta import BetaCoordinator, CommandState
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from boca_socios.panel.enrollment_http import EnrollmentApplication
from boca_socios.panel.owner_sessions import OwnerIdentity, OwnerSessions
from boca_socios.security.credential_vault import CredentialVault
from boca_socios.security.enrollment import MemberEnrollmentService
from boca_socios.storage.database import Database

ORIGIN = "https://boca.example.test"


class CountingBrowser:
    def __init__(self) -> None:
        self.calls = 0

    async def simulate_general_reservation(self) -> SimulationOutcome:
        self.calls += 1
        return SimulationOutcome.RESERVED_IN_SIMULATOR


class EnrollmentJourneyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "boca.sqlite3"
        self.db = Database(self.path)
        self.vault = CredentialVault(os.urandom(32))
        self.browser = CountingBrowser()
        self.coordinator = self.make_coordinator(self.db)
        self.coordinator.prepare_storage()
        self.db.create_event("synthetic-event", "Evento sintético")
        self.sessions = OwnerSessions(
            owner_subject="synthetic-owner",
            verify_owner=lambda _: OwnerIdentity("synthetic-owner", frozenset({"members:enroll"})),
        )
        issued = self.sessions.authenticate(object())
        assert issued is not None
        self.cookie = issued.split(";", 1)[0]
        self.app = EnrollmentApplication(
            MemberEnrollmentService(self.db, self.vault),
            self.sessions,
            origin=ORIGIN,
            now=lambda: datetime(2026, 10, 31, tzinfo=UTC),
        )

    async def asyncTearDown(self) -> None:
        await self.coordinator.close()

    def make_coordinator(self, db: Database) -> BetaCoordinator:
        return BetaCoordinator(
            database=db,
            outbox=SqliteNotificationOutbox(db),
            browser=self.browser,
            clock=lambda: 1000.0,
        )

    def request(
        self,
        method: str,
        path: str,
        fields: dict[str, str] | None = None,
        *,
        cookie: str | None = None,
    ) -> tuple[int, bytes]:
        payload = urlencode(fields or {}).encode()
        status_codes: list[int] = []

        def start(status: str, headers: list[tuple[str, str]]) -> None:
            status_codes.append(int(status.split()[0]))
            self.assertEqual(dict(headers)["Cache-Control"], "no-store")

        body = b"".join(
            self.app(
                {
                    "wsgi.url_scheme": "https",
                    "HTTP_HOST": "boca.example.test",
                    "HTTP_COOKIE": self.cookie if cookie is None else cookie,
                    "REQUEST_METHOD": method,
                    "PATH_INFO": path,
                    "QUERY_STRING": "",
                    "CONTENT_TYPE": "application/x-www-form-urlencoded",
                    "CONTENT_LENGTH": str(len(payload)) if method == "POST" else "0",
                    "HTTP_ORIGIN": ORIGIN if method == "POST" else "",
                    "wsgi.input": io.BytesIO(payload),
                },
                start,
            )
        )
        self.assertEqual(len(status_codes), 1)
        return status_codes[0], body

    def enroll(self) -> str:
        status, html = self.request("GET", "/socios/nuevo")
        self.assertEqual(status, 200)
        fields = {
            "csrf": re.search(rb'name="csrf" value="([A-Za-z0-9_-]+)"', html)[1].decode(),
            "operation_id": re.search(rb'name="operation_id" value="([a-f0-9-]+)"', html)[
                1
            ].decode(),
            "alias": "Socio de prueba",
            "email": "synthetic-member@example.test",
            "password": "synthetic-enrollment-secret",
            "consent": "yes",
        }
        status, body = self.request("POST", "/socios", fields)
        self.assertEqual(status, 201)
        self.assertNotIn(fields["password"].encode(), body)
        self.assertEqual(self.request("POST", "/socios", fields), (status, body))
        member_id = json.loads(body)["member_id"]
        stored = self.db.get_credential(member_id)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(self.vault.open(stored, member_id=member_id), fields["password"])
        return str(member_id)

    async def test_enrollment_to_result_survives_reconstructed_service_without_replay(self) -> None:
        member_id = self.enroll()
        intent = TicketIntent(member_id, "synthetic-event")
        command_id = str(uuid4())
        await self.coordinator.begin(command_id, intent)
        await self.coordinator.wait_idle()
        result = self.coordinator.status(command_id, member_id=member_id)
        assert result is not None
        self.assertEqual(result.state, CommandState.COMPLETED)
        self.assertEqual(result.external_confirmation, "not_observed")
        self.assertTrue(result.notice_enqueued)
        await self.coordinator.close()
        reopened = Database(self.path)
        self.coordinator = self.make_coordinator(reopened)
        await self.coordinator.recover()
        replay = await self.coordinator.begin(str(uuid4()), intent)
        await self.coordinator.wait_idle()
        self.assertEqual(replay.command_id, command_id)
        self.assertEqual(replay.state, CommandState.COMPLETED)
        self.assertEqual(self.browser.calls, 1)
        with reopened.connection() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM members").fetchone(), (1,))
            self.assertEqual(
                connection.execute("SELECT count(*) FROM credentials").fetchone(), (1,)
            )
            self.assertEqual(
                connection.execute("SELECT quantity FROM ticket_requests").fetchall(), [(1,)]
            )
            self.assertEqual(
                connection.execute("SELECT count(*) FROM notification_outbox").fetchone(), (1,)
            )
        credential = reopened.get_credential(member_id)
        assert credential is not None
        self.assertEqual(
            self.vault.open(credential, member_id=member_id), "synthetic-enrollment-secret"
        )

    async def test_stop_after_enrollment_preserves_member_and_never_runs_browser(self) -> None:
        member_id = self.enroll()
        command_id = str(uuid4())
        intent = TicketIntent(member_id, "synthetic-event")
        await self.coordinator.begin(command_id, intent)
        stopped = await self.coordinator.stop(command_id, member_id=member_id)
        assert stopped is not None
        self.assertEqual(stopped.state, CommandState.STOPPED)
        await self.coordinator.wait_idle()
        await self.coordinator.close()
        reopened = Database(self.path)
        self.coordinator = self.make_coordinator(reopened)
        await self.coordinator.recover()
        again = await self.coordinator.begin(str(uuid4()), intent)
        self.assertEqual(again.state, CommandState.STOPPED)
        self.assertEqual(self.browser.calls, 0)
        self.assertIsNotNone(reopened.get_credential(member_id))
        with reopened.connection() as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM ticket_requests").fetchone(), (1,)
            )
            self.assertEqual(
                connection.execute("SELECT count(*) FROM notification_outbox").fetchone(), (0,)
            )

    async def test_denied_enrollment_does_not_create_a_member_or_schedule_work(self) -> None:
        self.assertEqual(self.request("GET", "/socios/nuevo", cookie="")[0], 401)
        self.assertEqual(
            self.request("POST", "/socios", {"password": "synthetic"}, cookie="")[0], 401
        )
        with self.db.connection() as connection:
            for query in (
                "SELECT count(*) FROM members",
                "SELECT count(*) FROM credentials",
                "SELECT count(*) FROM ticket_requests",
                "SELECT count(*) FROM notification_outbox",
            ):
                self.assertEqual(connection.execute(query).fetchone(), (0,))
        self.assertEqual(self.browser.calls, 0)

    async def test_completed_result_recovers_missing_notice_without_repeating_browser(self) -> None:
        member_id = self.enroll()
        command_id = str(uuid4())
        with patch.object(
            self.coordinator._outbox,
            "enqueue",
            side_effect=RuntimeError("synthetic notice failure"),
        ):
            await self.coordinator.begin(command_id, TicketIntent(member_id, "synthetic-event"))
            await self.coordinator.wait_idle()
        self.assertTrue(self.coordinator.failed)
        result = self.coordinator.status(command_id, member_id=member_id)
        assert result is not None
        self.assertEqual(result.state, CommandState.COMPLETED)
        self.assertFalse(result.notice_enqueued)
        await self.coordinator.close()
        reopened = Database(self.path)
        self.coordinator = self.make_coordinator(reopened)
        await self.coordinator.recover()
        await self.coordinator.wait_idle()
        await self.coordinator.recover()
        recovered = self.coordinator.status(command_id, member_id=member_id)
        assert recovered is not None
        self.assertTrue(recovered.notice_enqueued)
        self.assertEqual(self.browser.calls, 1)
        with reopened.connection() as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM notification_outbox").fetchone(), (1,)
            )
