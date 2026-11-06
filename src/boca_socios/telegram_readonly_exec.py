"""Explicit one-method Telegram Bot API GET inside a disposable Boca worker.

No sender, webhook mutation, persistence, console token or public host port.
The protected host caller must hold its own lease and check exact container
identity before *each* Docker exec; this isolated helper cannot grant GO.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from typing import Any

from boca_socios.telegram_pairing_resolver import read_only_telegram_api

_MAX_STDIN = 512
_MAX_OUTPUT = 22_000
_GETS = frozenset({"getMe", "getWebhookInfo", "getUpdates", "getChat"})


class TelegramReadOnlyExecError(ValueError):
    """Publicly printable error without Bot API response or private coordinates."""


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TelegramReadOnlyExecError("duplicate_field")
        result[key] = value
    return result


def one_read(raw: bytes) -> bytes:
    """Process a single canonical stdin-only GET and return bounded private IPC.

    The caller MUST redirect stdout to an in-memory private channel; neither
    this JSON response nor its contents may enter public workflow summaries.
    """
    if not isinstance(raw, bytes) or not 0 < len(raw) <= _MAX_STDIN:
        raise TelegramReadOnlyExecError("telegram_readonly_frame_invalid")
    try:
        record = json.loads(raw.decode("ascii"), object_pairs_hook=_unique)
        if (
            type(record) is not dict
            or set(record) != {"version", "method", "token", "chat_id"}
            or type(record["version"]) is not int
            or record["version"] != 1
            or type(record["method"]) is not str
            or record["method"] not in _GETS
            or type(record["token"]) is not str
            or (record["method"] == "getChat") != (type(record["chat_id"]) is int)
            or (record["method"] != "getChat" and record["chat_id"] is not None)
            or raw != json.dumps(record, sort_keys=True, separators=(",", ":")).encode("ascii")
        ):
            raise TelegramReadOnlyExecError("telegram_readonly_frame_invalid")
        answer = read_only_telegram_api(record["token"], record["method"], record["chat_id"])
        if not isinstance(answer, bytes) or not 0 < len(answer) <= 16_384:
            raise TelegramReadOnlyExecError("telegram_readonly_provider_invalid")
        output = json.dumps(
            {
                "version": 1,
                "response_base64url": base64.urlsafe_b64encode(answer).rstrip(b"=").decode("ascii"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        if len(output) > _MAX_OUTPUT:
            raise TelegramReadOnlyExecError("telegram_readonly_response_unbounded")
        return output
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise TelegramReadOnlyExecError("telegram_readonly_get_no_go") from None


def main(argv: tuple[str, ...] | None = None) -> int:
    args = tuple(sys.argv[1:]) if argv is None else argv
    if (
        os.geteuid() != 10001
        or os.getegid() != 10001
        or os.environ.get("BOCA_RUNTIME_MODE") != "simulation"
        or os.environ.get("BOCA_ENGINE_MODE") != "off"
        or os.environ.get("BOCA_TELEGRAM_READONLY_MODE") != "explicit"
    ):
        print("BOCA_TELEGRAM_READONLY state=NO_GO reason=RUNTIME_BOUNDARY", file=sys.stderr)
        return 2
    if args == ("idle",):
        # The host owns the only transaction and must stop/remove this exact
        # Boca-only helper in finally. This process has no provider side effect.
        time.sleep(75)
        return 0
    if args != ("get",):
        print("BOCA_TELEGRAM_READONLY state=NO_GO reason=INVALID_OPERATION", file=sys.stderr)
        return 2
    try:
        result = one_read(sys.stdin.buffer.read(_MAX_STDIN + 1))
        sys.stdout.buffer.write(result)
        sys.stdout.buffer.flush()
        return 0
    except (TelegramReadOnlyExecError, OSError):
        print("BOCA_TELEGRAM_READONLY state=NO_GO reason=READ_UNVERIFIED", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
