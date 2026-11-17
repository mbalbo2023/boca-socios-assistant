"""Offline owner form; synthetic Telegram values never leave temporary DATA."""

import base64
import fcntl
import json
import multiprocessing
import os
import re
import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace

import pytest
from cryptography.hazmat.primitives import serialization

from boca_socios import runtime, telegram_bootstrap
from boca_socios.panel import telegram_recipient
from boca_socios.panel.passkey import PasskeyOwnerAuthentication
from boca_socios.panel.private_http import PrivatePanelApplication
from test_host_boca_owner_acceptance_v2 import _assertion
from test_private_beta_panel import PERMISSIONS, _app, _passkey, _request
from test_telegram_pairing_runtime_optin import _settings

FILE = "boca_telegram_direct_stage_v1.json"
V2 = "boca_telegram_pairing_stage_v2.json"
SHA = "b" * 40
TOKEN = "123456:OfflineFixtureOnly"
CHAT = "987654321"
URL = "/telegram/configurar"
LOCAL = "http://localhost:8443"


@pytest.fixture
def area(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(telegram_bootstrap, "UID", os.geteuid())
    monkeypatch.setattr(telegram_recipient, "PUBLIC_DATA_DIR", root)
    return root


def bound(area, mode="off"):
    factory = getattr(runtime, "_configured_telegram_direct_stage", None)
    assert factory is not None, "Missing direct BETA DATA factory"
    return factory(replace(_settings(area, mode=mode), source_sha=SHA), boca_volume_root=area)


def _panel(area, permissions):
    fixture_provider, key, credential = _passkey([0.0])
    orig, _ = _app(area / "boca.sqlite3", fixture_provider)
    provider = PasskeyOwnerAuthentication(
        credential_id=credential,
        public_key_der=key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
        rp_id="localhost",
        origin=LOCAL,
        owner_subject="owner",
        permissions=permissions,
    )
    app = PrivatePanelApplication(
        origin=LOCAL,
        database_path=area / "boca.sqlite3",
        owner_subject="owner",
        passkey=provider,
        members=orig._members,
        commands=None,
        events={},
        telegram_direct_stage=bound(area),
        source_sha=SHA,
    )
    cookie = ""

    def request(path=URL, *, owner=True, **kwargs):
        return _request(
            app,
            path,
            cookie=cookie if owner else "",
            origin=kwargs.pop("origin", LOCAL),
            extra={"wsgi.url_scheme": "http", "HTTP_HOST": "localhost:8443"},
            **kwargs,
        )

    _, _, page = request("/ingresar")
    challenge = re.search(rb'data-challenge="([A-Za-z0-9_-]+)"', page).group(1)
    proof = _assertion(key, credential, base64.urlsafe_b64decode(challenge + b"=="))
    code, hdrs, _ = request(
        "/sesion",
        method="POST",
        content_type="application/json",
        payload=json.dumps(asdict(proof)).encode(),
    )
    assert code == 204
    cookie = hdrs["Set-Cookie"].split(";", 1)[0]
    return request


@pytest.fixture
def panel(area):
    return _panel(area, PERMISSIONS)


def test_reader_session_cannot_open_or_post_credentials(area):
    req = _panel(area, frozenset({"members:enroll", "local-status:read"}))
    assert req()[0] == 403 and req("/telegram/emparejar")[0] == 403
    assert req(method="POST", payload={"bot_token": TOKEN, "chat_id": CHAT})[0] == 403
    assert not (area / FILE).exists()


def fields(page):
    hidden = dict(re.findall(rb'name="(csrf|operation_id)" value="([^"]+)"', page))
    return {
        **{k.decode(): v.decode() for k, v in hidden.items()},
        "bot_token": TOKEN,
        "chat_id": CHAT,
    }


def test_native_owner_form_stage_receipt_and_replay(area, panel):
    assert panel(owner=False)[0] == 401
    for path in (URL, "/telegram/emparejar"):
        code, headers, page = panel(path)
        assert code == 200 and b'form method="post" action="/telegram/configurar"' in page
        assert b'type="password"' in page and b'name="chat_id"' in page
        assert b"Guardar configuraci" in page and b"disabled" not in page
        assert headers["Referrer-Policy"] == "same-origin"
        assert headers["Cache-Control"] == "no-store"
    data = fields(page)

    def post(**kw):
        return panel(method="POST", payload=data, **kw)

    assert post(owner=False)[0] == 401
    assert post(origin="http://foreign.invalid")[0] == 403
    assert panel(method="POST", payload={**data, "csrf": "wrong"})[0] == 403
    assert panel(method="POST", payload={**data, "source_sha": "a" * 40})[0] == 400
    assert not (area / FILE).exists()
    code, _, body = post()
    assert code == 202 and b"PENDING_INSTALLATION" in body
    assert TOKEN.encode() not in body and CHAT.encode() not in body
    assert post()[0] == 409
    path = area / FILE
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and path.stat().st_nlink == 1
    raw = path.read_bytes()
    saved = json.loads(raw)
    assert re.fullmatch("[a-f0-9]{64}", saved.pop("stage_id")) and saved.pop("staged_at") > 0
    assert saved == dict(
        version=1,
        uid=10001,
        purpose="boca-telegram-direct-owner-stage-v1",
        repository="mbalbo2023/boca-socios-assistant",
        source_sha=SHA,
        bot_token=TOKEN,
        chat_id=CHAT,
    )
    assert raw == json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":")).encode()
    code, _, page = panel()
    assert code == 200 and b"Pendiente de instalaci" in page and TOKEN.encode() not in page


@pytest.mark.parametrize(
    "field,value",
    [
        ("chat_id", "0"),
        ("chat_id", "-2"),
        ("chat_id", "01"),
        ("chat_id", str(2**52)),
        ("bot_token", "00:OfflineFixture"),
        ("bot_token", "0:OfflineFixture"),
        ("bot_token", str(2**52) + ":OfflineFixture"),
        ("bot_token", "1:tiny"),
    ],
)
def test_reject_invalid_private_credentials(area, panel, field, value):
    data = {**fields(panel()[2]), field: value}
    code, _, page = panel(method="POST", payload=data)
    assert code == 400 and not (area / FILE).exists() and TOKEN.encode() not in page


@pytest.mark.parametrize("name", [FILE, V2])
def test_preexisting_slot_or_symlink_is_never_overwritten(area, panel, name):
    data = fields(panel()[2])
    (area / name).symlink_to(area / "missing")
    assert panel(method="POST", payload=data)[0] == 409
    assert (area / name).is_symlink() and not (area / "missing").exists()


def test_unsafe_or_replaced_data_is_rejected(area, panel):
    data = fields(panel()[2])
    area.chmod(0o777)
    assert panel(method="POST", payload=data)[0] == 503
    assert not (area / FILE).exists()
    area.chmod(0o700)
    area.rename(area.with_name("old"))
    area.mkdir(mode=0o700)
    assert panel()[0] != 200
    assert not (area / FILE).exists()


def test_only_one_concurrent_writer_can_publish(area):
    stage = bound(area, "encrypted-only")
    from boca_socios.panel.telegram_direct_staging import DirectStageRequest

    request = DirectStageRequest(TOKEN, CHAT, SHA)
    assert TOKEN not in repr(request) and CHAT not in repr(request)
    with pytest.raises(ValueError):
        stage.save(replace(request, source_sha="e" * 40))

    def attempt(_):
        try:
            return stage.save(request).state
        except ValueError:
            return "CONFLICT"

    with ThreadPoolExecutor(4) as pool:
        assert sorted(pool.map(attempt, range(4))) == ["CONFLICT"] * 3 + ["PENDING_INSTALLATION"]
    assert list(area.iterdir()) == [area / FILE]


def test_private_stage_fsync_failure_preserves_no_final(area, monkeypatch):
    stage = bound(area)
    from boca_socios.panel.telegram_direct_staging import DirectStageRequest

    def failure(_fd):
        raise OSError(TOKEN)

    monkeypatch.setattr(os, "fsync", failure)
    with pytest.raises(ValueError) as failure_info:
        stage.save(DirectStageRequest(TOKEN, CHAT, SHA))
    assert TOKEN not in str(failure_info.value)
    assert list(area.iterdir()) == []


def test_missing_beta_data_never_prevents_unrelated_controller_start(area):
    settings = replace(_settings(area, mode="encrypted-only"), source_sha=SHA)
    area.rmdir()
    select = getattr(runtime, "_telegram_staging_for_beta", None)
    assert select is not None, "Need one selection point for both routes"
    direct, legacy = select(settings, boca_volume_root=area)
    assert direct is not None and legacy is None
    with pytest.raises(ValueError):
        direct.pending()


def test_stage_pins_volume_before_owner_op(area):
    stage = bound(area)
    area.rename(area.with_name("old-data"))
    area.mkdir(mode=0o700)
    from boca_socios.panel.telegram_direct_staging import DirectStageRequest

    with pytest.raises(ValueError):
        stage.save(DirectStageRequest(TOKEN, CHAT, SHA))
    assert list(area.iterdir()) == []


def _exit_at_publication(area, cut):
    """Clean child interpreter; a real exit bypasses all stream/finally cleanup."""
    from boca_socios.panel.telegram_direct_staging import DirectStageRequest

    telegram_bootstrap.UID = os.geteuid()
    telegram_recipient.PUBLIC_DATA_DIR = area
    stage = bound(area)
    original_link, original_fsync = os.link, os.fsync

    def link(*args, **kwargs):
        if cut == "before_link":
            os._exit(47)
        original_link(*args, **kwargs)
        if cut == "after_link":
            os._exit(47)

    def sync(fd):
        if cut == "directory_fsync" and stat.S_ISDIR(os.fstat(fd).st_mode):
            os._exit(47)
        original_fsync(fd)

    os.link, os.fsync = link, sync
    stage.save(DirectStageRequest(TOKEN, CHAT, SHA))


@pytest.mark.parametrize("cut", ["before_link", "after_link", "directory_fsync"])
def test_interrupted_after_file_fsync_blocks_display_and_all_future_writes(area, panel, cut):
    data = fields(panel()[2])
    child = multiprocessing.get_context("spawn").Process(
        target=_exit_at_publication, args=(area, cut)
    )
    child.start()
    child.join(timeout=15)
    if child.is_alive():
        child.kill()
        child.join(timeout=5)
        pytest.fail("interrupted writer did not exit")
    assert child.exitcode == 47
    (orphan,) = area.glob(f".{FILE}.*.tmp")
    before = orphan.read_bytes()
    assert stat.S_IMODE(orphan.stat().st_mode) == 0o600
    assert TOKEN.encode() in before and (area / FILE).exists() == (cut != "before_link")
    if cut != "before_link":
        assert orphan.samefile(area / FILE) and orphan.stat().st_nlink == 2
    for path in (URL, "/telegram/emparejar"):
        code, _, body = panel(path)
        assert code == 503 and TOKEN.encode() not in body
    code, _, body = panel(method="POST", payload=data)
    assert code == 503 and TOKEN.encode() not in body
    assert list(area.glob(f".{FILE}.*.tmp")) == [orphan]
    assert orphan.read_bytes() == before and (area / FILE).exists() == (cut != "before_link")


def test_owner_telegram_navigation_describes_direct_state_not_v2(panel):
    for path in ("/", "/telegram"):
        _, _, page = panel(path)
        assert b'href="/telegram/configurar"' in page
        assert all(
            term not in page.lower()
            for term in (
                b"recibo aprobado",
                b"cifrada",
                b"emparejar chat privado",
                b'href="/telegram/emparejar"',
            )
        )
    assert b"Sin guardar en este panel" in panel("/telegram")[2]
    assert panel(method="POST", payload=fields(panel()[2]))[0] == 202
    _, _, current = panel("/telegram")
    assert b"Pendiente de instalaci" in current and b"Sin comprobaci" in current
    assert TOKEN.encode() not in current and CHAT.encode() not in current


def test_concurrent_active_writer_conflicts_without_writing_another_slot(area, panel):
    data = fields(panel()[2])
    fd = os.open(area, os.O_DIRECTORY | os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        code, _, _ = panel(method="POST", payload=data)
        assert code == 409
    finally:
        os.close(fd)
    assert not (area / FILE).exists() and not list(area.glob(f".{FILE}.*.tmp"))
