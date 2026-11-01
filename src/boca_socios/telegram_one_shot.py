"""One explicit synthetic Telegram test, after protected owner and host gates.

This entrypoint is never imported by the panel or default worker. A real
network request is possible only when a separate protected host operation
provides a verified bot/destination assertion and runs this fixed command.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import http.client
import json
import os
import re
import sqlite3
import ssl
import sys
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from boca_socios.notify.outbox import DeliveryState, NoticeKind, NotificationRequest
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from boca_socios.notify.telegram_delivery import TelegramDeliveryCoordinator
from boca_socios.notify.telegram_transport import TelegramSender, TelegramTransport
from boca_socios.runtime_probe import CGROUP_ROOT, SELF_CGROUP, _read_ascii
from boca_socios.telegram_bootstrap import verify as verify_custody
from boca_socios.telegram_storage_gate import verify as verify_storage

DATABASE = Path("/data/boca.sqlite3")
TOKEN = Path("/run/telegram/bot_token")
CHAT = Path("/run/telegram/chat_id")
NOTICE_ID = uuid5(NAMESPACE_URL, "boca-socios-telegram-owner-acceptance-v1")


class OneShotError(ValueError):
    """Only a fixed redacted failure may leave this boundary."""


def require_effective_limits() -> None:
    """The stopped controller leaves only a quarter CPU worker budget active."""
    if (
        not (CGROUP_ROOT / "cgroup.controllers").is_file()
        or _read_ascii(SELF_CGROUP, limit=256) != "0::/"
    ):
        raise OneShotError("private_cgroup_unverified")
    parts = _read_ascii(CGROUP_ROOT / "cpu.max").split()
    memory = _read_ascii(CGROUP_ROOT / "memory.max")
    pids = _read_ascii(CGROUP_ROOT / "pids.max")
    if (
        len(parts) != 2
        or any(re.fullmatch(r"[0-9]+", value) is None for value in (*parts, memory, pids))
        or not 0 < int(parts[1]) <= 1_000_000
        or int(parts[0]) * 4 != int(parts[1])
        or int(memory) != 134_217_728
        or int(pids) != 32
    ):
        raise OneShotError("effective_worker_budget_unverified")


class _Response(Protocol):
    status: int

    def read(self, amount: int) -> bytes: ...


class _Connection(Protocol):
    def request(self, method: str, url: str, body: bytes, headers: dict[str, str]) -> None: ...

    def getresponse(self) -> _Response: ...

    def close(self) -> None: ...


def _request(
    token: str,
    method: str,
    destination: int | None,
    connection_factory: Callable[..., _Connection],
) -> dict[str, object]:
    connection: _Connection | None = None
    try:
        connection = connection_factory(
            host="api.telegram.org", timeout=3.0, context=ssl.create_default_context()
        )
        suffix = f"?chat_id={destination}" if destination is not None else ""
        connection.request(
            "GET", f"/bot{token}/{method}{suffix}", b"", {"Accept": "application/json"}
        )
        response = connection.getresponse()
        raw = response.read(4097)
        if response.status != 200 or len(raw) > 4096:
            raise OneShotError("identity_unverified")
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise OneShotError("identity_unverified")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise OneShotError("identity_unverified")
        return result
    except Exception:
        # The URL contains the bot token. Never serialize an exception, URL or
        # response body into a workflow receipt or process log.
        raise OneShotError("identity_unverified") from None
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                raise OneShotError("identity_unverified") from None


def check_identity(
    transport: TelegramTransport,
    expected_bot_id: int,
    expected_chat_hmac: str,
    *,
    connection_factory: Callable[..., _Connection] = http.client.HTTPSConnection,
) -> None:
    """Prove token authentication and a separately attested private destination."""
    if (
        type(expected_bot_id) is not int
        or not 0 < expected_bot_id < 2**52
        or not isinstance(expected_chat_hmac, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_chat_hmac) is None
    ):
        raise OneShotError("owner_assertion_unavailable")
    token, destination = transport._configuration()
    if not 0 < destination < 2**52:
        raise OneShotError("private_destination_required")
    if not hmac.compare_digest(
        hmac.new(
            token.encode("ascii"), str(destination).encode("ascii"), hashlib.sha256
        ).hexdigest(),
        expected_chat_hmac,
    ):
        raise OneShotError("owner_destination_mismatch")
    bot = _request(token, "getMe", None, connection_factory)
    if (
        type(bot.get("id")) is not int
        or bot["id"] != expected_bot_id
        or bot.get("is_bot") is not True
    ):
        raise OneShotError("bot_identity_mismatch")
    chat = _request(token, "getChat", destination, connection_factory)
    if (
        type(chat.get("id")) is not int
        or chat["id"] != destination
        or chat.get("type") != "private"
    ):
        raise OneShotError("private_destination_mismatch")
    transport._pin_configuration(token, destination)


async def deliver_once(
    database: Path,
    sender: TelegramSender,
    source_sha: str,
    *,
    clock: Callable[[], float] = time.time,
) -> str:
    """Fence one static heartbeat in existing SQLite before the send attempt."""
    if re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
        raise OneShotError("source_unverified")
    verify_storage(database)
    try:
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
            outbox_count = connection.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()
            attempts_count = connection.execute(
                "SELECT COUNT(*) FROM telegram_delivery_attempts"
            ).fetchone()
        if outbox_count != (0,) or attempts_count != (0,):
            raise OneShotError("existing_notice_or_attempt_preserved")
        outbox = SqliteNotificationOutbox(database)
        notice = outbox.enqueue(
            NotificationRequest(NOTICE_ID, NoticeKind.HEARTBEAT), now=clock(), ttl_seconds=600
        )
        if notice.state is not DeliveryState.PENDING or notice.attempts != 0:
            raise OneShotError("synthetic_notice_unverified")
        report = await TelegramDeliveryCoordinator(
            outbox, sender, clock, max_per_tick=1, timeout_seconds=5
        ).tick()
        record = outbox.get(NOTICE_ID)
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
            marker = connection.execute(
                "SELECT state, provider_message_id FROM telegram_delivery_attempts WHERE idempotency_key=?",
                (str(NOTICE_ID),),
            ).fetchone()
            total = connection.execute("SELECT COUNT(*) FROM telegram_delivery_attempts").fetchone()
        if (
            (report.attempted, report.api_accepted, report.ambiguous) != (1, 1, 0)
            or record is None
            or record.state is not DeliveryState.ACCEPTED
            or marker is None
            or marker[0] != "api_accepted"
            or type(marker[1]) is not int
            or marker[1] <= 0
            or total != (1,)
        ):
            raise OneShotError("api_acceptance_unverified")
    except OneShotError:
        raise
    except Exception:
        # A prepared fence may remain after a transport crash. Any later
        # dispatch sees a nonempty outbox and refuses to send again.
        raise OneShotError("delivery_uncertain_no_retry") from None
    return "API_ACCEPTED"


def main(argv: tuple[str, ...] | None = None) -> int:
    args = tuple(sys.argv[1:]) if argv is None else argv
    try:
        if len(args) != 4 or args[0] != "test":
            raise OneShotError("invalid_phase")
        _, source_sha, bot_id, chat_hmac = args
        if re.fullmatch(r"[1-9][0-9]{0,15}", bot_id) is None:
            raise OneShotError("owner_assertion_unavailable")
        if any(
            os.environ.get(key) != value
            for key, value in {
                "BOCA_ENVIRONMENT": "staging",
                "BOCA_RUNTIME_MODE": "simulation",
                "BOCA_ENGINE_MODE": "off",
                "BOCA_TELEGRAM_DISPATCH_MODE": "explicit",
            }.items()
        ):
            raise OneShotError("simulation_boundary_unavailable")
        require_effective_limits()
        verify_custody()
        transport = TelegramTransport(TOKEN, CHAT)
        check_identity(transport, int(bot_id), chat_hmac)
        result = asyncio.run(deliver_once(DATABASE, transport, source_sha))
    except Exception:
        print("BOCA_TELEGRAM_TEST state=NO_GO", file=sys.stderr)
        return 1
    print(
        f"BOCA_TELEGRAM_TEST state={result} source_sha={source_sha} synthetic=1 human_receipt=unverified"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
