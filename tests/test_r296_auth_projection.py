"""Production monitor/view retain queue evidence through correlated authentication."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from boca_socios.browser.boca_auth_protocol import BocaAuthReadiness, BocaAuthReply
from boca_socios.browser.queue_page_observation import parse_queue_page_observation
from boca_socios.integration.automatic_observation import AutomaticObservationSession
from boca_socios.integration.boca_login import authenticate_member
from boca_socios.integration.command_store import CommandStore
from boca_socios.panel.lifecycle_intents import LifecycleIntentStore
from boca_socios.panel.private_token_view import automatic_message
from boca_socios.queue.private_pass_monitor import PrivateAutomaticObservationMonitor
from boca_socios.reservation_guard import ReservationAttemptGuard
from boca_socios.security.member_auth_contract import PrivateBocaAuthMonitor
from test_bot_work_session import confirm_start
from test_member_auth_contract import _enrolled


@pytest.mark.parametrize("result", ["success", "failed", "stop", "newer", "cancel"])
def test_real_monitor_authentication_overlay_preserves_queue_truth_and_correlation(
    tmp_path, result
):
    db, vault, member = _enrolled(tmp_path)
    CommandStore(db).migrate()
    guard = ReservationAttemptGuard(db)
    guard.migrate()
    guard.migrate_simulation()
    ledger = LifecycleIntentStore(db)
    start = str(uuid4())
    ledger.request("bot", "start", start, on_demand=True, auth_member_id=member)
    confirm_start(db, start)
    monitor = PrivateAutomaticObservationMonitor(configured=True)
    auth = PrivateBocaAuthMonitor()
    calls = []

    class Worker:
        async def prepare_boca_login(self, operation_id):
            waiting = not calls
            calls.append("prepare")
            observed = parse_queue_page_observation(
                final_url="https://offline.example.invalid/",
                queue_model=None,
                markers=frozenset({"prequeue"}) if waiting else frozenset(),
                observed_at=datetime.now(UTC),
            )
            return BocaAuthReadiness(
                operation_id, observed, None if waiting else "a" * 64, 0 if waiting else 15
            )

        async def login_boca(self, request):
            calls.append("login")
            snapshot = monitor.snapshot()
            assert snapshot["latest"]["outcome"] == "UNKNOWN"
            assert snapshot["status"] == "AUTHENTICATING"
            assert "en curso" in automatic_message(snapshot)
            assert "Ciclo finalizado" not in automatic_message(snapshot)
            if result == "failed":
                raise OSError("private failure")
            if result in ("stop", "newer"):
                ledger.request("bot", "stop", str(uuid4()), on_demand=True)
            if result == "newer":
                monitor.begin_activation(str(uuid4()))
                monitor.mark_checking()
            if result == "cancel":
                session._cancel.set()
            return BocaAuthReply(
                request.operation_id,
                request.nonce,
                b'{"token":"private-access","refreshToken":"private-refresh"}',
            )

    worker = Worker()

    async def forbidden():
        pytest.fail("selected member must use worker readiness")

    def wait(_seconds):
        state = monitor.snapshot()
        assert state["latest"]["outcome"] == "PREQUEUE"
        assert "Esperando" in automatic_message(state)
        return False

    session = AutomaticObservationSession(
        ledger=ledger,
        observe=forbidden,
        monitor=monitor,
        wake=lambda _: None,
        prepare_auth=worker.prepare_boca_login,
        authenticate=lambda selected, ready: authenticate_member(
            db, vault, worker, selected, ready
        ),
        auth_monitor=auth,
    )
    session.run_confirmed(start, wait=wait)
    assert calls == ["prepare", "prepare", "login"]
    expected = {
        "success": "AUTH_OBSERVED",
        "failed": "AUTH_FAILED",
        "stop": "AUTH_CANCELLED",
        "cancel": "AUTH_CANCELLED",
        "newer": "AUTOMATIC_CHECKING",
    }[result]
    snapshot = monitor.snapshot()
    assert snapshot["status"] == expected
    if result != "newer":
        assert snapshot["latest"]["outcome"] == "UNKNOWN"
        assert "No se reconocieron" not in automatic_message(snapshot)
    assert len(auth.list_summaries()) == (1 if result == "success" else 0)
    assert "private-access" not in repr(snapshot) and member not in repr(snapshot)


def test_auth_overlay_preserves_private_target_and_rejects_late_phase():
    monitor = PrivateAutomaticObservationMonitor(configured=True)
    old, current = str(uuid4()), str(uuid4())
    monitor.begin_activation(old)
    observed = parse_queue_page_observation(
        final_url="https://offline.example.invalid/?queueittoken=private-queue-value",
        queue_model=None,
        markers=frozenset(),
        observed_at=datetime.now(UTC),
    )
    assert monitor.observe_auth(old, "AUTHENTICATING", observation=observed)
    assert monitor.observe_auth(old, "AUTH_OBSERVED")
    assert monitor.snapshot()["has_target_url"] is True
    assert monitor.owner_global_details(owner_authenticated=True) is observed
    assert "private-queue-value" not in repr(monitor.snapshot())
    assert not monitor.observe_auth(old, "AUTH_CANCELLED")
    monitor.begin_activation(current)
    before = monitor.snapshot()
    assert not monitor.observe_auth(old, "AUTH_OBSERVED", observation=observed)
    after = monitor.snapshot()
    assert after["status"] == before["status"] == "AUTOMATIC_CHECKING"
    assert after["latest"] is None and not after["has_target_url"]
