"""Explicit, opt-in process for one-at-a-time synthetic Telegram notices.

This module has no startup side effects. The served panel and default controller
never import its entrypoint. Storage migration and secret provisioning are
separate reviewed operations, not worker startup steps.
"""

from __future__ import annotations

import asyncio
import os
import re
import signal
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from math import isfinite
from pathlib import Path
from threading import Event
from typing import cast

from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from boca_socios.notify.telegram_delivery import (
    TelegramDeliveryCoordinator,
    TelegramDeliveryStopped,
)
from boca_socios.notify.telegram_transport import TelegramSender, TelegramTransport
from boca_socios.telegram_bootstrap import verify as verify_custody
from boca_socios.telegram_one_shot import require_effective_limits, verify_ready

_DATABASE = Path("/data/boca.sqlite3")
_TOKEN = Path("/run/telegram/bot_token")
_DESTINATION = Path("/run/telegram/chat_id")
_REQUIRED_ENVIRONMENT = {
    "BOCA_ENVIRONMENT": "staging",
    "BOCA_RUNTIME_MODE": "simulation",
    "BOCA_ENGINE_MODE": "off",
    "BOCA_DB_PATH": str(_DATABASE),
    "BOCA_TELEGRAM_DISPATCH_MODE": "explicit",
}


def validate_worker_environment(environment: Mapping[str, str]) -> None:
    """Require the exact synthetic, explicit process contract before any I/O."""
    if any(environment.get(name) != value for name, value in _REQUIRED_ENVIRONMENT.items()):
        raise ValueError("Telegram worker configuration unavailable")


def build_coordinator(
    database: Path,
    transport: TelegramSender,
    *,
    clock: Callable[[], float] = time.time,
) -> TelegramDeliveryCoordinator:
    """Construction does not create a DB, migrate, claim or contact Telegram."""
    return TelegramDeliveryCoordinator(
        SqliteNotificationOutbox(database), transport, clock, max_per_tick=1
    )


async def run_worker(
    coordinator: TelegramDeliveryCoordinator,
    stopping: Event,
    *,
    interval: float = 2.0,
) -> None:
    """Stop at the first uncertain send; prepared keys are never auto-retried."""
    if type(interval) not in (float, int) or not isfinite(interval) or not 0 < interval <= 5:
        raise ValueError("Telegram worker interval invalid")
    while not stopping.is_set():
        report = await coordinator.tick()
        if report.ambiguous:
            raise TelegramDeliveryStopped("Telegram review required")
        if not stopping.is_set():
            await asyncio.sleep(interval)


def main(
    argv: Sequence[str] | None = None,
    environment: Mapping[str, str] | None = None,
) -> int:
    """A fixed, redacted process exit; never print a bot token or destination."""
    args = sys.argv[1:] if argv is None else argv
    env = os.environ if environment is None else environment
    previous_handlers: dict[signal.Signals, signal.Handlers] = {}
    try:
        if len(args) != 4 or args[0] != "serve":
            raise ValueError("Telegram worker requires explicit serve")
        _, source_sha, bot_id, chat_hmac = args
        if re.fullmatch(r"[1-9][0-9]{0,15}", bot_id) is None:
            raise ValueError("Telegram worker requires owner assertion")
        validate_worker_environment(env)
        require_effective_limits()
        verify_custody()
        transport = TelegramTransport(_TOKEN, _DESTINATION)
        verify_ready(_DATABASE, transport, source_sha, int(bot_id), chat_hmac)
        coordinator = build_coordinator(_DATABASE, transport)
        stopping = Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[sig] = cast(signal.Handlers, signal.getsignal(sig))
            signal.signal(sig, lambda _signal, _frame: stopping.set())
        print(
            f"BOCA_TELEGRAM_READY state=VERIFIED source_sha={source_sha}"
            " api_accepted=1 identity=pinned",
            flush=True,
        )
        asyncio.run(run_worker(coordinator, stopping))
    except Exception:
        # The Bot API request path contains the token. No exception or traceback
        # from a transport, storage driver or HTTP client belongs in host logs.
        print("TELEGRAM_WORKER_NO_GO", file=sys.stderr)
        return 2
    finally:
        for sig, previous in previous_handlers.items():
            signal.signal(sig, previous)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
