"""Automatic worker observation follows the confirmed owner activation only."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from boca_socios.panel.lifecycle_intents import LifecycleIntentStore
from test_bot_work_session import confirm_start, prepared  # noqa: F401


class Monitor:
    def __init__(self):
        self.observed = []
        self.checking = 0

    def mark_checking(self):
        self.checking += 1

    def observe_global(self, observation):
        self.observed.append(observation.outcome)


@pytest.mark.parametrize(
    "outcome", ["NO_EVENT_OBSERVED", "QUEUE_INACTIVE", "TARGET_OBSERVED", "CHECK_FAILED"]
)
def test_terminal_check_records_reason_and_wakes_one_stop(prepared, outcome):  # noqa: F811
    from boca_socios.integration.automatic_observation import AutomaticObservationSession

    database, _, _ = prepared
    ledger = LifecycleIntentStore(database)
    start = str(uuid4())
    ledger.request("bot", "start", start, on_demand=True)
    confirm_start(database, start)
    monitor = Monitor()
    calls = []

    async def observe():
        calls.append("observed")
        return SimpleNamespace(outcome=outcome, observed_at=datetime.now(UTC))

    wakes = []
    worker = AutomaticObservationSession(
        ledger=ledger, observe=observe, monitor=monitor, wake=wakes.append
    )
    worker.run_confirmed(start)
    assert calls == ["observed"] and monitor.observed == [outcome]
    assert ledger.current().work_start_id == start
    assert wakes == [ledger.current().operation_id]
    worker.run_confirmed(start)
    assert calls == ["observed"] and len(wakes) == 1


def test_queue_poll_reuses_activation_until_target_without_new_start(prepared):  # noqa: F811
    from boca_socios.integration.automatic_observation import AutomaticObservationSession

    database, _, _ = prepared
    ledger = LifecycleIntentStore(database)
    start = str(uuid4())
    ledger.request("bot", "start", start, on_demand=True)
    confirm_start(database, start)
    values = iter(["PREQUEUE", "QUEUE_ACTIVE", "TARGET_OBSERVED"])
    monitor = Monitor()
    pauses = []

    async def observe():
        return SimpleNamespace(outcome=next(values), observed_at=datetime.now(UTC))

    worker = AutomaticObservationSession(
        ledger=ledger, observe=observe, monitor=monitor, wake=lambda _: None
    )
    worker.run_confirmed(start, wait=lambda seconds: pauses.append(seconds) or False)
    assert monitor.observed == ["PREQUEUE", "QUEUE_ACTIVE", "TARGET_OBSERVED"]
    assert pauses == [5.0, 5.0]
    assert ledger.current().work_start_id == start


def test_unconfirmed_start_and_owner_stop_never_initiate_navigation(prepared):  # noqa: F811
    from boca_socios.integration.automatic_observation import AutomaticObservationSession

    database, _, _ = prepared
    ledger = LifecycleIntentStore(database)
    start = str(uuid4())
    ledger.request("bot", "start", start, on_demand=True)

    async def observe():
        pytest.fail("unconfirmed start must not contact worker")

    worker = AutomaticObservationSession(
        ledger=ledger, observe=observe, monitor=Monitor(), wake=lambda _: None
    )
    worker.run_confirmed(start)
    confirm_start(database, start)
    ledger.request("bot", "stop", str(uuid4()), on_demand=True)
    worker.run_confirmed(start)


def test_ack_between_observer_reads_does_not_lose_the_activation(prepared, monkeypatch):  # noqa: F811
    from boca_socios.integration.automatic_observation import AutomaticObservationSession
    from boca_socios.panel.lifecycle_intents import host_marker

    database, _, _ = prepared
    ledger = LifecycleIntentStore(database)
    start = str(uuid4())
    ledger.request("bot", "start", start, on_demand=True)
    with database.connection() as connection, connection:
        connection.execute(
            "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
            host_marker(start, "bot", "start", "CLAIMED"),
        )
    current = ledger.current
    first = True

    def commit_after_read():
        nonlocal first
        snapshot = current()
        if first:
            first = False
            with database.connection() as connection, connection:
                connection.execute(
                    "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
                    host_marker(start, "bot", "start", "APPLIED"),
                )
        return snapshot

    monkeypatch.setattr(ledger, "current", commit_after_read)
    monitor = Monitor()

    async def observe():
        return SimpleNamespace(outcome="NO_EVENT_OBSERVED", observed_at=datetime.now(UTC))

    worker = AutomaticObservationSession(
        ledger=ledger, observe=observe, monitor=monitor, wake=lambda _: None
    )
    worker._await_applied(start)
    assert monitor.observed == ["NO_EVENT_OBSERVED"]
