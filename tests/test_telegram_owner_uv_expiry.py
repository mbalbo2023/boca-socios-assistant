"""HTTP-level time and origin gates for real owner Telegram UV ceremony."""

from __future__ import annotations

import re
from pathlib import Path

from boca_socios.panel.telegram_pairing_staging import (
    STAGING_FILENAME,
    stage_private_telegram_pairing,
)
from test_private_beta_panel import _login, _request
from test_telegram_pairing_panel_handoff import _app_with_stage, _envelope, _stage_form


def test_expired_web_authenticator_challenge_never_writes_telegram_stage(tmp_path: Path) -> None:
    path = tmp_path / STAGING_FILENAME
    app, key, credential, clock = _app_with_stage(
        tmp_path / "boca.sqlite3",
        lambda request: stage_private_telegram_pairing(path, request),
    )
    cookie = _login(app, key, credential)
    _, _, page = _request(app, "/telegram/emparejar", cookie=cookie)
    fields = _stage_form(app, cookie, page, _envelope(), key, credential, clock)
    clock[0] += 121.0
    assert (
        _request(app, "/telegram/emparejar", method="POST", cookie=cookie, payload=fields)[0] == 403
    )
    assert not path.exists()
    assert (
        _request(app, "/telegram/emparejar", method="POST", cookie=cookie, payload=fields)[0] == 409
    )
    assert not path.exists()


def test_telegram_signature_challenge_requires_owner_origin_and_valid_sha(tmp_path: Path) -> None:
    path = tmp_path / STAGING_FILENAME
    app, key, credential, _clock = _app_with_stage(
        tmp_path / "boca.sqlite3",
        lambda request: stage_private_telegram_pairing(path, request),
    )
    cookie = _login(app, key, credential)
    _, _, page = _request(app, "/telegram/emparejar", cookie=cookie)
    csrf = re.search(rb'id="pairing-csrf" type="hidden" value="([^"]+)"', page)
    operation = re.search(rb'id="pairing-operation" type="hidden" value="([^"]+)"', page)
    assert csrf is not None and operation is not None
    payload = {
        "csrf": csrf.group(1).decode(),
        "operation_id": operation.group(1).decode(),
        "envelope_sha256": "a" * 64,
    }
    assert (
        _request(
            app,
            "/telegram/emparejar/desafio",
            method="POST",
            cookie=cookie,
            payload=payload,
            origin="https://evil.example.test",
        )[0]
        == 403
    )
    payload["envelope_sha256"] = "not-a-sha256"
    assert (
        _request(
            app,
            "/telegram/emparejar/desafio",
            method="POST",
            cookie=cookie,
            payload=payload,
        )[0]
        == 422
    )
    assert not path.exists()
