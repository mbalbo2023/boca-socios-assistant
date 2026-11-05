"""One owner Chrome bearer persists; local CSRF and operation cache never do."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from boca_socios.panel.owner_session_store import OwnerBrowserSessionStore
from boca_socios.panel.owner_sessions import OwnerIdentity, OwnerSessions
from boca_socios.storage.database import Database

PERMISSIONS = frozenset({"members:enroll", "members:read", "simulation:write"})
BINDING = bytes.fromhex("b3" * 32)


def _sessions(store: OwnerBrowserSessionStore, clock: list[float]) -> OwnerSessions:
    return OwnerSessions(
        owner_subject="owner",
        verify_owner=lambda proof: (
            OwnerIdentity("owner", PERMISSIONS) if proof == "proof" else None
        ),
        persistent_store=store,
        authorization_binding=BINDING,
        restore_permissions=PERMISSIONS,
        clock=lambda: clock[0],
    )


def test_browser_cookie_outlives_old_idle_absolute_windows_and_renews_rolling_max_age() -> None:
    with TemporaryDirectory() as temporary:
        database = Database(Path(temporary) / "boca.sqlite3")
        database.migrate()
        store = OwnerBrowserSessionStore(database, owner_subject="owner")
        store.migrate()
        clock = [1.0]
        sessions = _sessions(store, clock)
        assert sessions.authenticate("not-proof") is None
        cookie = sessions.authenticate("proof")
        assert cookie is not None
        assert cookie.endswith("Max-Age=34560000")
        assert "Secure; HttpOnly; SameSite=Strict" in cookie
        bearer = cookie.split(";", 1)[0]
        # There is no server-side idle/absolute expiry; only Chrome may expire
        # its 400-day cookie, and each authenticated GET refreshes that window.
        for elapsed in (16 * 60, 9 * 3600, 45 * 86400, 300 * 86400):
            clock[0] = float(elapsed)
            active = sessions.lookup(bearer)
            assert active is not None
            assert sessions.renew_cookie(bearer, active) == cookie
        assert sessions.lookup(bearer + "; unrelated=present") is not None
        assert sessions.lookup(bearer + "; __Host-boca_session=duplicate") is None


def test_restart_rebuilds_fresh_csrf_operations_and_singleton_replaces_prior_cookie() -> None:
    with TemporaryDirectory() as temporary:
        path = Path(temporary) / "boca.sqlite3"
        database = Database(path)
        database.migrate()
        store = OwnerBrowserSessionStore(database, owner_subject="owner")
        store.migrate()
        clock = [1.0]
        original = _sessions(store, clock)
        first_cookie = original.authenticate("proof")
        assert first_cookie is not None
        first_cookie = first_cookie.split(";", 1)[0]
        first = original.lookup(first_cookie)
        assert first is not None
        old_csrf = first.csrf
        operation_id = original.new_operation(first)
        assert operation_id is not None
        assert original.reserve(first, operation_id, first.csrf, b"old-intent")[0] == 0

        clock[0] = 50_000.0
        restarted = _sessions(
            OwnerBrowserSessionStore(Database(path), owner_subject="owner"), clock
        )
        recovered = restarted.lookup(first_cookie)
        assert recovered is not None
        assert recovered.csrf != old_csrf and recovered.operations == {}
        assert recovered.permissions == PERMISSIONS
        assert restarted.reserve(recovered, operation_id, old_csrf, b"old-intent")[0] == 403
        assert restarted.new_operation(recovered) is not None

        # A new passkey login atomically replaces the ONE global authorization.
        second_cookie = restarted.authenticate("proof")
        assert second_cookie is not None
        second_cookie = second_cookie.split(";", 1)[0]
        assert second_cookie != first_cookie
        assert original.lookup(first_cookie) is None
        assert restarted.lookup(first_cookie) is None
        assert restarted.lookup(second_cookie) is not None
        original.revoke(first_cookie)  # stale Chrome logout cannot delete new authorization
        assert restarted.lookup(second_cookie) is not None
        restarted.revoke(second_cookie)
        assert restarted.lookup(second_cookie) is None
        assert _sessions(store, clock).lookup(second_cookie) is None


def test_reconstructed_cookie_needs_same_verifier_and_permission_scope() -> None:
    with TemporaryDirectory() as temporary:
        db = Database(Path(temporary) / "boca.sqlite3")
        db.migrate()
        store = OwnerBrowserSessionStore(db, owner_subject="owner")
        store.migrate()
        clock = [1.0]
        cookie = _sessions(store, clock).authenticate("proof")
        assert cookie is not None
        cookie = cookie.split(";", 1)[0]
        incompatible_binding = OwnerSessions(
            owner_subject="owner",
            verify_owner=lambda _: OwnerIdentity("owner", PERMISSIONS),
            persistent_store=store,
            authorization_binding=bytes.fromhex("99" * 32),
            restore_permissions=PERMISSIONS,
            clock=lambda: clock[0],
        )
        assert incompatible_binding.lookup(cookie) is None
        incompatible_permissions = OwnerSessions(
            owner_subject="owner",
            verify_owner=lambda _: OwnerIdentity("owner", PERMISSIONS),
            persistent_store=store,
            authorization_binding=BINDING,
            restore_permissions=frozenset({"members:enroll"}),
            clock=lambda: clock[0],
        )
        assert incompatible_permissions.authenticate("proof") is None
