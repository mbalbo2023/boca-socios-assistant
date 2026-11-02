"""The Telegram process contract is exercised with local SQLite and fake sends."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest

from boca_socios.notify import telegram_worker as worker
from boca_socios.notify.outbox import DeliveryState, NoticeKind, NotificationRequest
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from boca_socios.notify.telegram_delivery import TelegramDeliveryCoordinator
from boca_socios.notify.telegram_transport import TelegramAck, TelegramUnconfirmed
from boca_socios.notify.telegram_worker import (
    build_coordinator,
    main,
    run_worker,
    validate_worker_environment,
)


class FakeTransport:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.fail_first = fail_first
        self.notices = []

    def preflight(self) -> None:
        return None

    async def send(self, notice):
        self.notices.append(notice)
        if self.fail_first:
            self.fail_first = False
            raise TelegramUnconfirmed("synthetic provider uncertainty")
        return TelegramAck(42)


def valid_environment() -> dict[str, str]:
    return {
        "BOCA_ENVIRONMENT": "staging",
        "BOCA_RUNTIME_MODE": "simulation",
        "BOCA_ENGINE_MODE": "off",
        "BOCA_DB_PATH": "/data/boca.sqlite3",
        "BOCA_TELEGRAM_DISPATCH_MODE": "explicit",
    }


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("BOCA_ENVIRONMENT", "production"),
        ("BOCA_RUNTIME_MODE", "live"),
        ("BOCA_ENGINE_MODE", "on"),
        ("BOCA_DB_PATH", "/other/boca.sqlite3"),
        ("BOCA_TELEGRAM_DISPATCH_MODE", "off"),
    ],
)
def test_worker_refuses_changed_or_missing_opt_in(name: str, value: str) -> None:
    environment = valid_environment()
    environment[name] = value
    with pytest.raises(ValueError, match="Telegram worker configuration unavailable"):
        validate_worker_environment(environment)
    environment.pop(name)
    with pytest.raises(ValueError, match="Telegram worker configuration unavailable"):
        validate_worker_environment(environment)


def test_worker_cli_requires_explicit_serve_and_redacts_configuration(capsys) -> None:
    assert main([], {}) == 2
    assert main(["serve"], {"BOCA_TELEGRAM_DISPATCH_MODE": "secret-looking-value"}) == 2
    assert capsys.readouterr().err == "TELEGRAM_WORKER_NO_GO\nTELEGRAM_WORKER_NO_GO\n"


def test_worker_requires_identity_bound_acceptance_before_build_or_claim(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(worker, "require_effective_limits", lambda: calls.append("limits"))
    monkeypatch.setattr(worker, "verify_custody", lambda: calls.append("custody"))

    def reject(*_args):
        calls.append("ready")
        raise ValueError("synthetic secret must not escape")

    monkeypatch.setattr(worker, "verify_ready", reject)
    monkeypatch.setattr(
        worker, "build_coordinator", lambda *_args: pytest.fail("claim construction forbidden")
    )
    assert main(["serve"], valid_environment()) == 2
    assert calls == []
    assert main(["serve", "a" * 40, "12345", "b" * 64], valid_environment()) == 2
    assert calls == ["limits", "custody", "ready"]
    assert capsys.readouterr().err == "TELEGRAM_WORKER_NO_GO\nTELEGRAM_WORKER_NO_GO\n"


def test_worker_only_runs_after_offline_gate_with_same_transport(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[object] = []
    marker = object()
    monkeypatch.setattr(worker, "require_effective_limits", lambda: calls.append("limits"))
    monkeypatch.setattr(worker, "verify_custody", lambda: calls.append("custody"))
    monkeypatch.setattr(worker, "TelegramTransport", lambda *_args: marker)
    monkeypatch.setattr(worker, "verify_ready", lambda *args: calls.append(("ready", args)))
    monkeypatch.setattr(
        worker,
        "build_coordinator",
        lambda *args: calls.append(("coordinator", args)) or marker,
    )

    async def stopped(coordinator, _stopping):
        calls.append(("run", coordinator))

    monkeypatch.setattr(worker, "run_worker", stopped)
    assert main(["serve", "a" * 40, "12345", "b" * 64], valid_environment()) == 0
    assert calls == [
        "limits",
        "custody",
        ("ready", (worker._DATABASE, marker, "a" * 40, 12345, "b" * 64)),
        ("coordinator", (worker._DATABASE, marker)),
        ("run", marker),
    ]
    assert capsys.readouterr().out == (
        f"BOCA_TELEGRAM_READY state=VERIFIED source_sha={'a' * 40} api_accepted=1 identity=pinned\n"
    )


class WorkerLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = Path(temporary.name) / "boca.sqlite3"
        self.transport = FakeTransport()

    def coordinator(self, transport: FakeTransport) -> TelegramDeliveryCoordinator:
        return build_coordinator(self.database, transport, clock=lambda: 200.0)

    def test_missing_or_unprepared_storage_never_creates_or_claims(self) -> None:
        stopping = Event()
        with self.assertRaisesRegex(RuntimeError, "storage is not prepared"):
            asyncio.run(run_worker(self.coordinator(self.transport), stopping, interval=0.01))
        self.assertFalse(self.database.exists())
        outbox = SqliteNotificationOutbox(self.database)
        outbox.migrate()
        request = NotificationRequest(uuid4(), NoticeKind.HEARTBEAT, {})
        outbox.enqueue(request, now=100.0)
        with self.assertRaisesRegex(RuntimeError, "storage is not prepared"):
            asyncio.run(run_worker(self.coordinator(self.transport), stopping, interval=0.01))
        self.assertEqual(outbox.get(request.idempotency_key).state, DeliveryState.PENDING)
        self.assertEqual(self.transport.notices, [])
        with outbox.database.connection() as connection:
            self.assertIsNone(
                connection.execute("SELECT 1 FROM schema_migrations WHERE version=7").fetchone()
            )

    def test_ambiguous_send_stops_before_next_notice_and_never_retries_it(self) -> None:
        outbox = SqliteNotificationOutbox(self.database)
        outbox.migrate()
        first = NotificationRequest(uuid4(), NoticeKind.STATE_CHANGED, {})
        second = NotificationRequest(uuid4(), NoticeKind.HEARTBEAT, {})
        outbox.enqueue(first, now=100.0)
        outbox.enqueue(second, now=101.0)
        transport = FakeTransport(fail_first=True)
        worker = self.coordinator(transport)
        worker.prepare_storage()  # Simulates a separate, reviewed preparation step.
        with self.assertRaisesRegex(RuntimeError, "review required"):
            asyncio.run(run_worker(worker, Event(), interval=0.01))
        self.assertEqual(len(transport.notices), 1)
        self.assertEqual(outbox.get(first.idempotency_key).state, DeliveryState.EXHAUSTED)
        self.assertEqual(outbox.get(second.idempotency_key).state, DeliveryState.PENDING)
        later = FakeTransport()
        self.assertEqual(asyncio.run(self.coordinator(later).tick()).attempted, 1)
        self.assertEqual(later.notices[0].idempotency_key, second.idempotency_key)
        # A separate explicit invocation can process the other key only.

    def test_graceful_stop_does_not_send_after_stop(self) -> None:
        outbox = SqliteNotificationOutbox(self.database)
        outbox.migrate()
        worker = self.coordinator(self.transport)
        worker.prepare_storage()
        stopping = Event()
        stopping.set()
        asyncio.run(run_worker(worker, stopping, interval=0.01))
        self.assertEqual(self.transport.notices, [])


def test_telegram_compose_is_separate_off_by_default_and_bounded() -> None:
    root = Path(__file__).resolve().parents[1]
    composed = json.loads((root / "compose.telegram.json").read_text(encoding="utf-8"))
    assert composed["name"] == "boca-socios"
    assert list(composed["services"]) == ["telegram"]
    worker = composed["services"]["telegram"]
    assert worker["profiles"] == ["telegram-opt-in"]
    assert worker["image"] == "${BOCA_IMAGE:?BOCA_IMAGE_digest_is_required}"
    assert worker["command"] == [
        "python",
        "-m",
        "boca_socios.notify.telegram_worker",
        "serve",
        "${BOCA_SOURCE_SHA:?BOCA_SOURCE_SHA_required}",
        "${BOCA_TELEGRAM_EXPECTED_BOT_ID:?BOCA_TELEGRAM_EXPECTED_BOT_ID_required}",
        "${BOCA_TELEGRAM_EXPECTED_CHAT_HMAC:?BOCA_TELEGRAM_EXPECTED_CHAT_HMAC_required}",
    ]
    assert worker["user"] == "10001:10001"
    assert worker["restart"] == "no"
    assert worker["healthcheck"] == {"disable": True}
    assert worker["ipc"] == "private"
    assert worker["cgroup"] == "private"
    assert worker["labels"] == {
        "boca.socios.browser-ipc-attempt": "${BOCA_BROWSER_ATTEMPT_ID:?BOCA_BROWSER_ATTEMPT_ID_required}",
        "boca.socios.telegram-runtime-attempt": "${BOCA_TELEGRAM_ATTEMPT_ID:?BOCA_TELEGRAM_ATTEMPT_ID_required}",
    }
    assert worker["read_only"] is True
    assert worker["cap_drop"] == ["ALL"]
    assert worker["security_opt"] == ["no-new-privileges:true"]
    assert worker["pids_limit"] == 32
    assert worker["mem_limit"] == "128m"
    assert worker["cpus"] == 0.25
    assert "ports" not in worker
    assert "privileged" not in worker
    assert "network_mode" not in worker
    assert worker["networks"] == ["telegram_egress"]
    assert worker["volumes"] == ["boca_data:/data", "boca_telegram:/run/telegram:ro"]
    assert composed["volumes"] == {
        "boca_data": {"external": True, "name": "boca-socios_boca_data"},
        "boca_telegram": {"external": True, "name": "boca-socios_boca_telegram"},
    }
    assert composed["networks"] == {
        "telegram_egress": {"driver": "bridge", "labels": worker["labels"]}
    }
    assert worker["environment"] == valid_environment()
    assert "bot_token" not in json.dumps(composed["services"])
    assert "chat_id" not in json.dumps(composed["services"])
