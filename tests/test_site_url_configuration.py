"""The owner can safely persist a simulation URL without touching browser logic."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from boca_socios.panel.site_url_settings import (
    SiteUrlInvalid,
    SiteUrlSettingsStore,
    SiteUrlSettingsUnavailable,
    require_site_url,
)
from test_private_beta_panel import _app, _login, _passkey, _request


def _owner(tmp_path: Path):
    provider, key, credential_id = _passkey([0.0])
    database = tmp_path / "boca.sqlite3"
    app, _ = _app(database, provider)
    return app, _login(app, key, credential_id), database


def _form_fields(app, cookie: str) -> dict[str, str]:
    status, headers, body = _request(app, "/configuracion", cookie=cookie)
    assert status == 200 and headers["Cache-Control"] == "no-store"
    return {
        name: re.search(rb'name="' + name.encode() + rb'" value="([^"]+)"', body).group(1).decode()
        for name in ("csrf", "operation_id")
    }


def test_site_url_configuration_is_owner_only_and_discoverable(tmp_path: Path) -> None:
    app, cookie, _ = _owner(tmp_path)
    assert _request(app, "/configuracion")[0] == 401
    status, headers, page = _request(app, "/configuracion", cookie=cookie)
    assert status == 200
    assert b"SITE_URL" in page
    assert b'form method="post" action="/configuracion"' in page
    assert "próximo arranque".encode() in page
    assert b'href="/configuracion"' in page
    assert "form-action 'self'" in headers["Content-Security-Policy"]


def test_owner_saves_site_url_and_it_survives_reloading_store(tmp_path: Path) -> None:
    app, cookie, database = _owner(tmp_path)
    fields = _form_fields(app, cookie)
    status, headers, _ = _request(
        app,
        "/configuracion",
        cookie=cookie,
        method="POST",
        payload={**fields, "SITE_URL": "https://ensayo.boca.internal/ruta"},
    )
    assert status == 303 and headers["Location"] == "/configuracion"
    store = SiteUrlSettingsStore.for_database(database)
    assert store.read() == "https://ensayo.boca.internal/ruta"
    assert store.path.stat().st_mode & 0o777 == 0o600
    code, _, page = _request(app, "/configuracion", cookie=cookie)
    assert code == 200 and b"ensayo.boca.internal/ruta" in page
    assert b"Guardada" in page


@pytest.mark.parametrize(
    "url",
    [
        "https://sandbox.test/?token=abc",
        "https://user:password@sandbox.test/",
        "file:///etc/passwd",
        "https://sandbox.test/#secret",
        "http://localhost:99999/",
        "https://sandbox.test/\nInjected:1",
        "https://169.254.169.254/latest/meta-data",
    ],
)
def test_malformed_and_credential_bearing_urls_are_rejected(url: str) -> None:
    with pytest.raises(SiteUrlInvalid):
        require_site_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://ensayo.test/",
        "http://sitio.boca.internal:8080/",
        "http://127.0.0.1:8444/test",
        "https://soysocio.bocajuniors.com.ar/",
        "https://api.telegram.org/",
        "https://evil.example.com/",
    ],
)
def test_public_and_private_destinations_are_accepted(url: str) -> None:
    assert require_site_url(url) == url


def test_bad_csrf_or_origin_cannot_change_destination(tmp_path: Path) -> None:
    app, cookie, database = _owner(tmp_path)
    fields = _form_fields(app, cookie)
    for override in ({"csrf": "bad"}, {"operation_id": "bad"}):
        code, _, _ = _request(
            app,
            "/configuracion",
            method="POST",
            cookie=cookie,
            payload={**fields, **override, "SITE_URL": "https://ensayo.test/"},
        )
        assert code in (400, 403)
    code, _, _ = _request(
        app,
        "/configuracion",
        method="POST",
        cookie=cookie,
        origin="https://forged.test",
        payload={**fields, "SITE_URL": "https://ensayo.test/"},
    )
    assert code == 403
    assert SiteUrlSettingsStore.for_database(database).read() is None


def test_owner_can_store_public_destination_without_launching_worker(tmp_path: Path) -> None:
    app, cookie, database = _owner(tmp_path)
    code, _, page = _request(
        app,
        "/configuracion",
        cookie=cookie,
        method="POST",
        payload={
            **_form_fields(app, cookie),
            "SITE_URL": "https://soysocio.bocajuniors.com.ar/",
        },
    )
    assert code == 303
    assert b"sandbox" not in page
    assert (
        SiteUrlSettingsStore.for_database(database).read() == "https://soysocio.bocajuniors.com.ar/"
    )


def test_url_settings_fail_closed_on_symlink(tmp_path: Path) -> None:
    store = SiteUrlSettingsStore.for_database(tmp_path / "boca.sqlite3")
    outside = tmp_path / "outside.json"
    outside.write_text('{"version":1,"SITE_URL":"https://ensayo.test/"}')
    store.path.symlink_to(outside)
    with pytest.raises(SiteUrlSettingsUnavailable):
        store.read()
    with pytest.raises(SiteUrlSettingsUnavailable):
        store.save("https://ensayo.test/")
    assert outside.read_text().startswith('{"version":1,')
