"""Member profile sector defaults, isolated from the legacy controller schema."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from boca_socios.domain.sector_preferences import SectorMode, evaluate_sector_preference
from boca_socios.panel.member_sector_store import (
    MemberSectorStorageUnavailable,
    MemberSectorStore,
)
from boca_socios.storage.database import Database

STAMP = datetime(2026, 11, 11, 15, 0, tzinfo=UTC)


@pytest.fixture
def fixture(tmp_path: Path) -> tuple[Database, MemberSectorStore]:
    db = Database(tmp_path / "boca.sqlite3")
    db.migrate()
    db.create_member("member-a", "first@example.test", STAMP.isoformat())
    db.create_member("member-b", "second@example.test", STAMP.isoformat())
    return db, MemberSectorStore.for_database(db.path)


def test_existing_member_reuses_single_profile_without_legacy_migration(
    fixture: tuple[Database, MemberSectorStore],
) -> None:
    db, store = fixture
    legacy_bytes = db.path.read_bytes()
    store.migrate()
    assert db.path.read_bytes() == legacy_bytes
    saved = store.save(
        "member-a", SectorMode.ORDERED_ALLOWLIST, ("fictional_upper", "fictional_lower"), STAMP
    )
    persisted = MemberSectorStore.for_database(db.path).load("member-a")
    assert persisted == saved
    assert persisted is not None
    assert persisted.version == 1
    assert persisted.for_event("fictional-event").event_id == "fictional-event"
    selection = evaluate_sector_preference(
        persisted.for_event("fictional-event"),
        ("fictional_lower", "fictional_upper"),
        {"fictional_upper": False, "fictional_lower": True},
    )
    assert selection.selected_sector_id == "fictional_lower"
    assert selection.ticket_intent.member_id == "member-a"
    assert selection.ticket_intent.quantity == 1
    with db.connection() as connection:
        assert connection.execute("SELECT version FROM schema_migrations").fetchall() == [(1,)]
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name='member_sector_preferences'"
            ).fetchall()
            == []
        )


def test_store_is_not_created_by_constructor_or_read_and_save_requires_explicit_migration(
    fixture: tuple[Database, MemberSectorStore],
) -> None:
    _, store = fixture
    assert store.load("member-a") is None
    assert not store.path.exists()
    with pytest.raises(MemberSectorStorageUnavailable):
        store.save("member-a", SectorMode.ALL, (), STAMP)
    assert not store.path.exists()


def test_previously_registered_members_do_not_share_preference_or_credentials(
    fixture: tuple[Database, MemberSectorStore],
) -> None:
    db, store = fixture
    store.migrate()
    store.save("member-a", SectorMode.ORDERED_ALLOWLIST, ("north",), STAMP)
    store.save("member-b", SectorMode.ORDERED_ALLOWLIST, ("south",), STAMP)
    assert store.load("member-a").sector_ids == ("north",)
    assert store.load("member-b").sector_ids == ("south",)
    with sqlite3.connect(store.path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(member_sector_preferences)")
        }
        assert columns == {"member_id", "mode", "sector_ids_json", "version", "updated_at"}
    with db.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM members").fetchone() == (2,)


def test_change_replaces_priority_in_place_and_all_clears_old_list(
    fixture: tuple[Database, MemberSectorStore],
) -> None:
    _, store = fixture
    store.migrate()
    store.save("member-a", SectorMode.ORDERED_ALLOWLIST, ("north", "south"), STAMP)
    second = store.save("member-a", SectorMode.ALL, (), STAMP)
    assert second.version == 2
    assert second.mode is SectorMode.ALL
    assert second.sector_ids == ()
    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM member_sector_preferences WHERE member_id='member-a'"
        ).fetchone() == (1,)


def test_unknown_or_deleted_member_is_never_enrolled_by_preference_save(
    fixture: tuple[Database, MemberSectorStore],
) -> None:
    db, store = fixture
    store.migrate()
    with pytest.raises(LookupError):
        store.save("not-enrolled", SectorMode.ALL, (), STAMP)
    store.save("member-a", SectorMode.ORDERED_ALLOWLIST, ("north",), STAMP)
    with db.connection() as connection, connection:
        connection.execute("DELETE FROM members WHERE member_id='member-a'")
    assert store.load("member-a") is None
    with pytest.raises(LookupError):
        store.save("member-a", SectorMode.ALL, (), STAMP)


@pytest.mark.parametrize(
    "sector_ids",
    [(), ("north", "north"), ("",), (" north",), tuple(str(i) for i in range(21))],
)
def test_invalid_ordered_list_never_replaces_saved_preference(
    fixture: tuple[Database, MemberSectorStore], sector_ids: tuple[str, ...]
) -> None:
    _, store = fixture
    store.migrate()
    before = store.save("member-a", SectorMode.ORDERED_ALLOWLIST, ("south",), STAMP)
    with pytest.raises(ValueError):
        store.save("member-a", SectorMode.ORDERED_ALLOWLIST, sector_ids, STAMP)
    assert store.load("member-a") == before


def test_sidecar_symlink_is_refused_and_not_repaired(
    fixture: tuple[Database, MemberSectorStore], tmp_path: Path
) -> None:
    _, store = fixture
    victim = tmp_path / "victim.txt"
    victim.write_text("leave me alone")
    store.path.symlink_to(victim)
    with pytest.raises(MemberSectorStorageUnavailable):
        store.migrate()
    assert victim.read_text() == "leave me alone"


def test_migration_is_idempotent_and_tampered_schema_fails_closed(
    fixture: tuple[Database, MemberSectorStore],
) -> None:
    _, store = fixture
    store.migrate()
    store.migrate()
    with sqlite3.connect(store.path) as connection, connection:
        connection.execute("UPDATE member_sector_schema SET checksum='wrong'")
    with pytest.raises(MemberSectorStorageUnavailable):
        store.load("member-a")
    with pytest.raises(MemberSectorStorageUnavailable):
        store.migrate()
