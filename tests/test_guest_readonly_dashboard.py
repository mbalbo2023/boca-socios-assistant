"""An unauthenticated observer can inspect Boca-only states, never owner controls."""

from types import SimpleNamespace

import pytest

from boca_socios.panel import private_http, worker_activity
from test_private_beta_panel import _request
from test_private_engine_controls import panel


def test_guest_navigation_reads_real_motor_states_without_owner_data(tmp_path, monkeypatch):
    app, engines, _cookie = panel(tmp_path, monkeypatch)
    private_marker = "member-secret-identity-marker"
    engines.snapshot = lambda: {
        "version": 1,
        "context_limit": 50,
        "observed_at": "2026-11-16T20:00:00Z",
        "engines": [
            {
                "engine": "queues_tokens",
                "state": "RUNNING",
                "active": 2,
                "created": 3,
                "member_id": private_marker,
                "activation_id": private_marker,
                "sessions": [{"display_url": "https://example.test/" + private_marker}],
            },
            {
                "engine": "browsers_members",
                "state": "STOPPED",
                "active": 0,
                "created": 0,
                "member_id": private_marker,
                "sessions": [],
            },
        ],
    }
    monkeypatch.setattr(
        app._sessions,
        "new_operation",
        lambda *args, **kwargs: pytest.fail("guest GET allocated owner operation"),
    )
    monkeypatch.setattr(
        app._directory,
        "list_members",
        lambda *args, **kwargs: pytest.fail("guest GET accessed owner members"),
    )
    for path in ("/", "/control", "/control/actividad", "/configuracion"):
        status, headers, body = _request(app, path)
        assert status == 200, path
        assert headers["Cache-Control"] == "no-store"
        assert "Set-Cookie" not in headers
        assert b'href="/control"' in body
        assert b'href="/control/actividad"' in body
        assert b'href="/configuracion"' in body
        assert body.count(b'href="/ingresar"') == 1
        assert b"Ingresar para operar motores y editar configuraci\xc3\xb3n" in body
        assert private_marker.encode() not in body
        assert b"<form" not in body
        assert b'name="csrf"' not in body
        assert b"operation_id" not in body
        assert b"/monitor/tokens/revelar" not in body
        assert b"Actualizar estado" in body

    status, _, control = _request(app, "/control")
    assert status == 200 and b"RUNNING" in control and b"STOPPED" in control
    assert b"2" in control
    assert b"Estado l\xc3\xb3gico" in control
    status, _, activity = _request(app, "/control/actividad")
    assert status == 200
    assert b"hist\xc3\xb3rico" in activity
    # Existing owner-control tests separately exercise authenticated operations.


def test_guest_configuration_reports_presence_without_disclosing_url(tmp_path, monkeypatch):
    app, _engines, _cookie = panel(tmp_path, monkeypatch)
    private_url = "https://example.invalid/secret-config-path-guest-canary"
    monkeypatch.setattr(app._site_url_settings, "read", lambda: private_url)
    status, _, page = _request(app, "/configuracion")
    assert status == 200
    assert b"SITE_URL" in page and b"configurada" in page
    assert private_url.encode() not in page
    assert b"<form" not in page


def test_guest_activity_observer_failure_is_unknown_without_leaking_exception(
    tmp_path, monkeypatch
):
    app, _engines, _cookie = panel(tmp_path, monkeypatch)
    secret = "owner-queue-credential-runtime-error-canary"

    class UnavailableMonitor:
        def activity_events(self):
            raise RuntimeError(secret)

    app._automatic_monitor = UnavailableMonitor()
    status, headers, page = _request(app, "/control/actividad")
    assert status == 200
    assert headers["Cache-Control"] == "no-store"
    assert b"UNKNOWN" in page
    assert secret.encode() not in page
    assert b"<form" not in page


@pytest.mark.parametrize(
    ("private_label", "safe_label"),
    [
        ("Chromium: proceso del navegador creado.", "Chromium: navegador iniciado."),
        ("Cola simulada: solicitud en espera.", "Cola: espera registrada."),
        (
            "Evento detectado: cola virtual activa; observando la misma sesión.",
            "Cola virtual: activa según la última observación.",
        ),
        (
            "La página informa que no hay eventos disponibles; comprobación finalizada.",
            "Evento: no observado según la última comprobación.",
        ),
    ],
)
def test_guest_event_labels_are_independent_public_copies(private_label, safe_label):
    assert worker_activity.guest_activity_label(private_label) == safe_label
    assert safe_label != private_label


def test_new_private_activity_label_never_auto_appears_in_guest(tmp_path, monkeypatch):
    app, _engines, _cookie = panel(tmp_path, monkeypatch)
    private_canary = "FUTURE PRIVATE LABEL: member=member@example.invalid queueittoken=SECRET"
    monkeypatch.setitem(
        worker_activity._AUTOMATIC_LABELS,
        "FUTURE_MEMBER_PRIVATE",
        ("success", private_canary),
    )
    monkeypatch.setattr(
        private_http,
        "read_worker_activity",
        lambda *_args, **_kwargs: SimpleNamespace(
            chromium_telemetry="available",
            events=(SimpleNamespace(source="chromium", message=private_canary),),
        ),
    )
    status, headers, page = _request(app, "/control/actividad")
    assert status == 200
    assert "Set-Cookie" not in headers
    assert private_canary.encode() not in page
    assert b"Actividad local observada; detalle no disponible" in page


def test_guest_navigation_does_not_authorize_json_post_or_wrong_origin(tmp_path, monkeypatch):
    app, engines, _cookie = panel(tmp_path, monkeypatch)
    for path in (
        "/control/motores.json",
        "/control/actividad.json",
        "/monitor/tokens.json",
        "/socios",
        "/control/sesiones/00000000-0000-4000-8000-000000000001",
    ):
        assert _request(app, path)[0] == 401, path
    for path in ("/control", "/control/actividad", "/configuracion"):
        assert _request(app, path, method="POST")[0] == 401
        assert _request(app, path, method="HEAD")[0] == 401
        assert _request(app, path, extra={"QUERY_STRING": "probe=1"})[0] == 400
        assert _request(app, path, extra={"HTTP_HOST": "foreign.example"})[0] == 400
    assert engines.calls == []


def test_guest_activity_drops_unknown_free_text_and_bad_cookie_is_readonly(tmp_path, monkeypatch):
    app, _engines, _cookie = panel(tmp_path, monkeypatch)
    canary = "https://secret.example.invalid/queueittoken=secret-canary"
    monkeypatch.setattr(
        private_http,
        "read_worker_activity",
        lambda *_args, **_kwargs: SimpleNamespace(
            chromium_telemetry="available",
            events=(SimpleNamespace(source="chromium", message=canary),),
        ),
    )
    status, _, page = _request(app, "/control/actividad")
    assert status == 200
    assert b"Chromium" in page
    assert canary.encode() not in page
    # Expired owner cookie keeps the four GET pages usable in read-only mode.
    for path in ("/", "/control", "/control/actividad", "/configuracion"):
        status, headers, readonly = _request(app, path, cookie="boca_session=invalid")
        assert status == 200
        assert "Set-Cookie" not in headers
        assert b"lectura" in readonly
        assert b"<form" not in readonly
        assert readonly.count(b'href="/ingresar"') == 1
    assert _request(app, "/control/actividad.json", cookie="boca_session=invalid")[0] == 401
    assert _request(app, "/control", method="POST", cookie="boca_session=invalid")[0] == 401
