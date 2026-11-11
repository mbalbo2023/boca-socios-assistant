"""R179: attest Boca's existing SQLite inode without opening database bytes."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from boca_socios import host_boca_sqlite_identity as identity
from boca_socios import host_on_demand_service


def volume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    root = tmp_path / "rootless-docker"
    database = root / "volumes/boca-socios_boca_data/_data/boca.sqlite3"
    database.parent.mkdir(parents=True)
    for directory in (root, root / "volumes", database.parent.parent, database.parent):
        directory.chmod(0o700)
    database.write_bytes(b"test-only-private-sqlite-placeholder")
    database.chmod(0o600)
    monkeypatch.setattr(identity, "_EXPECTED_ROOT", root)
    monkeypatch.setattr(identity, "_EXPECTED_FILE", database)
    return root, database


def test_contract_is_exact_host_on_demand_binding_path() -> None:
    assert identity._EXPECTED_FILE == host_on_demand_service._HOME / host_on_demand_service._DB
    assert identity._EXPECTED_ROOT / identity._DB_RELATIVE == identity._EXPECTED_FILE


def test_reads_only_regular_private_inode_and_redacts_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, database = volume(tmp_path, monkeypatch)
    original = database.read_bytes()
    captured = identity.capture_sqlite_identity(root)
    current = database.stat()
    assert (captured.device, captured.inode) == (current.st_dev, current.st_ino)
    assert (captured.owner_uid, captured.owner_gid) == (current.st_uid, current.st_gid)
    assert (captured.mode, captured.links) == (0o600, 1)
    assert str(current.st_ino) not in repr(captured)
    assert str(database) not in repr(captured)
    assert database.read_bytes() == original


@pytest.mark.parametrize("defect", ["symlink", "nonregular", "mode", "hardlink"])
def test_rejects_unsafe_database_inode(
    defect: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, database = volume(tmp_path, monkeypatch)
    if defect == "symlink":
        database.rename(database.with_name("other.db"))
        database.symlink_to(database.with_name("other.db"))
    elif defect == "nonregular":
        database.unlink()
        database.mkdir()
    elif defect == "mode":
        database.chmod(0o644)
    else:
        os.link(database, database.with_name("second-link.db"))
    with pytest.raises(identity.SqliteIdentityError, match="^sqlite_identity_unverified$"):
        identity.capture_sqlite_identity(root)


def test_rejects_symlinked_volume_ancestor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, database = volume(tmp_path, monkeypatch)
    volume_dir = database.parent.parent
    volume_dir.rename(volume_dir.with_name("original-volume"))
    volume_dir.symlink_to(volume_dir.with_name("original-volume"), target_is_directory=True)
    with pytest.raises(identity.SqliteIdentityError, match="^sqlite_identity_unverified$"):
        identity.capture_sqlite_identity(root)


def test_rejects_group_writable_volume_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, database = volume(tmp_path, monkeypatch)
    database.parent.chmod(0o770)
    with pytest.raises(identity.SqliteIdentityError, match="^sqlite_identity_unverified$"):
        identity.capture_sqlite_identity(root)


def test_observer_attests_pair_volume_and_root_twice_without_exposing_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, database = volume(tmp_path, monkeypatch)
    events: list[str] = []
    monkeypatch.setattr(identity.pair, "observe", lambda _: events.append("pair") or b"verified")
    monkeypatch.setattr(
        identity.host, "_validate_data_volume", lambda: events.append("data-volume")
    )
    monkeypatch.setattr(
        identity.host,
        "_checked_docker_storage_dir",
        lambda: events.append("rootless") or root,
    )
    result = identity.observe_sqlite_identity(root)
    assert result == "VERIFIED_STABLE"
    assert events == ["pair", "data-volume", "rootless"] * 2
    assert str(database) not in result
    assert str(database.stat().st_ino) not in result


def test_inode_replacement_between_attested_snapshots_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, database = volume(tmp_path, monkeypatch)
    attempt = 0

    def attest(_: Path) -> None:
        nonlocal attempt
        attempt += 1
        if attempt == 2:
            replacement = database.with_name("replacement.db")
            replacement.write_bytes(b"replacement")
            replacement.chmod(0o600)
            replacement.replace(database)

    monkeypatch.setattr(identity, "_attest_boundary", attest)
    assert identity.observe_sqlite_identity(root) == "NO_GO"
    assert attempt == 2


def test_no_go_on_unattested_root_even_when_file_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = volume(tmp_path, monkeypatch)
    monkeypatch.setattr(identity.pair, "observe", lambda _: b"verified")
    monkeypatch.setattr(identity.host, "_validate_data_volume", lambda: None)
    monkeypatch.setattr(identity.host, "_checked_docker_storage_dir", lambda: root / "foreign")
    assert identity.observe_sqlite_identity(root) == "NO_GO"


def test_missing_database_fails_closed_without_path_in_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, database = volume(tmp_path, monkeypatch)
    database.unlink()
    with pytest.raises(identity.SqliteIdentityError, match="^sqlite_identity_unverified$") as error:
        identity.capture_sqlite_identity(root)
    assert str(database) not in str(error.value)
