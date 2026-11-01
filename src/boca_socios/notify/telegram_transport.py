"""Opt-in Telegram Bot API boundary; sends fixed simulation text only."""

from __future__ import annotations

import asyncio
import http.client
import json
import os
import re
import ssl
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from boca_socios.notify.outbox import _SAFE_NOTICE, NoticeKind


class TelegramUnconfirmed(RuntimeError):
    """No trustworthy API acceptance receipt; never retry automatically."""


@dataclass(frozen=True, slots=True, repr=False)
class TelegramNotice:
    idempotency_key: UUID
    kind: NoticeKind

    def __repr__(self) -> str:
        return "TelegramNotice(<content omitted>)"


@dataclass(frozen=True, slots=True)
class TelegramAck:
    """Bot API acceptance, not delivery to or reading by a human."""

    message_id: int

    def __post_init__(self) -> None:
        if type(self.message_id) is not int or self.message_id <= 0:
            raise ValueError("invalid provider message ID")


class TelegramSender(Protocol):
    def preflight(self) -> None: ...

    async def send(self, notice: TelegramNotice) -> TelegramAck: ...


class _HttpResponse(Protocol):
    status: int

    def read(self, length: int) -> bytes: ...


class _HttpConnection(Protocol):
    def request(self, method: str, url: str, body: bytes, headers: dict[str, str]) -> None: ...

    def getresponse(self) -> _HttpResponse: ...

    def close(self) -> None: ...


class TelegramTransport:
    """Read private files at send time; no token/chat ID in repr, logs or SQLite.

    Construction is inert. Only an explicit coordinator tick can call send.
    The fixed HTTPSConnection does not follow redirects. The token appears in
    the required Bot API request path and must never be logged by callers.
    """

    def __init__(
        self,
        token_file: Path,
        chat_id_file: Path,
        *,
        connection_factory: Callable[..., _HttpConnection] = http.client.HTTPSConnection,
    ) -> None:
        self._token_file = token_file
        self._chat_id_file = chat_id_file
        self._connection_factory = connection_factory

    def __repr__(self) -> str:
        return "TelegramTransport(<private configuration omitted>)"

    @staticmethod
    def _read_private(path: Path) -> str:
        try:
            before = path.lstat()
            if not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) & 0o077:
                raise ValueError("invalid secret file")
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                after = os.fstat(descriptor)
                if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                    raise ValueError("secret file changed")
                raw = os.read(descriptor, 129)
            finally:
                os.close(descriptor)
            if not raw or len(raw) > 128:
                raise ValueError("invalid secret length")
            return raw.decode("ascii").strip()
        except (OSError, ValueError, UnicodeError):
            raise TelegramUnconfirmed("Telegram private configuration unavailable") from None

    def _configuration(self) -> tuple[str, int]:
        token = self._read_private(self._token_file)
        chat_id = self._read_private(self._chat_id_file)
        if not re.fullmatch(r"[0-9]{1,20}:[A-Za-z0-9_-]{8,128}", token) or not re.fullmatch(
            r"-?[0-9]{1,20}", chat_id
        ):
            raise TelegramUnconfirmed("Telegram private configuration invalid")
        destination = int(chat_id)
        if destination == 0:
            raise TelegramUnconfirmed("Telegram private configuration invalid")
        return token, destination

    def preflight(self) -> None:
        """Fail before consuming a notification if private files are unavailable."""
        self._configuration()

    def _send_blocking(self, notice: TelegramNotice) -> TelegramAck:
        if not isinstance(notice, TelegramNotice) or not isinstance(notice.kind, NoticeKind):
            raise TelegramUnconfirmed("Telegram notice invalid")
        token, destination = self._configuration()
        body = json.dumps(
            {
                "chat_id": destination,
                "text": _SAFE_NOTICE[notice.kind][1],
                "protect_content": True,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        connection: _HttpConnection | None = None
        try:
            connection = self._connection_factory(
                host="api.telegram.org", timeout=3.0, context=ssl.create_default_context()
            )
            connection.request(
                "POST",
                f"/bot{token}/sendMessage",
                body,
                {"Content-Type": "application/json", "Accept": "application/json"},
            )
            response = connection.getresponse()
            raw = response.read(4097)
            if response.status != 200 or len(raw) > 4096:
                raise TelegramUnconfirmed("Telegram API acceptance unconfirmed")
            payload = json.loads(raw)
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                raise TelegramUnconfirmed("Telegram API acceptance unconfirmed")
            result = payload.get("result")
            if not isinstance(result, dict) or not isinstance(result.get("chat"), dict):
                raise TelegramUnconfirmed("Telegram API acceptance unconfirmed")
            if type(result["chat"].get("id")) is not int or result["chat"].get("id") != destination:
                raise TelegramUnconfirmed("Telegram API acceptance unconfirmed")
            message_id = result.get("message_id")
            if type(message_id) is not int or message_id <= 0:
                raise TelegramUnconfirmed("Telegram API acceptance unconfirmed")
            return TelegramAck(message_id)
        except Exception:
            raise TelegramUnconfirmed("Telegram API acceptance unconfirmed") from None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    raise TelegramUnconfirmed("Telegram connection cleanup unconfirmed") from None

    async def send(self, notice: TelegramNotice) -> TelegramAck:
        return await asyncio.to_thread(self._send_blocking, notice)
