"""Private bounded authentication envelopes; no persistence or network imports."""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
from dataclasses import dataclass
from uuid import UUID

from boca_socios.browser.ipc_protocol import SyntheticIPCError
from boca_socios.browser.queue_page_observation import QueuePageObservation

MAX_AUTH_REQUEST = 32768
MAX_AUTH_RESPONSE = 90112
MAX_PROVIDER_RESPONSE = 65536


def invalid() -> SyntheticIPCError:
    return SyntheticIPCError("boca_auth_envelope_unverified")


def operation_id(value: object) -> str:
    try:
        if type(value) is not str or str(UUID(value)) != value or UUID(value).int == 0:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise invalid() from None
    return value


def _nonce(value: object) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise invalid()


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise invalid()
        result[key] = value
    return result


def decode(payload: bytes, keys: set[str], maximum: int) -> dict[str, object]:
    try:
        if type(payload) is not bytes or not 0 < len(payload) <= maximum:
            raise invalid()
        value = json.loads(payload, object_pairs_hook=_unique)
        if type(value) is not dict or set(value) != keys:
            raise invalid()
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise invalid() from None


def encode(value: dict[str, object], maximum: int) -> bytes:
    try:
        payload = json.dumps(
            value, ensure_ascii=True, separators=(",", ":"), allow_nan=False
        ).encode()
        if len(payload) > maximum:
            raise invalid()
        return payload
    except (ValueError, TypeError, UnicodeError):
        raise invalid() from None


@dataclass(frozen=True, slots=True, repr=False)
class BocaAuthReadiness:
    operation_id: str
    observation: QueuePageObservation
    nonce: str | None
    remaining_seconds: float

    def __post_init__(self) -> None:
        operation_id(self.operation_id)
        if not isinstance(self.observation, QueuePageObservation):
            raise invalid()
        if type(self.remaining_seconds) not in {int, float} or not math.isfinite(
            self.remaining_seconds
        ):
            raise invalid()
        if self.nonce is None:
            if self.remaining_seconds != 0:
                raise invalid()
        else:
            _nonce(self.nonce)
            if not 0 < self.remaining_seconds <= 15 or self.observation.outcome not in {
                "UNKNOWN",
                "TARGET_OBSERVED",
            }:
                raise invalid()

    @property
    def ready(self) -> bool:
        return self.nonce is not None

    def __repr__(self) -> str:
        return "BocaAuthReadiness(<private values omitted>)"

    def to_payload(self) -> bytes:
        return encode(
            {
                "operation_id": self.operation_id,
                "observation": json.loads(self.observation.to_payload()),
                "nonce": self.nonce,
                "remaining_seconds": self.remaining_seconds,
            },
            MAX_AUTH_RESPONSE,
        )

    @classmethod
    def from_payload(cls, payload: bytes) -> BocaAuthReadiness:
        value = decode(
            payload,
            {"operation_id", "observation", "nonce", "remaining_seconds"},
            MAX_AUTH_RESPONSE,
        )
        try:
            observed = QueuePageObservation.from_payload(json.dumps(value["observation"]).encode())
            return cls(value["operation_id"], observed, value["nonce"], value["remaining_seconds"])  # type: ignore[arg-type]
        except (ValueError, TypeError):
            raise invalid() from None


@dataclass(frozen=True, slots=True, repr=False)
class BocaAuthRequest:
    operation_id: str
    nonce: str
    email: str
    password: str

    def __post_init__(self) -> None:
        operation_id(self.operation_id)
        _nonce(self.nonce)
        if (
            type(self.email) is not str
            or not 0 < len(self.email) <= 320
            or type(self.password) is not str
            or not 0 < len(self.password) <= 4096
        ):
            raise invalid()

    def __repr__(self) -> str:
        return "BocaAuthRequest(<private values omitted>)"

    def to_payload(self) -> bytes:
        return encode(
            {
                "operation_id": self.operation_id,
                "nonce": self.nonce,
                "email": self.email,
                "password": self.password,
            },
            MAX_AUTH_REQUEST,
        )

    @classmethod
    def from_payload(cls, payload: bytes) -> BocaAuthRequest:
        value = decode(payload, {"operation_id", "nonce", "email", "password"}, MAX_AUTH_REQUEST)
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True, repr=False)
class BocaAuthReply:
    operation_id: str
    nonce: str
    provider_payload: bytes

    def __post_init__(self) -> None:
        operation_id(self.operation_id)
        _nonce(self.nonce)
        if (
            type(self.provider_payload) is not bytes
            or not 0 < len(self.provider_payload) <= MAX_PROVIDER_RESPONSE
        ):
            raise invalid()

    def __repr__(self) -> str:
        return "BocaAuthReply(<private values omitted>)"

    def to_payload(self) -> bytes:
        return encode(
            {
                "operation_id": self.operation_id,
                "nonce": self.nonce,
                "provider_payload": base64.b64encode(self.provider_payload).decode("ascii"),
            },
            MAX_AUTH_RESPONSE,
        )

    @classmethod
    def from_payload(cls, payload: bytes) -> BocaAuthReply:
        value = decode(payload, {"operation_id", "nonce", "provider_payload"}, MAX_AUTH_RESPONSE)
        try:
            if type(value["provider_payload"]) is not str:
                raise invalid()
            raw = base64.b64decode(value["provider_payload"], validate=True)
            return cls(value["operation_id"], value["nonce"], raw)  # type: ignore[arg-type]
        except (ValueError, TypeError, binascii.Error):
            raise invalid() from None
