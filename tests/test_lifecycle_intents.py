"""Durable owner intent contract; these tests never run a host operation."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

from boca_socios.domain.policy import TicketIntent
from boca_socios.integration.command_store import CommandStore
from boca_socios.panel.lifecycle_intents import (
    LifecycleConflict,
    LifecycleIntentStore,
    LifecycleStorageUnavailable,
    host_marker,
)
from boca_socios.reservation_guard import ReservationAttemptGuard
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


@pytest.mark.parametrize("claim_start", [False, True])
def test_on_demand_stop_supersedes_start_and_repeated_wakes_reuse_uuid(
    tmp_path: Path, claim_start: bool
) -> None:
    store, db = _store(tmp_path / "boca.sqlite3")
    first, second = str(uuid4()), str(uuid4())
    state = store.request("bot", "start", first, on_demand=True)
    if claim_start:
        _insert_marker(db, host_marker(first, "bot", "start", "CLAIMED"))
    assert store.request("bot", "start", str(uuid4()), on_demand=True).operation_id == first
    stop = store.request("bot", "stop", second, on_demand=True)
    assert stop.operation_id == second and stop.status == "REQUESTED"
    assert store.request("bot", "stop", str(uuid4()), on_demand=True) == stop
    with pytest.raises(LifecycleConflict):
        store.request("bot", "start", first, on_demand=True)
    with pytest.raises(LifecycleConflict):
        store.request("bot", "start", str(uuid4()), on_demand=True)
    with db.connection() as connection:
        history = store.for_operation(connection, state.operation_id)
        assert history is not None and history.status == ("CLAIMED" if claim_start else "REQUESTED")
        assert store.for_operation(connection, second) == stop
        assert store.for_operation(connection, str(uuid4())) is None
        assert connection.execute(
            "SELECT count(*) FROM audit_events WHERE action LIKE 'owner_lifecycle_v1_request_%'"
        ).fetchone() == (2,)


def test_on_demand_failure_ack_requires_claim_and_excludes_other_terminal_results(
    tmp_path: Path,
) -> None:
    store, db = _store(tmp_path / "boca.sqlite3")
    operation = str(uuid4())
    store.request("bot", "start", operation, on_demand=True)
    _insert_marker(db, host_marker(operation, "bot", "start", "CLAIMED"))
    _insert_marker(db, host_marker(operation, "bot", "start", "FAILED"))
    assert store.current().status == "FAILED"
    with pytest.raises(sqlite3.IntegrityError):
        _insert_marker(db, host_marker(operation, "bot", "start", "APPLIED"))


def test_on_demand_unknown_outcome_never_creates_or_replays_effect(tmp_path: Path) -> None:
    store, db = _store(tmp_path / "boca.sqlite3")
    current = str(uuid4())
    store.request("bot", "start", current, on_demand=True)
    for phase in ("CLAIMED", "UNCERTAIN"):
        _insert_marker(db, host_marker(current, "bot", "start", phase))
    assert store.request("bot", "start", str(uuid4()), on_demand=True).operation_id == current
    with pytest.raises(LifecycleConflict):
        store.request("bot", "stop", str(uuid4()), on_demand=True)
    with pytest.raises(ValueError):
        store.request("chromium", "start", str(uuid4()), on_demand=True)


def _work_run(tmp_path: Path) -> tuple[LifecycleIntentStore, Database, str, str]:
    store, db = _store(tmp_path / "boca.sqlite3")
    guard = ReservationAttemptGuard(db)
    guard.migrate()
    guard.migrate_simulation()
    commands = CommandStore(db)
    commands.migrate()
    start_id, command_id, member, event = (str(uuid4()) for _ in range(4))
    db.create_member(member, "owner@example.invalid", "2026-11-01")
    db.create_event(event, "Simulación")
    store.request("bot", "start", start_id, on_demand=True)
    for phase in ("CLAIMED", "APPLIED"):
        _insert_marker(db, host_marker(start_id, "bot", "start", phase))
    commands.enqueue(command_id, TicketIntent(member, event), now=10, max_pending=4)
    return store, db, start_id, command_id


def test_work_stop_requires_this_starts_command_notice_guard_and_no_active_work(
    tmp_path: Path,
) -> None:
    store, db, start, command = _work_run(tmp_path)
    assert store.request_work_stop(start) is None
    with db.connection() as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        store.bind_work(conn, start, command)
    assert store.request_work_stop(start) is None
    with db.connection() as conn, conn:
        conn.execute("UPDATE beta_commands SET state='completed' WHERE command_id=?", (command,))
    assert store.request_work_stop(start) is None
    with db.connection() as conn, conn:
        conn.execute("UPDATE beta_commands SET notice_enqueued=1 WHERE command_id=?", (command,))
    assert store.request_work_stop(start) is None
    with db.connection() as conn, conn:
        conn.execute(
            "INSERT INTO reservation_attempts(request_id,claim_token,attempt_kind,state,started_at,"
            "review_after,closed_at) SELECT request_id,?,'simulation','simulation_completed',0,10,5 "
            "FROM beta_commands WHERE command_id=?",
            (str(uuid4()), command),
        )
    stop = store.request_work_stop(start)
    assert stop is not None and stop.target == "stop" and stop.status == "REQUESTED"
    assert stop.work_start_id == start and stop.operation_id != start
    assert store.request_work_stop(start) == stop == store.current()
    assert store.request_work_stop(str(uuid4())) is None


def test_work_stop_ignores_unrelated_completed_command_and_manual_stop(tmp_path: Path) -> None:
    store, db, start, command = _work_run(tmp_path)
    with db.connection() as conn, conn:
        conn.execute("UPDATE beta_commands SET state='failed' WHERE command_id=?", (command,))
    assert store.request_work_stop(start) is None
    with db.connection() as conn, conn, pytest.raises(LifecycleConflict):
        conn.execute("BEGIN IMMEDIATE")
        store.bind_work(conn, start, command)
    manual = store.request("bot", "stop", str(uuid4()), on_demand=True)
    assert store.request_work_stop(start) is None
    assert store.current() == manual and manual.work_start_id is None


def test_claim_reads_exact_accepted_work_binding_and_manual_stop_wins(tmp_path: Path) -> None:
    store, db, start, command = _work_run(tmp_path)
    with db.connection() as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        assert not store.may_run_work(conn, start, command)
        store.bind_work(conn, start, command)
        assert store.may_run_work(conn, start, command)
        assert not store.may_run_work(conn, str(uuid4()), command)
        assert not store.may_run_work(conn, start, str(uuid4()))
    store.request("bot", "stop", str(uuid4()), on_demand=True)
    with db.connection() as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        assert not store.may_run_work(conn, start, command)


def test_manual_and_derived_stop_converge_and_wait_for_all_active_work(tmp_path: Path) -> None:
    store, db, start, command = _work_run(tmp_path)
    with db.connection() as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        store.bind_work(conn, start, command)
        conn.execute("UPDATE beta_commands SET state='failed' WHERE command_id=?", (command,))
        member = conn.execute("SELECT member_id FROM members").fetchone()[0]
    extra_event, extra_command = str(uuid4()), str(uuid4())
    db.create_event(extra_event, "Simulación pendiente")
    CommandStore(db).enqueue(
        extra_command, TicketIntent(member, extra_event), now=11, max_pending=4
    )
    assert store.request_work_stop(start) is None
    with db.connection() as conn, conn:
        conn.execute(
            "UPDATE beta_commands SET state='stopped' WHERE command_id=?", (extra_command,)
        )
    with ThreadPoolExecutor(max_workers=2) as pool:
        automatic = pool.submit(store.request_work_stop, start)
        human_id = str(uuid4())
        human = pool.submit(store.request, "bot", "stop", human_id, on_demand=True)
        human_stop = human.result()
        derived = automatic.result()
    assert store.current() == human_stop
    assert derived is None or derived == human_stop
    assert (human_stop.operation_id == human_id and human_stop.work_start_id is None) or (
        human_stop.operation_id != human_id and human_stop.work_start_id == start
    )
    with db.connection() as conn:
        assert conn.execute(
            "SELECT count(*) FROM audit_events WHERE action='owner_lifecycle_v1_request_bot_stop'"
        ).fetchone() == (1,)
