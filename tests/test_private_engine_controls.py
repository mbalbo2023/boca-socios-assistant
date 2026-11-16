"""Real passkey/CSRF routes fence the new independent engine controls."""

import json
import re
from types import SimpleNamespace
from uuid import uuid4

import pytest

from boca_socios.panel.private_http import PrivatePanelApplication
from test_private_beta_panel import PERMISSIONS, FakeHost, _app, _login, _passkey, _request


class Engines:
    def __init__(self):
        self.calls = []

    def snapshot(self):
        return {
            "version": 1,
            "context_limit": 50,
            "observed_at": "2026-11-15T00:00:00Z",
            "engines": [],
        }

    def start(self, engine, operation_id, *, member_id, counts):
        self.calls.append((engine, operation_id, member_id, counts))
        return SimpleNamespace(activation_id=operation_id)

    def private_details(self, session_id, *, owner_authenticated):
        assert owner_authenticated is True
        return None


def panel(tmp_path, monkeypatch, *, permissions=PERMISSIONS):
    provider, key, credential = _passkey([0.0], permissions=permissions)
    legacy, db = _app(tmp_path / "boca.sqlite3", provider, FakeHost())
    engines = Engines()
    app = PrivatePanelApplication(
        origin=legacy._origin,
        database_path=db.path,
        owner_subject="owner",
        passkey=provider,
        members=legacy._members,
        commands=legacy._commands,
        events=legacy._events,
        bot_control=lambda _: None,
        engine_control=engines,
    )
    monkeypatch.setattr(app, "_site_url_ready", lambda: True)
    return app, engines, _login(app, key, credential)


def test_independent_route_has_own_csrf_scope_and_only_dispatches_chosen_engine(
    tmp_path, monkeypatch
):
    app, engines, cookie = panel(tmp_path, monkeypatch)
    assert _request(app, "/control/motores.json")[0] == 401
    code, _headers, body = _request(app, "/control", cookie=cookie)
    assert code == 200
    form = re.search(
        rb'<form[^>]+action="/control/motores/queues_tokens/iniciar"[^>]*>(.*?)</form>', body, re.S
    )
    assert form is not None
    fields = dict(
        (name.decode(), value.decode())
        for name, value in re.findall(rb'name="([^"]+)"[^>]*value="([^"]*)"', form[1])
    )
    fields.update(chromium="3", firefox="1", webkit="1")
    fields.pop("member_id", None)
    path = "/control/motores/queues_tokens/iniciar"
    assert (
        _request(
            app, path, cookie=cookie, method="POST", payload=fields, origin="https://wrong.invalid"
        )[0]
        == 403
    )
    assert engines.calls == []
    assert (
        _request(app, path, cookie=cookie, method="POST", payload=fields, origin=app._origin)[0]
        == 303
    )
    assert engines.calls == [
        ("queues_tokens", fields["operation_id"], None, {"chromium": 3, "firefox": 1, "webkit": 1})
    ]
    # Reusing A's consumed operation on B must not invoke B.
    fields["member_id"] = str(uuid4())
    assert _request(
        app,
        "/control/motores/browsers_members/iniciar",
        cookie=cookie,
        method="POST",
        payload=fields,
        origin=app._origin,
    )[0] in {403, 409, 429}
    assert len(engines.calls) == 1


def test_metadata_and_inspection_routes_require_owner_and_do_not_start_work(tmp_path, monkeypatch):
    app, engines, cookie = panel(tmp_path, monkeypatch)
    code, headers, raw = _request(app, "/control/motores.json", cookie=cookie)
    assert code == 200 and headers["Cache-Control"] == "no-store"
    assert json.loads(raw)["context_limit"] == 50
    assert _request(app, "/control/sesiones/" + str(uuid4()), cookie=cookie)[0] == 404
    assert _request(app, "/control/sesiones/" + str(uuid4()))[0] == 401
    assert engines.calls == []


def test_owner_token_monitor_redirects_to_activity_without_allocating_operations(
    tmp_path, monkeypatch
):
    app, engines, cookie = panel(tmp_path, monkeypatch)
    monkeypatch.setattr(
        app._sessions, "new_operation", lambda *a, **k: pytest.fail("GET allocated")
    )
    assert _request(app, "/monitor/tokens")[0] == 401
    code, headers, page = _request(app, "/monitor/tokens", cookie=cookie)
    assert code == 303 and headers["Location"] == "/control/actividad"
    assert headers["Cache-Control"] == "no-store"
    assert page == b""
    code, headers, page = _request(app, "/control/actividad", cookie=cookie)
    assert code == 200 and headers["Cache-Control"] == "no-store"
    assert b"/control/actividad.json" in page
    assert b'action="/control/motores/' not in page
    assert _request(app, "/monitor/tokens.json", cookie=cookie)[0] == 200
    assert engines.calls == []


@pytest.mark.parametrize("path", ["/", "/control"])
def test_control_aliases_keep_controls_and_three_primary_navigation_links(
    tmp_path, monkeypatch, path
):
    app, engines, cookie = panel(tmp_path, monkeypatch)
    guest_status, _, guest = _request(app, path)
    assert guest_status == 200
    assert b"<form" not in guest and b"operation_id" not in guest
    code, _, page = _request(app, path, cookie=cookie)
    assert code == 200
    assert b'action="/control/motores/queues_tokens/iniciar"' in page
    primary = re.search(rb'<nav aria-label="Principal">(.*?)</nav>', page, re.S)
    assert primary is not None
    assert re.findall(rb'href="([^"]+)"[^>]*>([^<]+)</a>', primary[1]) == [
        (b"/control", b"Control"),
        (b"/control/actividad", b"Actividad"),
        (b"/configuracion", "Configuración".encode()),
    ]
    secondary = re.search(rb'<nav aria-label="Otras funciones">(.*?)</nav>', page, re.S)
    assert secondary is not None
    assert b"Otras funciones" in secondary.group(1)
    assert "Más secciones".encode() not in page
    for target in (
        b"/socios",
        b"/comandos",
        b"/telegram",
        b"/estado",
        b"/avisos",
        b"/avisos-oficiales",
        b"/monitor/tokens",
    ):
        assert secondary[1].count(b'href="' + target + b'"') == 1
    assert engines.calls == []


def test_reader_token_monitor_keeps_legacy_view_and_owner_routes_stay_forbidden(
    tmp_path, monkeypatch
):
    app, engines, cookie = panel(
        tmp_path, monkeypatch, permissions=frozenset({"members:enroll", "local-status:read"})
    )
    monkeypatch.setattr(
        app._sessions, "new_operation", lambda *a, **k: pytest.fail("GET allocated")
    )
    code, headers, page = _request(app, "/monitor/tokens", cookie=cookie)
    assert code == 200 and headers["Cache-Control"] == "no-store"
    assert b"Monitor de tokens" in page and b"Queue-it" in page
    assert b'action="/monitor/tokens/revelar"' not in page
    assert _request(app, "/monitor/tokens.json", cookie=cookie)[0] == 200
    for path in (
        "/control",
        "/control/actividad",
        "/control/actividad.json",
        "/control/motores.json",
    ):
        assert _request(app, path, cookie=cookie)[0] == 403
    assert _request(app, "/monitor/tokens/revelar", cookie=cookie, method="POST")[0] == 403
    assert engines.calls == []


def test_login_keeps_passkey_without_private_navigation(tmp_path):
    provider, _, _ = _passkey([0.0])
    app, _ = _app(tmp_path / "boca.sqlite3", provider, FakeHost())
    code, headers, page = _request(app, "/ingresar")
    assert code == 200 and b'id="passkey"' in page
    assert b"data-challenge=" in page and b"navigator.credentials.get" in page
    assert b"<nav" not in page
    assert b'href="/control"' not in page and b'href="/configuracion"' not in page
    assert "'sha256-" in headers["Content-Security-Policy"]


def test_live_activity_html_keeps_timeline_with_real_engine_coordinator(tmp_path):
    from boca_socios.integration.engine_sessions import EngineSessionCoordinator
    from test_engine_session_coordinator import prepared_store

    db, _vault, _member, store = prepared_store(tmp_path)
    provider, key, credential = _passkey([0.0])
    legacy, _ = _app(db.path, provider, FakeHost())
    wakes = []
    engines = EngineSessionCoordinator(store=store, wake=wakes.append)
    app = PrivatePanelApplication(
        origin=legacy._origin,
        database_path=db.path,
        owner_subject="owner",
        passkey=provider,
        members=legacy._members,
        commands=legacy._commands,
        events=legacy._events,
        bot_control=wakes.append,
        engine_control=engines,
    )
    cookie = _login(app, key, credential)
    try:
        guest_status, _, guest = _request(app, "/control/actividad")
        assert guest_status == 200
        assert b"/control/actividad.json" not in guest
        assert b"<form" not in guest
        code, headers, page = _request(app, "/control/actividad", cookie=cookie)
        assert code == 200 and headers["Cache-Control"] == "no-store"
        assert b"Actividad del worker y Chromium" in page
        assert b"Pausar actualizaciones" in page
        assert b"/control/actividad.json" in page
        assert b"/control/motores.json" in page
        assert b'action="/control/motores/' not in page
        assert _request(app, "/control/actividad.json", cookie=cookie)[0] == 200
        code, alias_headers, _ = _request(app, "/monitor/tokens", cookie=cookie)
        assert code == 303 and alias_headers["Location"] == "/control/actividad"
        assert wakes == []
    finally:
        engines.close()


def test_session_reveal_form_keeps_origin_and_secret_requires_one_owner_post(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from boca_socios.browser.engine_protocol import EngineIdentity, SessionInspection
    from boca_socios.integration.engine_sessions import PrivateSessionDetails

    app, engines, cookie = panel(tmp_path, monkeypatch)
    identity = EngineIdentity("queues_tokens", str(uuid4()), 1, str(uuid4()), "chromium")
    private_url = "https://offline.example.invalid/path?secret=copy-only-after-post"
    details = PrivateSessionDetails(
        identity,
        None,
        SessionInspection(final_url=private_url, observed_at=datetime.now(UTC), context_open=True),
        None,
        "ACTIVE",
        "PREQUEUE",
    )
    monkeypatch.setattr(engines, "private_details", lambda *a, **k: details)
    code, headers, page = _request(app, "/control/sesiones/" + identity.session_id, cookie=cookie)
    assert code == 200 and headers["Referrer-Policy"] == "same-origin"
    assert b"copy-only-after-post" not in page
    fields = dict(
        (key.decode(), value.decode())
        for key, value in re.findall(rb'name="([^"]+)"[^>]*value="([^"]*)"', page)
    )
    code, headers, page = _request(
        app,
        "/control/sesiones/revelar",
        cookie=cookie,
        method="POST",
        payload=fields,
        origin=app._origin,
    )
    assert code == 200 and private_url.encode() in page
    assert headers["Referrer-Policy"] == "no-referrer"
    assert (
        _request(
            app,
            "/control/sesiones/revelar",
            cookie=cookie,
            method="POST",
            payload=fields,
            origin=app._origin,
        )[0]
        == 409
    )
    assert engines.calls == []


@pytest.mark.parametrize("legacy_status", ["APPLIED", "FAILED", "UNCERTAIN"])
def test_authenticated_legacy_recovery_reuses_stop_and_requires_real_receipt(
    tmp_path, monkeypatch, legacy_status
):
    from boca_socios.integration.engine_sessions import EngineSessionCoordinator
    from boca_socios.panel.lifecycle_intents import LifecycleIntentStore
    from test_engine_intents import _receipt
    from test_engine_session_coordinator import prepared_store

    db, _vault, _member, store = prepared_store(tmp_path)
    provider, key, credential = _passkey([0.0])
    legacy, _ = _app(db.path, provider, FakeHost())
    old = LifecycleIntentStore(db).request("bot", "start", str(uuid4()), on_demand=True)
    _receipt(db, old.operation_id, status=legacy_status)
    wakes = []
    engines = EngineSessionCoordinator(store=store, wake=wakes.append)
    app = PrivatePanelApplication(
        origin=legacy._origin,
        database_path=db.path,
        owner_subject="owner",
        passkey=provider,
        members=legacy._members,
        commands=legacy._commands,
        events=legacy._events,
        bot_control=wakes.append,
        engine_control=engines,
    )
    clock = [0.0]
    monkeypatch.setattr(app._sessions, "_clock", lambda: clock[0])
    monkeypatch.setattr(app, "_site_url_ready", lambda: True)
    cookie = _login(app, key, credential)

    def fields_for(path):
        code, _headers, body = _request(app, "/control", cookie=cookie)
        assert code == 200
        form = re.search(
            rb'<form[^>]+action="' + path.encode() + rb'"[^>]*>(.*?)</form>', body, re.S
        )
        assert form is not None
        return {
            name.decode(): value.decode()
            for name, value in re.findall(rb'name="([^"]+)"[^>]*value="([^"]*)"', form[1])
        }

    try:
        recovery = fields_for("/control/bot/detener")
        assert (
            _request(
                app,
                "/control/bot/detener",
                cookie=cookie,
                method="POST",
                payload=recovery,
                origin="https://wrong.invalid",
            )[0]
            == 403
        )
        assert wakes == []
        assert (
            _request(
                app,
                "/control/bot/detener",
                cookie=cookie,
                method="POST",
                payload=recovery,
                origin=app._origin,
            )[0]
            == 303
        )
        physical = LifecycleIntentStore(db).current()
        assert physical.operation_id == recovery["operation_id"] and physical.target == "stop"
        assert physical.status == "REQUESTED" and store.snapshot() == ()
        assert wakes == [physical.operation_id]
        assert not store.restartable_engines()
        _receipt(db, physical.operation_id, "stop")
        assert store.restartable_engines() == frozenset({"queues_tokens", "browsers_members"})
        # A form prepared before a fresh engine START cannot stop that new job.
        stale_recovery = fields_for("/control/bot/detener")
        start = fields_for("/control/motores/queues_tokens/iniciar")
        start.update(chromium="1", firefox="0", webkit="0")
        clock[0] += 2.0
        assert (
            _request(
                app,
                "/control/motores/queues_tokens/iniciar",
                cookie=cookie,
                method="POST",
                payload=start,
                origin=app._origin,
            )[0]
            == 303
        )
        fresh = LifecycleIntentStore(db).current()
        assert fresh.target == "start"
        clock[0] += 2.0
        assert (
            _request(
                app,
                "/control/bot/detener",
                cookie=cookie,
                method="POST",
                payload=stale_recovery,
                origin=app._origin,
            )[0]
            == 409
        )
        assert LifecycleIntentStore(db).current() == fresh
        assert len(store.snapshot()) == 1
        assert wakes == [physical.operation_id, fresh.operation_id]
    finally:
        engines.close()


@pytest.mark.parametrize("received", [True, False])
def test_private_session_detail_separates_configuration_attempt_and_final_sample(
    tmp_path, monkeypatch, received
):
    from datetime import UTC, datetime

    from boca_socios.browser.engine_protocol import (
        EngineIdentity,
        NavigationAttempt,
        SessionInspection,
    )
    from boca_socios.browser.queue_page_observation import QueuePageObservation
    from boca_socios.integration.engine_sessions import PrivateSessionDetails

    app, engines, cookie = panel(tmp_path, monkeypatch)
    identity = EngineIdentity("queues_tokens", str(uuid4()), 1, str(uuid4()), "chromium")
    details = PrivateSessionDetails(
        identity,
        QueuePageObservation(
            "UNKNOWN",
            "EVENT_VERIFIED",
            "UNKNOWN",
            "EVENT_ID_OBSERVED",
            datetime(2026, 11, 15, 16, tzinfo=UTC),
            event_id="campaign:page-42",
        )
        if received
        else None,
        SessionInspection(
            final_url="https://final.example.invalid/prior?final-secret#private",
            observed_at=datetime(2026, 11, 15, 15, tzinfo=UTC),
            context_open=False,
            configured_url="https://site.example.invalid/start",
            navigation_attempt=NavigationAttempt(
                2,
                "QUEUE_BRIDGE",
                "https://queue.example.invalid/next",
                datetime(2026, 11, 15, 16, tzinfo=UTC),
                "FAILED",
            ),
        )
        if received
        else None,
        None,
        "FAILED",
        "SESSION_FAILED",
    )
    monkeypatch.setattr(engines, "private_details", lambda *a, **k: details)
    code, _, page = _request(app, "/control/sesiones/" + identity.session_id, cookie=cookie)
    assert code == 200
    for label in (
        "ID de evento observado en la página",
        "URL configurada",
        "Última navegación intentada",
        "Última URL final recibida",
    ):
        assert label.encode() in page
    if received:
        assert b"campaign:page-42" in page
        assert "ID recibido sin otras señales".encode() in page
        assert b"https://site.example.invalid/start" in page
        assert b"https://final.example.invalid/prior" in page
        assert b"2026-11-15 12:00:00 ART" in page
        assert b"2026-11-15 13:00:00 ART" in page
        assert "El intento falló".encode() in page
        assert "esos datos son históricos".encode() in page
    else:
        assert b"Dato no recibido" in page
        assert b"no hay eventos" not in page
    assert b"final-secret" not in page and b"configured-secret" not in page
    assert b'href="https://' not in page
    assert engines.calls == []
