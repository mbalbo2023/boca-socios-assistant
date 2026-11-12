"""Passkey-only 8443 token monitor, unrelated to manual legacy navigation."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from urllib.parse import urlencode

from boca_socios.queue.pass_observation import QueuePassObservation
from boca_socios.queue.private_pass_monitor import PrivateQueuePassMonitor
from boca_socios.security.member_auth_contract import (
    BocaAuthObservation,
    PrivateBocaAuthMonitor,
)
from test_private_beta_panel import (
    PERMISSIONS,
    FakeHost,
    _app,
    _login,
    _passkey,
    _request,
)

AT = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
MEMBER = "00000000-0000-0000-0000-000000000101"
EVENT = "00000000-0000-0000-0000-000000000102"
SESSION = "00000000-0000-0000-0000-000000000103"
QUEUE_URL = "https://sandbox.invalid/queue?e=local&queueittoken=private%2Fpass%3D&next=%2Fhome"


def _observations() -> tuple[PrivateQueuePassMonitor, PrivateBocaAuthMonitor]:
    queue = PrivateQueuePassMonitor()
    queue.observe(
        QueuePassObservation.from_observed_url(
            member_id=MEMBER,
            event_id=EVENT,
            session_id=SESSION,
            target_url=QUEUE_URL,
            observed_at=AT,
        )
    )
    auth = PrivateBocaAuthMonitor()
    auth.observe(
        BocaAuthObservation.from_provider_response(
            member_id=MEMBER,
            provider_payload=b'{"token":"private-boca-token","refreshToken":"private-boca-refresh"}',
            observed_at=AT,
        )
    )
    return queue, auth


def _form(page: bytes, kind: str) -> dict[str, str]:
    for form in re.findall(
        rb'<form method="post" action="/monitor/tokens/revelar">(.*?)</form>', page, re.S
    ):
        fields = {
            name.decode(): unescape(value.decode())
            for name, value in re.findall(rb'name="([^"]+)" value="([^"]*)"', form)
        }
        if fields.get("kind") == kind:
            return fields
    raise AssertionError("no owner-only reveal form for selected flow")


def test_unauthenticated_and_readonly_sessions_never_reveal_private_tokens(tmp_path: Path) -> None:
    queue, auth = _observations()
    provider, key, credential = _passkey([0.0])
    host = FakeHost()
    app, _ = _app(tmp_path / "boca.sqlite3", provider, host, queue_monitor=queue, auth_monitor=auth)
    assert _request(app, "/monitor/tokens")[0] == 401
    assert _request(app, "/monitor/tokens/revelar", method="POST")[0] == 401
    cookie = _login(app, key, credential)
    status, headers, page = _request(app, "/monitor/tokens", cookie=cookie)
    assert status == 200 and headers["Cache-Control"] == "no-store"
    assert b"Queue-it" in page and b"Boca" in page
    assert b"observado_no_validado" in page
    assert b"private/pass" not in page and b"private-boca-token" not in page
    assert b"private-boca-refresh" not in page
    assert b"private%2Fpass%3D" not in page
    assert b'href="/monitor/tokens"' in _request(app, "/", cookie=cookie)[2]
    assert host.calls == []

    read_permissions = PERMISSIONS - {"simulation:write"}
    readonly_provider, readonly_key, readonly_credential = _passkey(
        [0.0], permissions=frozenset(read_permissions)
    )
    readonly_app, _ = _app(
        tmp_path / "readonly" / "boca.sqlite3",
        readonly_provider,
        FakeHost(),
        queue_monitor=queue,
        auth_monitor=auth,
    )
    readonly_cookie = _login(readonly_app, readonly_key, readonly_credential)
    assert _request(readonly_app, "/monitor/tokens", cookie=readonly_cookie)[0] == 200
    assert (
        b'action="/monitor/tokens/revelar"'
        not in _request(readonly_app, "/monitor/tokens", cookie=readonly_cookie)[2]
    )
    code, _, body = _request(
        readonly_app, "/monitor/tokens/revelar", cookie=readonly_cookie, method="POST"
    )
    assert code == 403 and b"private-boca-token" not in body


def test_owner_can_deliberately_reveal_copy_full_queue_url_only_once(tmp_path: Path) -> None:
    queue, auth = _observations()
    provider, key, credential = _passkey([0.0])
    app, _ = _app(
        tmp_path / "boca.sqlite3", provider, FakeHost(), queue_monitor=queue, auth_monitor=auth
    )
    cookie = _login(app, key, credential)
    fields = _form(_request(app, "/monitor/tokens", cookie=cookie)[2], "queue")

    code, _, body = _request(
        app,
        "/monitor/tokens/revelar",
        cookie=cookie,
        method="POST",
        payload=fields,
        origin="https://not-owner.invalid",
    )
    assert code == 403 and b"private/pass" not in body
    code, _, body = _request(
        app,
        "/monitor/tokens/revelar",
        cookie=cookie,
        method="POST",
        payload={**fields, "csrf": "invalid"},
    )
    assert code == 403 and b"private/pass" not in body
    code, headers, body = _request(
        app, "/monitor/tokens/revelar", cookie=cookie, method="POST", payload=fields
    )
    assert code == 200 and headers["Cache-Control"] == "no-store"
    assert b"private/pass=" in body
    assert QUEUE_URL.replace("&", "&amp;").encode() in body
    assert b"Copiar URL completa" in body and b"Copiar token completo" in body
    assert b"navigator.clipboard.writeText" in body
    assert b"private-boca-token" not in body
    code, _, replay = _request(
        app, "/monitor/tokens/revelar", cookie=cookie, method="POST", payload=fields
    )
    assert code == 409 and b"private/pass=" not in replay


def test_boca_response_reveal_is_independent_and_no_endpoint_is_called(tmp_path: Path) -> None:
    queue, auth = _observations()
    provider, key, credential = _passkey([0.0])
    host = FakeHost()
    app, _ = _app(tmp_path / "boca.sqlite3", provider, host, queue_monitor=queue, auth_monitor=auth)
    cookie = _login(app, key, credential)
    fields = _form(_request(app, "/monitor/tokens", cookie=cookie)[2], "boca")
    code, headers, body = _request(
        app, "/monitor/tokens/revelar", cookie=cookie, method="POST", payload=fields
    )
    assert code == 200 and headers["Cache-Control"] == "no-store"
    assert b"private-boca-token" in body and b"private-boca-refresh" in body
    assert b"Copiar token completo" in body and b"Copiar refreshToken completo" in body
    assert b"private/pass" not in body and b"private%2Fpass" not in body
    assert host.calls == []


def test_default_new_token_view_is_inert_and_does_not_start_legacy(tmp_path: Path) -> None:
    provider, key, credential = _passkey([0.0])
    host = FakeHost()
    wakes: list[str] = []
    app, _ = _app(tmp_path / "boca.sqlite3", provider, host, bot_control=wakes.append)
    cookie = _login(app, key, credential)
    status, _, body = _request(app, "/monitor/tokens", cookie=cookie)
    assert status == 200
    assert b"Sin observaciones" in body
    assert b"No hay credenciales de sesi" in body
    assert b'action="/monitor/tokens/revelar"' not in body
    assert wakes == [] and host.calls == []
    assert not (tmp_path / "boca-tokens.sqlite3").exists()


def test_reveal_rejects_query_string_and_mismatched_identity(tmp_path: Path) -> None:
    queue, auth = _observations()
    provider, key, credential = _passkey([0.0])
    app, _ = _app(
        tmp_path / "boca.sqlite3", provider, FakeHost(), queue_monitor=queue, auth_monitor=auth
    )
    cookie = _login(app, key, credential)
    fields = _form(_request(app, "/monitor/tokens", cookie=cookie)[2], "queue")
    mismatch = {**fields, "session_id": "00000000-0000-0000-0000-000000000999"}
    assert _request(app, "/monitor/tokens/revelar", cookie=cookie, method="POST", payload=mismatch)[
        0
    ] in (404, 409)
    code, _, _ = _request(
        app,
        "/monitor/tokens",
        cookie=cookie,
        extra={"QUERY_STRING": urlencode({"queueittoken": "leak"})},
    )
    assert code == 400


def test_queue_token_can_be_copied_even_without_observed_target_url(tmp_path: Path) -> None:
    queue = PrivateQueuePassMonitor()
    queue.observe(
        QueuePassObservation.observed(
            member_id=MEMBER,
            event_id=EVENT,
            session_id=SESSION,
            token="observed-token-without-url",
            target_url=None,
            observed_at=AT,
        )
    )
    provider, key, credential = _passkey([0.0])
    app, _ = _app(tmp_path / "boca.sqlite3", provider, FakeHost(), queue_monitor=queue)
    cookie = _login(app, key, credential)
    fields = _form(_request(app, "/monitor/tokens", cookie=cookie)[2], "queue")
    code, _, body = _request(
        app, "/monitor/tokens/revelar", cookie=cookie, method="POST", payload=fields
    )
    assert code == 200
    assert b"observed-token-without-url" in body
    assert b"URL completa no observada" in body


def test_monitor_refreshes_do_not_exhaust_the_owner_operation_budget(tmp_path: Path) -> None:
    queue, auth = _observations()
    provider, key, credential = _passkey([0.0])
    app, _ = _app(
        tmp_path / "boca.sqlite3", provider, FakeHost(), queue_monitor=queue, auth_monitor=auth
    )
    cookie = _login(app, key, credential)
    first = _form(_request(app, "/monitor/tokens", cookie=cookie)[2], "queue")
    for _ in range(40):
        code, _, page = _request(app, "/monitor/tokens", cookie=cookie)
        assert code == 200
        assert _form(page, "queue")["operation_id"] == first["operation_id"]


def test_owner_token_live_snapshot_contains_metadata_but_no_bearer_material(
    tmp_path: Path,
) -> None:
    queue, auth = _observations()
    provider, key, credential = _passkey([0.0])
    host = FakeHost()
    app, _ = _app(tmp_path / "boca.sqlite3", provider, host, queue_monitor=queue, auth_monitor=auth)
    app._now = lambda: AT
    assert _request(app, "/monitor/tokens.json")[0] == 401
    cookie = _login(app, key, credential)

    code, headers, body = _request(app, "/monitor/tokens.json", cookie=cookie)
    assert code == 200
    assert headers["Content-Type"] == "application/json"
    assert headers["Cache-Control"] == "no-store"
    assert b"private" not in body and b"queueittoken" not in body
    assert b"refreshToken" not in body and b"sandbox.invalid" not in body
    snapshot = json.loads(body)
    assert snapshot == {
        "version": 1,
        "queue_source": "IN_MEMORY",
        "boca_source": "IN_MEMORY",
        "queue_observations": 1,
        "boca_observations": 1,
        "last_observed_at": AT.isoformat(),
        "observed_at": AT.isoformat(),
    }
    assert host.calls == []


def test_unwired_token_monitor_is_honest_and_has_accessible_refresh_controls(
    tmp_path: Path,
) -> None:
    provider, key, credential = _passkey([0.0])
    app, _ = _app(tmp_path / "boca.sqlite3", provider, FakeHost())
    cookie = _login(app, key, credential)

    code, _, body = _request(app, "/monitor/tokens", cookie=cookie)
    assert code == 200
    assert b"Fuente Queue-it no conectada" in body
    assert b"Fuente Boca no conectada" in body
    assert b'id="token-monitor-refresh"' in body
    assert b'id="token-monitor-live"' in body
    assert b"/monitor/tokens.json" in body
    assert b"5000" in body

    code, _, raw = _request(app, "/monitor/tokens.json", cookie=cookie)
    assert code == 200
    snapshot = json.loads(raw)
    assert snapshot["queue_source"] == "NOT_CONNECTED"
    assert snapshot["boca_source"] == "NOT_CONNECTED"
    assert snapshot["queue_observations"] == 0
    assert snapshot["boca_observations"] == 0
    assert snapshot["last_observed_at"] is None
