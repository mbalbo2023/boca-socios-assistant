"""The private page receives actual protected evidence without database migration."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from boca_socios import telegram_bootstrap as bootstrap
from boca_socios import telegram_status_publication as publication
from boca_socios.host_boca_installed_admin import publish_telegram_observation
from boca_socios.host_telegram_status import publish_installed_status
from boca_socios.notify.projection import load_telegram_admin
from boca_socios.panel.member_sector_store import MemberSectorStore
from boca_socios.panel.private_ui import telegram_admin
from test_r294_installed_admin import SOURCE, canonical, document, local_database


def test_strict_writer_replaces_old_status_without_touching_database_or_sector_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = local_database(tmp_path)
    before = database.read_bytes()

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("status publication cannot migrate sector storage")

    monkeypatch.setattr(MemberSectorStore, "migrate", forbidden)
    now = datetime.now(UTC)
    value = document()
    value.update(
        observed_at=now.isoformat(),
        configured="VERIFIED",
        paired="VERIFIED",
        sender="RUNNING",
        sender_id="9" * 64,
    )
    raw = canonical(value)
    assert (
        publish_telegram_observation(database, raw, expected_source_sha=SOURCE, now=now)
        == hashlib.sha256(raw).hexdigest()
    )
    snapshot = load_telegram_admin(
        database, staging_available=True, expected_source_sha=SOURCE, now=now
    )
    html = telegram_admin(snapshot).decode()
    assert "Chat emparejado y verificado" in html and "Emisor en ejecución" in html
    assert "No confirmada" in html
    assert database.read_bytes() == before
    assert not database.with_name("boca_sector_preferences.sqlite3").exists()
    later = load_telegram_admin(
        database,
        staging_available=True,
        expected_source_sha=SOURCE,
        now=now + timedelta(seconds=301),
    )
    assert later.receipt_state == "STALE"
    assert "Última observación histórica" in telegram_admin(later).decode()


def test_image_derives_prepared_and_partial_custody_status_without_trusting_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_database(tmp_path)
    custody = tmp_path / "custody"
    custody.mkdir(mode=0o700)
    monkeypatch.setattr(bootstrap, "UID", os.geteuid())
    bootstrap.prepare(custody, uid=os.geteuid())
    value = document()
    request = {
        key: item
        for key, item in value.items()
        if key not in {"version", "configured", "paired", "human_receipt"}
    }
    result = publication.publish(tmp_path, custody, request)
    assert result["configured"] == "ABSENT" and result["paired"] == "NOT_PAIRED"
    # A lone partial marker must not be described as absent or configured.
    (custody / "telegram_pairing_pending_v2").write_bytes(b"partial")
    result = publication.publish(tmp_path, custody, request)
    assert result["configured"] == result["paired"] == "UNVERIFIED"
    with pytest.raises(ValueError):
        publication.publish(tmp_path, custody, {**request, "configured": "VERIFIED"})


def test_publication_failure_preserves_previous_observation(tmp_path: Path) -> None:
    database = local_database(tmp_path)
    now = datetime.now(UTC)
    value = document()
    value["observed_at"] = now.isoformat()
    raw = canonical(value)
    publish_telegram_observation(database, raw, expected_source_sha=SOURCE, now=now)
    with pytest.raises(ValueError):
        publish_telegram_observation(database, raw, expected_source_sha="a" * 40, now=now)
    assert database.with_name("boca_telegram_admin_status_v1.json").read_bytes() == raw


@pytest.mark.parametrize("running,expected", [(True, None), (False, "ABSENT"), (False, "VERIFIED")])
def test_fresh_custody_downgrade_is_published_but_cannot_certify_ready_or_prepared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    running: bool,
    expected: str | None,
) -> None:
    database = local_database(tmp_path)
    custody = tmp_path / "custody"
    custody.mkdir(mode=0o700)
    (custody / "telegram_pairing_pending_v2").write_bytes(b"partial-state")
    monkeypatch.setattr(bootstrap, "UID", os.geteuid())
    value = document()
    context = SimpleNamespace(
        healthy=lambda: None,
        attempt_id=value["observation_run_id"],
        volumes=(("boca-socios_boca_telegram", str(custody)),),
        installation=SimpleNamespace(
            source_sha=SOURCE,
            installation_run_id=value["installation_run_id"],
            controller_id=value["controller_id"],
            worker_id=value["worker_id"],
            pair=SimpleNamespace(sender_id="9" * 64 if running else "", sender_running=running),
        ),
    )
    maintenance = SimpleNamespace(
        call=lambda operation, request: publication.publish(tmp_path, custody, request)
    )
    with pytest.raises(ValueError, match="custody_changed"):
        publish_installed_status(context, maintenance, expected_custody=expected)
    snapshot = load_telegram_admin(
        database, staging_available=True, expected_source_sha=SOURCE, now=datetime.now(UTC)
    )
    assert snapshot.receipt_state == "FRESH"
    assert snapshot.host_observation.configured == "UNVERIFIED"
    assert snapshot.host_observation.paired == "UNVERIFIED"
    if not running:
        # Explicit recovery of the controller alone never asserts pairing.
        publish_installed_status(context, maintenance)
