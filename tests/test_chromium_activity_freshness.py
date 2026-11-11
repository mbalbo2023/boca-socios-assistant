"""Old fixed-category Chromium evidence cannot masquerade as live activity."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from boca_socios.browser.activity_events import read_chromium_events
from boca_socios.panel.worker_activity import read_worker_activity
from test_worker_live_activity import _private_app


@pytest.fixture
def chromium_events_path() -> Iterator[Path]:
    with TemporaryDirectory(prefix="boca-ipc-fresh-") as temporary:
        directory = Path(temporary) / "ipc"
        directory.mkdir(mode=0o711)
        yield directory / "chromium-events.jsonl"


def _record_stages(path: Path, *entries: tuple[str, str]) -> None:
    path.write_text(
        "".join(
            json.dumps({"v": 1, "e": code, "t": at}, separators=(",", ":")) + "\n"
            for at, code in entries
        ),
        encoding="ascii",
    )
    path.chmod(0o644)


def _read(path: Path, observed_at: datetime):
    return read_chromium_events(
        path=path,
        owner_uid=os.geteuid(),
        owner_gid=os.getegid(),
        observed_at=observed_at,
    )


def test_old_chromium_events_do_not_count_as_current(chromium_events_path: Path) -> None:
    _record_stages(
        chromium_events_path,
        ("2026-11-11T11:40:00+00:00", "launch_requested"),
        ("2026-11-11T11:41:00+00:00", "launched"),
    )

    snapshot = _read(chromium_events_path, datetime(2026, 11, 11, 12, tzinfo=UTC))

    assert snapshot.state == "degraded"
    assert snapshot.events == ()
    assert snapshot.stale is True


def test_empty_chromium_file_cannot_claim_stages_are_available(
    chromium_events_path: Path,
) -> None:
    chromium_events_path.touch(mode=0o644)

    snapshot = _read(chromium_events_path, datetime(2026, 11, 11, 12, tzinfo=UTC))

    assert snapshot.state == "degraded"
    assert snapshot.events == ()
    assert snapshot.stale is False


def test_new_events_exclude_old_history_from_same_file(chromium_events_path: Path) -> None:
    _record_stages(
        chromium_events_path,
        ("2026-11-11T11:40:00+00:00", "browser_closed"),
        ("2026-11-11T11:55:00+00:00", "launch_requested"),
        ("2026-11-11T11:59:00+00:00", "launched"),
    )

    snapshot = _read(chromium_events_path, datetime(2026, 11, 11, 12, tzinfo=UTC))

    assert snapshot.state == "available"
    assert [event.code for event in snapshot.events] == ["launch_requested", "launched"]
    assert snapshot.stale is False


def test_private_projection_explains_stale_source_without_replaying_old_stages(
    chromium_events_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed_at = datetime(2026, 11, 11, 12, tzinfo=UTC)
    _record_stages(chromium_events_path, ("2026-11-11T11:30:00+00:00", "page_ready"))
    _app, _db, _cookie = _private_app(tmp_path)
    monkeypatch.setattr(
        "boca_socios.panel.worker_activity.read_chromium_events",
        partial(
            read_chromium_events,
            path=chromium_events_path,
            owner_uid=os.geteuid(),
            owner_gid=os.getegid(),
        ),
    )

    snapshot = read_worker_activity(tmp_path / "boca.sqlite3", observed_at=observed_at)

    assert snapshot.chromium_telemetry == "degraded"
    assert [event.message for event in snapshot.events if event.source == "chromium"] == [
        "Chromium: sólo hay telemetría antigua; no confirma un proceso activo."
    ]
    assert snapshot.events[-1].level == "warning"
