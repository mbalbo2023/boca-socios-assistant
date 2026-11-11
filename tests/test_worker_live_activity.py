"""Owner-only activity timeline, without raw logs or protected browser imports."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization

from boca_socios.browser.activity_events import ChromiumActivity, ChromiumStage
from boca_socios.panel.lifecycle_intents import LifecycleIntentStore, host_marker
from boca_socios.panel.passkey import PasskeyOwnerAuthentication
from test_private_beta_panel import EVENT_ID, ORIGIN, FakeHost, _app, _login, _passkey, _request


def _private_app(tmp_path: Path):
    provider, key, credential_id = _passkey([0.0])
    app, db = _app(tmp_path / "boca.sqlite3", provider, FakeHost(), bot_control=lambda _: None)
    return app, db, _login(app, key, credential_id)


@pytest.fixture
def isolated_ipc_directory() -> Iterator[Path]:
    # AF_UNIX paths have a kernel byte limit. A pytest-xdist runner's nested
    # tmp_path may exceed it even though this event file is a regular file.
    # Test against a short, genuine directory, keeping exact IPC custody.
    with TemporaryDirectory(prefix="boca-ipc-") as temporary:
        directory = Path(temporary) / "ipc"
        directory.mkdir(mode=0o711)
        yield directory


def test_private_live_activity_returns_only_known_verified_lifecycle_stages(tmp_path: Path) -> None:
    app, db, cookie = _private_app(tmp_path)
    operation = str(uuid4())
    LifecycleIntentStore(db).request("bot", "start", operation, on_demand=True)
    with db.connection() as connection, connection:
        for stage in ("CLAIMED", "APPLIED"):
            connection.execute(
                "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
                host_marker(operation, "bot", "start", stage),
            )
        connection.execute(
            "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
            (str(uuid4()), "private_secret_token_WOULD_BE_BAD"),
        )
    code, headers, data = _request(app, "/control/actividad.json", cookie=cookie)
    assert code == 200
    assert headers["Content-Type"] == "application/json"
    assert headers["Cache-Control"] == "no-store"
    report = json.loads(data)
    assert report["browser_detail"] == "fixed_stages_only"
    assert [item["level"] for item in report["events"] if item["source"] == "host"] == [
        "progress",
        "success",
    ]
    assert any(item["source"] == "owner" for item in report["events"])
    assert all(set(item) == {"at", "source", "level", "message"} for item in report["events"])
    assert operation.encode() not in data
    assert b"private_secret_token" not in data
    assert b"synthetic" not in data


def test_activity_requires_owner_passkey_permission_and_same_origin(tmp_path: Path) -> None:
    app, _db, cookie = _private_app(tmp_path)
    assert _request(app, "/control/actividad.json")[0] == 401
    assert _request(app, "/control/actividad")[0] == 401
    assert (
        _request(
            app,
            "/control/actividad.json",
            cookie=cookie,
            extra={"HTTP_HOST": "evil.example.test"},
        )[0]
        == 400
    )
    assert (
        _request(app, "/control/actividad.json", cookie=cookie, extra={"QUERY_STRING": "x=1"})[0]
        == 400
    )
    code, headers, body = _request(app, "/control/actividad", cookie=cookie)
    assert code == 200
    assert b"Actividad del worker y Chromium" in body
    assert b"Pausar actualizaciones" in body
    assert b"Actualizar ahora" in body
    assert b"/control/actividad.json" in body
    assert "script-src 'sha256-" in headers["Content-Security-Policy"]


def test_activity_denies_owner_session_without_simulation_permission(tmp_path: Path) -> None:
    _original, key, credential_id = _passkey([0.0])
    provider = PasskeyOwnerAuthentication(
        credential_id=credential_id,
        public_key_der=key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
        rp_id="boca.example.test",
        origin=ORIGIN,
        owner_subject="owner",
        permissions=frozenset({"members:enroll", "local-status:read"}),
        clock=lambda: 0.0,
    )
    app, _db = _app(tmp_path / "boca.sqlite3", provider, FakeHost())
    cookie = _login(app, key, credential_id)
    assert _request(app, "/control/actividad.json", cookie=cookie)[0] == 403
    assert _request(app, "/control/actividad", cookie=cookie)[0] == 403


def test_panel_merges_only_allowlisted_chromium_and_command_states(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, db, cookie = _private_app(tmp_path)
    member_id, request_id, command_id = (str(uuid4()) for _ in range(3))
    with db.connection() as connection, connection:
        connection.execute(
            "INSERT INTO members(member_id,email,consent_recorded_at) VALUES (?,?,?)",
            (member_id, "private.person@example.test", "2026-11-10T12:00:00Z"),
        )
        connection.execute(
            "INSERT INTO ticket_requests(request_id,member_id,event_id,quantity) VALUES (?,?,?,1)",
            (request_id, member_id, EVENT_ID),
        )
        connection.execute(
            "INSERT INTO beta_commands(command_id,request_id,state,created_at,updated_at) "
            "VALUES (?,?,'running',1,2)",
            (command_id, request_id),
        )
    monkeypatch.setattr(
        "boca_socios.panel.worker_activity.read_chromium_events",
        lambda **_kwargs: ChromiumActivity(
            "available", (ChromiumStage("2026-11-10T12:00:00+00:00", "launched"),)
        ),
    )
    code, _headers, data = _request(app, "/control/actividad.json", cookie=cookie)
    assert code == 200
    result = json.loads(data)
    assert result["chromium_telemetry"] == "available"
    assert any(item["source"] == "chromium" for item in result["events"])
    assert any(item["source"] == "simulation" for item in result["events"])
    assert b"private.person" not in data
    assert member_id.encode() not in data
    assert request_id.encode() not in data
    assert command_id.encode() not in data


def test_chromium_events_emit_fixed_codes_only_and_read_on_shared_directory(
    isolated_ipc_directory: Path,
) -> None:
    from boca_socios.browser.activity_events import (
        emit_chromium_event,
        read_chromium_events,
    )

    target = isolated_ipc_directory / "chromium-events.jsonl"
    emit_chromium_event(
        "launch_requested", path=target, owner_uid=os.geteuid(), owner_gid=os.getegid()
    )
    emit_chromium_event("launched", path=target, owner_uid=os.geteuid(), owner_gid=os.getegid())
    with pytest.raises(ValueError):
        emit_chromium_event(
            "token=secret", path=target, owner_uid=os.geteuid(), owner_gid=os.getegid()
        )
    observed = read_chromium_events(
        path=target,
        owner_uid=os.geteuid(),
        owner_gid=os.getegid(),
        observed_at=datetime.now(UTC),
    )
    assert observed.state == "available"
    assert [item.code for item in observed.events] == ["launch_requested", "launched"]
    assert target.stat().st_size < 1024
    assert target.stat().st_mode & 0o777 == 0o644


def test_chromium_activity_rejects_malformed_and_untrusted_files(
    isolated_ipc_directory: Path,
) -> None:
    from boca_socios.browser.activity_events import read_chromium_events

    path = isolated_ipc_directory / "chromium-events.jsonl"
    now = datetime.now(UTC)
    assert read_chromium_events(
        path=path, owner_uid=os.geteuid(), owner_gid=os.getegid(), observed_at=now
    ).state == ("missing")
    path.write_text('{"v":1,"e":"password=secret","t":0}\n', encoding="utf-8")
    path.chmod(0o644)
    result = read_chromium_events(
        path=path, owner_uid=os.geteuid(), owner_gid=os.getegid(), observed_at=now
    )
    assert result.state == "degraded" and not result.events
    path.unlink()
    path.symlink_to(isolated_ipc_directory.parent / "private_file")
    result = read_chromium_events(
        path=path, owner_uid=os.geteuid(), owner_gid=os.getegid(), observed_at=now
    )
    assert result.state == "degraded" and not result.events
