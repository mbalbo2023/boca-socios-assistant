"""Pure projection of a page already received by the browser adapter.

No function here navigates, resolves a hostname, validates admission or creates
an event/member/session identity. A target remains an observed, unvalidated URL.
``to_payload`` is a private IPC envelope and must never be logged or published.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, cast
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from .site_url_runtime import require_site_url

ObservationOutcome = Literal[
    "QUEUE_ACTIVE",
    "PREQUEUE",
    "QUEUE_INACTIVE",
    "NO_EVENT_OBSERVED",
    "TARGET_OBSERVED",
    "CHALLENGE",
    "UNKNOWN",
    "CHECK_FAILED",
]
ObservedEventState = Literal[
    "EVENT_ANNOUNCED",
    "EVENT_VERIFIED",
    "NO_EVENT_CONFIRMED",
    "UNRECOGNIZED",
]
ObservedQueueState = Literal[
    "QUEUE_ACTIVE",
    "PREQUEUE",
    "QUEUE_INACTIVE",
    "ACCESS_OBSERVED",
    "UNKNOWN",
]
ObservationReason = Literal[
    "VISIBLE_CHALLENGE",
    "CHECK_FAILED",
    "HTTP_FAILURE",
    "INVALID_OBSERVATION",
    "CONTRADICTORY_EVIDENCE",
    "RECEIVED_TARGET",
    "OBSERVED_IDLE",
    "OBSERVED_PREQUEUE",
    "OBSERVED_QUEUE",
    "EXPLICIT_NO_EVENTS",
    "EVENT_ID_OBSERVED",
    "NO_RECOGNIZED_EVIDENCE",
]

MAX_OBSERVATION_PAYLOAD = 32768
_MAX_URL = 8192
_MAX_TEXT = 16384
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_MARKERS = frozenset(
    {
        "prequeue",
        "progressbar",
        "queueid",
        "queuenumber",
        "expectedservice",
        "captcha",
        "challenge",
    }
)
_QUEUE_MARKERS = frozenset({"progressbar", "queueid", "queuenumber", "expectedservice"})
_MODEL_KEYS = frozenset(
    {
        "eventId",
        "queueId",
        "queueState",
        "targetUrl",
        "isBeforeOrIdle",
        "isIdle",
        "ticket",
    }
)
_TICKET_KEYS = frozenset(
    {
        "queuePaused",
        "progress",
        "expectedServiceTime",
        "whichIsIn",
        "usersInLineAheadOfYou",
        "usersInQueue",
        "queueNumber",
    }
)
_ABSENCE_LINES = frozenset({"No hay eventos disponibles", "No hay partidos disponibles"})
_FIELDS = frozenset(
    {
        "version",
        "outcome",
        "event_state",
        "queue_state",
        "reason",
        "observed_at",
        "event_id",
        "target_url",
    }
)
_REASONS: dict[str, tuple[ObservationOutcome, ObservedQueueState]] = {
    "VISIBLE_CHALLENGE": ("CHALLENGE", "UNKNOWN"),
    "CHECK_FAILED": ("CHECK_FAILED", "UNKNOWN"),
    "HTTP_FAILURE": ("CHECK_FAILED", "UNKNOWN"),
    "INVALID_OBSERVATION": ("UNKNOWN", "UNKNOWN"),
    "CONTRADICTORY_EVIDENCE": ("UNKNOWN", "UNKNOWN"),
    "RECEIVED_TARGET": ("TARGET_OBSERVED", "ACCESS_OBSERVED"),
    "OBSERVED_IDLE": ("QUEUE_INACTIVE", "QUEUE_INACTIVE"),
    "OBSERVED_PREQUEUE": ("PREQUEUE", "PREQUEUE"),
    "OBSERVED_QUEUE": ("QUEUE_ACTIVE", "QUEUE_ACTIVE"),
    "EXPLICIT_NO_EVENTS": ("NO_EVENT_OBSERVED", "UNKNOWN"),
    "EVENT_ID_OBSERVED": ("UNKNOWN", "UNKNOWN"),
    "NO_RECOGNIZED_EVIDENCE": ("UNKNOWN", "UNKNOWN"),
}


def _invalid() -> ValueError:
    return ValueError("Queue page observation is invalid")


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _invalid()
    try:
        return value.astimezone(UTC)
    except (ValueError, OverflowError):
        raise _invalid() from None


def _bounded_text(value: object, maximum: int) -> bool:
    if type(value) is not str:
        return False
    try:
        return len(value.encode("utf-8")) <= maximum
    except UnicodeError:
        return False


def _identifier(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise _invalid()
    return value


def _received_target(value: str) -> str | None:
    """Use the existing pass query contract without inventing its required IDs."""
    if (
        not _bounded_text(value, _MAX_URL)
        or not value
        or any(ord(character) <= 32 or ord(character) == 127 for character in value)
    ):
        raise _invalid()
    try:
        parts = urlsplit(value)
        # Only the base is passed to the existing syntax validator, which forbids
        # credentials and metadata/link-local hosts. The returned URL stays exact.
        require_site_url(urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")))
        pairs = parse_qsl(parts.query, keep_blank_values=True, max_num_fields=64, errors="strict")
    except (ValueError, UnicodeError):
        raise _invalid() from None
    tokens = [token for key, token in pairs if key == "queueittoken"]
    if not tokens:
        return None
    if len(tokens) != 1 or not tokens[0].strip():
        raise _invalid()
    return value


def _model_is_valid(model: dict[str, object]) -> bool:
    if not set(model) <= _MODEL_KEYS:
        return False
    try:
        _identifier(model.get("eventId"))
        _identifier(model.get("queueId"))
    except ValueError:
        return False
    for key in ("isIdle", "isBeforeOrIdle"):
        if model.get(key) is not None and type(model[key]) is not bool:
            return False
    queue_state = model.get("queueState")
    if queue_state is not None and not (
        type(queue_state) is int and -1000 <= queue_state <= 1000 or _bounded_text(queue_state, 128)
    ):
        return False
    if model.get("targetUrl") is not None and not _bounded_text(model["targetUrl"], _MAX_URL):
        return False
    ticket = model.get("ticket")
    if ticket is None:
        return True
    if type(ticket) is not dict or not set(ticket) <= _TICKET_KEYS:
        return False
    for key, value in ticket.items():
        if value is None:
            continue
        if key == "queuePaused":
            if type(value) is not bool:
                return False
        elif type(value) in {int, float}:
            if not -1e15 <= value <= 1e15 or not math.isfinite(value):
                return False
        elif not _bounded_text(value, 256):
            return False
    return True


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _invalid()
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class QueuePageObservation:
    outcome: ObservationOutcome
    event_state: ObservedEventState
    queue_state: ObservedQueueState
    reason: ObservationReason
    observed_at: datetime
    event_id: str | None = field(default=None, repr=False)
    target_url: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if type(self.reason) is not str or _REASONS.get(self.reason) != (
            self.outcome,
            self.queue_state,
        ):
            raise _invalid()
        object.__setattr__(self, "observed_at", _utc(self.observed_at))
        if self.event_id is not None and _identifier(self.event_id) != self.event_id:
            raise _invalid()
        expected_event: ObservedEventState = "EVENT_VERIFIED" if self.event_id else "UNRECOGNIZED"
        if self.outcome == "PREQUEUE":
            expected_event = "EVENT_ANNOUNCED"
        elif self.outcome == "NO_EVENT_OBSERVED":
            expected_event = "NO_EVENT_CONFIRMED"
        if self.event_state != expected_event:
            raise _invalid()
        if (
            self.reason
            in {
                "VISIBLE_CHALLENGE",
                "CHECK_FAILED",
                "HTTP_FAILURE",
                "INVALID_OBSERVATION",
                "CONTRADICTORY_EVIDENCE",
                "EXPLICIT_NO_EVENTS",
                "NO_RECOGNIZED_EVIDENCE",
            }
            and self.event_id is not None
        ):
            raise _invalid()
        if self.reason == "EVENT_ID_OBSERVED" and self.event_id is None:
            raise _invalid()
        if self.outcome == "TARGET_OBSERVED":
            if self.target_url is None or _received_target(self.target_url) != self.target_url:
                raise _invalid()
        elif self.target_url is not None:
            raise _invalid()

    def metadata(self) -> dict[str, object]:
        """Redacted status only; no received URL, token, raw DOM or opaque ID."""
        return {
            "outcome": self.outcome,
            "event_state": self.event_state,
            "queue_state": self.queue_state,
            "reason": self.reason,
            "observed_at": self.observed_at.isoformat(),
            "event_id_observed": self.event_id is not None,
        }

    def to_payload(self) -> bytes:
        """Serialize exclusively for the authenticated private IPC channel."""
        document = self.metadata()
        document.pop("event_id_observed")
        document.update(version=1, event_id=self.event_id, target_url=self.target_url)
        payload = json.dumps(
            document, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
        if len(payload) > MAX_OBSERVATION_PAYLOAD:
            raise _invalid()
        return payload

    @classmethod
    def from_payload(cls, raw: bytes) -> QueuePageObservation:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_OBSERVATION_PAYLOAD:
            raise _invalid()
        try:
            data = json.loads(raw, object_pairs_hook=_unique_object)
            if (
                type(data) is not dict
                or set(data) != _FIELDS
                or type(data["version"]) is not int
                or data["version"] != 1
                or any(
                    type(data[key]) is not str
                    for key in (
                        "outcome",
                        "event_state",
                        "queue_state",
                        "reason",
                        "observed_at",
                    )
                )
                or any(
                    data[key] is not None and type(data[key]) is not str
                    for key in (
                        "event_id",
                        "target_url",
                    )
                )
            ):
                raise _invalid()
            return cls(
                outcome=cast(ObservationOutcome, data["outcome"]),
                event_state=cast(ObservedEventState, data["event_state"]),
                queue_state=cast(ObservedQueueState, data["queue_state"]),
                reason=cast(ObservationReason, data["reason"]),
                observed_at=datetime.fromisoformat(data["observed_at"]),
                event_id=data["event_id"],
                target_url=data["target_url"],
            )
        except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
            raise _invalid() from None


def _observation(
    reason: ObservationReason,
    observed_at: datetime,
    *,
    event_id: str | None = None,
    target_url: str | None = None,
) -> QueuePageObservation:
    outcome, queue_state = _REASONS[reason]
    event_state: ObservedEventState = "EVENT_VERIFIED" if event_id else "UNRECOGNIZED"
    if outcome == "PREQUEUE":
        event_state = "EVENT_ANNOUNCED"
    elif outcome == "NO_EVENT_OBSERVED":
        event_state = "NO_EVENT_CONFIRMED"
    return QueuePageObservation(
        outcome, event_state, queue_state, reason, observed_at, event_id, target_url
    )


def parse_queue_page_observation(
    *,
    final_url: str,
    queue_model: dict[str, object] | None,
    markers: frozenset[str],
    observed_at: datetime,
    visible_text: str = "",
    http_status: int | None = None,
    check_failed: bool = False,
) -> QueuePageObservation:
    """Classify received facts without treating HTTP success as event absence."""
    now = _utc(observed_at)
    if isinstance(markers, frozenset) and markers & {"captcha", "challenge"}:
        return _observation("VISIBLE_CHALLENGE", now)
    if check_failed is True:
        return _observation("CHECK_FAILED", now)
    if type(http_status) is int and 400 <= http_status <= 599:
        return _observation("HTTP_FAILURE", now)
    if (
        type(check_failed) is not bool
        or (
            http_status is not None
            and (type(http_status) is not int or not 100 <= http_status <= 599)
        )
        or not _bounded_text(visible_text, _MAX_TEXT)
        or type(markers) is not frozenset
        or not markers <= _MARKERS
        or (
            queue_model is not None
            and (type(queue_model) is not dict or not _model_is_valid(queue_model))
        )
    ):
        return _observation("INVALID_OBSERVATION", now)
    model = queue_model or {}
    try:
        event_id = _identifier(model.get("eventId"))
        final_target = _received_target(final_url)
        raw_target = model.get("targetUrl")
        model_target = (
            _received_target(raw_target) if isinstance(raw_target, str) and raw_target else None
        )
    except (ValueError, TypeError):
        return _observation("INVALID_OBSERVATION", now)
    targets = {target for target in (final_target, model_target) if target is not None}
    if len(targets) > 1:
        return _observation("CONTRADICTORY_EVIDENCE", now)
    explicit_absence = any(
        " ".join(line.split()) in _ABSENCE_LINES for line in visible_text.splitlines()
    )
    if explicit_absence:
        if model or markers & (_QUEUE_MARKERS | {"prequeue"}) or targets:
            return _observation("CONTRADICTORY_EVIDENCE", now)
        return _observation("EXPLICIT_NO_EVENTS", now)
    if targets:
        return _observation(
            "RECEIVED_TARGET", now, event_id=event_id, target_url=next(iter(targets))
        )
    if model.get("isIdle") is True:
        if markers & _QUEUE_MARKERS:
            return _observation("CONTRADICTORY_EVIDENCE", now)
        return _observation("OBSERVED_IDLE", now, event_id=event_id)
    if model.get("isBeforeOrIdle") is True or "prequeue" in markers:
        return _observation("OBSERVED_PREQUEUE", now, event_id=event_id)
    ticket = model.get("ticket")
    has_ticket = isinstance(ticket, dict) and any(
        value is not None and value != "" for value in ticket.values()
    )
    if markers & _QUEUE_MARKERS or has_ticket:
        return _observation("OBSERVED_QUEUE", now, event_id=event_id)
    if event_id is not None:
        return _observation("EVENT_ID_OBSERVED", now, event_id=event_id)
    return _observation("NO_RECOGNIZED_EVIDENCE", now)
