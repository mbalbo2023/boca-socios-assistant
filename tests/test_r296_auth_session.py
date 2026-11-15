"""Selected member activation uses the real ledger/vault and an offline worker."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest

from boca_socios.panel.lifecycle_intents import LifecycleConflict, LifecycleIntentStore
from test_bot_work_session import confirm_start
from test_member_auth_contract import _enrolled


def test_selection_is_atomic_persistent_and_cannot_change(tmp_path):
    db, _, member = _enrolled(tmp_path)
    ledger = LifecycleIntentStore(db)
    start = str(uuid4())
    ledger.request("bot", "start", start, on_demand=True, auth_member_id=member)
    assert LifecycleIntentStore(db).auth_member_for_start(start) == member
    for operation in (start, str(uuid4())):
        with pytest.raises(LifecycleConflict):
            ledger.request("bot", "start", operation, on_demand=True)
    with db.connection() as conn, conn:
        conn.execute("DELETE FROM credentials WHERE member_id=?", (member,))
    with pytest.raises(LifecycleConflict):
        ledger.request("bot", "start", start, on_demand=True, auth_member_id=member)


@pytest.mark.parametrize("mutation", ["stop", "revoke"])
def test_publication_fence_serializes_stop_and_revocation(tmp_path, mutation):
    db, _, member = _enrolled(tmp_path)
    ledger = LifecycleIntentStore(db)
    start = str(uuid4())
    ledger.request("bot", "start", start, on_demand=True, auth_member_id=member)
    confirm_start(db, start)
    entered, release, stopping = Event(), Event(), Event()
    published = []

    def publish():
        entered.set()
        assert release.wait(2)
        published.append("published")

    def stop():
        stopping.set()
        if mutation == "stop":
            ledger.request("bot", "stop", str(uuid4()), on_demand=True)
        else:
            with db.connection() as conn, conn:
                conn.execute("DELETE FROM credentials WHERE member_id=?", (member,))
        published.append("stopped")

    with ThreadPoolExecutor(2) as pool:
        publication = pool.submit(ledger.publish_auth_if_current, start, member, publish)
        assert entered.wait(2)
        stopped = pool.submit(stop)
        assert stopping.wait(2)
        assert not stopped.done()
        release.set()
        assert publication.result()
        stopped.result()
    assert published == ["published", "stopped"]
    assert not ledger.publish_auth_if_current(start, member, lambda: published.append("late"))


@pytest.mark.parametrize(
    "race", ["none", "stop", "revoke", "unavailable", "bad_reply", "wrong_prepare"]
)
def test_real_sqlite_vault_fake_worker_end_to_end(tmp_path, race):
    from datetime import UTC, datetime

    from boca_socios.browser.boca_auth_protocol import BocaAuthReadiness, BocaAuthReply
    from boca_socios.browser.queue_page_observation import parse_queue_page_observation
    from boca_socios.integration.automatic_observation import AutomaticObservationSession
    from boca_socios.integration.boca_login import authenticate_member
    from boca_socios.integration.command_store import CommandStore
    from boca_socios.reservation_guard import ReservationAttemptGuard
    from boca_socios.security.member_auth_contract import PrivateBocaAuthMonitor
    from test_automatic_observation_session import Monitor

    db, vault, member = _enrolled(tmp_path)
    CommandStore(db).migrate()
    guard = ReservationAttemptGuard(db)
    guard.migrate()
    guard.migrate_simulation()
    ledger = LifecycleIntentStore(db)
    start = str(uuid4())
    ledger.request("bot", "start", start, on_demand=True, auth_member_id=member)
    confirm_start(db, start)
    monitor = PrivateBocaAuthMonitor()
    calls, wakes, pauses = [], [], []

    class Worker:
        async def prepare_boca_login(self, operation_id):
            calls.append("prepare")
            if race == "unavailable":
                raise OSError("private error must not escape")
            waiting = calls.count("prepare") == 1 and race != "wrong_prepare"
            observation = parse_queue_page_observation(
                final_url="https://offline.example.invalid/",
                queue_model=None,
                markers=frozenset({"prequeue"}) if waiting else frozenset(),
                observed_at=datetime.now(UTC),
            )
            return BocaAuthReadiness(
                str(uuid4()) if race == "wrong_prepare" else operation_id,
                observation,
                None if waiting else "a" * 64,
                0 if waiting else 15,
            )

        async def login_boca(self, request):
            calls.append("login")
            assert request.email == "socio@example.invalid"
            assert request.password == "existing-encrypted-credential"
            assert monitor.list_summaries() == ()  # Service cannot publish ahead of fence.
            if race == "stop":
                ledger.request("bot", "stop", str(uuid4()), on_demand=True)
            elif race == "revoke":
                with db.connection() as conn, conn:
                    conn.execute("DELETE FROM credentials WHERE member_id=?", (member,))
            return BocaAuthReply(
                request.operation_id,
                "b" * 64 if race == "bad_reply" else request.nonce,
                b'{"token":"offline-access","refreshToken":"offline-refresh"}',
            )

    worker = Worker()

    async def forbidden():
        pytest.fail("selected member must prepare through auth worker")

    session = AutomaticObservationSession(
        ledger=ledger,
        observe=forbidden,
        monitor=Monitor(),
        wake=wakes.append,
        prepare_auth=worker.prepare_boca_login,
        authenticate=lambda member_id, readiness: authenticate_member(
            db, vault, worker, member_id, readiness
        ),
        auth_monitor=monitor,
    )
    session.run_confirmed(start, wait=lambda seconds: pauses.append(seconds) or False)
    assert len(monitor.list_summaries()) == (1 if race == "none" else 0)
    assert calls == (
        ["prepare"] if race in ("unavailable", "wrong_prepare") else ["prepare", "prepare", "login"]
    )
    assert pauses == ([] if race in ("unavailable", "wrong_prepare") else [5.0])
    current = ledger.current()
    assert current.target == "stop"
    assert len(wakes) == (0 if race == "stop" else 1)
    if race != "stop":
        assert current.work_start_id == start
    session.run_confirmed(start)
    assert calls.count("login") <= 1
    restored = AutomaticObservationSession(
        ledger=LifecycleIntentStore(db), observe=forbidden, monitor=Monitor(), wake=wakes.append
    )
    with pytest.raises(RuntimeError):
        restored.start(start)
    with db.connection() as conn:
        serialized = repr(conn.execute("SELECT action FROM audit_events").fetchall())
    assert "offline-access" not in serialized and "existing-encrypted-credential" not in serialized


def test_final_fence_refuses_revoked_member_before_callback(tmp_path):
    db, _, member = _enrolled(tmp_path)
    ledger = LifecycleIntentStore(db)
    start = str(uuid4())
    ledger.request("bot", "start", start, on_demand=True, auth_member_id=member)
    confirm_start(db, start)
    with db.connection() as conn, conn:
        conn.execute("DELETE FROM credentials WHERE member_id=?", (member,))
    assert not ledger.publish_auth_if_current(start, member, lambda: pytest.fail("late publish"))


@pytest.mark.parametrize("count", [0, 1, 2])
def test_accessible_selector_has_explicit_observation_and_no_implicit_first_of_many(count):
    from boca_socios.panel.members import MemberView
    from boca_socios.panel.private_ui import bot_control

    members = tuple(
        MemberView(str(uuid4()), "Socio", "s•••@example.invalid", True) for _ in range(count)
    )
    revoked = MemberView(str(uuid4()), "Revocado", "r•••@example.invalid", False)
    page = bot_control(
        None, "csrf", str(uuid4()), str(uuid4()), auth_members=members + (revoked,)
    ).decode()
    assert '<label for="auth-member">' in page
    assert 'name="auth_member_id"' in page and "Sólo observar" in page
    assert revoked.member_id not in page
    if count == 1:
        assert f'value="{members[0].member_id}" selected' in page
    else:
        assert '<option value="" selected>' in page
        assert all(f'value="{m.member_id}" selected' not in page for m in members)
