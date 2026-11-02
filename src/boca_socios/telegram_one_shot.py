"""One explicit synthetic Telegram test, after protected owner and host gates.

The worker reuses only the offline readiness gate. A real network request is
possible only when a separate protected host operation provides a verified
bot/destination assertion and runs the explicit test command.
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
from math import isfinite
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

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


def _pin_owner_configuration(
    transport: TelegramTransport,
    expected_bot_id: int,
    expected_chat_hmac: str,
) -> tuple[str, int]:
    """Match protected owner pins and two private-file reads without network."""
    if (
        type(expected_bot_id) is not int
        or not 0 < expected_bot_id < 2**52
        or not isinstance(expected_chat_hmac, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_chat_hmac) is None
    ):
        raise OneShotError("owner_assertion_unavailable")
    token, destination = transport._configuration()
    if token.partition(":")[0] != str(expected_bot_id):
        raise OneShotError("bot_identity_mismatch")
    if not 0 < destination < 2**52:
        raise OneShotError("private_destination_required")
    if not hmac.compare_digest(
        hmac.new(
            token.encode("ascii"), str(destination).encode("ascii"), hashlib.sha256
        ).hexdigest(),
        expected_chat_hmac,
    ):
        raise OneShotError("owner_destination_mismatch")
    transport._pin_configuration(token, destination)
    return token, destination


def acceptance_notice_id(
    transport: TelegramTransport,
    source_sha: str,
    expected_bot_id: int,
    expected_chat_hmac: str,
) -> UUID:
    """Bind the single acceptance fence to the exact release and private pair.

    Only the opaque UUID enters SQLite. A generic historical heartbeat, a
    different source or a replaced secret cannot authorize this worker.
    """
    if re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
        raise OneShotError("source_unverified")
    token, _destination = _pin_owner_configuration(transport, expected_bot_id, expected_chat_hmac)
    binding = hmac.new(
        token.encode("ascii"),
        f"boca-telegram-ready-v1:{source_sha}:{expected_bot_id}:{expected_chat_hmac}".encode(
            "ascii"
        ),
        hashlib.sha256,
    ).hexdigest()
    return uuid5(NOTICE_ID, binding)


def check_identity(
    transport: TelegramTransport,
    expected_bot_id: int,
    expected_chat_hmac: str,
    *,
    connection_factory: Callable[..., _Connection] = http.client.HTTPSConnection,
) -> None:
    """Prove token authentication and a separately attested private destination."""
    token, destination = _pin_owner_configuration(transport, expected_bot_id, expected_chat_hmac)
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


def verify_ready(
    database: Path,
    transport: TelegramTransport,
    source_sha: str,
    expected_bot_id: int,
    expected_chat_hmac: str,
) -> None:
    """Read a prior bound API acceptance without migration, claim or HTTP."""
    notice_id = acceptance_notice_id(transport, source_sha, expected_bot_id, expected_chat_hmac)
    verify_storage(database)
    try:
        with closing(
            sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=3)
        ) as connection:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            row = connection.execute(
                """SELECT n.kind, n.state, n.attempts, a.state, a.attempt_number,
                   a.provider_message_id, n.accepted_at, a.settled_at
                   FROM notification_outbox n JOIN telegram_delivery_attempts a
                   ON n.idempotency_key=a.idempotency_key WHERE n.idempotency_key=?""",
                (str(notice_id),),
            ).fetchone()
            uncertain = connection.execute(
                "SELECT 1 FROM telegram_delivery_attempts WHERE state!='api_accepted' LIMIT 1"
            ).fetchone()
        if (
            row is None
            or row[:5] != ("heartbeat", "accepted", 1, "api_accepted", 1)
            or type(row[5]) is not int
            or row[5] <= 0
            or type(row[6]) not in (int, float)
            or not isfinite(row[6])
            or row[6] < 0
            or row[6] != row[7]
            or uncertain is not None
        ):
            raise OneShotError("api_acceptance_unverified")
    except (OSError, sqlite3.DatabaseError):
        raise OneShotError("api_acceptance_unverified") from None
    # Preserve the pin across the readiness read and every subsequent tick.
    transport.preflight()


async def deliver_once(
    database: Path,
    sender: TelegramSender,
    source_sha: str,
    *,
    notice_id: UUID = NOTICE_ID,
    clock: Callable[[], float] = time.time,
) -> str:
    """Fence one static heartbeat in existing SQLite before the send attempt."""
    if re.fullmatch(r"[0-9a-f]{40}", source_sha) is None or type(notice_id) is not UUID:
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
            NotificationRequest(notice_id, NoticeKind.HEARTBEAT), now=clock(), ttl_seconds=600
        )
        if notice.state is not DeliveryState.PENDING or notice.attempts != 0:
            raise OneShotError("synthetic_notice_unverified")
        report = await TelegramDeliveryCoordinator(
            outbox, sender, clock, max_per_tick=1, timeout_seconds=5
        ).tick()
        record = outbox.get(notice_id)
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
            marker = connection.execute(
                "SELECT state, provider_message_id FROM telegram_delivery_attempts WHERE idempotency_key=?",
                (str(notice_id),),
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
    label = "READY" if args and args[0] == "verify-ready" else "TEST"
    try:
        if len(args) != 4 or args[0] not in {"test", "verify-ready"}:
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
        if args[0] == "verify-ready":
            verify_ready(DATABASE, transport, source_sha, int(bot_id), chat_hmac)
            print(
                f"BOCA_TELEGRAM_READY state=VERIFIED source_sha={source_sha}"
                " api_accepted=1 identity=pinned"
            )
            return 0
        notice_id = acceptance_notice_id(transport, source_sha, int(bot_id), chat_hmac)
        check_identity(transport, int(bot_id), chat_hmac)
        result = asyncio.run(deliver_once(DATABASE, transport, source_sha, notice_id=notice_id))
    except Exception:
        print(f"BOCA_TELEGRAM_{label} state=NO_GO", file=sys.stderr)
        return 1
    print(
        f"BOCA_TELEGRAM_TEST state={result} source_sha={source_sha} synthetic=1 human_receipt=unverified"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
