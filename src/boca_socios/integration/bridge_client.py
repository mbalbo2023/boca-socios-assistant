"""Opt-in outbound, signed Site bridge for synthetic commands only.

The transport has no inbound listener and never sends member credentials.
Site acknowledgement is a delivery receipt, not a final Boca outcome.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import json
import os
import re
import sqlite3
import ssl
import stat
import time
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Literal, Protocol
from urllib.parse import quote, urlsplit
from uuid import UUID, uuid4

from boca_socios.integration.command_host import CommandResultUnknown
from boca_socios.integration.command_store import (
    CommandCapacityError,
    CommandConflict,
    CommandSnapshot,
)
from boca_socios.panel.local_status import read_local_status

SITE_ORIGIN = "https://boca-socios-consola-demo-20261031.mbalbo14901.chatgpt.site"
SIMULATION_EVENT_ID = "00000000-0000-4000-8000-000000000001"
_TOKEN = re.compile(rb"[A-Za-z0-9._~+/-]+=*\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_MAX_REQUEST = 2048
_MAX_RESPONSE = 4096
_RESULTS = frozenset(
    {
        "accepted",
        "running",
        "stop_requested",
        "stopped",
        "completed",
        "failed",
        "needs_review",
        "not_found",
        "conflict",
        "capacity",
    }
)


class BridgeUnavailable(RuntimeError):
    """Remote response or local transport cannot be trusted; never reveal details."""


def _uuid(value: object) -> str:
    if not isinstance(value, str):
        raise BridgeUnavailable("invalid bridge response")
    try:
        if str(UUID(value)) != value or UUID(value).int == 0:
            raise ValueError
    except ValueError:
        raise BridgeUnavailable("invalid bridge response") from None
    return value


def _private_file(path: Path, *, limit: int) -> bytes:
    if not path.is_absolute():
        raise ValueError("private bridge file path must be absolute")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as source:
            metadata = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid not in {0, os.geteuid()}
                or stat.S_IMODE(metadata.st_mode) & 0o077
            ):
                raise ValueError("private bridge file is unsafe")
            content = source.read(limit + 1)
    except OSError:
        raise ValueError("private bridge file is unavailable") from None
    if not content or len(content) > limit:
        raise ValueError("private bridge file is invalid")
    return content


@dataclass(frozen=True, slots=True)
class BridgeLease:
    operation_id: str
    command_id: str
    operation: Literal["synthetic_begin", "synthetic_stop"]
    member_id: str
    event_id: str | None
    lease_id: str
    attempts: int


class SiteBridgeTransport:
    """Exact pinned Site, strict TLS and HMAC per non-redirecting JSON POST."""

    def __init__(
        self,
        *,
        origin: str,
        token_file: Path,
        hmac_key_file: Path,
        context: ssl.SSLContext | None = None,
        clock: Callable[[], float] = time.time,
        nonce: Callable[[], UUID] = uuid4,
    ) -> None:
        if origin != SITE_ORIGIN:
            raise ValueError("unapproved bridge destination")
        host = urlsplit(origin).hostname
        assert host is not None
        self._host = host
        token = _private_file(token_file, limit=2048).removesuffix(b"\n")
        if not 16 <= len(token) <= 2048 or _TOKEN.fullmatch(token) is None:
            raise ValueError("invalid private bridge credential")
        key = _private_file(hmac_key_file, limit=32)
        if len(key) != 32:
            raise ValueError("invalid private bridge signature key")
        self._token = token.decode("ascii")
        self._key = key
        self._context = context or ssl.create_default_context()
        self._clock = clock
        self._nonce = nonce

    def _request(self, path: str, payload: Mapping[str, object]) -> dict[str, Any]:
        if path not in {"/api/bridge/lease", "/api/bridge/ack", "/api/bridge/heartbeat"}:
            raise ValueError("unapproved bridge operation")
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        if len(body) > _MAX_REQUEST:
            raise BridgeUnavailable("bridge request too large")
        timestamp = str(int(self._clock()))
        nonce = str(self._nonce())
        _uuid(nonce)
        message = (
            f"boca-site-bridge-v1\n{timestamp}\n{nonce}\nPOST\n{path}\n"
            f"{hashlib.sha256(body).hexdigest()}\n"
        ).encode()
        signature = base64.urlsafe_b64encode(hmac.new(self._key, message, hashlib.sha256).digest())
        headers = {
            "Content-Type": "application/json",
            "OAI-Sites-Authorization": f"Bearer {self._token}",
            "x-boca-bridge-ts": timestamp,
            "x-boca-bridge-nonce": nonce,
            "x-boca-bridge-signature": signature.rstrip(b"=").decode("ascii"),
        }
        connection = http.client.HTTPSConnection(
            self._host, 443, timeout=3.0, context=self._context
        )
        try:
            connection.request("POST", path, body=body, headers=headers)
            response = connection.getresponse()
            received = response.read(_MAX_RESPONSE + 1)
            if (
                response.status != 200
                or len(received) > _MAX_RESPONSE
                or not response.getheader("Content-Type", "").lower().startswith("application/json")
            ):
                raise BridgeUnavailable("bridge response unavailable")
            data = json.loads(received, object_pairs_hook=_unique_pairs)
            if not isinstance(data, dict):
                raise BridgeUnavailable("invalid bridge response")
            return data
        except (OSError, ssl.SSLError, ValueError, UnicodeError, json.JSONDecodeError):
            raise BridgeUnavailable("bridge response unavailable") from None
        finally:
            connection.close()

    def lease(self) -> BridgeLease | None:
        data = self._request("/api/bridge/lease", {})
        if data == {"status": "empty"}:
            return None
        if set(data) != {"status", "operation"} or data["status"] != "leased":
            raise BridgeUnavailable("invalid bridge response")
        item = data["operation"]
        if not isinstance(item, dict) or set(item) not in (
            {
                "operation_id",
                "command_id",
                "operation",
                "member_id",
                "lease_id",
                "lease_until",
                "attempts",
            },
            {
                "operation_id",
                "command_id",
                "operation",
                "member_id",
                "event_id",
                "lease_id",
                "lease_until",
                "attempts",
            },
        ):
            raise BridgeUnavailable("invalid bridge response")
        operation = item["operation"]
        event = item.get("event_id")
        if (
            operation not in ("synthetic_begin", "synthetic_stop")
            or (operation == "synthetic_begin") != ("event_id" in item)
            or (event is not None and not isinstance(event, str))
            or type(item["attempts"]) is not int
            or not 1 <= item["attempts"] <= 10
            or not isinstance(item["lease_until"], str)
            or len(item["lease_until"]) > 40
        ):
            raise BridgeUnavailable("invalid bridge response")
        try:
            expires = datetime.fromisoformat(item["lease_until"].replace("Z", "+00:00"))
            remaining = expires.timestamp() - self._clock()
            if expires.utcoffset() is None or not 0 < remaining <= 150:
                raise ValueError
        except (ValueError, OverflowError):
            raise BridgeUnavailable("expired or invalid bridge lease") from None
        return BridgeLease(
            _uuid(item["operation_id"]),
            _uuid(item["command_id"]),
            operation,
            _uuid(item["member_id"]),
            event,
            _uuid(item["lease_id"]),
            item["attempts"],
        )

    def ack(self, lease: BridgeLease, state: str) -> None:
        if state not in _RESULTS:
            raise ValueError("unapproved bridge result")
        result = self._request(
            "/api/bridge/ack",
            {
                "operation_id": lease.operation_id,
                "lease_id": lease.lease_id,
                "result": {
                    "state": state,
                    "mode": "simulation",
                    "external_confirmation": "not_observed",
                },
            },
        )
        if result != {"status": "acknowledged"}:
            raise BridgeUnavailable("invalid bridge acknowledgement")

    def heartbeat(
        self, source_sha: str, runtime_state: str, snapshot: Mapping[str, object]
    ) -> None:
        if _SHA.fullmatch(source_sha) is None or runtime_state not in {
            "ready",
            "degraded",
            "stopping",
        }:
            raise ValueError("invalid bridge heartbeat")
        result = self._request(
            "/api/bridge/heartbeat",
            {"runtime_sha": source_sha, "runtime_state": runtime_state, "snapshot": snapshot},
        )
        if set(result) != {"status", "received_at"} or result["status"] != "recorded":
            raise BridgeUnavailable("invalid bridge heartbeat")


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BridgeUnavailable("invalid bridge response")
        result[key] = value
    return result


class BridgeTransport(Protocol):
    def lease(self) -> BridgeLease | None: ...

    def ack(self, lease: BridgeLease, state: str) -> None: ...

    def heartbeat(
        self, source_sha: str, runtime_state: str, snapshot: Mapping[str, object]
    ) -> None: ...


class BridgeCommands(Protocol):
    @property
    def failed(self) -> bool: ...

    def begin(self, command_id: str, *, member_id: str, event_id: str) -> CommandSnapshot: ...

    def status(self, command_id: str, *, member_id: str) -> CommandSnapshot | None: ...

    def stop(self, command_id: str, *, member_id: str) -> CommandSnapshot | None: ...


def _member_exists(db_path: Path, member_id: str) -> bool:
    try:
        with closing(
            sqlite3.connect(f"file:{quote(str(db_path), safe='/')}?mode=ro", uri=True, timeout=1.0)
        ) as connection:
            connection.execute("PRAGMA query_only = ON")
            return (
                connection.execute(
                    "SELECT 1 FROM members WHERE member_id=?", (member_id,)
                ).fetchone()
                is not None
            )
    except sqlite3.Error:
        raise BridgeUnavailable("local bridge storage unavailable") from None


class SiteBridgeWorker:
    """One bounded outbound loop; D1 lease redelivery meets local command IDs.

    Unknown local outcomes are deliberately not acknowledged. The remote
    lease may expire and redeliver the same command ID; status is inspected
    first before any repeat. Site ack is only a transport receipt.
    """

    def __init__(
        self,
        *,
        transport: BridgeTransport,
        commands: BridgeCommands,
        database_path: Path,
        source_sha: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if _SHA.fullmatch(source_sha) is None or not database_path.is_absolute():
            raise ValueError("invalid local bridge configuration")
        self._transport = transport
        self._commands = commands
        self._db_path = database_path
        self._sha = source_sha
        self._clock = clock
        self._last_heartbeat = -float("inf")
        self._last_snapshot: dict[str, object] | None = None
        self._stop = Event()
        self._lock = Lock()
        self._thread = Thread(target=self._run, name="boca-site-bridge", daemon=False)
        self._started = False
        self._failed = False

    @property
    def failed(self) -> bool:
        return self._failed or (
            self._started and not self._thread.is_alive() and not self._stop.is_set()
        )

    def start(self) -> None:
        with self._lock:
            if self._started:
                raise RuntimeError("bridge already started")
            self._started = True
            self._thread.start()

    def _snapshot(self) -> dict[str, object]:
        value = read_local_status(self._db_path, observed_at=datetime.now(UTC))
        result: dict[str, object] = {
            "source": value.source,
            "external_confirmation": value.external_confirmation,
            "observed_at": value.observed_at.isoformat(),
            "local_data_age": value.local_data_age,
            "last_local_update_at": (
                value.last_local_update_at.isoformat() if value.last_local_update_at else None
            ),
            "counts": asdict(value.counts),
        }
        return result

    def _dispatch(self, lease: BridgeLease) -> str | None:
        if lease.operation == "synthetic_begin" and lease.event_id != SIMULATION_EVENT_ID:
            raise BridgeUnavailable("unapproved synthetic event")
        if lease.operation == "synthetic_stop" and lease.event_id is not None:
            raise BridgeUnavailable("invalid stop operation")
        if not _member_exists(self._db_path, lease.member_id):
            return "not_found"
        try:
            existing = self._commands.status(lease.command_id, member_id=lease.member_id)
            snapshot: CommandSnapshot | None
            if lease.operation == "synthetic_begin":
                snapshot = existing or self._commands.begin(
                    lease.command_id, member_id=lease.member_id, event_id=SIMULATION_EVENT_ID
                )
            elif existing is None:
                return "not_found"
            else:
                snapshot = self._commands.stop(lease.command_id, member_id=lease.member_id)
            if snapshot is None:
                return "not_found"
            return str(snapshot.state)
        except CommandResultUnknown:
            # The operation might have committed. Do not report failure or
            # generate another command ID; D1 will redeliver after lease expiry.
            return None
        except CommandConflict:
            return "conflict"
        except CommandCapacityError:
            return "capacity"

    def tick(self) -> None:
        """One heartbeat (at most every 20s), one lease and one ack at most."""
        if self._commands.failed:
            raise BridgeUnavailable("local command loop unavailable")
        now = self._clock()
        if now - self._last_heartbeat >= 20:
            snapshot = self._snapshot()
            self._transport.heartbeat(self._sha, "ready", snapshot)
            self._last_snapshot = snapshot
            self._last_heartbeat = now
        lease = self._transport.lease()
        if lease is not None:
            outcome = self._dispatch(lease)
            if outcome is not None:
                self._transport.ack(lease, outcome)

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    self.tick()
                except (BridgeUnavailable, CommandResultUnknown, OSError, ValueError):
                    # Remote outage/ambiguity is visible through stale Site
                    # heartbeat and its D1 lease. No secrets in local logs.
                    pass
                self._stop.wait(5)
        except Exception:
            self._failed = True

    def close(self) -> None:
        with self._lock:
            if not self._started:
                return
            self._stop.set()
        self._thread.join(timeout=20)
        if self._thread.is_alive():
            raise RuntimeError("bridge did not stop")
        if self._last_snapshot is not None:
            try:
                self._transport.heartbeat(self._sha, "stopping", self._last_snapshot)
            except (BridgeUnavailable, OSError, ValueError):
                pass
