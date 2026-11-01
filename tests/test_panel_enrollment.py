"""Synthetic request acceptance; no listener, network or real credentials."""

import io
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch
from urllib.parse import urlencode
from uuid import UUID

from boca_socios.panel.enrollment_http import EnrollmentApplication
from boca_socios.panel.owner_sessions import OwnerIdentity, OwnerSessions
from boca_socios.security.credential_vault import CredentialVault
from boca_socios.security.enrollment import MemberEnrollmentService
from boca_socios.storage.database import Database

ORIGIN = "https://boca.example.test"


def _request(
    app: EnrollmentApplication,
    cookie: str,
    *,
    method: str = "GET",
    path: str = "/socios/nuevo",
    fields: dict[str, str] | None = None,
    overrides: dict[str, object] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    payload = urlencode(fields or {}).encode()
    environ: dict[str, object] = {
        "wsgi.url_scheme": "https",
        "HTTP_HOST": "boca.example.test",
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "HTTP_COOKIE": cookie,
        "CONTENT_LENGTH": str(len(payload)) if method == "POST" else "0",
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
        "HTTP_ORIGIN": ORIGIN if method == "POST" else "",
        "wsgi.input": io.BytesIO(payload),
    }
    environ.update(overrides or {})
    captured: list[tuple[str, list[tuple[str, str]]]] = []

    def start(status: str, headers: list[tuple[str, str]]) -> None:
        captured.append((status, headers))

    body = b"".join(app(environ, start))
    status, headers = captured[0]
    return int(status.split()[0]), dict(headers), body


def _sessions(clock: list[float] | None = None) -> tuple[OwnerSessions, str]:
    sessions = OwnerSessions(
        owner_subject="owner",
        verify_owner=lambda _: OwnerIdentity("owner", frozenset({"members:enroll"})),
        clock=(lambda: clock[0]) if clock is not None else None,
        idle_timeout=timedelta(minutes=15),
        absolute_timeout=timedelta(hours=8),
    )
    issued = sessions.authenticate("synthetic-proof")
    assert issued is not None
    assert "; Secure" in issued and "; HttpOnly" in issued and "; SameSite=Strict" in issued
    assert "Domain=" not in issued
    return sessions, issued.split(";", 1)[0]


def _form(app: EnrollmentApplication, cookie: str) -> dict[str, str]:
    status, headers, body = _request(app, cookie)
    assert status == 200
    assert headers["Cache-Control"] == "no-store"
    html = body.decode()
    assert 'for="email"' in html and 'for="password"' in html and 'for="alias"' in html
    assert 'type="password"' in html and 'role="status"' in html
    assert "Agregar socio" in html and "consentimiento" in html
    return {
        "csrf": re.search(r'name="csrf" value="([A-Za-z0-9_-]+)"', html).group(1),
        "operation_id": re.search(r'name="operation_id" value="([a-f0-9-]+)"', html).group(1),
        "alias": "Socio sintético",
        "email": "persona@example.test",
        "password": "synthetic-private-value",
        "consent": "yes",
    }


def test_default_authentication_denies_and_tokens_are_rotated() -> None:
    assert OwnerSessions(owner_subject="owner").authenticate("anything") is None
    sessions, cookie = _sessions()
    another = sessions.authenticate("synthetic-proof")
    assert another is not None and not another.startswith(cookie + ";")
    for identity in (None, "owner", OwnerIdentity("other", frozenset({"members:enroll"}))):
        denied = OwnerSessions(owner_subject="owner", verify_owner=lambda _, x=identity: x)
        assert denied.authenticate("proof") is None


def test_form_to_enrollment_is_encrypted_atomic_and_retry_idempotent() -> None:
    with TemporaryDirectory() as directory:
        db = Database(Path(directory) / "boca.sqlite3")
        db.migrate()
        vault = CredentialVault(os.urandom(32))
        sessions, cookie = _sessions()
        app = EnrollmentApplication(MemberEnrollmentService(db, vault), sessions, origin=ORIGIN)
        fields = _form(app, cookie)
        first = _request(app, cookie, method="POST", path="/socios", fields=fields)
        second = _request(app, cookie, method="POST", path="/socios", fields=fields)
        assert first[0] == second[0] == 201
        assert first[2] == second[2]
        result = json.loads(first[2])
        member_id = result["member_id"]
        assert str(UUID(member_id)) == member_id
        assert b"synthetic-private-value" not in first[2]
        assert b"persona@" not in first[2]
        with db.connection() as connection:
            assert connection.execute("SELECT count(*) FROM members").fetchone() == (1,)
            assert connection.execute("SELECT count(*) FROM credentials").fetchone() == (1,)
            assert connection.execute("SELECT count(*) FROM audit_events").fetchone() == (1,)
        credential = db.get_credential(member_id)
        assert credential is not None
        assert vault.open(credential, member_id=member_id) == fields["password"]
        altered = dict(fields, email="changed@example.test")
        assert _request(app, cookie, method="POST", path="/socios", fields=altered)[0] == 409


def test_unauthenticated_or_expired_request_never_reads_body_or_calls_service() -> None:
    class NoRead:
        def read(self, size: int) -> bytes:
            raise AssertionError("unauthenticated body read")

    class NoEnroll:
        def enroll(self, **kwargs: object) -> str:
            raise AssertionError("unauthenticated write")

    clock = [0.0]
    sessions, cookie = _sessions(clock)
    app = EnrollmentApplication(NoEnroll(), sessions, origin=ORIGIN)
    fields = _form(app, cookie)
    clock[0] = 901
    for invalid_cookie in ("", cookie, cookie + "; " + cookie):
        status, _, body = _request(
            app,
            invalid_cookie,
            method="POST",
            path="/socios",
            fields=fields,
            overrides={"wsgi.input": NoRead()},
        )
        assert status == 401 and b"synthetic-private-value" not in body


def test_origin_csrf_limits_and_missing_consent_fail_before_write() -> None:
    class NoEnroll:
        def enroll(self, **kwargs: object) -> str:
            raise AssertionError("invalid request wrote")

    sessions, cookie = _sessions()
    app = EnrollmentApplication(NoEnroll(), sessions, origin=ORIGIN)
    fields = _form(app, cookie)
    for overrides in (
        {"HTTP_ORIGIN": "https://other.example.test"},
        {"HTTP_ORIGIN": ""},
        {"HTTP_HOST": "other.example.test"},
        {"CONTENT_LENGTH": "20000"},
        {"HTTP_TRANSFER_ENCODING": "chunked"},
        {"CONTENT_TYPE": "application/json"},
        {"QUERY_STRING": "password=synthetic"},
        {"wsgi.url_scheme": "http", "HTTP_X_FORWARDED_PROTO": "https"},
    ):
        assert (
            _request(
                app, cookie, method="POST", path="/socios", fields=fields, overrides=overrides
            )[0]
            >= 400
        )
    for changes in ({"csrf": "wrong"}, {"consent": "no"}, {"operation_id": "arbitrary"}):
        assert (
            _request(app, cookie, method="POST", path="/socios", fields=dict(fields, **changes))[0]
            >= 400
        )


def test_service_errors_are_redacted_and_not_retried() -> None:
    class Failed:
        calls = 0

        def enroll(self, **kwargs: object) -> str:
            self.calls += 1
            raise RuntimeError("synthetic-private-value persona@example.test /private/db")

    sessions, cookie = _sessions()
    service = Failed()
    app = EnrollmentApplication(service, sessions, origin=ORIGIN)
    fields = _form(app, cookie)
    for _ in range(2):
        status, _, body = _request(app, cookie, method="POST", path="/socios", fields=fields)
        assert status == 503
        assert b"synthetic-private-value" not in body and b"/private" not in body
    assert service.calls == 1


def test_session_expiration_is_absolute_and_logout_invalidates() -> None:
    clock = [0.0]
    sessions, cookie = _sessions(clock)
    for moment in range(1, 28800, 600):
        clock[0] = float(moment)
        assert sessions.lookup(cookie) is not None
    clock[0] = 28801
    assert sessions.lookup(cookie) is None
    fresh = sessions.authenticate("synthetic-proof")
    assert fresh is not None
    cookie = fresh.split(";", 1)[0]
    sessions.revoke(cookie)
    assert sessions.lookup(cookie) is None


def test_no_time_driven_form_erasure_or_secret_echo() -> None:
    sessions, cookie = _sessions()
    app = EnrollmentApplication(None, sessions, origin=ORIGIN)
    _, _, body = _request(app, cookie)
    assert b"setTimeout" not in body and b"setInterval" not in body
    assert b"localStorage" not in body and b"sessionStorage" not in body
    assert b"textContent" in body and b"fetch(" in body
    assert b"password.value = ''" in body
    assert b"alias.value = ''" not in body and b"email.value = ''" not in body


def test_concurrent_same_operation_calls_enrollment_once() -> None:
    entered, released = Event(), Event()

    class WaitingService:
        calls = 0

        def enroll(self, **kwargs: object) -> str:
            self.calls += 1
            entered.set()
            assert released.wait(5)
            return "338792d2-1f1a-48a2-93c8-315daed320ef"

    sessions, cookie = _sessions()
    service = WaitingService()
    app = EnrollmentApplication(service, sessions, origin=ORIGIN)
    fields = _form(app, cookie)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_request, app, cookie, method="POST", path="/socios", fields=fields)
        assert entered.wait(5)
        try:
            second = _request(app, cookie, method="POST", path="/socios", fields=fields)
            assert second[0] == 409 and service.calls == 1
        finally:
            released.set()
        assert first.result()[0] == 201
    assert _request(app, cookie, method="POST", path="/socios", fields=fields)[0] == 201
    assert service.calls == 1


def test_duplicate_fields_and_oversized_values_fail_without_enrollment() -> None:
    sessions, cookie = _sessions()
    app = EnrollmentApplication(None, sessions, origin=ORIGIN)
    fields = _form(app, cookie)
    for field, value in (
        ("alias", "a" * 201),
        ("email", "a" * 255),
        ("password", "x" * 4097),
        ("consent", ""),
    ):
        assert (
            _request(
                app, cookie, method="POST", path="/socios", fields=dict(fields, **{field: value})
            )[0]
            == 422
        )
    body = (urlencode(fields) + "&email=other%40example.test").encode()
    assert (
        _request(
            app,
            cookie,
            method="POST",
            path="/socios",
            fields=fields,
            overrides={"CONTENT_LENGTH": str(len(body)), "wsgi.input": io.BytesIO(body)},
        )[0]
        == 400
    )


def test_expired_and_revoked_session_cannot_resume_reserved_form() -> None:
    clock = [0.0]
    sessions, cookie = _sessions(clock)
    session = sessions.lookup(cookie)
    assert session is not None
    operation_id = sessions.new_operation(session)
    assert operation_id is not None
    sessions.revoke(cookie)
    assert sessions.new_operation(session) is None
    assert sessions.reserve(session, operation_id, session.csrf, b"synthetic")[0] == 401


def test_form_and_session_count_are_bounded() -> None:
    sessions, cookie = _sessions()
    session = sessions.lookup(cookie)
    assert session is not None
    for _ in range(16):
        assert sessions.new_operation(session) is not None
    assert sessions.new_operation(session) is None
    for _ in range(31):
        assert sessions.authenticate("synthetic-proof") is not None
    assert sessions.authenticate("synthetic-proof") is None


def test_internal_provider_failure_never_escapes_request_boundary() -> None:
    sessions, cookie = _sessions()
    app = EnrollmentApplication(None, sessions, origin=ORIGIN)

    def failed_operation(session: object) -> None:
        raise RuntimeError("synthetic-secret-in-provider-error")

    with patch.object(sessions, "new_operation", side_effect=failed_operation):
        status, _, body = _request(app, cookie)
        assert status == 503 and b"synthetic-secret" not in body
