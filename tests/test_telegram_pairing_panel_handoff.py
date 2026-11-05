"""Passkey-authenticated Chrome -> encrypted V2 STAGING, not installation."""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from boca_socios import telegram_bootstrap as bootstrap
from boca_socios.panel.private_http import PrivatePanelApplication
from boca_socios.panel.telegram_pairing_staging import (
    STAGING_FILENAME,
    PairingStageReceipt,
    stage_private_telegram_pairing,
)
from test_private_beta_panel import ORIGIN, _app, _login, _passkey, _request
from test_telegram_pairing_ui import TOKEN, _recipient, _run


def _app_with_stage(
    path: Path, stage: Callable[[bytes], PairingStageReceipt] | None
) -> tuple[PrivatePanelApplication, Any, bytes]:
    provider, key, credential = _passkey([0.0])
    original, _ = _app(path, provider)
    app = PrivatePanelApplication(
        origin=ORIGIN,
        database_path=path,
        owner_subject="owner",
        passkey=provider,
        members=original._members,
        commands=None,
        events={},
        telegram_pairing_stager=stage,
    )
    return app, key, credential


def _stage_form(page: bytes, envelope: bytes) -> dict[str, str]:
    return {
        "csrf": re.search(rb'id="pairing-csrf" type="hidden" value="([A-Za-z0-9_-]+)"', page)
        .group(1)
        .decode(),
        "operation_id": re.search(
            rb'id="pairing-operation" type="hidden" value="([0-9a-f-]+)"', page
        )
        .group(1)
        .decode(),
        "envelope": bootstrap._b64(envelope),
    }


def _envelope() -> bytes:
    _, _, fragment = _recipient()
    return bootstrap._unb64(_run(fragment)["output"], maximum=4096)


def test_get_is_authenticated_and_post_stages_ciphertext_once(tmp_path: Path) -> None:
    stage_path = tmp_path / STAGING_FILENAME
    app, key, credential = _app_with_stage(
        tmp_path / "boca.sqlite3",
        lambda envelope: stage_private_telegram_pairing(stage_path, envelope),
    )
    assert _request(app, "/telegram/emparejar")[0] == 401
    assert _request(app, "/telegram/emparejar", method="POST")[0] == 401
    cookie = _login(app, key, credential)
    status, headers, page = _request(app, "/telegram/emparejar", cookie=cookie)
    assert status == 200
    assert "connect-src 'self'" in headers["Content-Security-Policy"]
    assert "form-action 'none'" in headers["Content-Security-Policy"]
    assert b'id="pairing-stage"' in page
    assert b'id="pairing-csrf"' in page
    assert b'role="status" aria-live="polite"' in page

    envelope = _envelope()
    fields = _stage_form(page, envelope)
    posted, headers, response = _request(
        app, "/telegram/emparejar", method="POST", cookie=cookie, payload=fields
    )
    assert posted == 202
    assert headers["Content-Type"] == "application/json"
    assert json.loads(response) == {
        "state": "STAGED_PENDING_PROTECTED_CUTOVER",
        "telegram_connected": False,
        "sender": "OFF",
        "notification_receipt": "UNVERIFIED",
    }
    assert stage_path.is_file()
    assert TOKEN.encode() not in response
    assert b"pairing_code" not in response
    replay, _, replay_body = _request(
        app, "/telegram/emparejar", method="POST", cookie=cookie, payload=fields
    )
    assert replay == 409 and TOKEN.encode() not in replay_body


def test_post_rejects_wrong_origin_csrf_plaintext_and_disabled_gateway(tmp_path: Path) -> None:
    stage_path = tmp_path / STAGING_FILENAME
    app, key, credential = _app_with_stage(
        tmp_path / "boca.sqlite3",
        lambda envelope: stage_private_telegram_pairing(stage_path, envelope),
    )
    cookie = _login(app, key, credential)
    _, _, page = _request(app, "/telegram/emparejar", cookie=cookie)
    fields = _stage_form(page, _envelope())
    assert (
        _request(
            app,
            "/telegram/emparejar",
            method="POST",
            cookie=cookie,
            payload=fields,
            origin="https://evil.example.test",
        )[0]
        == 403
    )
    assert (
        _request(
            app,
            "/telegram/emparejar",
            method="POST",
            cookie=cookie,
            payload={**fields, "csrf": "wrong"},
        )[0]
        == 403
    )
    assert _request(
        app,
        "/telegram/emparejar",
        method="POST",
        cookie=cookie,
        payload={**fields, "envelope": TOKEN},
    )[0] in (400, 422)
    assert not stage_path.exists()

    app_without_stage, key2, credential2 = _app_with_stage(tmp_path / "other.sqlite3", None)
    cookie2 = _login(app_without_stage, key2, credential2)
    assert (
        _request(
            app_without_stage,
            "/telegram/emparejar",
            method="POST",
            cookie=cookie2,
            payload=fields,
        )[0]
        == 404
    )


def test_post_does_not_reflect_or_log_ciphertext_on_failure(tmp_path: Path) -> None:
    calls: list[bytes] = []

    def rejected_stage(envelope: bytes) -> PairingStageReceipt:
        calls.append(envelope)
        raise RuntimeError("sensitive: " + TOKEN)

    app, key, credential = _app_with_stage(tmp_path / "boca.sqlite3", rejected_stage)
    cookie = _login(app, key, credential)
    _, _, page = _request(app, "/telegram/emparejar", cookie=cookie)
    envelope = _envelope()
    fields = _stage_form(page, envelope)
    status, _, body = _request(
        app, "/telegram/emparejar", method="POST", cookie=cookie, payload=fields
    )
    assert status == 503 and calls == [envelope]
    assert TOKEN.encode() not in body and envelope not in body
    assert base64.urlsafe_b64encode(envelope).rstrip(b"=") not in body


def test_post_rejects_duplicate_form_fields_before_stage(tmp_path: Path) -> None:
    staged: list[bytes] = []
    app, key, credential = _app_with_stage(tmp_path / "boca.sqlite3", staged.append)
    cookie = _login(app, key, credential)
    _, _, page = _request(app, "/telegram/emparejar", cookie=cookie)
    fields = _stage_form(page, _envelope())
    body = urlencode(fields).encode() + b"&envelope=duplicate"
    status, _, _ = _request(app, "/telegram/emparejar", method="POST", cookie=cookie, payload=body)
    assert status == 400 and staged == []
