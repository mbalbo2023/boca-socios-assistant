"""Offline Boca event snapshots; all fixtures are fictitious public notices."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from boca_socios.events.official_catalog import OfficialCatalogError
from boca_socios.events.official_snapshot import (
    OFFICIAL_SNAPSHOT_NAME,
    OfficialSnapshotError,
    load_official_snapshot,
)


def _envelope(number: int = 1) -> dict[str, object]:
    return {
        "version": "official-notice-observation-v1",
        "source_url": f"https://www.bocajuniors.com.ar/noticias/evento-ficticio-{number:02d}",
        "published_on": "2026-11-03",
        "observed_at": "2026-11-04T18:00:00-03:00",
        "source_sha256": "a" * 64,
        "event_key": f"boca-evento-ficticio-{number:02d}",
        "title": f"Boca ante rival ficticio {number:02d}",
        "kickoff_at": f"2026-11-{(number % 20) + 5:02d}T17:30:00-03:00",
        "windows": [
            {
                "member_category": "activos_interior",
                "seat_area": "generales",
                "opens_at": "2026-11-03T13:00:00-03:00",
                "closes_at": None,
                "close_rule": "unspecified",
            }
        ],
    }


def _snapshot(tmp_path: Path, *documents: dict[str, object]) -> Path:
    path = tmp_path / OFFICIAL_SNAPSHOT_NAME
    payload = b"\n".join(json.dumps(doc).encode("utf-8") for doc in documents)
    path.write_bytes(payload + b"\n" if payload else b"")
    path.chmod(0o600)
    return path


def test_absent_optional_snapshot_is_empty_and_does_not_create_files(tmp_path: Path) -> None:
    path = tmp_path / OFFICIAL_SNAPSHOT_NAME
    assert load_official_snapshot(path) == ()
    assert list(tmp_path.iterdir()) == []


def test_valid_two_line_snapshot_remains_nonactionable_and_sorted(tmp_path: Path) -> None:
    path = _snapshot(tmp_path, _envelope(2), _envelope(1))
    before = path.stat()
    notices = load_official_snapshot(path)
    assert len(notices) == 2
    assert notices[0].event_key == "boca-evento-ficticio-01"
    assert all(notice.actionable is False for notice in notices)
    assert all(notice.verification_state == "SOURCE_OBSERVED_UNVERIFIED" for notice in notices)
    assert path.stat() == before  # reader does not rewrite, migrate, or cache the file


def test_present_empty_snapshot_is_nonactionable(tmp_path: Path) -> None:
    path = _snapshot(tmp_path)
    assert load_official_snapshot(path) == ()


def test_owner_readonly_snapshot_is_accepted_without_a_write(tmp_path: Path) -> None:
    path = _snapshot(tmp_path, _envelope())
    path.chmod(0o400)
    before = path.stat()
    assert len(load_official_snapshot(path)) == 1
    assert path.stat() == before


@pytest.mark.parametrize(
    "payload",
    [
        b"not json\n",
        b"\xff\n",
        b"\n",
        b"{}\n\n",
        b"{}\r\n",
        b"{}\x00\n",
        b" " * 17_000 + b"\n",
    ],
)
def test_corrupt_or_ambiguous_jsonl_fails_closed(tmp_path: Path, payload: bytes) -> None:
    path = tmp_path / OFFICIAL_SNAPSHOT_NAME
    path.write_bytes(payload)
    path.chmod(0o400)
    with pytest.raises(OfficialCatalogError):
        load_official_snapshot(path)


def test_invalid_notice_and_duplicate_event_are_rejected(tmp_path: Path) -> None:
    first = _envelope()
    bad = dict(first, version="fake-feed")
    path = _snapshot(tmp_path, bad)
    with pytest.raises(OfficialCatalogError):
        load_official_snapshot(path)
    path = _snapshot(tmp_path, first, first)
    with pytest.raises(OfficialCatalogError):
        load_official_snapshot(path)


def test_twenty_one_notices_are_rejected_without_any_operation(tmp_path: Path) -> None:
    path = _snapshot(tmp_path, *(_envelope(index) for index in range(1, 22)))
    with pytest.raises(OfficialSnapshotError, match="capacity"):
        load_official_snapshot(path)


def test_snapshot_byte_budget_rejects_oversized_input_before_parsing(tmp_path: Path) -> None:
    path = tmp_path / OFFICIAL_SNAPSHOT_NAME
    path.write_bytes(b"x" * 400_000)
    path.chmod(0o600)
    with pytest.raises(OfficialSnapshotError, match="capacity"):
        load_official_snapshot(path)


def test_missing_parent_is_not_treated_as_a_valid_empty_snapshot(tmp_path: Path) -> None:
    with pytest.raises(OfficialSnapshotError):
        load_official_snapshot(tmp_path / "missing" / OFFICIAL_SNAPSHOT_NAME)


@pytest.mark.parametrize("mode", [0o644, 0o660, 0o700, 0o444])
def test_file_must_be_owner_private_without_executable_bits(tmp_path: Path, mode: int) -> None:
    path = _snapshot(tmp_path, _envelope())
    path.chmod(mode)
    with pytest.raises(OfficialSnapshotError, match="mode"):
        load_official_snapshot(path)


def test_inode_or_owner_is_not_trusted_from_name_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _snapshot(tmp_path, _envelope())
    current = os.geteuid()
    monkeypatch.setattr(os, "geteuid", lambda: current + 1)
    with pytest.raises(OfficialSnapshotError, match="owner"):
        load_official_snapshot(path)


def test_symlink_file_and_hardlink_file_are_rejected(tmp_path: Path) -> None:
    original = _snapshot(tmp_path, _envelope())
    outside = tmp_path / "outside.jsonl"
    original.rename(outside)
    original.symlink_to(outside)
    with pytest.raises(OfficialSnapshotError):
        load_official_snapshot(original)
    original.unlink()
    os.link(outside, original)
    with pytest.raises(OfficialSnapshotError, match="link"):
        load_official_snapshot(original)


def test_fifo_is_rejected_without_blocking_for_a_writer(tmp_path: Path) -> None:
    path = tmp_path / OFFICIAL_SNAPSHOT_NAME
    os.mkfifo(path, 0o600)
    with pytest.raises(OfficialSnapshotError, match="regular"):
        load_official_snapshot(path)


def test_untrusted_parent_directory_mode_fails_before_child_read(tmp_path: Path) -> None:
    parent = tmp_path / "public"
    parent.mkdir(mode=0o700)
    _snapshot(parent, _envelope())
    parent.chmod(0o777)
    with pytest.raises(OfficialSnapshotError, match="directory owner or mode"):
        load_official_snapshot(parent / OFFICIAL_SNAPSHOT_NAME)


def test_directory_alias_is_rejected_before_reading_outside_snapshot(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    _snapshot(real, _envelope())
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(OfficialSnapshotError):
        load_official_snapshot(alias / OFFICIAL_SNAPSHOT_NAME)


def test_wrong_filename_and_relative_path_never_opened(tmp_path: Path) -> None:
    _snapshot(tmp_path, _envelope())
    with pytest.raises(OfficialSnapshotError):
        load_official_snapshot(tmp_path / "different.jsonl")
    with pytest.raises(OfficialSnapshotError):
        load_official_snapshot(Path(OFFICIAL_SNAPSHOT_NAME))


def test_file_swap_between_lstat_and_open_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _snapshot(tmp_path, _envelope())
    replacement = tmp_path / "replacement"
    replacement.write_bytes(path.read_bytes())
    replacement.chmod(0o600)
    open_original = os.open
    swapped = False

    def swapping_open(
        pathname: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if str(pathname) == OFFICIAL_SNAPSHOT_NAME and not swapped:
            swapped = True
            path.unlink()
            replacement.rename(path)
        if dir_fd is None:
            return open_original(pathname, flags, mode)
        return open_original(pathname, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swapping_open)
    with pytest.raises(OfficialSnapshotError, match="changed"):
        load_official_snapshot(path)
    assert swapped
