"""Passkey-authenticated Chrome -> encrypted V2 STAGING, not installation."""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Callable
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from cryptography.hazmat.primitives.asymmetric import ec

from boca_socios import telegram_bootstrap as bootstrap
from boca_socios.panel.private_http import PrivatePanelApplication
from boca_socios.panel.telegram_pairing_staging import (
    STAGING_FILENAME,
    PairingStageReceipt,
    PairingStageRequest,
    stage_private_telegram_pairing,
)
from test_private_beta_panel import ORIGIN, _app, _assertion, _login, _passkey, _request
from test_telegram_pairing_ui import TOKEN, _recipient, _run


def _app_with_stage(
    path: Path, stage: Callable[[PairingStageRequest], PairingStageReceipt] | None
) -> tuple[PrivatePanelApplication, Any, bytes, list[float]]:
    clock = [0.0]
    provider, key, credential = _passkey(clock)
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
    return app, key, credential, clock


def _stage_form(
    app: PrivatePanelApplication,
    cookie: str,
    page: bytes,
    envelope: bytes,
    key: ec.EllipticCurvePrivateKey,
    credential: bytes,
    clock: list[float],
) -> dict[str, str]:
    form = {
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
    clock[0] += 2.0
    status, _, body = _request(
        app,
        "/telegram/emparejar/desafio",
        method="POST",
        cookie=cookie,
        payload={
            "csrf": form["csrf"],
            "operation_id": form["operation_id"],
            "envelope_sha256": sha256(envelope).hexdigest(),
        },
    )
    assert status == 200
    issued = json.loads(body)
    signed = asdict(_assertion(key, credential, issued["challenge"]))
    return {
        **form,
        "request_nonce": issued["request_nonce"],
        "challenged_at": str(issued["challenged_at"]),
        **signed,
    }


def _envelope() -> bytes:
    _, _, fragment = _recipient()
    return bootstrap._unb64(_run(fragment)["output"], maximum=4096)


def test_get_is_authenticated_and_post_stages_ciphertext_once(tmp_path: Path) -> None:
    stage_path = tmp_path / STAGING_FILENAME
    app, key, credential, clock = _app_with_stage(
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
    fields = _stage_form(app, cookie, page, envelope, key, credential, clock)
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
        "owner_passkey": "UV_VERIFIED_ONLY",
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
    app, key, credential, clock = _app_with_stage(
        tmp_path / "boca.sqlite3",
        lambda envelope: stage_private_telegram_pairing(stage_path, envelope),
    )
    cookie = _login(app, key, credential)
    _, _, page = _request(app, "/telegram/emparejar", cookie=cookie)
    fields = _stage_form(app, cookie, page, _envelope(), key, credential, clock)
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

    app_without_stage, key2, credential2, _clock2 = _app_with_stage(
        tmp_path / "other.sqlite3", None
    )
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

    def rejected_stage(request: PairingStageRequest) -> PairingStageReceipt:
        calls.append(request.sealed_envelope)
        raise RuntimeError("sensitive: " + TOKEN)

    app, key, credential, clock = _app_with_stage(tmp_path / "boca.sqlite3", rejected_stage)
    cookie = _login(app, key, credential)
    _, _, page = _request(app, "/telegram/emparejar", cookie=cookie)
    envelope = _envelope()
    fields = _stage_form(app, cookie, page, envelope, key, credential, clock)
    status, _, body = _request(
        app, "/telegram/emparejar", method="POST", cookie=cookie, payload=fields
    )
    assert status == 503 and calls == [envelope]
    assert TOKEN.encode() not in body and envelope not in body
    assert base64.urlsafe_b64encode(envelope).rstrip(b"=") not in body


def test_post_rejects_duplicate_form_fields_before_stage(tmp_path: Path) -> None:
    staged: list[PairingStageRequest] = []
    app, key, credential, clock = _app_with_stage(tmp_path / "boca.sqlite3", staged.append)
    cookie = _login(app, key, credential)
    _, _, page = _request(app, "/telegram/emparejar", cookie=cookie)
    fields = _stage_form(app, cookie, page, _envelope(), key, credential, clock)
    body = urlencode(fields).encode() + b"&envelope=duplicate"
    status, _, _ = _request(app, "/telegram/emparejar", method="POST", cookie=cookie, payload=body)
    assert status == 400 and staged == []
