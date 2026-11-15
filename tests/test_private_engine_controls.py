"""Real passkey/CSRF routes fence the new independent engine controls."""

import json
import re
from types import SimpleNamespace
from uuid import uuid4

import pytest

from boca_socios.panel.private_http import PrivatePanelApplication
from test_private_beta_panel import FakeHost, _app, _login, _passkey, _request


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


def panel(tmp_path, monkeypatch):
    provider, key, credential = _passkey([0.0])
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


def test_token_monitor_reuses_live_session_inventory_instead_of_a_static_count(
    tmp_path, monkeypatch
):
    app, engines, cookie = panel(tmp_path, monkeypatch)
    code, headers, page = _request(app, "/monitor/tokens", cookie=cookie)
    assert code == 200 and headers["Cache-Control"] == "no-store"
    assert b"/control/motores.json" in page
    assert engines.calls == []


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
