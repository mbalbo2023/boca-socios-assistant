"""Disposable loopback HTTP journey; the HTTPS gateway and passkey are synthetic.

No request leaves 127.0.0.1. The only browser port returns a local simulation
outcome and cannot log in to Boca, join a queue, reserve, or buy anything.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import http.client
import json
import re
import sqlite3
import statistics
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from urllib.parse import urlencode
from uuid import uuid4
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.domain.policy import TicketIntent
from boca_socios.integration.command_store import CommandStore
from boca_socios.integration.operational import LocalBetaRuntime
from boca_socios.panel.passkey import PasskeyOwnerAuthentication
from boca_socios.panel.private_http import PrivatePanelApplication
from boca_socios.reservation_guard import ReservationAttemptGuard, ReservationResolution
from boca_socios.storage.database import Database

ORIGIN = "https://boca.example.test"
EVENT_ID = "5387eb20-c962-42f5-933e-d5f681ab0877"
PERMISSIONS = frozenset(
    {"members:enroll", "members:read", "members:write", "simulation:write", "local-status:read"}
)


class _SyntheticBrowser:
    calls = 0

    async def simulate_general_reservation(self) -> SimulationOutcome:
        self.calls += 1
        return SimulationOutcome.RESERVED_IN_SIMULATOR


class _WaitingBrowser(_SyntheticBrowser):
    def __init__(self) -> None:
        self.calls = 0
        self.started = Event()
        self.cancelled = False

    async def simulate_general_reservation(self) -> SimulationOutcome:
        self.calls += 1
        self.started.set()
        try:
            while True:
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class _FailingBrowser(_SyntheticBrowser):
    def __init__(self) -> None:
        self.calls = 0

    async def simulate_general_reservation(self) -> SimulationOutcome:
        self.calls += 1
        raise RuntimeError("PRIVATE_SYNTHETIC_ADAPTER_ERROR_MUST_NOT_LEAK")


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        pass


@contextmanager
def _loopback(app: PrivatePanelApplication) -> Iterator[int]:
    def synthetic_gateway(environ: dict[str, object], start_response: object) -> object:
        # Model only the trusted gateway's WSGI scheme assertion. The socket is
        # cleartext loopback; this test is not TLS or gateway configuration proof.
        environ["wsgi.url_scheme"] = "https"
        return app(environ, start_response)

    server = make_server("127.0.0.1", 0, synthetic_gateway, handler_class=_QuietHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert server.socket.fileno() == -1


def _request(
    port: int,
    path: str,
    *,
    method: str = "GET",
    cookie: str = "",
    fields: dict[str, str] | None = None,
    body: bytes | None = None,
    content_type: str = "application/x-www-form-urlencoded",
    origin: str = ORIGIN,
    timings: list[float],
) -> tuple[int, dict[str, str], bytes]:
    payload = (
        body if body is not None else urlencode(fields or {}).encode() if method == "POST" else None
    )
    headers = {"Host": "boca.example.test"}
    if cookie:
        headers["Cookie"] = cookie
    if method == "POST":
        headers.update({"Origin": origin, "Content-Type": content_type})
    started = time.perf_counter_ns()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        data = response.read()
        result = response.status, {key: value for key, value in response.getheaders()}, data
    finally:
        connection.close()
    timings.append((time.perf_counter_ns() - started) / 1_000_000)
    assert result[1]["Cache-Control"] == "no-store"
    assert int(result[1]["Content-Length"]) == len(result[2])
    assert len(result[2]) < 65536
    return result


def _passkey(
    key: ec.EllipticCurvePrivateKey | None = None, credential_id: bytes | None = None
) -> tuple[PasskeyOwnerAuthentication, ec.EllipticCurvePrivateKey, bytes]:
    key = key or ec.generate_private_key(ec.SECP256R1())
    credential_id = credential_id or b"synthetic-credential-id-32-bytes!"
    provider = PasskeyOwnerAuthentication(
        credential_id=credential_id,
        public_key_der=key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
        rp_id="boca.example.test",
        origin=ORIGIN,
        owner_subject="synthetic-owner",
        permissions=PERMISSIONS,
    )
    return provider, key, credential_id


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _login(
    port: int, key: ec.EllipticCurvePrivateKey, credential_id: bytes, timings: list[float]
) -> str:
    status, _, page = _request(port, "/ingresar", timings=timings)
    assert status == 200
    challenge = re.search(rb'data-challenge="([A-Za-z0-9_-]+)"', page).group(1).decode()
    client_data = json.dumps(
        {"type": "webauthn.get", "challenge": challenge, "origin": ORIGIN},
        separators=(",", ":"),
    ).encode()
    auth_data = hashlib.sha256(b"boca.example.test").digest() + b"\x05" + (1).to_bytes(4, "big")
    signature = key.sign(
        auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
    )
    assertion = {
        "credential_id": _b64(credential_id),
        "client_data_json": _b64(client_data),
        "authenticator_data": _b64(auth_data),
        "signature": _b64(signature),
    }
    status, headers, body = _request(
        port,
        "/sesion",
        method="POST",
        body=json.dumps(assertion).encode(),
        content_type="application/json",
        timings=timings,
    )
    assert status == 204 and body == b""
    assert "Secure" in headers["Set-Cookie"] and "HttpOnly" in headers["Set-Cookie"]
    return headers["Set-Cookie"].split(";", 1)[0]


def _hidden(page: bytes, name: str) -> str:
    return re.search(rb'name="' + name.encode() + rb'" value="([^\"]+)"', page).group(1).decode()


def _app(
    runtime: LocalBetaRuntime, provider: PasskeyOwnerAuthentication
) -> PrivatePanelApplication:
    return PrivatePanelApplication(
        origin=ORIGIN,
        database_path=runtime.database.path,
        owner_subject="synthetic-owner",
        passkey=provider,
        members=runtime.members,
        commands=runtime.commands,
        events={EVENT_ID: "Partido sintético"},
    )


def test_loopback_http_enrollment_command_notice_and_restart() -> None:
    timings: list[float] = []
    browser = _SyntheticBrowser()
    with TemporaryDirectory() as directory:
        path = Path(directory)
        database_path, key_file = path / "boca.sqlite3", path / "boca.key"
        key_file.write_bytes(base64.b64encode(b"k" * 32) + b"\n")
        key_file.chmod(0o400)
        runtime = LocalBetaRuntime.start(
            database_path=database_path, key_file=key_file, browser=browser, initialize_new=True
        )
        provider, key, credential_id = _passkey()
        try:
            runtime.database.create_event(EVENT_ID, "Partido sintético")
            with _loopback(_app(runtime, provider)) as port:
                for route in ("/socios", "/comandos", "/avisos"):
                    status, _, denied = _request(port, route, timings=timings)
                    assert status == 401 and b"boca.key" not in denied
                cookie = _login(port, key, credential_id, timings)
                status, _, form = _request(port, "/socios/nuevo", cookie=cookie, timings=timings)
                assert status == 200
                fields = {
                    "csrf": _hidden(form, "csrf"),
                    "operation_id": _hidden(form, "operation_id"),
                    "alias": "Socio sintético",
                    "email": "person@example.test",
                    "password": "synthetic-secret-only",
                    "consent": "yes",
                }
                status, _, enrolled = _request(
                    port, "/socios", method="POST", cookie=cookie, fields=fields, timings=timings
                )
                assert status == 201 and b"synthetic-secret-only" not in enrolled
                assert (
                    _request(
                        port,
                        "/socios",
                        method="POST",
                        cookie=cookie,
                        fields=fields,
                        timings=timings,
                    )[2]
                    == enrolled
                )
                member_id = json.loads(enrolled)["member_id"]
                status, _, listing = _request(port, "/socios", cookie=cookie, timings=timings)
                assert status == 200 and b"Socio sint" in listing
                assert b"person@example.test" not in listing
                status, _, command_form = _request(
                    port, "/comandos", cookie=cookie, timings=timings
                )
                assert status == 200
                command_id = _hidden(command_form, "operation_id")
                command = {
                    "csrf": _hidden(command_form, "csrf"),
                    "operation_id": command_id,
                    "member_id": member_id,
                    "event_id": EVENT_ID,
                }
                denied = _request(
                    port,
                    "/comandos",
                    method="POST",
                    cookie=cookie,
                    fields=command,
                    origin="https://foreign.example.test",
                    timings=timings,
                )
                assert denied[0] == 403
                # Enrollment and command writes share a one-second session rate gate.
                time.sleep(1.05)
                started = _request(
                    port,
                    "/comandos",
                    method="POST",
                    cookie=cookie,
                    fields=command,
                    timings=timings,
                )
                assert started[0] == 303
                assert started[1]["Location"] == f"/comandos/{command_id}"
                assert (
                    _request(
                        port,
                        "/comandos",
                        method="POST",
                        cookie=cookie,
                        fields=command,
                        timings=timings,
                    )[0]
                    == 303
                )
                deadline = time.monotonic() + 3
                while True:
                    status, _, detail = _request(
                        port, f"/comandos/{command_id}", cookie=cookie, timings=timings
                    )
                    assert status == 200
                    if b"Estado: completed" in detail:
                        break
                    assert time.monotonic() < deadline
                    time.sleep(0.02)
                status, _, notices = _request(port, "/avisos", cookie=cookie, timings=timings)
                assert status == 200 and b"Aviso local" in notices
                assert b"person@example.test" not in notices
                assert b"Telegram no configurado" in notices
                assert _request(port, "/estado", cookie=cookie, timings=timings)[0] == 200
            runtime.close()
            with sqlite3.connect(database_path) as connection:
                before = connection.execute(
                    "SELECT version, checksum FROM schema_migrations ORDER BY version"
                ).fetchall()
                assert connection.execute("SELECT count(*) FROM members").fetchone() == (1,)
                assert connection.execute("SELECT quantity FROM ticket_requests").fetchall() == [
                    (1,)
                ]
                assert connection.execute(
                    "SELECT count(*) FROM notification_outbox"
                ).fetchone() == (1,)
            assert browser.calls == 1
            restarted = LocalBetaRuntime.start(
                database_path=database_path,
                key_file=key_file,
                browser=browser,
                initialize_new=False,
            )
            try:
                new_provider, _, _ = _passkey(key, credential_id)
                # A new process has a new session store. Old cookies cannot read data.
                with _loopback(_app(restarted, new_provider)) as port:
                    assert _request(port, "/avisos", cookie=cookie, timings=timings)[0] == 401
                    fresh_cookie = _login(port, key, credential_id, timings)
                    assert (
                        _request(
                            port, f"/comandos/{command_id}", cookie=fresh_cookie, timings=timings
                        )[0]
                        == 200
                    )
                    assert (
                        b"Aviso local"
                        in _request(port, "/avisos", cookie=fresh_cookie, timings=timings)[2]
                    )
                with sqlite3.connect(database_path) as connection:
                    assert (
                        connection.execute(
                            "SELECT version, checksum FROM schema_migrations ORDER BY version"
                        ).fetchall()
                        == before
                    )
                assert browser.calls == 1
            finally:
                restarted.close()
        finally:
            runtime.close()
    ordered = sorted(timings)
    p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
    print(
        f"BOCA_SYNTHETIC_HTTP samples={len(ordered)} "
        f"median_ms={statistics.median(ordered):.2f} p95_ms={p95:.2f} "
        f"unexpected_errors=0 scope=loopback_no_tls_no_host"
    )


def test_loopback_http_stop_cancels_worker_and_survives_restart() -> None:
    timings: list[float] = []
    browser = _WaitingBrowser()
    with TemporaryDirectory() as directory:
        path = Path(directory)
        database_path, key_file = path / "boca.sqlite3", path / "boca.key"
        key_file.write_bytes(base64.b64encode(b"k" * 32) + b"\n")
        key_file.chmod(0o400)
        runtime = LocalBetaRuntime.start(
            database_path=database_path, key_file=key_file, browser=browser, initialize_new=True
        )
        provider, key, credential_id = _passkey()
        try:
            runtime.database.create_event(EVENT_ID, "Partido sintético")
            member_id = runtime.members.enroll(
                email="stop@example.test",
                password="synthetic-stop-secret",
                consent_recorded_at=datetime.now(UTC),
            )
            with _loopback(_app(runtime, provider)) as port:
                cookie = _login(port, key, credential_id, timings)
                status, _, command_form = _request(
                    port, "/comandos", cookie=cookie, timings=timings
                )
                assert status == 200
                command_id = _hidden(command_form, "operation_id")
                command = {
                    "csrf": _hidden(command_form, "csrf"),
                    "operation_id": command_id,
                    "member_id": member_id,
                    "event_id": EVENT_ID,
                }
                assert (
                    _request(
                        port,
                        "/comandos",
                        method="POST",
                        cookie=cookie,
                        fields=command,
                        timings=timings,
                    )[0]
                    == 303
                )
                assert browser.started.wait(2)
                status, _, detail = _request(
                    port, f"/comandos/{command_id}", cookie=cookie, timings=timings
                )
                assert status == 200
                csrf = _hidden(detail, "csrf")
                stop_path = f"/comandos/{command_id}/detener"
                assert (
                    _request(
                        port, stop_path, method="POST", fields={"csrf": csrf}, timings=timings
                    )[0]
                    == 401
                )
                assert (
                    _request(
                        port,
                        stop_path,
                        method="POST",
                        cookie=cookie,
                        fields={"csrf": csrf},
                        origin="https://foreign.example.test",
                        timings=timings,
                    )[0]
                    == 403
                )
                assert (
                    _request(
                        port,
                        stop_path,
                        method="POST",
                        cookie=cookie,
                        fields={"csrf": csrf},
                        timings=timings,
                    )[0]
                    == 303
                )
                deadline = time.monotonic() + 3
                while True:
                    status, _, detail = _request(
                        port, f"/comandos/{command_id}", cookie=cookie, timings=timings
                    )
                    assert status == 200
                    if b"Estado: stopped" in detail:
                        break
                    assert time.monotonic() < deadline
                    time.sleep(0.02)
                assert browser.cancelled
            runtime.close()
            reopened = LocalBetaRuntime.start(
                database_path=database_path,
                key_file=key_file,
                browser=browser,
                initialize_new=False,
            )
            try:
                new_provider, _, _ = _passkey(key, credential_id)
                with _loopback(_app(reopened, new_provider)) as port:
                    new_cookie = _login(port, key, credential_id, timings)
                    status, _, detail = _request(
                        port, f"/comandos/{command_id}", cookie=new_cookie, timings=timings
                    )
                    assert status == 200 and b"Estado: stopped" in detail
                    assert (
                        b"Sin avisos locales"
                        in _request(port, "/avisos", cookie=new_cookie, timings=timings)[2]
                    )
                assert browser.calls == 1
                with sqlite3.connect(database_path) as connection:
                    assert connection.execute(
                        "SELECT quantity FROM ticket_requests"
                    ).fetchall() == [(1,)]
                    assert connection.execute(
                        "SELECT count(*) FROM notification_outbox"
                    ).fetchone() == (0,)
            finally:
                reopened.close()
        finally:
            runtime.close()


def test_loopback_http_failed_browser_is_redacted_and_not_retried_after_restart() -> None:
    timings: list[float] = []
    browser = _FailingBrowser()
    with TemporaryDirectory() as directory:
        path = Path(directory)
        database_path, key_file = path / "boca.sqlite3", path / "boca.key"
        key_file.write_bytes(base64.b64encode(b"k" * 32) + b"\n")
        key_file.chmod(0o400)
        runtime = LocalBetaRuntime.start(
            database_path=database_path, key_file=key_file, browser=browser, initialize_new=True
        )
        _, key, credential_id = _passkey()
        try:
            runtime.database.create_event(EVENT_ID, "Partido sintético")
            member_id = runtime.members.enroll(
                email="failure@example.test",
                password="synthetic-failure-secret",
                consent_recorded_at=datetime.now(UTC),
            )
            provider, _, _ = _passkey(key, credential_id)
            with _loopback(_app(runtime, provider)) as port:
                cookie = _login(port, key, credential_id, timings)
                status, _, form = _request(port, "/comandos", cookie=cookie, timings=timings)
                assert status == 200
                command_id = _hidden(form, "operation_id")
                command = {
                    "csrf": _hidden(form, "csrf"),
                    "operation_id": command_id,
                    "member_id": member_id,
                    "event_id": EVENT_ID,
                }
                status, _, _ = _request(
                    port,
                    "/comandos",
                    method="POST",
                    cookie=cookie,
                    fields=command,
                    timings=timings,
                )
                assert status == 303
                deadline = time.monotonic() + 3
                while True:
                    status, _, detail = _request(
                        port, f"/comandos/{command_id}", cookie=cookie, timings=timings
                    )
                    assert status == 200
                    assert b"PRIVATE_SYNTHETIC_ADAPTER_ERROR_MUST_NOT_LEAK" not in detail
                    if b"Estado: failed" in detail:
                        break
                    assert time.monotonic() < deadline
                    time.sleep(0.02)
                assert (
                    b"Sin avisos locales"
                    in _request(port, "/avisos", cookie=cookie, timings=timings)[2]
                )
            runtime.close()
            reopened = LocalBetaRuntime.start(
                database_path=database_path,
                key_file=key_file,
                browser=browser,
                initialize_new=False,
            )
            try:
                provider, _, _ = _passkey(key, credential_id)
                with _loopback(_app(reopened, provider)) as port:
                    cookie = _login(port, key, credential_id, timings)
                    status, _, detail = _request(
                        port, f"/comandos/{command_id}", cookie=cookie, timings=timings
                    )
                    assert status == 200 and b"Estado: failed" in detail
                    status, _, form = _request(port, "/comandos", cookie=cookie, timings=timings)
                    assert status == 200
                    retry = {
                        "csrf": _hidden(form, "csrf"),
                        "operation_id": _hidden(form, "operation_id"),
                        "member_id": member_id,
                        "event_id": EVENT_ID,
                    }
                    status, headers, body = _request(
                        port,
                        "/comandos",
                        method="POST",
                        cookie=cookie,
                        fields=retry,
                        timings=timings,
                    )
                    assert status == 303 and headers["Location"] == f"/comandos/{command_id}"
                    assert b"PRIVATE_SYNTHETIC_ADAPTER_ERROR_MUST_NOT_LEAK" not in body
                    assert (
                        b"Sin avisos locales"
                        in _request(port, "/avisos", cookie=cookie, timings=timings)[2]
                    )
            finally:
                reopened.close()
        finally:
            runtime.close()

        assert browser.calls == 1
        with sqlite3.connect(database_path) as connection:
            assert connection.execute("SELECT state FROM beta_commands").fetchall() == [("failed",)]
            assert connection.execute("SELECT quantity FROM ticket_requests").fetchall() == [(1,)]
            assert connection.execute("SELECT count(*) FROM notification_outbox").fetchone() == (0,)


@pytest.mark.parametrize(
    ("resolved", "expected_state", "notice_count"),
    [
        (False, b"needs_review", 0),
        (True, b"completed", 1),
    ],
    ids=("ambiguous-running", "completed-before-notice"),
)
def test_loopback_http_interrupted_command_recovery_does_not_replay_browser(
    resolved: bool, expected_state: bytes, notice_count: int
) -> None:
    """Seed the two crash boundaries, then assert recovery through real HTTP.

    Unlike coordinator-only recovery tests, this checks that the authenticated
    browser-facing routes expose the durable result after two process lifecycles.
    """
    timings: list[float] = []
    browser = _SyntheticBrowser()
    with TemporaryDirectory() as directory:
        path = Path(directory)
        database_path, key_file = path / "boca.sqlite3", path / "boca.key"
        key_file.write_bytes(base64.b64encode(b"k" * 32) + b"\n")
        key_file.chmod(0o400)
        first = LocalBetaRuntime.start(
            database_path=database_path, key_file=key_file, browser=browser, initialize_new=True
        )
        try:
            first.database.create_event(EVENT_ID, "Partido sintético")
            member_id = first.members.enroll(
                email="interrupted@example.test",
                password="synthetic-interrupted-secret",
                consent_recorded_at=datetime.now(UTC),
            )
        finally:
            first.close()

        # Persist exactly the state that survives an abrupt worker/process loss:
        # a RUNNING command with an unresolved or already-completed guard.
        database = Database(database_path)
        store = CommandStore(database)
        command_id = str(uuid4())
        store.enqueue(command_id, TicketIntent(member_id, EVENT_ID), now=1000, max_pending=16)
        claimed = store.claim_next(now=1000)
        assert claimed is not None
        snapshot, _ = claimed
        guard = ReservationAttemptGuard(database)
        claim = guard.claim_simulation(snapshot.request_id, now=1000)
        assert claim is not None
        if resolved:
            guard.resolve(claim, ReservationResolution.SIMULATION_COMPLETED, now=1000)

        previous_cookie = ""
        _, key, credential_id = _passkey()
        for _ in range(2):
            provider, _, _ = _passkey(key, credential_id)
            restarted = LocalBetaRuntime.start(
                database_path=database_path,
                key_file=key_file,
                browser=browser,
                initialize_new=False,
            )
            try:
                with _loopback(_app(restarted, provider)) as port:
                    # Authentication is process-local even when command state
                    # and the offline outbox survive repeated startup.
                    if previous_cookie:
                        assert (
                            _request(
                                port,
                                f"/comandos/{command_id}",
                                cookie=previous_cookie,
                                timings=timings,
                            )[0]
                            == 401
                        )
                    assert _request(port, "/avisos", timings=timings)[0] == 401
                    cookie = _login(port, key, credential_id, timings)
                    status, _, detail = _request(
                        port, f"/comandos/{command_id}", cookie=cookie, timings=timings
                    )
                    assert status == 200 and b"Estado: " + expected_state in detail
                    assert b"interrupted@example.test" not in detail

                    # A fresh user retry for the same member/event must map to
                    # the original UUID, without arming another browser call.
                    status, _, form = _request(port, "/comandos", cookie=cookie, timings=timings)
                    assert status == 200
                    retry = {
                        "csrf": _hidden(form, "csrf"),
                        "operation_id": _hidden(form, "operation_id"),
                        "member_id": member_id,
                        "event_id": EVENT_ID,
                    }
                    status, headers, _ = _request(
                        port,
                        "/comandos",
                        method="POST",
                        cookie=cookie,
                        fields=retry,
                        timings=timings,
                    )
                    assert status == 303
                    assert headers["Location"] == f"/comandos/{command_id}"
                    status, _, notices = _request(port, "/avisos", cookie=cookie, timings=timings)
                    assert status == 200
                    assert (b"Aviso local" in notices) is resolved
                    assert (b"Sin avisos locales" in notices) is not resolved
                    assert b"interrupted@example.test" not in notices
                    previous_cookie = cookie
            finally:
                restarted.close()

        assert browser.calls == 0
        with sqlite3.connect(database_path) as connection:
            assert connection.execute(
                "SELECT command_id,state,notice_enqueued FROM beta_commands"
            ).fetchall() == [(command_id, expected_state.decode(), notice_count)]
            assert connection.execute("SELECT quantity FROM ticket_requests").fetchall() == [(1,)]
            assert connection.execute("SELECT count(*) FROM notification_outbox").fetchone() == (
                notice_count,
            )
