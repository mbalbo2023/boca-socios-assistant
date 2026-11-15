"""Strict, private and fully correlated envelopes on the existing worker socket.

Nothing in this module navigates or grants ticket authority. Payloads can contain
received bearer URLs or transient credentials and must never become telemetry.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from urllib.parse import urlsplit, urlunsplit

from boca_socios.browser.boca_auth_protocol import (
    BocaAuthReadiness,
    BocaAuthReply,
    BocaAuthRequest,
    decode,
    encode,
    operation_id,
)
from boca_socios.browser.ipc_protocol import SyntheticIPCError
from boca_socios.browser.queue_page_observation import QueuePageObservation
from boca_socios.browser.site_url_runtime import require_site_url

EngineName = Literal["queues_tokens", "browsers_members"]
BrowserKind = Literal["chromium", "firefox", "webkit"]
EngineCommand = Literal["observe", "prepare_login", "login", "inspect", "close"]
CloseScope = Literal["session", "activation"]
ReplyStatus = Literal["OK", "CLOSED", "BUSY", "NO_GO", "TEARDOWN_UNVERIFIED"]
NavigationPurpose = Literal["SITE_URL", "QUEUE_BRIDGE", "RECEIVED_TARGET"]
NavigationResult = Literal["STARTED", "RETURNED", "FAILED", "CANCELLED"]
Scalar = str | int | float | None
MAX_ENGINE_REQUEST = 33792
MAX_ENGINE_RESPONSE = 98304
MAX_CONTEXTS = 50
_IDENTITY_KEYS = {"engine", "activation_id", "generation", "session_id", "browser"}


def _invalid() -> SyntheticIPCError:
    return SyntheticIPCError("engine_envelope_unverified")


def _one_of(value: object, allowed: tuple[str, ...]) -> bool:
    return type(value) is str and value in allowed


def parse_queue_opening_time(value: object) -> datetime | None:
    """Accept only the explicitly observed UTC timestamp, without inference."""
    if (
        type(value) is not str
        or len(value) > 64
        or re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
            r"(?:\.[0-9]{1,6})?(?:Z|\+00:00)",
            value,
        )
        is None
    ):
        return None
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except (ValueError, OverflowError):
        return None


@dataclass(frozen=True, slots=True)
class EngineIdentity:
    engine: EngineName
    activation_id: str
    generation: int
    session_id: str
    browser: BrowserKind

    def __post_init__(self) -> None:
        if (
            not _one_of(self.engine, ("queues_tokens", "browsers_members"))
            or not _one_of(self.browser, ("chromium", "firefox", "webkit"))
            or type(self.generation) is not int
            or not 0 < self.generation <= 2147483647
        ):
            raise _invalid()
        operation_id(self.activation_id)
        operation_id(self.session_id)

    @classmethod
    def from_value(cls, value: object) -> EngineIdentity:
        if type(value) is not dict or set(value) != _IDENTITY_KEYS:
            raise _invalid()
        return cls(**value)


@dataclass(frozen=True, slots=True, repr=False)
class NavigationAttempt:
    """One actual goto attempt; its display URL never carries query credentials."""

    sequence: int
    purpose: NavigationPurpose
    display_url: str
    started_at: datetime
    result: NavigationResult
    http_status: int | None = None

    def __post_init__(self) -> None:
        if (
            type(self.sequence) is not int
            or not 1 <= self.sequence <= 3
            or not _one_of(self.purpose, ("SITE_URL", "QUEUE_BRIDGE", "RECEIVED_TARGET"))
            or not _one_of(self.result, ("STARTED", "RETURNED", "FAILED", "CANCELLED"))
            or not isinstance(self.started_at, datetime)
            or self.started_at.utcoffset() is None
            or (
                self.http_status is not None
                and (
                    self.result != "RETURNED"
                    or type(self.http_status) is not int
                    or not 100 <= self.http_status <= 599
                )
            )
        ):
            raise _invalid()
        try:
            if type(self.display_url) is not str:
                raise ValueError
            require_site_url(self.display_url)
        except (ValueError, UnicodeError):
            raise _invalid() from None
        object.__setattr__(self, "started_at", self.started_at.astimezone(UTC))

    def __repr__(self) -> str:
        return "NavigationAttempt(<private values omitted>)"

    def to_value(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "purpose": self.purpose,
            "display_url": self.display_url,
            "started_at": self.started_at.isoformat(),
            "result": self.result,
            "http_status": self.http_status,
        }

    @classmethod
    def from_value(cls, value: object) -> NavigationAttempt:
        if type(value) is not dict or set(value) != set(cls.__dataclass_fields__):
            raise _invalid()
        timestamp = value["started_at"]
        try:
            if type(timestamp) is not str:
                raise ValueError
            return cls(**{**value, "started_at": datetime.fromisoformat(timestamp)})
        except (ValueError, UnicodeError, OverflowError):
            raise _invalid() from None


@dataclass(frozen=True, slots=True, repr=False)
class SessionInspection:
    """Last received sample, not a fresh navigation or evidence of DOM login."""

    final_url: str | None = None
    queue_id: str | None = None
    queue_number: Scalar = None
    users_ahead: Scalar = None
    users_in_queue: Scalar = None
    expected_service_time: Scalar = None
    observed_at: datetime | None = None
    context_open: bool = False
    auth_response_received: bool = False
    dom_authentication: Literal["UNVERIFIED"] = "UNVERIFIED"
    configured_url: str | None = None
    navigation_attempt: NavigationAttempt | None = None
    queue_opening_at: datetime | None = None
    queue_opening_event_id: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.context_open) is not bool
            or type(self.auth_response_received) is not bool
            or self.dom_authentication != "UNVERIFIED"
        ):
            raise _invalid()
        if self.configured_url is not None:
            try:
                if type(self.configured_url) is not str:
                    raise ValueError
                require_site_url(self.configured_url)
            except (ValueError, UnicodeError):
                raise _invalid() from None
        if self.navigation_attempt is not None and not isinstance(
            self.navigation_attempt, NavigationAttempt
        ):
            raise _invalid()
        if self.final_url is not None:
            try:
                if (
                    type(self.final_url) is not str
                    or not 0 < len(self.final_url.encode()) <= 8192
                    or any(ord(c) <= 32 or ord(c) == 127 for c in self.final_url)
                ):
                    raise ValueError
                parts = urlsplit(self.final_url)
                require_site_url(urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")))
            except (ValueError, UnicodeError):
                raise _invalid() from None
        if self.queue_id is not None and (
            type(self.queue_id) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", self.queue_id) is None
        ):
            raise _invalid()
        for value in (
            self.queue_number,
            self.users_ahead,
            self.users_in_queue,
            self.expected_service_time,
        ):
            if value is None:
                continue
            if type(value) in (int, float):
                if not math.isfinite(value) or not -1e15 <= value <= 1e15:  # type: ignore[arg-type,operator]
                    raise _invalid()
            elif type(value) is str:
                if len(value.encode()) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in value):
                    raise _invalid()
            else:
                raise _invalid()
        if self.observed_at is not None:
            if not isinstance(self.observed_at, datetime) or self.observed_at.utcoffset() is None:
                raise _invalid()
            object.__setattr__(self, "observed_at", self.observed_at.astimezone(UTC))
        if (self.queue_opening_at is None) != (self.queue_opening_event_id is None):
            raise _invalid()
        if self.queue_opening_at is not None:
            if (
                not isinstance(self.queue_opening_at, datetime)
                or self.queue_opening_at.utcoffset() != timedelta(0)
                or type(self.queue_opening_event_id) is not str
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", self.queue_opening_event_id)
                is None
                or self.observed_at is None
            ):
                raise _invalid()
            object.__setattr__(self, "queue_opening_at", self.queue_opening_at.astimezone(UTC))

    def __repr__(self) -> str:
        return "SessionInspection(<private values omitted>)"

    def to_payload(self) -> bytes:
        value = asdict(self)
        value["observed_at"] = self.observed_at.isoformat() if self.observed_at else None
        value["queue_opening_at"] = (
            self.queue_opening_at.isoformat() if self.queue_opening_at else None
        )
        value["navigation_attempt"] = (
            self.navigation_attempt.to_value() if self.navigation_attempt else None
        )
        return encode(value, 32768)

    @classmethod
    def from_payload(cls, payload: bytes) -> SessionInspection:
        keys = set(cls.__dataclass_fields__)
        r301_keys = keys - {"queue_opening_at", "queue_opening_event_id"}
        try:
            value = decode(payload, keys, 32768)
        except SyntheticIPCError:
            # Exactly the two former complete shapes remain readable. Neither
            # partial upgrades nor open dictionaries can cross this boundary.
            try:
                value = decode(payload, r301_keys, 32768)
            except SyntheticIPCError:
                value = decode(payload, r301_keys - {"configured_url", "navigation_attempt"}, 32768)
        timestamp = value["observed_at"]
        try:
            if timestamp is not None:
                if type(timestamp) is not str:
                    raise ValueError
                value["observed_at"] = datetime.fromisoformat(timestamp)
            opening = value.get("queue_opening_at")
            if opening is not None:
                parsed_opening = parse_queue_opening_time(opening)
                if parsed_opening is None:
                    raise _invalid()
                value["queue_opening_at"] = parsed_opening
            if value.get("navigation_attempt") is not None:
                value["navigation_attempt"] = NavigationAttempt.from_value(
                    value["navigation_attempt"]
                )
            return cls(**value)  # type: ignore[arg-type]
        except (ValueError, UnicodeError, OverflowError):
            raise _invalid() from None


@dataclass(frozen=True, slots=True, repr=False)
class EngineRequest:
    identity: EngineIdentity
    command: EngineCommand
    auth: BocaAuthRequest | None = None
    close_scope: CloseScope = "session"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.identity, EngineIdentity)
            or not _one_of(self.command, ("observe", "prepare_login", "login", "inspect", "close"))
            or not _one_of(self.close_scope, ("session", "activation"))
            or (self.command != "close" and self.close_scope != "session")
        ):
            raise _invalid()
        if (
            self.command in {"prepare_login", "login"}
            and self.identity.engine != "browsers_members"
        ):
            raise _invalid()
        if self.command == "login":
            if (
                not isinstance(self.auth, BocaAuthRequest)
                or self.auth.operation_id != self.identity.activation_id
            ):
                raise _invalid()
        elif self.auth is not None:
            raise _invalid()

    def __repr__(self) -> str:
        return "EngineRequest(<private values omitted>)"

    def to_payload(self) -> bytes:
        return encode(
            {
                "version": 2,
                "identity": asdict(self.identity),
                "command": self.command,
                "close_scope": self.close_scope,
                "auth": json.loads(self.auth.to_payload()) if self.auth else None,
            },
            MAX_ENGINE_REQUEST,
        )

    @classmethod
    def from_payload(cls, payload: bytes) -> EngineRequest:
        value = decode(
            payload, {"version", "identity", "command", "close_scope", "auth"}, MAX_ENGINE_REQUEST
        )
        if type(value["version"]) is not int or value["version"] != 2:
            raise _invalid()
        auth = (
            BocaAuthRequest.from_payload(encode(cast(dict[str, object], value["auth"]), 32768))
            if value["auth"] is not None
            else None
        )
        return cls(
            EngineIdentity.from_value(value["identity"]),
            cast(EngineCommand, value["command"]),
            auth,
            cast(CloseScope, value["close_scope"]),
        )


EngineResult = QueuePageObservation | BocaAuthReadiness | BocaAuthReply | SessionInspection | None


@dataclass(frozen=True, slots=True, repr=False)
class EngineReply:
    identity: EngineIdentity
    command: EngineCommand
    status: ReplyStatus
    result: EngineResult = None
    close_scope: CloseScope = "session"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.identity, EngineIdentity)
            or not _one_of(self.command, ("observe", "prepare_login", "login", "inspect", "close"))
            or not _one_of(self.status, ("OK", "CLOSED", "BUSY", "NO_GO", "TEARDOWN_UNVERIFIED"))
            or not _one_of(self.close_scope, ("session", "activation"))
            or (self.command != "close" and self.close_scope != "session")
        ):
            raise _invalid()
        if self.status == "OK":
            expected = {
                "observe": QueuePageObservation,
                "prepare_login": BocaAuthReadiness,
                "login": BocaAuthReply,
                "inspect": SessionInspection,
            }.get(self.command)
            if expected is None or not isinstance(self.result, expected):
                raise _invalid()
            if isinstance(self.result, (BocaAuthReadiness, BocaAuthReply)) and (
                self.identity.engine != "browsers_members"
                or self.result.operation_id != self.identity.activation_id
            ):
                raise _invalid()
        elif self.result is not None or (self.status == "CLOSED" and self.command != "close"):
            raise _invalid()

    def __repr__(self) -> str:
        return "EngineReply(<private values omitted>)"

    def to_payload(self) -> bytes:
        return encode(
            {
                "version": 2,
                "identity": asdict(self.identity),
                "command": self.command,
                "status": self.status,
                "close_scope": self.close_scope,
                "result": json.loads(self.result.to_payload()) if self.result is not None else None,
            },
            MAX_ENGINE_RESPONSE,
        )

    @classmethod
    def from_payload(cls, payload: bytes) -> EngineReply:
        value = decode(
            payload,
            {"version", "identity", "command", "status", "result", "close_scope"},
            MAX_ENGINE_RESPONSE,
        )
        if type(value["version"]) is not int or value["version"] != 2:
            raise _invalid()
        command = value["command"]
        if not _one_of(command, ("observe", "prepare_login", "login", "inspect", "close")):
            raise _invalid()
        result: EngineResult = None
        if value["result"] is not None:
            codecs: dict[
                str,
                type[QueuePageObservation]
                | type[BocaAuthReadiness]
                | type[BocaAuthReply]
                | type[SessionInspection],
            ] = {
                "observe": QueuePageObservation,
                "prepare_login": BocaAuthReadiness,
                "login": BocaAuthReply,
                "inspect": SessionInspection,
            }
            codec = codecs.get(str(command))
            if codec is None:
                raise _invalid()
            try:
                result = codec.from_payload(
                    encode(cast(dict[str, object], value["result"]), MAX_ENGINE_RESPONSE)
                )
            except (ValueError, TypeError, UnicodeError):
                raise _invalid() from None
        return cls(
            EngineIdentity.from_value(value["identity"]),
            cast(EngineCommand, command),
            cast(ReplyStatus, value["status"]),
            result,
            cast(CloseScope, value["close_scope"]),
        )
