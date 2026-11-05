"""Browser owner session must not stage Telegram without a fresh ES256 UV proof."""

from __future__ import annotations

from pathlib import Path

from boca_socios import telegram_bootstrap as bootstrap
from boca_socios.panel.telegram_pairing_staging import (
    STAGING_FILENAME,
    stage_private_telegram_pairing,
)
from test_private_beta_panel import _login, _request
from test_telegram_pairing_panel_handoff import _app_with_stage, _envelope, _stage_form


def test_session_cookie_and_csrf_do_not_replace_fresh_telegram_webauthn(tmp_path: Path) -> None:
    path = tmp_path / STAGING_FILENAME
    app, key, credential, clock = _app_with_stage(
        tmp_path / "boca.sqlite3",
        lambda request: stage_private_telegram_pairing(path, request),
    )
    cookie = _login(app, key, credential)
    _, _, page = _request(app, "/telegram/emparejar", cookie=cookie)
    envelope = _envelope()
    fields = _stage_form(app, cookie, page, envelope, key, credential, clock)
    old_cookie_only_form = {field: fields[field] for field in ("csrf", "operation_id", "envelope")}
    assert (
        _request(
            app,
            "/telegram/emparejar",
            method="POST",
            cookie=cookie,
            payload=old_cookie_only_form,
        )[0]
        == 400
    )
    assert not path.exists()
    assert (
        _request(app, "/telegram/emparejar", method="POST", cookie=cookie, payload=fields)[0] == 202
    )
    assert path.exists()


def test_signed_assertion_of_other_ciphertext_is_denied_without_stage(tmp_path: Path) -> None:
    path = tmp_path / STAGING_FILENAME
    app, key, credential, clock = _app_with_stage(
        tmp_path / "boca.sqlite3",
        lambda request: stage_private_telegram_pairing(path, request),
    )
    cookie = _login(app, key, credential)
    _, _, page = _request(app, "/telegram/emparejar", cookie=cookie)
    envelope = _envelope()
    fields = _stage_form(app, cookie, page, envelope, key, credential, clock)
    fields["envelope"] = bootstrap._b64(_envelope())
    assert fields["envelope"] != bootstrap._b64(envelope)
    assert (
        _request(app, "/telegram/emparejar", method="POST", cookie=cookie, payload=fields)[0] == 403
    )
    assert not path.exists()
    # A failed operation cannot be resurrected by switching back to the real
    # ciphertext; owner must start another independent passkey ceremony.
    fields["envelope"] = bootstrap._b64(envelope)
    assert (
        _request(app, "/telegram/emparejar", method="POST", cookie=cookie, payload=fields)[0] == 409
    )
    assert not path.exists()
