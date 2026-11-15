"""Independent logical engines share one real SQLite physical authority."""

from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest

from boca_socios.domain.policy import TicketIntent
from boca_socios.integration.command_store import CommandStore
from boca_socios.panel.lifecycle_intents import LifecycleIntentStore, host_marker
from boca_socios.reservation_guard import ReservationAttemptGuard
from boca_socios.security.credential_vault import CredentialVault
from boca_socios.security.enrollment import MemberEnrollmentService
from boca_socios.storage.database import Database
from test_member_auth_contract import _enrolled

COUNTS = {"chromium": 15, "firefox": 5, "webkit": 5}


def _api():
    assert find_spec("boca_socios.panel.engine_intents") is not None, "engine authority missing"
    return import_module("boca_socios.panel.engine_intents")


def _store(tmp_path: Path, *, boot_id: str | None = None):
    database, _vault, member = _enrolled(tmp_path)
    commands = CommandStore(database)
    commands.migrate()
    guard = ReservationAttemptGuard(database)
    guard.migrate()
    guard.migrate_simulation()
    return _api().EngineIntentStore(database, boot_id=boot_id or str(uuid4())), database, member


def _start(store, engine="queues_tokens", *, member=None, counts=None, operation=None):
    return store.start(
        engine,
        operation or str(uuid4()),
        member_id=member,
        counts=COUNTS if counts is None else counts,
    )


def _receipt(database, operation, target="start", status="APPLIED"):
    with database.connection() as connection, connection:
        for phase in ("CLAIMED",) if status == "CLAIMED" else ("CLAIMED", status):
            connection.execute(
                "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
                host_marker(operation, "bot", target, phase),
            )


def _stop(store, activation, operation=None):
    return store.stop(
        activation.engine,
        operation or str(uuid4()),
        activation_id=activation.activation_id,
        generation=activation.generation,
    )


def _release(store, activation, *, closed=True):
    return store.release(
        activation.engine, activation.activation_id, activation.generation, closed=closed
    )


def test_start_commits_engine_hold_and_physical_start_together(tmp_path: Path) -> None:
    assert find_spec("boca_socios.panel.engine_intents") is not None, "engine authority missing"
    from boca_socios.panel.engine_intents import EngineIntentStore

    database = Database(tmp_path / "boca.sqlite3")
    database.migrate()
    boot_id, operation_id = str(uuid4()), str(uuid4())
    store = EngineIntentStore(database, boot_id=boot_id)
    result = store.start(
        "queues_tokens", operation_id, counts={"chromium": 15, "firefox": 5, "webkit": 5}
    )
    assert result.activation.activation_id == operation_id
    assert result.activation.generation == 1
    assert result.activation.boot_id == boot_id
    assert result.activation.requested_contexts == 25
    assert result.activation.state == "REQUESTED"
    assert not result.activation.released
    assert result.physical_intent == LifecycleIntentStore(database).current()
    assert result.physical_intent.target == "start"
    assert result.physical_intent.operation_id == result.activation.physical_start_id
    assert store.snapshot() == (result.activation,)


@pytest.mark.parametrize(
    "order", [("queues_tokens", "browsers_members"), ("browsers_members", "queues_tokens")]
)
def test_both_orders_share_physical_start_and_each_stop_preserves_other(tmp_path, order):
    store, database, member = _store(tmp_path)
    assert store.snapshot() == ()
    first = _start(store, order[0], member=member if order[0] == "browsers_members" else None)
    _receipt(database, first.activation.physical_start_id)
    second = _start(store, order[1], member=member if order[1] == "browsers_members" else None)
    assert second.physical_intent is None
    assert second.activation.physical_start_id == first.activation.physical_start_id
    assert len(store.snapshot()) == 2
    _stop(store, first.activation)
    released = _release(store, first.activation)
    assert released.activation.released
    assert released.physical_intent is None
    remaining = next(item for item in store.snapshot() if item.engine == second.activation.engine)
    assert remaining.state == "REQUESTED" and not remaining.released
    assert LifecycleIntentStore(database).current().target == "start"
    _stop(store, remaining)
    final = _release(store, remaining)
    assert final.physical_intent.target == "stop"
    assert final.physical_intent.work_start_id == first.activation.physical_start_id
    assert _release(store, remaining).physical_intent == final.physical_intent
    with database.connection() as connection:
        assert connection.execute(
            "SELECT count(*) FROM audit_events WHERE action='owner_lifecycle_v1_request_bot_start'"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM audit_events WHERE action='owner_lifecycle_v1_request_bot_stop'"
        ).fetchone() == (1,)


def test_simulation_completion_cannot_stop_any_engine_hold(tmp_path):
    store, database, _member = _store(tmp_path)
    activation = _start(store).activation
    _receipt(database, activation.physical_start_id)
    legacy = LifecycleIntentStore(database)
    legacy.record_automatic_check(activation.physical_start_id, "NO_EVENT_OBSERVED")
    assert legacy.request_work_stop(activation.physical_start_id) is None
    _stop(store, activation)
    assert legacy.request_work_stop(activation.physical_start_id) is None
    assert _release(store, activation).physical_intent.target == "stop"


def test_last_release_waits_for_actual_legacy_completion_without_fake_observation(tmp_path):
    store, database, member = _store(tmp_path)
    activation = _start(store).activation
    _receipt(database, activation.physical_start_id)
    event, command = str(uuid4()), str(uuid4())
    database.create_event(event, "Offline event")
    commands = CommandStore(database)
    commands.enqueue(
        command,
        TicketIntent(member, event),
        now=1,
        max_pending=2,
        bind_work=lambda connection, key: LifecycleIntentStore.bind_work(
            connection, activation.physical_start_id, key
        ),
    )
    _stop(store, activation)
    assert _release(store, activation).physical_intent is None
    assert LifecycleIntentStore(database).current().target == "start"
    commands.stop(command, member_id=member, now=2)
    stop = LifecycleIntentStore(database).request_work_stop(activation.physical_start_id)
    assert stop is not None and stop.target == "stop"
    with database.connection() as connection:
        assert connection.execute(
            "SELECT count(*) FROM audit_events WHERE action LIKE 'boca_automatic_check_v1:%'"
        ).fetchone() == (0,)


def test_released_engine_allows_idle_stop_after_preexisting_unbound_work_finishes(tmp_path):
    store, database, member = _store(tmp_path)
    event, command = str(uuid4()), str(uuid4())
    database.create_event(event, "Offline work accepted before engine start")
    commands = CommandStore(database)
    commands.enqueue(command, TicketIntent(member, event), now=1, max_pending=2)
    activation = _start(store).activation
    _receipt(database, activation.physical_start_id)
    _stop(store, activation)
    assert _release(store, activation).physical_intent is None
    commands.stop(command, member_id=member, now=2)
    stop = LifecycleIntentStore(database).request_work_stop(activation.physical_start_id)
    assert stop is not None and stop.target == "stop"


def test_parallel_starts_reserve_once_per_engine_and_one_physical_start(tmp_path):
    store, database, member = _store(tmp_path)
    with ThreadPoolExecutor(4) as pool:
        results = list(
            pool.map(
                lambda engine: _start(
                    store, engine, member=member if engine == "browsers_members" else None
                ),
                ["queues_tokens", "browsers_members", "queues_tokens", "browsers_members"],
            )
        )
    assert len({item.activation.activation_id for item in results}) == 2
    assert len({item.activation.physical_start_id for item in results}) == 1
    assert sum(item.requested_contexts for item in store.snapshot() if not item.released) == 50
    assert len(_api().EngineIntentStore(database, boot_id=store.boot_id).snapshot()) == 2


def test_duplicate_start_changes_and_cross_engine_uuid_replay_are_rejected(tmp_path):
    store, _database, member = _store(tmp_path)
    first = _start(store)
    alias = str(uuid4())
    assert _start(store, operation=alias).activation == first.activation
    for operation in (first.activation.activation_id, alias, str(uuid4())):
        with pytest.raises(_api().EngineConflict):
            _start(store, counts={"chromium": 1, "firefox": 0, "webkit": 0}, operation=operation)
    for operation in (first.activation.activation_id, alias):
        with pytest.raises(_api().EngineConflict):
            _start(store, "browsers_members", member=member, operation=operation)
    second = _start(store, "browsers_members", member=member).activation
    with pytest.raises(_api().EngineConflict):
        store.stop(
            "queues_tokens",
            str(uuid4()),
            activation_id=second.activation_id,
            generation=second.generation,
        )
    with pytest.raises(_api().EngineConflict):
        _stop(store, first.activation, operation=alias)


def test_selected_member_cannot_change_or_omit_active_credential(tmp_path):
    store, database, member = _store(tmp_path)
    with pytest.raises(_api().EngineConflict):
        _start(store, "browsers_members")
    with pytest.raises(_api().EngineConflict):
        _start(store, "browsers_members", member=str(uuid4()))
    _start(store, "browsers_members", member=member)
    with pytest.raises(_api().EngineConflict):
        _start(store, "browsers_members", member=str(uuid4()))
    with database.connection() as connection, connection:
        connection.execute("DELETE FROM credentials WHERE member_id=?", (member,))
    with pytest.raises(_api().EngineConflict):
        _start(store, "browsers_members", member=member)


def test_capacity_reservation_is_global_and_uncertain_contexts_remain_reserved(tmp_path):
    store, _database, member = _store(tmp_path)
    first = _start(store, counts={"chromium": 30, "firefox": 0, "webkit": 0}).activation
    with pytest.raises(_api().EngineConflict):
        _start(
            store,
            "browsers_members",
            member=member,
            counts={"chromium": 21, "firefox": 0, "webkit": 0},
        )
    second = _start(
        store, "browsers_members", member=member, counts={"chromium": 20, "firefox": 0, "webkit": 0}
    ).activation
    assert sum(item.requested_contexts for item in store.snapshot()) == 50
    _stop(store, first)
    uncertain = _release(store, first, closed=False)
    assert uncertain.activation.state == "UNCERTAIN"
    assert not uncertain.activation.released
    assert uncertain.physical_intent is None
    with pytest.raises(_api().EngineConflict):
        _start(store, counts={"chromium": 1, "firefox": 0, "webkit": 0})
    assert not next(item for item in store.snapshot() if item.engine == second.engine).released


@pytest.mark.parametrize(
    "counts",
    [
        {"chromium": 0, "firefox": 0, "webkit": 0},
        {"chromium": 51, "firefox": 0, "webkit": 0},
        {"chromium": True, "firefox": 0, "webkit": 0},
        {"chromium": -1, "firefox": 1, "webkit": 1},
        {"chromium": 1, "firefox": 0, "webkit": 0, "unknown": 1},
    ],
)
def test_invalid_counts_never_write_physical_intent(tmp_path, counts):
    store, database, _member = _store(tmp_path)
    with pytest.raises(ValueError):
        _start(store, counts=counts)
    assert store.snapshot() == ()
    assert LifecycleIntentStore(database).current() is None


def test_stop_restart_fences_old_generation_and_consumed_operations(tmp_path):
    store, database, _member = _store(tmp_path)
    first = _start(store).activation
    _receipt(database, first.physical_start_id)
    store.transition(first.engine, first.activation_id, first.generation, "RUNNING")
    publication = []
    assert store.publish_if_current(
        first.engine, first.activation_id, first.generation, lambda: publication.append("first")
    )
    stop_operation = str(uuid4())
    _stop(store, first, operation=stop_operation)
    assert not store.publish_if_current(
        first.engine, first.activation_id, first.generation, lambda: publication.append("late")
    )
    final = _release(store, first)
    _receipt(database, final.physical_intent.operation_id, "stop")
    second = _start(store).activation
    assert second.generation == 2
    assert second.activation_id != first.activation_id
    with pytest.raises(_api().EngineConflict):
        _start(store, operation=first.activation_id)
    with pytest.raises(_api().EngineConflict):
        _stop(store, first, operation=stop_operation)
    with pytest.raises(_api().EngineConflict):
        store.transition(first.engine, first.activation_id, first.generation, "RUNNING")
    assert not store.publish_if_current(
        second.engine,
        second.activation_id,
        first.generation,
        lambda: publication.append("wrong generation"),
    )
    assert publication == ["first"]


@pytest.mark.parametrize("receipt", [None, "FAILED", "REFUSED", "UNCERTAIN"])
def test_physical_receipt_is_required_before_running_or_publishing(tmp_path, receipt):
    store, database, _member = _store(tmp_path)
    activation = _start(store).activation
    if receipt is not None:
        _receipt(database, activation.physical_start_id, status=receipt)
    with pytest.raises(_api().EngineConflict):
        store.transition(
            activation.engine, activation.activation_id, activation.generation, "RUNNING"
        )
    published = []
    assert not store.publish_if_current(
        activation.engine,
        activation.activation_id,
        activation.generation,
        lambda: published.append(True),
    )
    assert published == []


def test_failed_engine_release_preserves_failure_and_creates_no_claim_of_success(tmp_path):
    store, database, _member = _store(tmp_path)
    activation = _start(store).activation
    _receipt(database, activation.physical_start_id, status="FAILED")
    store.transition(activation.engine, activation.activation_id, activation.generation, "FAILED")
    result = _release(store, activation)
    assert result.activation.state == "FAILED" and result.activation.released
    assert result.physical_intent is not None and result.physical_intent.target == "stop"


@pytest.mark.parametrize("mutation", ["stop", "revoke"])
def test_publication_serializes_with_stop_and_credential_revocation(tmp_path, mutation):
    store, database, member = _store(tmp_path)
    activation = _start(store, "browsers_members", member=member).activation
    _receipt(database, activation.physical_start_id)
    entered, finish, stopping = Event(), Event(), Event()
    effects = []

    def publish():
        entered.set()
        assert finish.wait(2)
        effects.append("published")

    def mutate():
        stopping.set()
        if mutation == "stop":
            _stop(store, activation)
        else:
            with database.connection() as connection, connection:
                connection.execute("DELETE FROM credentials WHERE member_id=?", (member,))
        effects.append("fenced")

    with ThreadPoolExecutor(2) as pool:
        publication = pool.submit(
            store.publish_if_current,
            activation.engine,
            activation.activation_id,
            activation.generation,
            publish,
            member_id=member,
        )
        assert entered.wait(2)
        mutation_done = pool.submit(mutate)
        assert stopping.wait(2)
        assert not mutation_done.done()
        finish.set()
        assert publication.result()
        mutation_done.result()
    assert effects == ["published", "fenced"]
    assert not store.publish_if_current(
        activation.engine,
        activation.activation_id,
        activation.generation,
        lambda: effects.append("late"),
        member_id=member,
    )


@pytest.mark.parametrize("mutation", ["rotate", "reinsert", "reinsert_original"])
def test_replaced_credential_fences_old_member_activation_while_queue_engine_continues(
    tmp_path, mutation
):
    store, database, member = _store(tmp_path)
    queue = _start(store).activation
    browser = _start(store, "browsers_members", member=member).activation
    _receipt(database, queue.physical_start_id)
    published = []
    assert store.publish_if_current(
        browser.engine,
        browser.activation_id,
        browser.generation,
        lambda: published.append("before"),
        member_id=member,
    )
    vault = CredentialVault(b"d" * 32)
    service = MemberEnrollmentService(database, vault)
    original = database.get_credential(member)
    if mutation == "rotate":
        service.rotate_password(member, "replacement-offline-credential")
    else:
        assert service.revoke_credential(member)
        replacement = (
            original
            if mutation == "reinsert_original"
            else vault.seal("replacement-offline-credential", member_id=member)
        )
        database.save_credential(member, replacement)
    assert not store.publish_if_current(
        browser.engine,
        browser.activation_id,
        browser.generation,
        lambda: published.append("stale"),
        member_id=member,
    )
    with pytest.raises(_api().EngineConflict):
        store.transition(browser.engine, browser.activation_id, browser.generation, "RUNNING")
    with pytest.raises(_api().EngineConflict):
        _start(store, "browsers_members", member=member)
    assert store.publish_if_current(
        queue.engine, queue.activation_id, queue.generation, lambda: published.append("queues")
    )
    assert published == ["before", "queues"]


def test_cold_recovery_never_adopts_stale_applied_start_or_releases_uncertain_hold(tmp_path):
    store, database, member = _store(tmp_path)
    original = _start(store).activation
    _receipt(database, original.physical_start_id)
    cold = _api().EngineIntentStore(database, boot_id=str(uuid4()))
    recovered = cold.recover_cold()
    assert recovered[0].state == "UNCERTAIN" and not recovered[0].released
    assert recovered[0].boot_id == original.boot_id
    assert cold.recover_cold() == recovered
    with pytest.raises(_api().EngineConflict):
        _start(cold, "browsers_members", member=member)
    with pytest.raises(_api().EngineConflict):
        _release(cold, original, closed=True)
    assert not cold.publish_if_current(
        original.engine,
        original.activation_id,
        original.generation,
        lambda: pytest.fail("cold publish"),
    )
    legacy = LifecycleIntentStore(database)
    legacy.record_automatic_check(original.physical_start_id, "NO_EVENT_OBSERVED")
    assert legacy.request_work_stop(original.physical_start_id) is None
    physical_stop = legacy.request("bot", "stop", str(uuid4()), on_demand=True)
    assert not cold.recover_cold()[0].released
    _receipt(database, physical_stop.operation_id, "stop")
    recovered = cold.recover_cold()
    assert recovered[0].released and recovered[0].state == "STOPPED"
    fresh = _start(cold).activation
    assert fresh.generation == 2 and fresh.boot_id == cold.boot_id
    assert fresh.physical_start_id != original.physical_start_id


@pytest.mark.parametrize("both", [False, True])
@pytest.mark.parametrize("physical_status", ["APPLIED", "UNCERTAIN"])
def test_explicit_cold_stop_uses_physical_runner_and_retains_holds_until_applied(
    tmp_path, both, physical_status
):
    store, database, member = _store(tmp_path)
    original = _start(store).activation
    if both:
        _start(store, "browsers_members", member=member)
    _receipt(database, original.physical_start_id, status=physical_status)
    cold = _api().EngineIntentStore(database, boot_id=str(uuid4()))
    assert all(item.state == "UNCERTAIN" for item in cold.recover_cold())
    operation = str(uuid4())
    decision = _stop(cold, original, operation=operation)
    assert decision.physical_intent is not None and decision.physical_intent.target == "stop"
    assert decision.physical_intent.work_start_id == original.physical_start_id
    assert _stop(cold, original, operation=operation).physical_intent == decision.physical_intent
    assert all(not item.released for item in cold.recover_cold())
    _receipt(database, decision.physical_intent.operation_id, "stop")
    assert all(item.released for item in cold.recover_cold())
    fresh = _start(cold).activation
    assert fresh.generation == 2 and fresh.boot_id == cold.boot_id


def test_physical_stop_reconciles_uncertain_current_boot_hold_without_auto_resume(tmp_path):
    store, database, _member = _store(tmp_path)
    activation = _start(store).activation
    _receipt(database, activation.physical_start_id)
    _stop(store, activation)
    assert not _release(store, activation, closed=False).activation.released
    physical = LifecycleIntentStore(database).request("bot", "stop", str(uuid4()), on_demand=True)
    _receipt(database, physical.operation_id, "stop")
    reconciled = store.recover_cold()
    assert reconciled[0].released and reconciled[0].state == "STOPPED"
    assert LifecycleIntentStore(database).current().operation_id == physical.operation_id


@pytest.mark.parametrize("physical_status", ["APPLIED", "UNCERTAIN"])
def test_explicit_uncertain_stop_recovers_physically_only_after_peer_is_fenced(
    tmp_path, physical_status
):
    store, database, member = _store(tmp_path)
    first = _start(store).activation
    second = _start(store, "browsers_members", member=member).activation
    _receipt(database, first.physical_start_id, status=physical_status)
    _stop(store, first)
    _release(store, first, closed=False)
    assert _stop(store, first).physical_intent is None
    assert LifecycleIntentStore(database).current().target == "start"
    _stop(store, second)
    _release(store, second, closed=False)
    operation = str(uuid4())
    recovery = _stop(store, first, operation=operation)
    assert recovery.physical_intent is not None
    assert recovery.physical_intent.target == "stop"
    assert recovery.physical_intent.work_start_id == first.physical_start_id
    assert _stop(store, first, operation=operation).physical_intent == recovery.physical_intent
    assert all(not state.released for state in store.snapshot())
    _receipt(database, recovery.physical_intent.operation_id, "stop")
    before = store.snapshot()
    assert store.restartable_engines() == frozenset({first.engine, second.engine})
    assert store.snapshot() == before  # Readiness GET never reconciles the ledger.
    assert all(state.released for state in store.recover_cold())


@pytest.mark.parametrize("prior_status", ["CLAIMED", "REFUSED", "FAILED", "UNCERTAIN"])
@pytest.mark.parametrize("cold_boot", [False, True])
def test_fresh_scoped_stop_reconciles_incomplete_physical_stop_without_replaying_old_operation(
    tmp_path, prior_status, cold_boot
):
    store, database, _member = _store(tmp_path)
    activation = _start(store).activation
    _receipt(database, activation.physical_start_id)
    _stop(store, activation)
    _release(store, activation, closed=False)
    first_operation = str(uuid4())
    first = _stop(store, activation, operation=first_operation).physical_intent
    assert first is not None
    _receipt(database, first.operation_id, "stop", status=prior_status)
    if cold_boot:
        store = _api().EngineIntentStore(database, boot_id=str(uuid4()))
        store.recover_cold()
    before = LifecycleIntentStore(database).current()
    assert before.status == prior_status
    assert _stop(store, activation, operation=first_operation).physical_intent is None
    assert LifecycleIntentStore(database).current() == before
    assert store.legacy_recovery_state() == "NONE"
    operation = str(uuid4())
    retry = _stop(store, activation, operation=operation).physical_intent
    assert retry is not None and retry.operation_id != first.operation_id
    assert retry.target == "stop" and retry.work_start_id == activation.physical_start_id
    assert retry.status == "REQUESTED"
    assert _stop(store, activation, operation=operation).physical_intent == retry
    assert all(not item.released for item in store.snapshot())
    with database.connection() as connection:
        assert connection.execute(
            "SELECT action FROM audit_events WHERE audit_id=?",
            (host_marker(first.operation_id, "bot", "stop", prior_status)[0],),
        ).fetchone() == (host_marker(first.operation_id, "bot", "stop", prior_status)[1],)
    _receipt(database, retry.operation_id, "stop")
    assert all(item.released for item in store.recover_cold())


def test_fresh_legacy_stop_recovers_claim_from_an_old_installation_without_replaying_it(
    tmp_path, monkeypatch
):
    from boca_socios import host_on_demand_lifecycle as demand
    from test_host_on_demand_lifecycle import setup_demand

    _start_id, ledger, io, apply = setup_demand.__wrapped__(tmp_path, monkeypatch)
    database = ledger._database
    old = ledger.request("bot", "stop", str(uuid4()), on_demand=True)
    demand._transact(database.path, old.operation_id, "e" * 64, "claim")
    old_receipt = ledger.current()
    with pytest.raises(demand.OnDemandUnavailable):
        apply(old.operation_id)
    assert ledger.current() == old_receipt and io.events == []
    store = _api().EngineIntentStore(database, boot_id=str(uuid4()))
    assert store.legacy_recovery_state() == "CLAIMED"
    assert store.request_legacy_stop(old.operation_id) == old_receipt
    assert ledger.current() == old_receipt
    fresh = store.request_legacy_stop(str(uuid4()))
    assert fresh.operation_id != old.operation_id and fresh.status == "REQUESTED"
    assert apply(fresh.operation_id).status == "APPLIED"
    assert io.events == []
    with database.connection() as connection:
        assert LifecycleIntentStore.for_operation(connection, old.operation_id) == old_receipt
    next_start = _start(store).physical_intent
    assert next_start is not None and apply(next_start.operation_id).status == "APPLIED"
    assert io.events.count("worker-start") == 1


def test_start_readiness_requires_usable_shared_epoch_and_available_budget(tmp_path):
    store, database, member = _store(tmp_path)
    first = _start(store).activation
    second = _start(store, "browsers_members", member=member).activation
    _receipt(database, first.physical_start_id)
    _stop(store, first)
    _release(store, first, closed=True)
    assert store.restartable_engines() == frozenset({first.engine})
    _stop(store, second)
    _release(store, second, closed=False)
    assert not store.restartable_engines()
    recovery = _stop(store, second).physical_intent
    assert recovery is not None
    assert not store.restartable_engines()
    _receipt(database, recovery.operation_id, "stop")
    store.recover_cold()
    full = store.start(
        "queues_tokens", str(uuid4()), counts={"chromium": 50, "firefox": 0, "webkit": 0}
    ).activation
    _receipt(database, full.physical_start_id)
    assert not store.restartable_engines()
    _stop(store, full)
    final = _release(store, full, closed=True).physical_intent
    assert final is not None
    assert not store.restartable_engines()  # STOP is requested, not physically confirmed.
    _receipt(database, final.operation_id, "stop")
    assert store.restartable_engines() == frozenset({first.engine, second.engine})


@pytest.mark.parametrize("status", ["APPLIED", "FAILED", "UNCERTAIN"])
def test_explicit_legacy_recovery_preserves_history_and_creates_no_logical_job(tmp_path, status):
    store, database, _member = _store(tmp_path)
    legacy = LifecycleIntentStore(database).request("bot", "start", str(uuid4()), on_demand=True)
    _receipt(database, legacy.operation_id, status=status)
    assert store.snapshot() == () and not store.restartable_engines()
    assert store.legacy_recovery_state() == "REQUIRED"
    operation = str(uuid4())
    recovery = store.request_legacy_stop(operation)
    assert recovery.operation_id == operation and recovery.target == "stop"
    assert recovery.on_demand and recovery.status == "REQUESTED"
    assert store.request_legacy_stop(operation) == recovery
    assert store.request_legacy_stop(str(uuid4())) == recovery
    assert store.legacy_recovery_state() == "REQUESTED"
    assert store.snapshot() == ()  # Recovery cannot manufacture an engine activation.
    with pytest.raises(_api().EngineConflict):
        _start(store)
    _receipt(database, operation, "stop")
    assert store.legacy_recovery_state() == "NONE"
    assert store.restartable_engines() == frozenset({"queues_tokens", "browsers_members"})
    fresh = _start(store).activation
    assert fresh.generation == 1 and fresh.physical_start_id not in {operation, legacy.operation_id}
    with database.connection() as connection:
        assert connection.execute(
            "SELECT 1 FROM audit_events WHERE audit_id=?", (legacy.operation_id,)
        ).fetchone() == (1,)


def test_legacy_recovery_rechecks_holds_before_superseding_a_physical_start(tmp_path):
    store, database, _member = _store(tmp_path)
    fresh = _start(store).activation
    for completed in (False, True):
        if completed:
            _receipt(database, fresh.physical_start_id)
        assert store.legacy_recovery_state() == "NONE"
        with pytest.raises(_api().EngineConflict):
            store.request_legacy_stop(str(uuid4()))
        assert LifecycleIntentStore(database).current().operation_id == fresh.physical_start_id
    _stop(store, fresh)
    _release(store, fresh, closed=False)
    with pytest.raises(_api().EngineConflict):
        store.request_legacy_stop(str(uuid4()))


def test_cold_stop_reports_quarantine_even_when_start_failed_before_restart(tmp_path):
    store, database, _member = _store(tmp_path)
    original = _start(store).activation
    _receipt(database, original.physical_start_id, status="FAILED")
    store.transition(original.engine, original.activation_id, original.generation, "FAILED")
    cold = _api().EngineIntentStore(database, boot_id=str(uuid4()))
    result = _stop(cold, original)
    assert result.activation.state == "UNCERTAIN"
    assert result.activation == cold.snapshot()[0]
    assert result.physical_intent.target == "stop"


def test_storage_identity_change_is_checked_before_in_memory_publication(tmp_path, monkeypatch):
    store, database, _member = _store(tmp_path)
    activation = _start(store).activation
    _receipt(database, activation.physical_start_id)
    api = _api()
    original_identity = api._db_identity(database.path)
    identities = iter([original_identity, (original_identity[0], original_identity[1] + 1)])
    # Replace only the OS metadata boundary; the ledger and writer transaction
    # are real SQLite and must never publish an already-invalid snapshot.
    monkeypatch.setattr(api, "_db_identity", lambda path: next(identities))
    published = []
    with pytest.raises(api.EngineStorageUnavailable):
        store.publish_if_current(
            activation.engine,
            activation.activation_id,
            activation.generation,
            lambda: published.append("stale"),
        )
    assert published == []


def test_legacy_applied_start_without_current_boot_hold_cannot_be_adopted(tmp_path):
    store, database, _member = _store(tmp_path)
    old = LifecycleIntentStore(database).request("bot", "start", str(uuid4()), on_demand=True)
    _receipt(database, old.operation_id)
    with pytest.raises(_api().EngineConflict):
        _start(store)
    assert store.snapshot() == ()
    assert LifecycleIntentStore(database).current().operation_id == old.operation_id


def test_hold_failure_rolls_back_physical_start_and_budget_without_schema_changes(tmp_path):
    store, database, _member = _store(tmp_path)
    with database.connection() as connection, connection:
        connection.execute(
            "CREATE TRIGGER refuse_engine_hold BEFORE INSERT ON audit_events "
            "WHEN NEW.action LIKE 'boca_engine_v1:hold:%' "
            "BEGIN SELECT RAISE(ABORT, 'fixture hold failure'); END"
        )
        before = connection.execute(
            "SELECT type,name,sql FROM sqlite_master ORDER BY name"
        ).fetchall()
    with pytest.raises(_api().EngineStorageUnavailable):
        _start(store)
    assert store.snapshot() == ()
    assert LifecycleIntentStore(database).current() is None
    with database.connection() as connection:
        assert (
            connection.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall()
            == before
        )


def test_unknown_engine_ledger_record_fails_closed_without_repair(tmp_path):
    store, database, _member = _store(tmp_path)
    activation = _start(store).activation
    with database.connection() as connection, connection:
        connection.execute(
            "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
            (str(uuid4()), "boca_engine_v1:future:unreviewed"),
        )
    with pytest.raises(_api().EngineStorageUnavailable):
        store.snapshot()
    with pytest.raises(_api().EngineStorageUnavailable):
        _release(store, activation)


def test_absent_database_is_never_created_by_read_or_start(tmp_path):
    database = Database(tmp_path / "missing.sqlite3")
    store = _api().EngineIntentStore(database, boot_id=str(uuid4()))
    with pytest.raises(_api().EngineStorageUnavailable):
        store.snapshot()
    with pytest.raises(_api().EngineStorageUnavailable):
        _start(store)
    assert not database.path.exists()
