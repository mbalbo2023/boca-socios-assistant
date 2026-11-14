"""Private Telegram administration uses local evidence, never provider calls."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from boca_socios.notify import projection
from boca_socios.notify.outbox import NoticeKind, NotificationRequest
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from boca_socios.notify.telegram_delivery import TelegramDeliveryCoordinator
from boca_socios.notify.telegram_transport import TelegramAck, TelegramNotice
from boca_socios.panel import private_ui, telegram_setup_ui

NOW = datetime(2026, 11, 14, 16, 5, tzinfo=UTC)
SOURCE = "a" * 40
RECEIPT_NAME = "boca_telegram_admin_status_v1.json"


class _AcceptedSender:
    def preflight(self) -> None:
        pass

    async def send(self, _notice: TelegramNotice) -> TelegramAck:
        return TelegramAck(17)


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    path = tmp_path / "boca.sqlite3"
    SqliteNotificationOutbox(path).migrate()
    return path


def _receipt() -> dict[str, object]:
    return {
        "version": 1,
        "source_sha": SOURCE,
        "observation_run_id": "43500000002",
        "installation_run_id": "43500000001",
        "controller_id": "b" * 64,
        "worker_id": "c" * 64,
        "sender_id": "d" * 64,
        "observed_at": "2026-11-14T16:04:30+00:00",
        "configured": "VERIFIED",
        "paired": "VERIFIED",
        "sender": "STOPPED",
        "human_receipt": "UNVERIFIED",
    }


def _write_receipt(database_path: Path, document: dict[str, object]) -> Path:
    path = database_path.with_name(RECEIPT_NAME)
    path.write_text(json.dumps(document), encoding="utf-8")
    path.chmod(0o600)
    return path


def _load(database_path: Path, *, now: datetime = NOW, staging_available: bool = True):
    loader = getattr(projection, "load_telegram_admin", None)
    assert callable(loader), "the private admin must load authenticated local evidence"
    return loader(
        database_path,
        staging_available=staging_available,
        expected_source_sha=SOURCE,
        now=now,
    )


def _render(snapshot) -> str:
    render = getattr(private_ui, "telegram_admin", None)
    assert callable(render), "Telegram needs its principal private administration view"
    return render(snapshot).decode("utf-8")


def test_staging_and_api_history_never_claim_pairing_sender_or_human_receipt(
    database_path: Path,
) -> None:
    outbox = SqliteNotificationOutbox(database_path)
    outbox.enqueue(NotificationRequest(uuid4(), NoticeKind.HEARTBEAT), now=NOW.timestamp())
    coordinator = TelegramDeliveryCoordinator(outbox, _AcceptedSender(), NOW.timestamp)
    coordinator.prepare_storage()
    asyncio.run(coordinator.tick())
    before = database_path.read_bytes()

    snapshot = _load(database_path)
    assert snapshot.receipt_state == "ABSENT"
    assert snapshot.host_observation is None
    assert snapshot.staging_available is True
    assert snapshot.history_available is True
    assert snapshot.notices[0].telegram_state == "api_accepted"
    rendered = _render(snapshot)
    assert "API aceptó" in rendered and "Recepción humana" in rendered
    assert "No confirmada" in rendered
    assert "Estado físico sin comprobación" in rendered
    assert database_path.read_bytes() == before
    assert not database_path.with_name(RECEIPT_NAME).exists()


@pytest.mark.parametrize(
    ("configured", "paired", "sender", "sender_id", "label"),
    [
        ("ABSENT", "NOT_PAIRED", "ABSENT", None, "Emisor no instalado"),
        ("VERIFIED", "NOT_PAIRED", "STOPPED", "d" * 64, "Emisor detenido"),
        ("VERIFIED", "VERIFIED", "RUNNING", "d" * 64, "Emisor en ejecución"),
    ],
)
def test_fresh_receipt_preserves_independent_effective_states(
    database_path: Path,
    configured: str,
    paired: str,
    sender: str,
    sender_id: str | None,
    label: str,
) -> None:
    document = _receipt()
    document.update(configured=configured, paired=paired, sender=sender, sender_id=sender_id)
    _write_receipt(database_path, document)

    snapshot = _load(database_path)
    assert snapshot.receipt_state == "FRESH"
    assert snapshot.host_observation is not None
    assert snapshot.host_observation.configured == configured
    assert snapshot.host_observation.paired == paired
    assert snapshot.host_observation.sender == sender
    rendered = _render(snapshot)
    assert label in rendered and "2026-11-14 13:04:30 ART" in rendered
    assert "No confirmada" in rendered


def test_old_receipt_is_retained_as_history_and_never_as_current_state(
    database_path: Path,
) -> None:
    document = _receipt()
    document["sender"] = "RUNNING"
    _write_receipt(database_path, document)

    snapshot = _load(database_path, now=NOW + timedelta(minutes=10))
    assert snapshot.receipt_state == "STALE"
    assert snapshot.host_observation is not None
    assert snapshot.host_observation.sender == "RUNNING"
    rendered = _render(snapshot)
    assert "Última observación histórica" in rendered
    assert "El estado actual no está comprobado" in rendered
    assert "Estado físico reciente" not in rendered


@pytest.mark.parametrize(
    "change",
    [
        {"source_sha": "e" * 40},
        {"observed_at": "2026-11-14T16:05:01+00:00"},
        {"observed_at": "2026-11-14T16:04:30"},
        {"version": True},
        {"extra_private_value": "never-render-this"},
        {"worker_id": "b" * 64},
        {"sender": "ABSENT", "sender_id": "d" * 64},
        {"configured": "ABSENT", "paired": "VERIFIED"},
        {"human_receipt": "CONFIRMED"},
    ],
)
def test_invalid_receipt_never_promotes_unverified_host_claims(
    database_path: Path, change: dict[str, object]
) -> None:
    document = _receipt()
    document.update(change)
    receipt_path = _write_receipt(database_path, document)
    original = receipt_path.read_bytes()

    snapshot = _load(database_path)
    assert snapshot.receipt_state == "INVALID"
    assert snapshot.host_observation is None
    rendered = _render(snapshot)
    assert "Estado físico sin comprobación" in rendered
    assert "never-render-this" not in rendered
    assert receipt_path.read_bytes() == original


def test_duplicate_json_fields_are_rejected_instead_of_using_the_last_claim(
    database_path: Path,
) -> None:
    path = _write_receipt(database_path, _receipt())
    path.write_text(path.read_text().replace('"version": 1', '"version": 0, "version": 1'))
    assert _load(database_path).receipt_state == "INVALID"


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "public", "oversized", "fifo"])
def test_unsafe_receipt_files_are_never_read_repaired_or_followed(
    database_path: Path, kind: str
) -> None:
    path = _write_receipt(database_path, _receipt())
    if kind in ("symlink", "hardlink"):
        target = path.with_name("unrelated.json")
        path.rename(target)
        if kind == "symlink":
            path.symlink_to(target)
        else:
            os.link(target, path)
    elif kind == "public":
        path.chmod(0o644)
    elif kind == "oversized":
        path.write_bytes(b"x" * 4097)
    else:
        path.unlink()
        os.mkfifo(path, 0o600)
    before = path.lstat()

    snapshot = _load(database_path)
    assert snapshot.receipt_state == "INVALID"
    assert snapshot.host_observation is None
    after = path.lstat()
    assert (after.st_ino, after.st_mode, after.st_size) == (
        before.st_ino,
        before.st_mode,
        before.st_size,
    )


def test_missing_history_is_localized_and_never_creates_storage(tmp_path: Path) -> None:
    path = tmp_path / "boca.sqlite3"
    _write_receipt(path, _receipt())

    snapshot = _load(path)
    assert snapshot.receipt_state == "FRESH"
    assert snapshot.history_available is False
    assert snapshot.notices == ()
    assert "Historial local no disponible" in _render(snapshot)
    assert not path.exists()


def test_telegram_navigation_reuses_existing_private_routes(database_path: Path) -> None:
    rendered = _render(_load(database_path))
    for route in ("/telegram/configurar", "/telegram/emparejar", "/avisos"):
        assert f'href="{route}"' in rendered
    assert '<a href="/telegram">Telegram</a>' in private_ui.home("fixture").decode()
    assert '<a href="/telegram">Telegram</a>' in telegram_setup_ui.page().decode()
    pairing = telegram_setup_ui.pairing_page().decode()
    assert '<a href="/telegram">Telegram</a>' in pairing
    assert "Nada se transmite al panel" not in pairing
