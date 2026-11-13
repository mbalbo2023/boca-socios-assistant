"""The owner can safely persist a simulation URL without touching browser logic."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from boca_socios.browser import site_url_runtime
from boca_socios.panel import private_http
from boca_socios.panel.site_url_settings import (
    SiteUrlInvalid,
    SiteUrlSettingsStore,
    SiteUrlSettingsUnavailable,
    require_site_url,
)
from test_private_beta_panel import EVENT_ID, ORIGIN, FakeHost, _app, _login, _passkey, _request


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


def test_unconfigured_site_url_field_is_visibly_blank_without_sample_url(
    tmp_path: Path,
) -> None:
    app, cookie, _ = _owner(tmp_path)
    status, _, page = _request(app, "/configuracion", cookie=cookie)
    assert status == 200
    assert b'id="site-url" name="SITE_URL" type="url" value=""' in page
    assert b"ensayo.boca.internal" not in page
    assert b'placeholder="https://' not in page
    assert b"SITE_URL no configurada" in page


@pytest.mark.parametrize("path", ["/", "/control", "/configuracion"])
def test_private_owner_form_page_preserves_same_origin_for_native_post(
    tmp_path: Path, path: str
) -> None:
    """An HTML form POST must not inherit a policy that makes Origin null."""
    app, cookie, _ = _owner(tmp_path)
    status, headers, _ = _request(app, path, cookie=cookie)
    assert status == 200
    assert headers["Referrer-Policy"] == "same-origin"


@pytest.mark.parametrize("state", ["missing", "diverged", "matched"])
def test_on_demand_home_and_control_show_actual_site_url_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    destination = "https://offline-fixture.invalid/"
    provider, key, credential_id = _passkey([0.0])
    wakes: list[str] = []
    app, _ = _app(tmp_path / "boca.sqlite3", provider, FakeHost(), bot_control=wakes.append)
    cookie = _login(app, key, credential_id)
    if state != "missing":
        SiteUrlSettingsStore.for_database(tmp_path / "boca.sqlite3").save(destination)
    if state == "diverged":
        monkeypatch.setattr(private_http, "read_site_url", lambda _path: "https://old.test/")
    elif state == "matched":
        monkeypatch.setattr(private_http, "read_site_url", lambda _path: destination)

    for path in ("/", "/control"):
        code, _headers, page = _request(app, path, cookie=cookie)
        assert code == 200
        start = re.search(rb'<form method="post" action="/control/bot/iniciar">(.*?)</form>', page)
        stop = re.search(rb'<form method="post" action="/control/bot/detener">(.*?)</form>', page)
        assert start is not None and stop is not None
        if state == "matched":
            assert b"SITE_URL lista para solicitar un inicio" in page
            assert b"disabled" not in start.group(1)
        else:
            assert b"SITE_URL no verificable para iniciar" in page
            assert b"disabled" in start.group(1)
            assert b'href="/configuracion"' in page
        assert b"disabled" not in stop.group(1)
        assert b"No acredita actividad del worker" in page
    assert wakes == []


def test_owner_saves_site_url_and_it_survives_reloading_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    published: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        private_http,
        "publish_site_url",
        lambda path, destination: published.append((path, destination)),
        raising=False,
    )
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
    assert published == [(private_http.RUNTIME_SITE_URL_PATH, "https://ensayo.boca.internal/ruta")]
    store = SiteUrlSettingsStore.for_database(database)
    assert store.read() == "https://ensayo.boca.internal/ruta"
    assert store.path.stat().st_mode & 0o777 == 0o600
    code, _, page = _request(app, "/configuracion", cookie=cookie)
    assert code == 200 and b"ensayo.boca.internal/ruta" in page
    assert b"Guardada" in page


def test_owner_post_publishes_real_worker_mirror_for_next_cold_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The owner POST must join both durable URL files, without launching a worker."""
    runtime_dir = tmp_path / "boca-site-config"
    runtime_dir.mkdir(mode=0o711)
    runtime_dir.chmod(0o711)
    runtime_path = runtime_dir / "boca-site-url.runtime.json"
    owner = {"owner_uid": os.geteuid(), "owner_gid": os.getegid()}
    monkeypatch.setattr(private_http, "RUNTIME_SITE_URL_PATH", runtime_path)
    monkeypatch.setattr(
        private_http,
        "publish_site_url",
        lambda path, url: site_url_runtime.publish_site_url(path, url, **owner),
    )
    monkeypatch.setattr(
        private_http,
        "read_site_url",
        lambda path: site_url_runtime.read_site_url(path, **owner),
    )

    provider, key, credential = _passkey([0.0])
    database = tmp_path / "boca.sqlite3"
    wake_calls: list[str] = []
    app, _ = _app(database, provider, FakeHost(), bot_control=wake_calls.append)
    cookie = _login(app, key, credential)
    first = "https://first-offline.example.invalid/path"
    status, headers, _ = _request(
        app,
        "/configuracion",
        cookie=cookie,
        method="POST",
        payload={**_form_fields(app, cookie), "SITE_URL": first},
    )
    assert status == 303 and headers["Location"] == "/configuracion"
    assert wake_calls == []
    assert SiteUrlSettingsStore.for_database(database).read() == first
    assert site_url_runtime.read_site_url(runtime_path, **owner) == first
    assert runtime_path.stat().st_mode & 0o777 == 0o644
    assert b"SITE_URL lista para solicitar un inicio" in _request(app, "/control", cookie=cookie)[2]

    # Recreating the controller from the same Boca database must not lose the
    # setting. A later form update must replace the worker's next cold read.
    restarted = private_http.PrivatePanelApplication(
        origin=ORIGIN,
        database_path=database,
        owner_subject="owner",
        passkey=provider,
        members=app._members,
        commands=FakeHost(),
        events={EVENT_ID: "Partido sintético"},
        bot_control=wake_calls.append,
    )
    assert (
        b"first-offline.example.invalid" in _request(restarted, "/configuracion", cookie=cookie)[2]
    )
    second = "https://second-offline.example.invalid/"
    status, _, _ = _request(
        restarted,
        "/configuracion",
        cookie=cookie,
        method="POST",
        payload={**_form_fields(restarted, cookie), "SITE_URL": second},
    )
    assert status == 303
    assert SiteUrlSettingsStore.for_database(database).read() == second
    assert site_url_runtime.read_site_url(runtime_path, **owner) == second
    assert wake_calls == []


@pytest.mark.parametrize("received", [None, "", "null", "https://forged.example.test"])
def test_origin_rejection_cannot_persist_or_publish_site_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, received: str | None
) -> None:
    """A missing, opaque, or cross-site Origin is not repaired by Referer headers."""
    published: list[str] = []
    monkeypatch.setattr(
        private_http,
        "publish_site_url",
        lambda _path, url: published.append(url),
    )
    app, cookie, database = _owner(tmp_path)
    status, _, _ = _request(
        app,
        "/configuracion",
        cookie=cookie,
        method="POST",
        payload={**_form_fields(app, cookie), "SITE_URL": "https://offline.example.invalid/"},
        extra={"HTTP_ORIGIN": received, "HTTP_REFERER": "https://boca.example.test/"},
    )
    assert status == 403
    assert SiteUrlSettingsStore.for_database(database).read() is None
    assert published == []


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
        "http://2852039166/latest/meta-data",  # Chromium: 169.254.169.254
        "http://0xa9fea9fe/latest/meta-data",  # Chromium: 169.254.169.254
        "http://169.254.43518/latest/meta-data",  # Short IPv4 notation
        "https://sandbox.test:/",  # Empty port is not a destination port
        "https://sandbox..test/",  # Empty DNS label
        "https://-sandbox.test/",  # Invalid DNS label
        "https://sandbox.test?",  # Empty query delimiter remains a query
        "https://sandbox.test#",  # Empty fragment delimiter remains a fragment
        "https://api.telegram.org/bot12345:TEST_TOKEN/getUpdates",
        "https://api.telegram.org/%62ot12345%3ATEST_TOKEN/getUpdates",
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


def test_owner_can_store_public_destination_without_launching_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    published: list[str] = []
    monkeypatch.setattr(
        private_http,
        "publish_site_url",
        lambda _path, destination: published.append(destination),
        raising=False,
    )
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
    assert published == ["https://soysocio.bocajuniors.com.ar/"]
    assert b"sandbox" not in page
    assert (
        SiteUrlSettingsStore.for_database(database).read() == "https://soysocio.bocajuniors.com.ar/"
    )


def test_site_url_publication_failure_fails_closed_without_starting_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from boca_socios.browser.site_url_runtime import RuntimeSiteUrlUnavailable

    def unavailable(_path: Path, _destination: str) -> None:
        raise RuntimeSiteUrlUnavailable("runtime mirror unavailable")

    monkeypatch.setattr(private_http, "publish_site_url", unavailable, raising=False)
    app, cookie, _ = _owner(tmp_path)
    code, _, body = _request(
        app,
        "/configuracion",
        cookie=cookie,
        method="POST",
        payload={
            **_form_fields(app, cookie),
            "SITE_URL": "https://sandbox.example.com/",
        },
    )
    assert code == 503
    assert b"Configuraci" in body


@pytest.mark.parametrize("saved_url", [None, "https://ensayo.example.test/"])
def test_absent_site_url_setting_or_worker_mirror_cannot_submit_bot_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, saved_url: str | None
) -> None:
    from boca_socios.browser.site_url_runtime import RuntimeSiteUrlUnavailable
    from test_private_lifecycle_controls import _bot_fields

    wakes: list[str] = []
    provider, key, credential_id = _passkey([0.0])
    database = tmp_path / "boca.sqlite3"
    app, db = _app(database, provider, FakeHost(), bot_control=wakes.append)
    cookie = _login(app, key, credential_id)
    if saved_url is not None:
        SiteUrlSettingsStore.for_database(database).save(saved_url)

    def absent_mirror(_path: Path) -> str:
        raise RuntimeSiteUrlUnavailable("no published worker destination")

    monkeypatch.setattr(private_http, "read_site_url", absent_mirror)
    code, _, control_page = _request(app, "/control", cookie=cookie)
    assert code == 200
    code, _, body = _request(
        app,
        "/control/bot/iniciar",
        cookie=cookie,
        method="POST",
        payload=_bot_fields(control_page, "iniciar"),
    )

    assert code == 503
    assert b"Configuraci" in body
    assert wakes == []
    with db.connection() as connection:
        assert connection.execute(
            "SELECT count(*) FROM audit_events WHERE action='owner_lifecycle_v1_request_bot_start'"
        ).fetchone() == (0,)


def test_diverged_persistent_and_worker_url_cannot_submit_bot_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[str] = []
    provider, key, credential_id = _passkey([0.0])
    database = tmp_path / "boca.sqlite3"
    app, db = _app(database, provider, FakeHost(), bot_control=sent.append)
    cookie = _login(app, key, credential_id)
    SiteUrlSettingsStore.for_database(database).save("https://new.example.test/")
    monkeypatch.setattr(
        private_http,
        "read_site_url",
        lambda _path: "https://previous.example.test/",
        raising=False,
    )
    code, _, page = _request(app, "/control", cookie=cookie)
    assert code == 200
    form = re.search(rb'<form method="post" action="/control/bot/iniciar">(.*?)</form>', page)
    assert form is not None
    fields = {
        name: re.search(rb'name="' + name.encode() + rb'" value="([^"]+)"', form.group(1))
        .group(1)
        .decode()
        for name in ("csrf", "operation_id")
    }

    code, _, body = _request(
        app,
        "/control/bot/iniciar",
        cookie=cookie,
        method="POST",
        payload=fields,
    )

    assert code == 503
    assert b"URL" in body
    assert sent == []
    with db.connection() as connection:
        assert connection.execute(
            "SELECT count(*) FROM audit_events WHERE action='owner_lifecycle_v1_request_bot_start'"
        ).fetchone() == (0,)


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


def test_unicode_url_size_limit_does_not_corrupt_persisted_settings(tmp_path: Path) -> None:
    store = SiteUrlSettingsStore.for_database(tmp_path / "boca.sqlite3")
    previous = "https://ensayo.test/"
    store.save(previous)
    # <512 Unicode characters, but JSON escaping would exceed the 2 KiB
    # durable settings and URL-only worker-file bounds.
    too_large = previous + "🚀" * 210

    with pytest.raises(SiteUrlInvalid):
        store.save(too_large)

    assert store.read() == previous
