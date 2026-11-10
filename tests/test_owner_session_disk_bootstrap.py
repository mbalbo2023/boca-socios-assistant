"""Host-free proof that Option B's standalone memfd source needs only stdlib."""

from __future__ import annotations

import ast
import base64
import fcntl
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path

import pytest

from boca_socios.config import Settings
from boca_socios.panel import owner_session_disk_bootstrap as bootstrap
from boca_socios.panel.owner_session_store import OwnerBrowserSessionStore
from boca_socios.runtime import initialize_beta
from boca_socios.storage.database import Database


@pytest.fixture
def staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, bytes]:
    db = tmp_path / "boca.sqlite3"
    key = tmp_path / "synthetic.key"
    key.write_bytes(base64.b64encode(b"k" * 32))
    key.chmod(0o400)
    initialize_beta(Settings("staging", "simulation", db, key))
    lock = tmp_path / "boca-socios-protected-job.lock"
    lock.touch(mode=0o600)
    monkeypatch.setattr(bootstrap, "_UID", os.getuid())
    monkeypatch.setattr(bootstrap, "_LOCK", lock)
    sql = (
        files("boca_socios.panel.owner_session_sql")
        .joinpath("0001_owner_browser_session.sql")
        .read_bytes()
    )
    return db, lock, sql


@contextmanager
def _held(lock: Path) -> Iterator[int]:
    fd = os.open(lock, os.O_RDWR | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield fd
    finally:
        os.close(fd)


def _invoke(db: Path, fd: int, sql: bytes) -> str:
    meta = db.stat()
    return bootstrap.bootstrap_attested_session_file(
        db,
        held_lease_fd=fd,
        expected_db_identity=(meta.st_dev, meta.st_ino),
        session_schema_bytes=sql,
    )


def _legacy(db: Path) -> tuple[tuple[object, ...], ...]:
    with sqlite3.connect(db) as connection:
        return tuple(
            connection.execute("SELECT version, checksum FROM schema_migrations ORDER BY version")
        )


def test_host_stdlib_bootstrap_and_repeat_preserve_legacy_and_cookie(
    staging: tuple[Path, Path, bytes],
) -> None:
    db, lock, sql = staging
    before, original_bytes = _legacy(db), db.read_bytes()
    with _held(lock) as fd:
        assert _invoke(db, fd, sql) == "APPLIED"
        store = OwnerBrowserSessionStore(Database(db), owner_subject="owner")
        store.verify_schema()
        token, verifier = b"x" * 32, b"y" * 32
        store.replace(token, verifier)
        assert _invoke(db, fd, sql) == "ALREADY_APPLIED"
        assert store.matches(token, verifier)
    assert _legacy(db) == before
    assert db.read_bytes() == original_bytes
    with sqlite3.connect(db) as connection:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name='owner_browser_session'"
            ).fetchone()
            is None
        )


@pytest.mark.parametrize(
    "failure",
    ["unlocked", "foreign_fd", "bad_digest", "wrong_db_inode", "bad_uid", "bad_db_mode", "ledger8"],
)
def test_host_stdlib_bootstrap_fails_closed_before_session_creation(
    staging: tuple[Path, Path, bytes], monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    db, lock, sql = staging
    before = _legacy(db)
    if failure == "bad_digest":
        sql = sql + b"\n"
    elif failure == "bad_uid":
        monkeypatch.setattr(bootstrap, "_UID", os.getuid() + 1)
    elif failure == "bad_db_mode":
        db.chmod(0o644)
    elif failure == "ledger8":
        with sqlite3.connect(db) as connection:
            connection.execute(
                "INSERT INTO schema_migrations(version,checksum) VALUES (8,?)",
                ("f" * 64,),
            )
        before = _legacy(db)
    fd = os.open(lock, os.O_RDWR | os.O_NOFOLLOW)
    try:
        if failure != "unlocked":
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if failure == "foreign_fd":
            foreign = lock.parent / "other.lock"
            foreign.touch(mode=0o600)
            os.close(fd)
            fd = os.open(foreign, os.O_RDWR | os.O_NOFOLLOW)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        meta = db.stat()
        identity = (meta.st_dev, meta.st_ino)
        if failure == "wrong_db_inode":
            identity = (meta.st_dev, meta.st_ino + 1)
        with pytest.raises(bootstrap.SessionDiskBootstrapUnavailable):
            bootstrap.bootstrap_attested_session_file(
                db,
                held_lease_fd=fd,
                expected_db_identity=identity,
                session_schema_bytes=sql,
            )
    finally:
        os.close(fd)
    assert not db.with_name("boca_owner_session.sqlite3").exists()
    assert _legacy(db) == before


def test_host_stdlib_bootstrap_does_not_repair_partial_session(
    staging: tuple[Path, Path, bytes],
) -> None:
    db, lock, sql = staging
    sidecar = db.with_name("boca_owner_session.sqlite3")
    sidecar.touch(mode=0o600)
    inode = sidecar.stat().st_ino
    with _held(lock) as fd:
        with pytest.raises(bootstrap.SessionDiskBootstrapUnavailable):
            _invoke(db, fd, sql)
    assert sidecar.stat().st_size == 0 and sidecar.stat().st_ino == inode


def test_host_stdlib_bootstrap_denies_extra_session_objects(
    staging: tuple[Path, Path, bytes],
) -> None:
    db, lock, sql = staging
    with _held(lock) as fd:
        assert _invoke(db, fd, sql) == "APPLIED"
        with sqlite3.connect(db.with_name("boca_owner_session.sqlite3")) as connection:
            connection.execute("CREATE VIEW unauthorized AS SELECT 1")
        with pytest.raises(bootstrap.SessionDiskBootstrapUnavailable):
            _invoke(db, fd, sql)


def test_host_stdlib_bootstrap_source_has_no_application_dependencies() -> None:
    path = Path(bootstrap.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(alias.name.startswith("boca_socios") for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("boca_socios")
    assert not hasattr(bootstrap, "main")  # No separate host command/dispatch entrypoint.


def test_mounted_bootstrap_requires_same_inode_and_preserves_credential_database(
    staging, monkeypatch
):
    db, _, _ = staging
    monkeypatch.setattr(bootstrap, "_MOUNTED_DATABASE", db)
    identity = db.stat()
    before = db.read_bytes()
    with pytest.raises(bootstrap.SessionDiskBootstrapUnavailable):
        bootstrap.bootstrap_mounted_session(identity.st_dev, identity.st_ino + 1)
    assert not db.with_name("boca_owner_session.sqlite3").exists()
    assert bootstrap.bootstrap_mounted_session(identity.st_dev, identity.st_ino) == "APPLIED"
    assert (
        bootstrap.bootstrap_mounted_session(identity.st_dev, identity.st_ino) == "ALREADY_APPLIED"
    )
    assert db.read_bytes() == before
    assert db.with_name("boca_owner_session.sqlite3").stat().st_mode & 0o777 == 0o600
