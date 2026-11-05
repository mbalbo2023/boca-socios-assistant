"""Reboot-safe Boca synthetic engine: never replay after a durable owner STOP."""

from __future__ import annotations

import base64
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from boca_socios import runtime
from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.integration.beta import BetaCoordinator
from boca_socios.integration.command_host import BetaCommandHost
from boca_socios.integration.operational import LocalBetaRuntime, LocalRuntimeUnavailable
from boca_socios.panel.lifecycle_intents import LifecycleIntentStore, host_marker
from boca_socios.storage.database import Database


class NoSiteBrowser:
    calls = 0

    async def simulate_general_reservation(self) -> SimulationOutcome:
        self.calls += 1
        return SimulationOutcome.RESERVED_IN_SIMULATOR


@pytest.fixture
def prepared(tmp_path: Path) -> tuple[Path, Path, NoSiteBrowser, Database]:
    key = tmp_path / "boca_key"
    key.write_bytes(base64.b64encode(b"k" * 32) + b"\n")
    key.chmod(0o400)
    database_path = tmp_path / "boca.sqlite3"
    browser = NoSiteBrowser()
    first = LocalBetaRuntime.start(
        database_path=database_path, key_file=key, browser=browser, initialize_new=True
    )
    first.close()
    return database_path, key, browser, Database(database_path)


def accepted(db: Database, component: str, target: str) -> None:
    store = LifecycleIntentStore(db)
    request_id = str(uuid4())
    store.request(component, target, request_id)
    with db.connection() as connection, connection:
        for status in ("CLAIMED", "APPLIED"):
            connection.execute(
                "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
                host_marker(request_id, component, target, status),
            )
    assert store.current() is not None and store.current().status == "APPLIED"


def test_no_lifecycle_intent_preserves_legacy_start(
    prepared: tuple[Path, Path, NoSiteBrowser, Database],
) -> None:
    db_path, _key, _browser, _db = prepared
    assert runtime._engine_stopped_after_reboot(db_path, browser_backend="ipc") is False


def test_applied_bot_stop_is_recovered_as_stopped_before_any_thread_or_replay(
    prepared: tuple[Path, Path, NoSiteBrowser, Database],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path, key, browser, db = prepared
    accepted(db, "bot", "stop")
    assert runtime._engine_stopped_after_reboot(db_path, browser_backend="ipc") is True
    with sqlite3.connect(db_path) as connection:
        old_schema = connection.execute(
            "SELECT version, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert 8 not in {version for version, _ in old_schema}

    def forbidden_start(*_args: object, **_kwargs: object) -> None:
        pytest.fail("boot tried to start a synthetic command thread")

    async def forbidden_recover(_self: BetaCoordinator) -> None:
        pytest.fail("boot tried to replay an old command before STOP attestation")

    with monkeypatch.context() as patch:
        patch.setattr(BetaCommandHost, "start", classmethod(forbidden_start))
        patch.setattr(BetaCoordinator, "recover", forbidden_recover)
        service = LocalBetaRuntime.start(
            database_path=db_path,
            key_file=key,
            browser=browser,
            initial_engine_stopped=True,
        )
        assert service.ready
        assert service.commands.engine_stopped
        assert not service.commands.engine_running
        assert browser.calls == 0
        service.close()
    assert browser.calls == 0
    with sqlite3.connect(db_path) as connection:
        assert (
            connection.execute(
                "SELECT version, checksum FROM schema_migrations ORDER BY version"
            ).fetchall()
            == old_schema
        )


def test_stopped_boot_can_explicitly_start_after_owner_ack(
    prepared: tuple[Path, Path, NoSiteBrowser, Database],
) -> None:
    db_path, key, browser, db = prepared
    accepted(db, "bot", "stop")
    service = LocalBetaRuntime.start(
        database_path=db_path,
        key_file=key,
        browser=browser,
        initial_engine_stopped=runtime._engine_stopped_after_reboot(db_path, browser_backend="ipc"),
    )
    try:
        assert service.commands.engine_stopped
        assert service.commands.start_engine()
        assert service.commands.engine_running
    finally:
        service.close()


def test_applied_bot_start_reboots_running(
    prepared: tuple[Path, Path, NoSiteBrowser, Database],
) -> None:
    db_path, _key, _browser, db = prepared
    accepted(db, "bot", "start")
    assert runtime._engine_stopped_after_reboot(db_path, browser_backend="ipc") is False


def test_refused_host_receipt_never_assumes_a_running_engine(
    prepared: tuple[Path, Path, NoSiteBrowser, Database],
) -> None:
    db_path, _key, _browser, db = prepared
    request_id = str(uuid4())
    store = LifecycleIntentStore(db)
    store.request("bot", "start", request_id)
    with db.connection() as connection, connection:
        for status in ("CLAIMED", "REFUSED"):
            connection.execute(
                "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
                host_marker(request_id, "bot", "start", status),
            )
    assert store.current() is not None and store.current().status == "REFUSED"
    assert runtime._engine_stopped_after_reboot(db_path, browser_backend="ipc") is True


@pytest.mark.parametrize("progress", ("REQUESTED", "CLAIMED", "UNCERTAIN"))
def test_unresolved_host_request_cannot_boot_engine_or_service(
    prepared: tuple[Path, Path, NoSiteBrowser, Database],
    monkeypatch: pytest.MonkeyPatch,
    progress: str,
) -> None:
    db_path, _key, _browser, db = prepared
    request_id = str(uuid4())
    LifecycleIntentStore(db).request("bot", "stop", request_id)
    with db.connection() as connection, connection:
        if progress in {"CLAIMED", "UNCERTAIN"}:
            connection.execute(
                "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
                host_marker(request_id, "bot", "stop", "CLAIMED"),
            )
        if progress == "UNCERTAIN":
            connection.execute(
                "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
                host_marker(request_id, "bot", "stop", "UNCERTAIN"),
            )

    with pytest.raises(LocalRuntimeUnavailable):
        runtime._engine_stopped_after_reboot(db_path, browser_backend="ipc")

    class FakeSettings:
        browser_backend = "ipc"

        def __init__(self, path: Path) -> None:
            self.db_path = path

        def validate_beta(self) -> None:
            return None

    monkeypatch.setattr(
        runtime.LocalBetaRuntime,
        "start",
        lambda **_kwargs: pytest.fail("engine started before pending host request reconciled"),
    )
    with pytest.raises(LocalRuntimeUnavailable):
        runtime.build_beta_server(FakeSettings(db_path))  # type: ignore[arg-type]


def test_chromium_last_receipt_does_not_silently_reactivate_old_bot_stop(
    prepared: tuple[Path, Path, NoSiteBrowser, Database],
) -> None:
    db_path, _key, _browser, db = prepared
    accepted(db, "bot", "stop")
    accepted(db, "chromium", "stop")
    assert runtime._engine_stopped_after_reboot(db_path, browser_backend="ipc") is True


def test_legacy_backend_off_ignores_new_ipc_reboot_gate(
    prepared: tuple[Path, Path, NoSiteBrowser, Database],
) -> None:
    db_path, _key, _browser, db = prepared
    LifecycleIntentStore(db).request("bot", "stop", str(uuid4()))
    assert runtime._engine_stopped_after_reboot(db_path, browser_backend="off") is False


def test_new_storage_may_not_boot_pre_stopped_without_existing_ledger(
    tmp_path: Path,
) -> None:
    key = tmp_path / "key"
    key.write_bytes(base64.b64encode(b"k" * 32) + b"\n")
    key.chmod(0o400)
    with pytest.raises(ValueError):
        LocalBetaRuntime.start(
            database_path=tmp_path / "new.sqlite3",
            key_file=key,
            browser=NoSiteBrowser(),
            initialize_new=True,
            initial_engine_stopped=True,
        )
    assert not (tmp_path / "new.sqlite3").exists()
