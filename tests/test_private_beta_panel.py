"""Synthetic private HTTP journey and passkey security regression."""

import base64
import hashlib
import io
import json
import os
import re
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep
from urllib.parse import urlencode
from uuid import uuid4

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from boca_socios.domain.policy import TicketIntent
from boca_socios.events.official_catalog import (
    OfficialCatalogError,
    OfficialNotice,
    load_observed_notice,
)
from boca_socios.integration.command_store import CommandStore
from boca_socios.notify.outbox import NoticeKind, NotificationRequest
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from boca_socios.panel.owner_session_store import OwnerBrowserSessionStore
from boca_socios.panel.passkey import PasskeyAssertion, PasskeyOwnerAuthentication
from boca_socios.panel.private_http import PrivatePanelApplication
from boca_socios.security.credential_vault import CredentialVault
from boca_socios.security.enrollment import MemberEnrollmentService
from boca_socios.storage.database import Database

ORIGIN = "https://boca.example.test"
EVENT_ID = "5387eb20-c962-42f5-933e-d5f681ab0877"
PERMISSIONS = frozenset(
    {"members:enroll", "members:read", "members:write", "simulation:write", "local-status:read"}
)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _assertion(
    key: ec.EllipticCurvePrivateKey,
    credential_id: bytes,
    challenge: str,
    *,
    origin: str = ORIGIN,
    flags: int = 0x05,
) -> PasskeyAssertion:
    client = json.dumps(
        {"type": "webauthn.get", "challenge": challenge, "origin": origin},
        separators=(",", ":"),
    ).encode()
    auth = hashlib.sha256(b"boca.example.test").digest() + bytes([flags]) + (1).to_bytes(4, "big")
    signature = key.sign(auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
    return PasskeyAssertion(_b64(credential_id), _b64(client), _b64(auth), _b64(signature))


def _passkey(
    clock: list[float],
) -> tuple[PasskeyOwnerAuthentication, ec.EllipticCurvePrivateKey, bytes]:
    key = ec.generate_private_key(ec.SECP256R1())
    credential_id = os.urandom(32)
    provider = PasskeyOwnerAuthentication(
        credential_id=credential_id,
        public_key_der=key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
        rp_id="boca.example.test",
        origin=ORIGIN,
        owner_subject="owner",
        permissions=PERMISSIONS,
        clock=lambda: clock[0],
    )
    return provider, key, credential_id


def _request(
    app: PrivatePanelApplication,
    path: str,
    *,
    method: str = "GET",
    cookie: str = "",
    payload: dict[str, str] | bytes | None = None,
    content_type: str = "application/x-www-form-urlencoded",
    origin: str = ORIGIN,
    extra: dict[str, object] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    body = payload if isinstance(payload, bytes) else urlencode(payload or {}).encode()
    environ: dict[str, object] = {
        "wsgi.url_scheme": "https",
        "HTTP_HOST": "boca.example.test",
        "PATH_INFO": path,
        "REQUEST_METHOD": method,
        "QUERY_STRING": "",
        "HTTP_COOKIE": cookie,
        "HTTP_ORIGIN": origin if method == "POST" else "",
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": content_type,
        "wsgi.input": io.BytesIO(body),
    }
    environ.update(extra or {})
    captured: list[tuple[str, list[tuple[str, str]]]] = []
    response = b"".join(app(environ, lambda status, headers: captured.append((status, headers))))
    status, headers = captured[0]
    return int(status.split()[0]), dict(headers), response


@dataclass
class FakeCommand:
    state: str = "accepted"
    updated_at: float = 1.0
    command_id: str = ""


class FakeHost:
    failed = False
    calls: list[tuple[str, str, str]]

    def __init__(self) -> None:
        self.calls = []

    def begin(self, command_id: str, *, member_id: str, event_id: str) -> FakeCommand:
        self.calls.append((command_id, member_id, event_id))
        return FakeCommand(command_id=command_id)

    def status(self, command_id: str, *, member_id: str) -> FakeCommand | None:
        return FakeCommand()

    def stop(self, command_id: str, *, member_id: str) -> FakeCommand | None:
        return FakeCommand("stopped")


def _app(
    path: Path,
    provider: PasskeyOwnerAuthentication,
    host: FakeHost | None = None,
    *,
    official_notices: tuple[OfficialNotice, ...] = (),
    official_loader: Callable[[], tuple[OfficialNotice, ...]] | None = None,
) -> tuple[PrivatePanelApplication, Database]:
    db = Database(path)
    db.migrate()
    SqliteNotificationOutbox(db).migrate()
    CommandStore(db).migrate()
    OwnerBrowserSessionStore(db, owner_subject="owner").migrate()
    db.create_event(EVENT_ID, "Partido sintético")
    app = PrivatePanelApplication(
        origin=ORIGIN,
        database_path=path,
        owner_subject="owner",
        passkey=provider,
        members=MemberEnrollmentService(db, CredentialVault(os.urandom(32))),
        commands=host,
        events={EVENT_ID: "Partido sintético"},
        observed_official_notices=official_notices,
        official_notices_loader=official_loader,
    )
    return app, db


def _login(
    app: PrivatePanelApplication, key: ec.EllipticCurvePrivateKey, credential_id: bytes
) -> str:
    status, _, page = _request(app, "/ingresar")
    assert status == 200 and b"navigator.credentials.get" in page
    assert b"button, select" in page and b"min-height: 52px" in page
    challenge = re.search(rb'data-challenge="([A-Za-z0-9_-]+)"', page).group(1).decode()
    assertion = _assertion(key, credential_id, challenge)
    status, headers, body = _request(
        app,
        "/sesion",
        method="POST",
        content_type="application/json",
        payload=json.dumps(asdict(assertion)).encode(),
    )
    assert status == 204 and body == b""
    assert "Secure" in headers["Set-Cookie"] and "HttpOnly" in headers["Set-Cookie"]
    assert "Max-Age=34560000" in headers["Set-Cookie"]
    return headers["Set-Cookie"].split(";", 1)[0]


def _control_action(
    app: PrivatePanelApplication, cookie: str, action: str
) -> tuple[int, dict[str, str], bytes]:
    status, _, page = _request(app, "/control", cookie=cookie)
    assert status == 200
    match = re.search(
        rb'<form method="post" action="/control/(?:reanudar|pausar)">(.*?)</form>',
        page,
        re.S,
    )
    assert match is not None
    fields = {
        "csrf": re.search(rb'name="csrf" value="([^"]+)"', match.group(1)).group(1).decode(),
        "operation_id": re.search(rb'name="operation_id" value="([^"]+)"', match.group(1))
        .group(1)
        .decode(),
    }
    return _request(app, f"/control/{action}", cookie=cookie, method="POST", payload=fields)


def test_private_official_events_routes_are_read_only_and_empty_without_receipts() -> None:
    provider, key, credential_id = _passkey([0.0])
    with TemporaryDirectory() as directory:
        host = FakeHost()
        app, _db = _app(Path(directory) / "boca.sqlite3", provider, host)
        for path in ("/avisos-oficiales", "/avisos-oficiales.json"):
            assert _request(app, path)[0] == 401
        cookie = _login(app, key, credential_id)
        code, headers, home = _request(app, "/", cookie=cookie)
        assert code == 200 and b'href="/avisos-oficiales"' in home
        code, headers, page = _request(app, "/avisos-oficiales", cookie=cookie)
        assert code == 200 and headers["Cache-Control"] == "no-store"
        assert b"No hay avisos oficiales observados cargados" in page
        assert b"No confirma disponibilidad" in page
        assert b"Iniciar simulaci" not in page
        code, headers, data = _request(app, "/avisos-oficiales.json", cookie=cookie)
        assert code == 200 and headers["Content-Type"] == "application/json"
        document = json.loads(data)
        assert document["events"] == []
        assert document["source_mode"] == "OFFLINE_PREOBSERVED_ONLY"
        assert document["actionable"] is False
        assert document["live_feed"] is False
        assert document["availability_verified"] is False
        assert _request(app, "/avisos-oficiales", method="POST", cookie=cookie)[0] == 404
        assert host.calls == []


def test_private_official_events_renders_only_preobserved_synthetic_notice() -> None:
    provider, key, credential_id = _passkey([0.0])
    example = load_observed_notice(
        json.dumps(
            {
                "version": "official-notice-observation-v1",
                "source_url": "https://www.bocajuniors.com.ar/noticias/ejemplo-sintetico-no-publicado",
                "published_on": "2026-11-03",
                "observed_at": "2026-11-03T13:00:00-03:00",
                "source_sha256": "a" * 64,
                "event_key": "boca-prueba-sintetica-2026-11-09",
                "title": "Evento sintético <no publicado>",
                "kickoff_at": "2026-11-09T17:30:00-03:00",
                "windows": [],
            }
        )
    )
    with TemporaryDirectory() as directory:
        host = FakeHost()
        app, _db = _app(
            Path(directory) / "boca.sqlite3",
            provider,
            host,
            official_notices=(example,),
        )
        cookie = _login(app, key, credential_id)
        code, _headers, page = _request(app, "/avisos-oficiales", cookie=cookie)
        assert code == 200
        assert b"Evento sint\xc3\xa9tico &lt;no publicado&gt;" in page
        assert b"No hay horarios por categor" in page
        code, _headers, data = _request(app, "/avisos-oficiales.json", cookie=cookie)
        assert code == 200
        notice = json.loads(data)["events"][0]
        assert notice["title"] == "Evento sintético <no publicado>"
        assert notice["actionable"] is False
        assert notice["admission_channel_verified"] is False
        assert host.calls == []


def test_official_snapshot_refresh_is_private_and_failure_stays_isolated_to_notices() -> None:
    provider, key, credential_id = _passkey([0.0])
    notice = load_observed_notice(
        json.dumps(
            {
                "version": "official-notice-observation-v1",
                "source_url": "https://www.bocajuniors.com.ar/noticias/observacion-sintetica",
                "published_on": "2026-11-03",
                "observed_at": "2026-11-03T13:00:00-03:00",
                "source_sha256": "b" * 64,
                "event_key": "boca-test-offline-2026-11-09",
                "title": "Aviso offline sintético",
                "kickoff_at": "2026-11-09T17:30:00-03:00",
                "windows": [],
            }
        )
    )
    source: list[tuple[OfficialNotice, ...] | None] = [(notice,)]
    reads = 0

    def loader() -> tuple[OfficialNotice, ...]:
        nonlocal reads
        reads += 1
        if source[0] is None:
            raise OfficialCatalogError("private detail must not escape")
        return source[0]

    with TemporaryDirectory() as directory:
        host = FakeHost()
        app, _db = _app(Path(directory) / "boca.sqlite3", provider, host, official_loader=loader)
        assert _request(app, "/avisos-oficiales")[0] == 401
        assert reads == 0  # never read the local snapshot for an unauthenticated caller
        cookie = _login(app, key, credential_id)
        status, _, page = _request(app, "/avisos-oficiales", cookie=cookie)
        assert status == 200 and b"Aviso offline sint" in page and reads == 1
        source[0] = ()
        status, _, page = _request(app, "/avisos-oficiales", cookie=cookie)
        assert status == 200 and b"No hay avisos oficiales observados cargados" in page
        source[0] = None
        status, _, page = _request(app, "/avisos-oficiales", cookie=cookie)
        assert status == 503 and b"La simulaci" in page
        assert b"private detail" not in page
        status, headers, payload = _request(app, "/avisos-oficiales.json", cookie=cookie)
        assert status == 503 and headers["Content-Type"] == "application/json"
        assert json.loads(payload) == {
            "source_mode": "OFFLINE_PREOBSERVED_ONLY",
            "source_health": "UNAVAILABLE",
            "events": [],
            "actionable": False,
            "availability_verified": False,
            "live_feed": False,
        }
        assert _request(app, "/control", cookie=cookie)[0] == 200
        assert _request(app, "/", cookie=cookie)[0] == 200
        assert host.calls == []


def test_owner_cookie_survives_controller_restart_and_logout_revokes_server_side() -> None:
    clock = [0.0]
    provider, key, credential_id = _passkey(clock)
    with TemporaryDirectory() as directory:
        path = Path(directory) / "boca.sqlite3"
        app, db = _app(path, provider, FakeHost())
        cookie = _login(app, key, credential_id)
        first_status, headers, home = _request(app, "/", cookie=cookie)
        assert first_status == 200 and b"Boca Socios" in home
        assert headers["Set-Cookie"].startswith(cookie + ";")
        assert "Max-Age=34560000" in headers["Set-Cookie"]
        assert "Secure; HttpOnly; SameSite=Strict" in headers["Set-Cookie"]
        status, _, old_form = _request(app, "/control", cookie=cookie)
        assert status == 200
        old_csrf = re.search(rb'name="csrf" value="([^\"]+)"', old_form).group(1).decode()
        old_operation = (
            re.search(rb'name="operation_id" value="([^\"]+)"', old_form).group(1).decode()
        )
        with closing(sqlite3.connect(path.with_name("boca_owner_session.sqlite3"))) as connection:
            persisted = connection.execute(
                "SELECT singleton,token_sha256,verifier_sha256,owner_sha256"
                " FROM owner_browser_session"
            ).fetchone()
        assert persisted is not None and persisted[0] == 1
        assert all(isinstance(value, bytes) and len(value) == 32 for value in persisted[1:])
        assert cookie.encode() not in persisted[1:]
        with db.connection() as connection:
            assert connection.execute(
                "SELECT count(*) FROM schema_migrations WHERE version=8"
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT count(*) FROM sqlite_master WHERE name='owner_browser_session'"
            ).fetchone() == (0,)

        # Same trusted verifier, same browser cookie, NEW controller lifetime:
        # no passkey prompt. But old form's CSRF and operation never persist.
        restarted = PrivatePanelApplication(
            origin=ORIGIN,
            database_path=path,
            owner_subject="owner",
            passkey=provider,
            members=MemberEnrollmentService(db, CredentialVault(os.urandom(32))),
            commands=FakeHost(),
            events={EVENT_ID: "Partido sintético"},
        )
        status, headers, _ = _request(restarted, "/", cookie=cookie)
        assert status == 200 and "Max-Age=34560000" in headers["Set-Cookie"]
        assert _request(restarted, "/", cookie=cookie)[0] == 200  # same Chrome's next tab
        old_submit = _request(
            restarted,
            "/control/reanudar",
            method="POST",
            cookie=cookie,
            payload={"csrf": old_csrf, "operation_id": old_operation},
        )
        assert old_submit[0] == 403
        fresh_status, _, fresh_page = _request(restarted, "/", cookie=cookie)
        assert fresh_status == 200
        fresh_csrf = re.search(rb'name="csrf" value="([^\"]+)"', fresh_page).group(1).decode()
        assert fresh_csrf != old_csrf
        status, headers, _ = _request(
            restarted,
            "/salir",
            cookie=cookie,
            method="POST",
            payload={"csrf": fresh_csrf},
        )
        assert status == 200 and "Max-Age=0" in headers["Set-Cookie"]
        assert "Max-Age=34560000" not in headers["Set-Cookie"]
        assert _request(app, "/", cookie=cookie)[0] == 401
        assert _request(restarted, "/", cookie=cookie)[0] == 401
        with closing(sqlite3.connect(path.with_name("boca_owner_session.sqlite3"))) as connection:
            assert connection.execute("SELECT count(*) FROM owner_browser_session").fetchone() == (
                0,
            )


def test_global_intake_pause_resume_never_stops_http_or_existing_commands() -> None:
    clock = [0.0]
    provider, key, credential_id = _passkey(clock)
    host = FakeHost()
    with TemporaryDirectory() as directory:
        app, db = _app(Path(directory) / "boca.sqlite3", provider, host)
        member = MemberEnrollmentService(db, CredentialVault(os.urandom(32))).enroll(
            email="global@example.test",
            password="test-password",
            consent_recorded_at=datetime.now(UTC),
        )
        assert _request(app, "/control")[0] == 401
        cookie = _login(app, key, credential_id)
        assert _request(app, "/", cookie=cookie)[0] == 200
        initial = _request(app, "/control", cookie=cookie)
        assert initial[0] == 200 and b"Pausada" in initial[2]
        assert b'<nav aria-label="Secciones">' in initial[2]
        assert b'<a href="/control">Control</a>' in initial[2]
        assert b'<button type="submit">Reanudar nuevas simulaciones</button>' in initial[2]
        assert b'<p role="status">Estado: Pausada.' in initial[2]
        _, _, form = _request(app, "/comandos", cookie=cookie)
        fields = {
            "csrf": re.search(rb'name="csrf" value="([^"]+)"', form).group(1).decode(),
            "operation_id": re.search(rb'name="operation_id" value="([^"]+)"', form)
            .group(1)
            .decode(),
            "member_id": member,
            "event_id": EVENT_ID,
        }
        blocked = _request(app, "/comandos", cookie=cookie, method="POST", payload=fields)
        assert blocked[0] == 409 and host.calls == []
        started = _control_action(app, cookie, "reanudar")
        assert started[0] == 303 and started[1]["Location"] == "/control"
        assert b"Admitiendo" in _request(app, "/control", cookie=cookie)[2]
        sleep(1.05)
        accepted = _request(app, "/comandos", cookie=cookie, method="POST", payload=fields)
        assert accepted[0] == 303 and len(host.calls) == 1
        sleep(1.05)
        paused = _control_action(app, cookie, "pausar")
        assert paused[0] == 303 and paused[1]["Location"] == "/control"
        panel = _request(app, "/control", cookie=cookie)
        assert panel[0] == 200 and b"Pausada" in panel[2]
        assert b"simulaciones en curso" in panel[2]
        assert _request(app, "/", cookie=cookie)[0] == 200
        assert _request(app, "/comandos", cookie=cookie)[0] == 200
        assert _request(app, f"/comandos/{fields['operation_id']}", cookie=cookie)[0] in (
            200,
            404,
        )
        assert host.calls == [(fields["operation_id"], member, EVENT_ID)]
        another = dict(fields, operation_id=str(uuid4()))
        assert _request(app, "/comandos", cookie=cookie, method="POST", payload=another)[0] == 409


def test_global_control_rejects_unauthorized_post_and_persists_idempotent_state() -> None:
    clock = [0.0]
    provider, key, credential_id = _passkey(clock)
    with TemporaryDirectory() as directory:
        path = Path(directory) / "boca.sqlite3"
        app, db = _app(path, provider, FakeHost())
        cookie = _login(app, key, credential_id)
        _, _, form = _request(app, "/control", cookie=cookie)
        operation_id = re.search(rb'name="operation_id" value="([^"]+)"', form).group(1).decode()
        csrf = re.search(rb'name="csrf" value="([^"]+)"', form).group(1).decode()
        for origin, token in (("https://evil.example.test", csrf), (ORIGIN, "bad")):
            assert (
                _request(
                    app,
                    "/control/reanudar",
                    cookie=cookie,
                    method="POST",
                    payload={"csrf": token, "operation_id": operation_id},
                    origin=origin,
                )[0]
                == 403
            )
        assert b"Pausada" in _request(app, "/control", cookie=cookie)[2]
        assert _control_action(app, cookie, "reanudar")[0] == 303
        assert b"Admitiendo" in _request(app, "/control", cookie=cookie)[2]
        with db.connection() as connection:
            assert connection.execute(
                "SELECT action FROM audit_events WHERE action LIKE 'owner_simulation_intake_%'"
            ).fetchall() == [("owner_simulation_intake_resumed",)]
        # The restarted controller reads the durable owner decision from SQLite.
        next_provider, next_key, next_credential = _passkey(clock)
        restarted = PrivatePanelApplication(
            origin=ORIGIN,
            database_path=path,
            owner_subject="owner",
            passkey=next_provider,
            members=MemberEnrollmentService(db, CredentialVault(os.urandom(32))),
            commands=FakeHost(),
            events={EVENT_ID: "Partido sintético"},
        )
        assert _request(restarted, "/control")[0] == 401
        clock[0] = 3.0
        restart_cookie = _login(restarted, next_key, next_credential)
        assert b"Admitiendo" in _request(restarted, "/control", cookie=restart_cookie)[2]
        assert _control_action(restarted, restart_cookie, "pausar")[0] == 303
        # A new verified passkey login replaces and revokes the old browser token.
        assert _request(app, "/control", cookie=cookie)[0] == 401
        assert b"Pausada" in _request(restarted, "/control", cookie=restart_cookie)[2]
        with db.connection() as connection:
            assert connection.execute(
                "SELECT action FROM audit_events WHERE action LIKE 'owner_simulation_intake_%' "
                "ORDER BY rowid"
            ).fetchall() == [
                ("owner_simulation_intake_resumed",),
                ("owner_simulation_intake_paused",),
            ]
        # Repeated intent from the active owner causes no additional audit write.
        sleep(1.05)
        assert _control_action(restarted, restart_cookie, "pausar")[0] == 303
        with db.connection() as connection:
            assert connection.execute(
                "SELECT count(*) FROM audit_events WHERE action LIKE 'owner_simulation_intake_%'"
            ).fetchone() == (2,)
        final_provider, final_key, final_credential = _passkey(clock)
        final = PrivatePanelApplication(
            origin=ORIGIN,
            database_path=path,
            owner_subject="owner",
            passkey=final_provider,
            members=MemberEnrollmentService(db, CredentialVault(os.urandom(32))),
            commands=FakeHost(),
            events={EVENT_ID: "Partido sintético"},
        )
        clock[0] = 6.0
        final_cookie = _login(final, final_key, final_credential)
        assert b"Pausada" in _request(final, "/control", cookie=final_cookie)[2]


def test_global_control_refuses_to_claim_active_when_command_host_failed() -> None:
    clock = [0.0]
    provider, key, credential_id = _passkey(clock)
    with TemporaryDirectory() as directory:
        app, _ = _app(Path(directory) / "boca.sqlite3", provider, None)
        cookie = _login(app, key, credential_id)
        response = _control_action(app, cookie, "reanudar")
        assert response[0] == 503
        assert b"Pausada" in _request(app, "/control", cookie=cookie)[2]


def test_passkey_requires_exact_origin_uv_signature_and_one_use_challenge() -> None:
    clock = [0.0]
    provider, key, credential_id = _passkey(clock)
    first = provider.challenge()
    assert first is not None
    assert provider.challenge() is None
    invalid_origin = _assertion(key, credential_id, first, origin="https://evil.example.test")
    assert provider.verify(invalid_origin) is None
    # Failed origin does not authenticate; a new challenge requires the next budget window.
    clock[0] = 2.0
    second = provider.challenge()
    assert second is not None
    assert provider.verify(_assertion(key, credential_id, second, flags=0x01)) is None
    clock[0] = 4.0
    third = provider.challenge()
    assert third is not None
    proof = _assertion(key, credential_id, third)
    assert provider.verify(proof) is not None
    assert provider.verify(proof) is None


def test_owner_cookie_can_coexist_with_other_localhost_cookies_but_not_duplicates(
    tmp_path: Path,
) -> None:
    """A browser shares localhost cookies across ports; Boca must select its own once."""
    clock = [0.0]
    provider, key, credential_id = _passkey(clock)
    app, _ = _app(tmp_path / "boca.sqlite3", provider)
    cookie = _login(app, key, credential_id)

    # Unrelated cookies from another localhost service must not log out the owner.
    assert _request(app, "/socios", cookie=f"other_service=on; {cookie}")[0] == 200
    assert _request(app, "/socios", cookie=f"{cookie}; theme=dark")[0] == 200

    # Ambiguous, malformed or duplicated Boca credentials still fail closed.
    assert _request(app, "/socios", cookie=f"{cookie}; {cookie}")[0] == 401
    assert _request(app, "/socios", cookie=f"__Host-boca_session=broken; {cookie}")[0] == 401
    assert _request(app, "/socios", cookie="other_service=on")[0] == 401
    assert _request(app, "/socios", cookie=f"{cookie}; other={'v' * 4096}")[0] == 401
    extras = "; ".join(f"other_{index}=on" for index in range(32))
    assert _request(app, "/socios", cookie=f"{cookie}; {extras}")[0] == 401


def test_private_login_enrollment_listing_and_local_command_are_connected() -> None:
    clock = [0.0]
    provider, key, credential_id = _passkey(clock)
    host = FakeHost()
    with TemporaryDirectory() as directory:
        app, db = _app(Path(directory) / "boca.sqlite3", provider, host)
        assert _request(app, "/socios")[0] == 401
        assert _request(app, "/comandos")[0] == 401
        assert _request(app, "/avisos")[0] == 401
        cookie = _login(app, key, credential_id)
        status, _, home = _request(app, "/", cookie=cookie)
        assert status == 200 and b"Funciones no habilitadas" in home
        assert b"Backup y restauraci" in home and b"compra reales en Boca" in home
        assert b'action="/backup"' not in home and b'action="/reservar"' not in home
        status, headers, page = _request(app, "/socios/nuevo", cookie=cookie)
        assert status == 200 and headers["Cache-Control"] == "no-store"
        csrf = re.search(rb'name="csrf" value="([^"]+)"', page).group(1).decode()
        operation = re.search(rb'name="operation_id" value="([^"]+)"', page).group(1).decode()
        fields = {
            "csrf": csrf,
            "operation_id": operation,
            "alias": "Persona de prueba",
            "email": "persona@example.test",
            "password": "test-only-password",
            "consent": "yes",
        }
        assert _request(app, "/socios", cookie=cookie, method="POST", payload=fields)[0] == 201
        status, _, listing = _request(app, "/socios", cookie=cookie)
        assert status == 200 and b"Persona de prueba" in listing
        assert b"test-only-password" not in listing and b"persona@example.test" not in listing
        with db.connection() as connection:
            member_id = connection.execute("SELECT member_id FROM members").fetchone()[0]
            assert connection.execute("SELECT count(*) FROM credentials").fetchone() == (1,)
        sleep(1.05)
        assert _control_action(app, cookie, "reanudar")[0] == 303
        status, _, command_page = _request(app, "/comandos", cookie=cookie)
        assert status == 200 and b"Iniciar simulaci" in command_page
        command_id = (
            re.search(rb'name="operation_id" value="([^"]+)"', command_page).group(1).decode()
        )
        csrf = re.search(rb'name="csrf" value="([^"]+)"', command_page).group(1).decode()
        command_fields = {
            "csrf": csrf,
            "operation_id": command_id,
            "member_id": member_id,
            "event_id": EVENT_ID,
        }
        assert (
            _request(app, "/comandos", cookie=cookie, method="POST", payload=command_fields)[0]
            == 429
        )
        sleep(1.05)
        started = _request(app, "/comandos", cookie=cookie, method="POST", payload=command_fields)
        assert started[0] == 303 and started[1]["Location"] == f"/comandos/{command_id}"
        assert host.calls == [(command_id, member_id, EVENT_ID)]
        replay = _request(app, "/comandos", cookie=cookie, method="POST", payload=command_fields)
        assert replay[0] == 303 and len(host.calls) == 1
        assert _request(app, "/estado", cookie=cookie)[0] == 200
        SqliteNotificationOutbox(db).enqueue(
            NotificationRequest(uuid4(), NoticeKind.STATE_CHANGED), now=1.0
        )
        notices = _request(app, "/avisos", cookie=cookie)
        assert notices[0] == 200 and b"Aviso local" in notices[2]
        assert b"no configurado" in notices[2]
        assert b"persona@example.test" not in notices[2]


def test_new_command_key_redirects_to_existing_canonical_result() -> None:
    clock = [0.0]
    provider, key, credential_id = _passkey(clock)
    canonical = str(uuid4())

    class DeduplicatingHost(FakeHost):
        def begin(self, command_id: str, *, member_id: str, event_id: str) -> FakeCommand:
            self.calls.append((command_id, member_id, event_id))
            return FakeCommand(state="completed", command_id=canonical)

    host = DeduplicatingHost()
    with TemporaryDirectory() as directory:
        app, db = _app(Path(directory) / "boca.sqlite3", provider, host)
        member_id = MemberEnrollmentService(db, CredentialVault(os.urandom(32))).enroll(
            email="member@example.test",
            password="test-password",
            consent_recorded_at=datetime.now(UTC),
        )
        CommandStore(db).enqueue(
            canonical, TicketIntent(member_id, EVENT_ID), now=1.0, max_pending=16
        )
        cookie = _login(app, key, credential_id)
        assert _control_action(app, cookie, "reanudar")[0] == 303
        sleep(1.05)
        status, _, form = _request(app, "/comandos", cookie=cookie)
        assert status == 200
        new_id = re.search(rb'name="operation_id" value="([^"]+)"', form).group(1).decode()
        assert new_id != canonical
        fields = {
            "csrf": re.search(rb'name="csrf" value="([^"]+)"', form).group(1).decode(),
            "operation_id": new_id,
            "member_id": member_id,
            "event_id": EVENT_ID,
        }
        result = _request(app, "/comandos", cookie=cookie, method="POST", payload=fields)
        assert result[0] == 303
        assert result[1]["Location"] == f"/comandos/{canonical}"
        replay = _request(app, "/comandos", cookie=cookie, method="POST", payload=fields)
        assert replay[1]["Location"] == f"/comandos/{canonical}"
        assert host.calls == [(new_id, member_id, EVENT_ID)]
        assert _request(app, f"/comandos/{canonical}", cookie=cookie)[0] == 200
        assert _request(app, f"/comandos/{new_id}", cookie=cookie)[0] == 404


def test_malformed_command_result_never_becomes_a_redirect() -> None:
    clock = [0.0]
    provider, key, credential_id = _passkey(clock)

    class MalformedHost(FakeHost):
        def begin(self, command_id: str, *, member_id: str, event_id: str) -> FakeCommand:
            self.calls.append((command_id, member_id, event_id))
            return FakeCommand(command_id="../outside")

    host = MalformedHost()
    with TemporaryDirectory() as directory:
        app, db = _app(Path(directory) / "boca.sqlite3", provider, host)
        member_id = MemberEnrollmentService(db, CredentialVault(os.urandom(32))).enroll(
            email="member@example.test",
            password="test-password",
            consent_recorded_at=datetime.now(UTC),
        )
        cookie = _login(app, key, credential_id)
        assert _control_action(app, cookie, "reanudar")[0] == 303
        sleep(1.05)
        status, _, form = _request(app, "/comandos", cookie=cookie)
        assert status == 200
        fields = {
            "csrf": re.search(rb'name="csrf" value="([^"]+)"', form).group(1).decode(),
            "operation_id": re.search(rb'name="operation_id" value="([^"]+)"', form)
            .group(1)
            .decode(),
            "member_id": member_id,
            "event_id": EVENT_ID,
        }
        first = _request(app, "/comandos", cookie=cookie, method="POST", payload=fields)
        replay = _request(app, "/comandos", cookie=cookie, method="POST", payload=fields)
        assert first[0] == replay[0] == 503
        assert "Location" not in first[1] and "Location" not in replay[1]
        assert len(host.calls) == 1


def test_cross_origin_csrf_and_spoofed_tls_never_start_simulation() -> None:
    clock = [0.0]
    provider, key, credential_id = _passkey(clock)
    host = FakeHost()
    with TemporaryDirectory() as directory:
        app, db = _app(Path(directory) / "boca.sqlite3", provider, host)
        member_id = MemberEnrollmentService(db, CredentialVault(os.urandom(32))).enroll(
            email="member@example.test",
            password="test-password",
            consent_recorded_at=datetime.now(UTC),
        )
        cookie = _login(app, key, credential_id)
        assert _control_action(app, cookie, "reanudar")[0] == 303
        _, _, page = _request(app, "/comandos", cookie=cookie)
        fields = {
            "csrf": re.search(rb'name="csrf" value="([^"]+)"', page).group(1).decode(),
            "operation_id": re.search(rb'name="operation_id" value="([^"]+)"', page)
            .group(1)
            .decode(),
            "member_id": member_id,
            "event_id": EVENT_ID,
        }
        for extra, origin in (
            ({}, "https://evil.example.test"),
            ({"wsgi.url_scheme": "http", "HTTP_X_FORWARDED_PROTO": "https"}, ORIGIN),
            ({"QUERY_STRING": "member=test"}, ORIGIN),
        ):
            assert (
                _request(
                    app,
                    "/comandos",
                    cookie=cookie,
                    method="POST",
                    payload=fields,
                    origin=origin,
                    extra=extra,
                )[0]
                >= 400
            )
        assert (
            _request(
                app, "/comandos", cookie=cookie, method="POST", payload=dict(fields, csrf="invalid")
            )[0]
            == 403
        )
        assert host.calls == []


def test_credential_rotation_and_revocation_are_local_idempotent_and_redacted() -> None:
    clock = [0.0]
    provider, key, credential_id = _passkey(clock)
    with TemporaryDirectory() as directory:
        path = Path(directory) / "boca.sqlite3"
        db = Database(path)
        db.migrate()
        CommandStore(db).migrate()
        OwnerBrowserSessionStore(db, owner_subject="owner").migrate()
        vault = CredentialVault(os.urandom(32))
        service = MemberEnrollmentService(db, vault)
        member_id = service.enroll(
            email="member@example.test",
            password="initial-test-only",
            consent_recorded_at=datetime.now(UTC),
            display_name="<Persona>",
        )
        app = PrivatePanelApplication(
            origin=ORIGIN,
            database_path=path,
            owner_subject="owner",
            passkey=provider,
            members=service,
            commands=None,
            events={},
        )
        cookie = _login(app, key, credential_id)
        status, _, detail = _request(app, f"/socios/{member_id}", cookie=cookie)
        assert status == 200 and b"&lt;Persona&gt;" in detail and b"<Persona>" not in detail
        identifiers = re.findall(rb'name="operation_id" value="([^"]+)"', detail)
        csrf = re.search(rb'name="csrf" value="([^"]+)"', detail).group(1).decode()
        rotation = {
            "csrf": csrf,
            "operation_id": identifiers[0].decode(),
            "password": "rotated-test-only",
        }
        rotated = _request(
            app, f"/socios/{member_id}/credencial", cookie=cookie, method="POST", payload=rotation
        )
        assert rotated[0] == 303
        assert (
            _request(
                app,
                f"/socios/{member_id}/credencial",
                cookie=cookie,
                method="POST",
                payload=rotation,
            )[0]
            == 303
        )
        sealed = db.get_credential(member_id)
        assert sealed is not None and vault.open(sealed, member_id=member_id) == "rotated-test-only"
        assert b"rotated-test-only" not in rotated[2]
        sleep(1.05)
        revocation = {"csrf": csrf, "operation_id": identifiers[1].decode()}
        assert (
            _request(
                app,
                f"/socios/{member_id}/revocar",
                cookie=cookie,
                method="POST",
                payload=revocation,
            )[0]
            == 303
        )
        assert db.get_credential(member_id) is None
        assert (
            _request(
                app,
                f"/socios/{member_id}/revocar",
                cookie=cookie,
                method="POST",
                payload=revocation,
            )[0]
            == 303
        )
        status, _, page = _request(app, "/socios", cookie=cookie)
        assert status == 200 and b"Credencial revocada" in page
        assert b"member@example.test" not in page and b"initial-test-only" not in page
