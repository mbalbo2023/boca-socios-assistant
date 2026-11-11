"""R179: owner-only offline journey across socios, activity and Telegram.

No HTTP listener, provider, real site, Telegram API or browser is instantiated.
This verifies that a completed local enrollment is not an operational ack.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from boca_socios.panel.site_url_settings import SiteUrlSettingsStore
from test_private_beta_panel import FakeHost, _app, _login, _passkey, _request


def _fields(page: bytes) -> dict[str, str]:
    return {
        field: re.search(rb'name="' + field.encode("ascii") + rb'" value="([^"]+)"', page)
        .group(1)
        .decode("ascii")
        for field in ("csrf", "operation_id")
    }


def test_one_owner_enrollment_does_not_trigger_browser_telegram_or_real_reservation(
    tmp_path: Path,
) -> None:
    provider, key, credential_id = _passkey([0.0])
    host = FakeHost()
    wakes: list[str] = []
    app, db = _app(tmp_path / "boca.sqlite3", provider, host, bot_control=wakes.append)

    # Private resources must not be discoverable before passkey authentication.
    for path in ("/socios", "/socios/nuevo", "/control/actividad.json"):
        assert _request(app, path)[0] == 401

    cookie = _login(app, key, credential_id)
    assert app.owner_session_ready()
    code, headers, form = _request(app, "/socios/nuevo", cookie=cookie)
    assert code == 200 and headers["Cache-Control"] == "no-store"
    fields = {
        **_fields(form),
        "alias": "Socio R179",
        "email": "owner.fixture@example.test",
        "password": "R179_private_password_NeverLog",
        "consent": "yes",
    }
    code, _, receipt = _request(app, "/socios", cookie=cookie, method="POST", payload=fields)
    assert code == 201 and b"ninguna reserva" in receipt

    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM members").fetchone() == (1,)
        assert conn.execute("SELECT COUNT(*) FROM credentials").fetchone() == (1,)
        # Successful enrollment does not create a reservation or dispatch.
        assert conn.execute("SELECT COUNT(*) FROM ticket_requests").fetchone() == (0,)
        assert conn.execute("SELECT COUNT(*) FROM notification_outbox").fetchone() == (0,)

    assert SiteUrlSettingsStore.for_database(db.path).read() is None
    code, _, listing = _request(app, "/socios", cookie=cookie)
    assert code == 200 and b"Socio R179" in listing
    code, _, activity = _request(app, "/control/actividad.json", cookie=cookie)
    assert code == 200
    projection = json.loads(activity)
    assert projection["browser_detail"] == "fixed_stages_only"
    assert all(
        item["source"] in ("owner", "host", "simulation", "chromium")
        for item in projection["events"]
    )

    for path in ("/telegram/configurar", "/telegram/emparejar", "/control/actividad"):
        code, _, page = _request(app, path, cookie=cookie)
        assert code == 200
        for secret in (b"owner.fixture@example.test", b"R179_private_password_NeverLog"):
            assert secret not in page
    assert b"owner.fixture@example.test" not in listing + activity
    assert b"R179_private_password_NeverLog" not in listing + activity
    assert host.calls == [] and wakes == []


def test_wrong_origin_cannot_consume_local_member_form_or_leak_secrets(tmp_path: Path) -> None:
    provider, key, credential_id = _passkey([0.0])
    app, db = _app(tmp_path / "boca.sqlite3", provider, FakeHost())
    cookie = _login(app, key, credential_id)
    form = _request(app, "/socios/nuevo", cookie=cookie)[2]
    fields = {
        **_fields(form),
        "alias": "Socio Rechazado",
        "email": "reject.fixture@example.test",
        "password": "Synthetic-R179-secret",
        "consent": "yes",
    }
    code, _, body = _request(
        app,
        "/socios",
        cookie=cookie,
        method="POST",
        payload=fields,
        origin="https://untrusted.example.test",
    )
    assert code == 403
    assert b"Synthetic-R179-secret" not in body
    assert b"reject.fixture@example.test" not in body
    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM members").fetchone() == (0,)
