"""Owner-only lifecycle request UI: no local worker, Docker or website action."""

import re
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep
from uuid import uuid4

from boca_socios.panel.lifecycle_intents import host_marker
from boca_socios.panel.private_http import PrivatePanelApplication
from test_private_beta_panel import (
    ORIGIN,
    FakeHost,
    _app,
    _login,
    _passkey,
    _request,
)


def _lifecycle_action(
    app: PrivatePanelApplication,
    cookie: str,
    component: str,
    target: str,
    *,
    csrf: str | None = None,
    origin: str = ORIGIN,
) -> tuple[int, dict[str, str], bytes]:
    code, _headers, page = _request(app, "/control", cookie=cookie)
    assert code == 200
    pattern = (
        rb'<form method="post" action="/control/'
        + component.encode()
        + b"/"
        + (b"iniciar" if target == "start" else b"detener")
        + rb'">(.*?)</form>'
    )
    form = re.search(pattern, page, re.S)
    assert form is not None
    fields = {
        "csrf": csrf
        if csrf is not None
        else re.search(rb'name="csrf" value="([^"]+)"', form.group(1)).group(1).decode(),
        "operation_id": re.search(rb'name="operation_id" value="([^"]+)"', form.group(1))
        .group(1)
        .decode(),
    }
    path = "/control/" + component + "/" + ("iniciar" if target == "start" else "detener")
    return _request(app, path, cookie=cookie, method="POST", payload=fields, origin=origin)


def test_owner_controls_are_accessible_requests_not_fake_operational_ack() -> None:
    provider, key, credential_id = _passkey([0.0])
    with TemporaryDirectory() as directory:
        host = FakeHost()
        app, db = _app(Path(directory) / "boca.sqlite3", provider, host)
        assert _request(app, "/control/bot/iniciar")[0] == 401
        cookie = _login(app, key, credential_id)
        code, _headers, page = _request(app, "/control", cookie=cookie)
        assert code == 200
        assert b"Solicitar inicio del motor del bot" in page
        assert b"Solicitar detenci" in page
        assert b"Solicitar inicio de Chromium" in page
        assert b"Solicitar detenci\xc3\xb3n de Chromium" in page
        assert b"No hay confirmaci\xc3\xb3n de inicio o parada" in page
        result = _lifecycle_action(app, cookie, "bot", "start")
        assert result[0] == 303 and result[1]["Location"] == "/control"
        code, headers, page = _request(app, "/control", cookie=cookie)
        assert code == 200 and headers["Cache-Control"] == "no-store"
        assert b"PENDIENTE" in page and b"Sin confirmaci\xc3\xb3n del host" in page
        assert host.calls == []
        with db.connection() as connection:
            assert connection.execute(
                "SELECT action FROM audit_events WHERE action LIKE 'owner_lifecycle_v1_%'"
            ).fetchall() == [("owner_lifecycle_v1_request_bot_start",)]
        sleep(1.05)  # Existing per-session write budget; not a lifecycle bypass.
        assert _lifecycle_action(app, cookie, "chromium", "start")[0] == 409
        assert _request(app, "/", cookie=cookie)[0] == 200


def test_lifecycle_routes_require_owner_passkey_origin_csrf_and_exact_post() -> None:
    provider, key, credential_id = _passkey([0.0])
    with TemporaryDirectory() as directory:
        app, db = _app(Path(directory) / "boca.sqlite3", provider, FakeHost())
        cookie = _login(app, key, credential_id)
        assert _request(app, "/control/bot/iniciar", cookie=cookie)[0] == 404
        assert (
            _lifecycle_action(app, cookie, "bot", "start", origin="https://evil.example.test")[0]
            == 403
        )
        assert _lifecycle_action(app, cookie, "bot", "start", csrf="bad")[0] == 403
        assert _lifecycle_action(app, cookie, "bot", "start")[0] == 303
        with db.connection() as connection:
            assert connection.execute(
                "SELECT count(*) FROM audit_events WHERE action LIKE 'owner_lifecycle_v1_%'"
            ).fetchone() == (1,)
        assert (
            _request(
                app,
                "/control/bot/detener",
                cookie=cookie,
                method="POST",
                payload={"csrf": "bad", "operation_id": str(uuid4())},
            )[0]
            == 403
        )


def test_persistent_host_ack_is_visible_only_after_exact_claim_and_receipt() -> None:
    provider, key, credential_id = _passkey([0.0])
    with TemporaryDirectory() as directory:
        app, db = _app(Path(directory) / "boca.sqlite3", provider, FakeHost())
        cookie = _login(app, key, credential_id)
        assert _lifecycle_action(app, cookie, "chromium", "stop")[0] == 303
        with db.connection() as connection:
            request_id = connection.execute(
                "SELECT audit_id FROM audit_events "
                "WHERE action='owner_lifecycle_v1_request_chromium_stop'"
            ).fetchone()[0]
        for status in ("CLAIMED", "APPLIED"):
            with db.connection() as connection, connection:
                connection.execute(
                    "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
                    host_marker(request_id, "chromium", "stop", status),
                )
        code, _headers, page = _request(app, "/control", cookie=cookie)
        assert code == 200
        assert b"CONFIRMADA" in page
        assert b"recibo protegido" in page
        sleep(1.05)
        assert _lifecycle_action(app, cookie, "bot", "stop")[0] == 303
        assert b"PENDIENTE" in _request(app, "/control", cookie=cookie)[2]
