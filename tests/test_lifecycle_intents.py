"""Durable owner intent contract; these tests never run a host operation."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

from boca_socios.panel.lifecycle_intents import (
    LifecycleConflict,
    LifecycleIntentStore,
    LifecycleStorageUnavailable,
    host_marker,
)
from boca_socios.storage.database import Database


def _store(path: Path) -> tuple[LifecycleIntentStore, Database]:
    db = Database(path)
    db.migrate()
    return LifecycleIntentStore(db), db


def _insert_marker(db: Database, marker: tuple[str, str]) -> None:
    with db.connection() as connection, connection:
        connection.execute("INSERT INTO audit_events(audit_id,action) VALUES (?,?)", marker)


def test_one_global_pending_intent_is_durable_and_idempotent(tmp_path: Path) -> None:
    store, db = _store(tmp_path / "boca.sqlite3")
    first = str(uuid4())
    second = str(uuid4())
    assert store.current() is None
    state = store.request("bot", "start", first)
    assert (state.component, state.target, state.status, state.operation_id) == (
        "bot",
        "start",
        "REQUESTED",
        first,
    )
    assert store.request("bot", "start", first) == state
    assert LifecycleIntentStore(db).current() == state
    with pytest.raises(LifecycleConflict):
        store.request("chromium", "stop", second)
    with db.connection() as connection:
        assert connection.execute(
            "SELECT count(*) FROM audit_events WHERE action LIKE 'owner_lifecycle_v1_%'"
        ).fetchone() == (1,)

    claim = host_marker(first, "bot", "start", "CLAIMED")
    _insert_marker(db, claim)
    assert store.current().status == "CLAIMED"
    with pytest.raises(LifecycleConflict):
        store.request("bot", "stop", second)
    ack = host_marker(first, "bot", "start", "APPLIED")
    _insert_marker(db, ack)
    assert store.current().status == "APPLIED"
    next_state = store.request("chromium", "stop", second)
    assert (next_state.component, next_state.target, next_state.status) == (
        "chromium",
        "stop",
        "REQUESTED",
    )
    assert store.current() == next_state


def test_host_ack_requires_claim_and_matching_operation_order(tmp_path: Path) -> None:
    store, db = _store(tmp_path / "boca.sqlite3")
    request_id = str(uuid4())
    store.request("chromium", "start", request_id)
    _insert_marker(db, host_marker(request_id, "chromium", "start", "APPLIED"))
    with pytest.raises(LifecycleStorageUnavailable):
        store.current()
    with pytest.raises(LifecycleStorageUnavailable):
        store.request("bot", "start", str(uuid4()))


def test_refused_and_applied_are_mutually_exclusive_terminal_ack(tmp_path: Path) -> None:
    store, db = _store(tmp_path / "boca.sqlite3")
    request_id = str(uuid4())
    store.request("chromium", "start", request_id)
    _insert_marker(db, host_marker(request_id, "chromium", "start", "CLAIMED"))
    refused = host_marker(request_id, "chromium", "start", "REFUSED")
    applied = host_marker(request_id, "chromium", "start", "APPLIED")
    assert refused[0] == applied[0]  # Same deterministic ACK UUID, different evidence.
    assert refused[1] != applied[1]
    _insert_marker(db, refused)
    assert store.current().status == "REFUSED"
    with pytest.raises(sqlite3.IntegrityError):
        _insert_marker(db, applied)
    assert store.current().status == "REFUSED"
    assert store.request("bot", "stop", str(uuid4())).status == "REQUESTED"


def test_uncertain_host_receipt_blocks_all_new_operations(tmp_path: Path) -> None:
    store, db = _store(tmp_path / "boca.sqlite3")
    request_id = str(uuid4())
    store.request("bot", "stop", request_id)
    _insert_marker(db, host_marker(request_id, "bot", "stop", "CLAIMED"))
    _insert_marker(db, host_marker(request_id, "bot", "stop", "UNCERTAIN"))
    assert store.current().status == "UNCERTAIN"
    with pytest.raises(LifecycleConflict):
        store.request("bot", "start", str(uuid4()))
    # A new protected host inspection can resolve the frozen request without
    # rewriting/deleting the original uncertainty receipt.
    _insert_marker(db, host_marker(request_id, "bot", "stop", "REFUSED"))
    assert store.current().status == "REFUSED"
    assert store.request("bot", "start", str(uuid4())).status == "REQUESTED"


def test_two_controller_processes_cannot_queue_two_host_intents(tmp_path: Path) -> None:
    first, db = _store(tmp_path / "boca.sqlite3")
    second = LifecycleIntentStore(db)
    one, two = str(uuid4()), str(uuid4())

    def issue(store: LifecycleIntentStore, component: str, operation_id: str) -> str:
        try:
            store.request(component, "start", operation_id)
        except LifecycleConflict:
            return "CONFLICT"
        return "REQUESTED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        requests = [
            pool.submit(issue, first, "bot", one),
            pool.submit(issue, second, "chromium", two),
        ]
        assert sorted(future.result() for future in requests) == ["CONFLICT", "REQUESTED"]
    assert LifecycleIntentStore(db).current().status == "REQUESTED"
    with db.connection() as connection:
        assert connection.execute(
            "SELECT count(*) FROM audit_events WHERE action LIKE 'owner_lifecycle_v1_request_%'"
        ).fetchone() == (1,)


def test_missing_or_misowned_database_never_created_for_lifecycle(tmp_path: Path) -> None:
    empty = LifecycleIntentStore(Database(tmp_path / "missing.sqlite3"))
    with pytest.raises(LifecycleStorageUnavailable):
        empty.request("bot", "start", str(uuid4()))
    assert not (tmp_path / "missing.sqlite3").exists()

    store, _db = _store(tmp_path / "boca.sqlite3")
    path = tmp_path / "boca.sqlite3"
    path.chmod(0o644)
    with pytest.raises(LifecycleStorageUnavailable):
        store.current()
    with pytest.raises(LifecycleStorageUnavailable):
        store.request("chromium", "stop", str(uuid4()))
    path.chmod(0o600)
    alias = tmp_path / "symlink.sqlite3"
    alias.symlink_to(path)
    with pytest.raises(LifecycleStorageUnavailable):
        LifecycleIntentStore(Database(alias)).request("bot", "stop", str(uuid4()))


def test_corrupted_lifecycle_ledger_fails_closed_without_repair(tmp_path: Path) -> None:
    store, db = _store(tmp_path / "boca.sqlite3")
    request_id = str(uuid4())
    store.request("bot", "start", request_id)
    with db.connection() as connection, connection:
        connection.execute(
            "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
            (str(uuid4()), "owner_lifecycle_v1_unknown_control"),
        )
    with pytest.raises(LifecycleStorageUnavailable):
        store.current()
    with pytest.raises(LifecycleStorageUnavailable):
        store.request("bot", "stop", str(uuid4()))


@pytest.mark.parametrize(
    ("component", "target"),
    [("browser", "start"), ("chromium", "restart"), ("bot", "toggle")],
)
def test_only_four_exact_lifecycle_actions_are_admitted(
    tmp_path: Path, component: str, target: str
) -> None:
    store, _db = _store(tmp_path / "boca.sqlite3")
    with pytest.raises(ValueError):
        store.request(component, target, str(uuid4()))
    assert store.current() is None
