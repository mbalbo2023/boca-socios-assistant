"""Owner-only lifecycle request UI: no local worker, Docker or website action."""

import re
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep
from uuid import uuid4

import pytest

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


def _bot_fields(page: bytes, action: str) -> dict[str, str]:
    form = re.search(
        rb'<form method="post" action="/control/bot/' + action.encode() + rb'">(.*?)</form>',
        page,
        re.S,
    )
    assert form is not None
    return {
        key.decode(): value.decode()
        for key, value in re.findall(rb'name="(csrf|operation_id)" value="([^"]+)"', form[1])
    }


def test_one_touch_commit_precedes_wake_and_stop_can_follow_immediately(tmp_path: Path) -> None:
    received = []
    provider, key, credential_id = _passkey([0.0])

    def observe(operation: str) -> None:
        with db.connection() as conn:
            received.append(
                conn.execute(
                    "SELECT action FROM audit_events WHERE audit_id=?", (operation,)
                ).fetchone()[0]
            )

    app, db = _app(tmp_path / "boca.sqlite3", provider, FakeHost(), bot_control=observe)
    cookie = _login(app, key, credential_id)
    _, _, home = _request(app, "/", cookie=cookie)
    assert b"Iniciar bot" in home and b"Detener bot" in home
    assert b"Pausar o reanudar nuevas simulaciones" not in home
    _, _, page = _request(app, "/control", cookie=cookie)
    assert b"Iniciar bot" in page and b"Detener bot" in page
    assert b"/control/chromium/" not in page
    start = _bot_fields(page, "iniciar")
    stop = _bot_fields(page, "detener")
    assert start["operation_id"] != stop["operation_id"]
    for action, fields in (("iniciar", start), ("detener", stop)):
        status, headers, _ = _request(
            app, f"/control/bot/{action}", cookie=cookie, method="POST", payload=fields
        )
        assert status == 303 and headers["Location"] == "/control"
    assert received == [
        "owner_lifecycle_v1_request_bot_start",
        "owner_lifecycle_v1_request_bot_stop",
    ]
    assert b"Pendiente" in _request(app, "/control", cookie=cookie)[2]


def test_unavailable_lifecycle_keeps_other_home_sections_reachable(tmp_path: Path) -> None:
    provider, key, credential_id = _passkey([0.0])
    app, db = _app(tmp_path / "boca.sqlite3", provider, FakeHost(), bot_control=lambda _: None)
    cookie = _login(app, key, credential_id)
    with db.connection() as conn, conn:
        conn.execute(
            "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
            (str(uuid4()), "owner_lifecycle_v1_unknown"),
        )
    code, _, home = _request(app, "/", cookie=cookie)
    assert code == 200 and b"Control del bot no disponible" in home and b'href="/socios"' in home
    assert b"/control/bot/iniciar" not in home
    assert _request(app, "/control", cookie=cookie)[0] == 503


def test_historical_legacy_ack_cannot_enable_admission_or_appear_as_current_profile(
    tmp_path: Path,
) -> None:
    from boca_socios.panel.lifecycle_intents import LifecycleIntentStore

    provider, key, credential_id = _passkey([0.0])
    wakes: list[str] = []
    app, db = _app(tmp_path / "boca.sqlite3", provider, FakeHost(), bot_control=wakes.append)
    old = str(uuid4())
    LifecycleIntentStore(db).request("bot", "start", old)
    for phase in ("CLAIMED", "APPLIED"):
        with db.connection() as conn, conn:
            conn.execute(
                "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
                host_marker(old, "bot", "start", phase),
            )
    cookie = _login(app, key, credential_id)
    assert not app._read_intake()
    _, _, page = _request(app, "/control", cookie=cookie)
    assert b"perfil bajo demanda" in page and old.encode() not in page
    assert _lifecycle_action(app, cookie, "bot", "start")[0] == 303
    assert len(wakes) == 1 and wakes[0] != old


def test_lost_wake_is_recoverable_by_owner_without_creating_a_second_intent(tmp_path: Path) -> None:
    operations = []
    provider, key, credential_id = _passkey([0.0])

    def notify(operation: str) -> None:
        operations.append(operation)
        if len(operations) == 1:
            raise OSError("private-transport-sentinel")

    app, db = _app(tmp_path / "boca.sqlite3", provider, FakeHost(), bot_control=notify)
    cookie = _login(app, key, credential_id)
    status, _, body = _lifecycle_action(app, cookie, "bot", "start")
    assert status == 503 and b"guardada" in body and b"private-transport-sentinel" not in body
    sleep(1.05)
    assert _lifecycle_action(app, cookie, "bot", "start")[0] == 303
    assert len(operations) == 2 and operations[0] == operations[1]
    with db.connection() as conn:
        assert conn.execute(
            "SELECT count(*) FROM audit_events WHERE action LIKE 'owner_lifecycle_v1_request_%'"
        ).fetchone() == (1,)


def test_retry_of_identical_failed_post_wakes_its_exact_committed_request_once(
    tmp_path: Path,
) -> None:
    operations = []
    provider, key, credential_id = _passkey([0.0])

    def notify(operation: str) -> None:
        operations.append(operation)
        if len(operations) == 1:
            raise ConnectionError

    app, _ = _app(tmp_path / "boca.sqlite3", provider, FakeHost(), bot_control=notify)
    cookie = _login(app, key, credential_id)
    _, _, page = _request(app, "/control", cookie=cookie)
    fields = _bot_fields(page, "iniciar")

    def submit():
        return _request(app, "/control/bot/iniciar", cookie=cookie, method="POST", payload=fields)[
            0
        ]

    assert submit() == 503
    assert submit() == 503 and operations == [fields["operation_id"]]
    sleep(1.05)
    assert submit() == 303 and operations == [fields["operation_id"]] * 2
    assert submit() == 303 and len(operations) == 2


@pytest.mark.parametrize(
    ("phase", "label"), [("FAILED", "Fallo confirmado"), ("UNCERTAIN", "Resultado incierto")]
)
def test_confirmed_failure_and_unknown_result_are_different_owner_states(
    tmp_path: Path, phase: str, label: str
) -> None:
    operations: list[str] = []
    provider, key, credential_id = _passkey([0.0])
    app, db = _app(tmp_path / "boca.sqlite3", provider, FakeHost(), bot_control=operations.append)
    cookie = _login(app, key, credential_id)
    assert _lifecycle_action(app, cookie, "bot", "start")[0] == 303
    for marker in ("CLAIMED", phase):
        with db.connection() as conn, conn:
            conn.execute(
                "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
                host_marker(operations[0], "bot", "start", marker),
            )
    _, _, page = _request(app, "/control", cookie=cookie)
    assert b'aria-live="polite"' in page and label.encode() in page
    assert b"<summary>Identificador de solicitud</summary>" in page
    assert b"<code>" + operations[0].encode() + b"</code>" in page


def test_on_demand_denies_unauthenticated_foreign_or_separate_chromium_orders(
    tmp_path: Path,
) -> None:
    operations: list[str] = []
    provider, key, credential_id = _passkey([0.0])
    app, db = _app(tmp_path / "boca.sqlite3", provider, FakeHost(), bot_control=operations.append)
    assert _request(app, "/control/bot/iniciar", method="POST")[0] == 401
    cookie = _login(app, key, credential_id)
    _, _, page = _request(app, "/control", cookie=cookie)
    fields = _bot_fields(page, "iniciar")
    assert (
        _request(
            app,
            "/control/bot/iniciar",
            cookie=cookie,
            method="POST",
            payload=fields,
            origin="https://invalid.test",
        )[0]
        == 403
    )
    assert (
        _request(
            app,
            "/control/bot/iniciar",
            cookie=cookie,
            method="POST",
            payload={**fields, "csrf": "bad"},
        )[0]
        == 403
    )
    assert (
        _request(app, "/control/chromium/iniciar", cookie=cookie, method="POST", payload=fields)[0]
        == 404
    )
    assert operations == []
    with db.connection() as conn:
        assert conn.execute(
            "SELECT count(*) FROM audit_events WHERE action LIKE 'owner_lifecycle_v1_request_%'"
        ).fetchone() == (0,)


def test_refresh_and_duplicate_start_preserve_the_single_active_run(tmp_path: Path) -> None:
    operations: list[str] = []
    provider, key, credential_id = _passkey([0.0])
    app, db = _app(tmp_path / "boca.sqlite3", provider, FakeHost(), bot_control=operations.append)
    cookie = _login(app, key, credential_id)
    for _ in range(24):
        status, _, page = _request(app, "/control", cookie=cookie)
        assert status == 200
    fields = _bot_fields(page, "iniciar")
    post = {"cookie": cookie, "method": "POST", "payload": fields}
    assert _request(app, "/control/bot/iniciar", **post)[0] == 303
    assert _request(app, "/control/bot/iniciar", **post)[0] == 303
    assert len(operations) == 1
    for status in ("CLAIMED", "APPLIED"):
        with db.connection() as conn, conn:
            conn.execute(
                "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
                host_marker(operations[0], "bot", "start", status),
            )
    sleep(1.05)
    assert _lifecycle_action(app, cookie, "bot", "start")[0] == 303
    assert len(operations) == 1
    with db.connection() as conn:
        assert conn.execute(
            "SELECT audit_id FROM audit_events WHERE action='owner_lifecycle_v1_request_bot_start'"
        ).fetchall() == [(operations[0],)]
