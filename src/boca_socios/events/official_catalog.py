"""Fail-closed import of manually observed Boca *public* match notices.

The input is a small externally extracted JSON evidence envelope, never a
browser fetch or official API response. This module has no I/O: it cannot read
the club, a member account, the queue, Docker, Telegram or local database.
Passing its structural checks does not establish that a club publication was
actually retrieved, that a window is current, or that any ticket is available.
It must never be converted directly into an actionable TicketIntent.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from itertools import islice
from typing import Literal
from urllib.parse import urlsplit

_SOURCE_PATH = re.compile(r"/noticias/[a-z0-9][a-z0-9-]{1,110}\Z")
_ART_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::00)?-03:00\Z")
_EVENT_KEY = re.compile(r"[a-z0-9][a-z0-9-]{5,80}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_LOCAL_OFFSET = timedelta(hours=-3)
_MAX_ENVELOPE_BYTES = 16_384
_MAX_WINDOWS = 16
_MAX_NOTICES = 20
_TOP_FIELDS = frozenset(
    {
        "version",
        "source_url",
        "published_on",
        "observed_at",
        "source_sha256",
        "event_key",
        "title",
        "kickoff_at",
        "windows",
    }
)
_TOP_FIELDS_V2 = _TOP_FIELDS | frozenset({"admission_channel_claim", "admission_channel_excerpt"})
_WINDOW_FIELDS = frozenset({"member_category", "seat_area", "opens_at", "closes_at", "close_rule"})

MemberCategory = Literal[
    "activos_interior", "adherentes", "plenos", "abonados", "abono_solidario", "vitalicios"
]
SeatArea = Literal["generales", "plateas", "plateas_y_generales"]
CloseRule = Literal["unspecified", "timestamp", "stadium_open"]
AdmissionChannelClaim = Literal["BOCA_SOCIOS", "CONMEBOL", "UNKNOWN"]
ObservationPhase = Literal["UPCOMING_UNVERIFIED", "HISTORICAL"]

_CATEGORIES = frozenset(
    {"activos_interior", "adherentes", "plenos", "abonados", "abono_solidario", "vitalicios"}
)
_AREAS = frozenset({"generales", "plateas", "plateas_y_generales"})
_CLOSE_RULES = frozenset({"unspecified", "timestamp", "stadium_open"})


class OfficialCatalogError(ValueError):
    """Unverified or contradictory event-source evidence must not be promoted."""


@dataclass(frozen=True)
class CategoryWindow:
    member_category: MemberCategory
    seat_area: SeatArea
    opens_at: datetime
    closes_at: datetime | None
    close_rule: CloseRule


@dataclass(frozen=True)
class OfficialNotice:
    source_url: str
    published_on: date
    observed_at: datetime
    source_sha256: str
    event_key: str
    title: str
    kickoff_at: datetime
    windows: tuple[CategoryWindow, ...]
    admission_channel_claim: AdmissionChannelClaim = "UNKNOWN"
    admission_channel_excerpt: str | None = None
    verification_state: Literal["SOURCE_OBSERVED_UNVERIFIED"] = field(
        init=False, default="SOURCE_OBSERVED_UNVERIFIED"
    )
    actionable: Literal[False] = field(init=False, default=False)


@dataclass(frozen=True)
class OfficialNoticeAssessment:
    source_url: str
    event_key: str
    title: str
    phase: ObservationPhase
    windows_count: int
    actionable: Literal[False] = False


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    seen: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise OfficialCatalogError("duplicate source envelope field")
        seen[key] = value
    return seen


def _reject_constant(_: str) -> None:
    raise OfficialCatalogError("nonfinite source envelope value")


def _object(value: object, expected: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != expected:
        raise OfficialCatalogError("unknown, missing or malformed source field")
    if any(type(key) is not str for key in value):
        raise OfficialCatalogError("non-string source field")
    return value


def _local_datetime(value: object) -> datetime:
    if type(value) is not str or not _ART_TIMESTAMP.fullmatch(value):
        raise OfficialCatalogError("source timestamp must be explicit ISO 8601 with ART offset")
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as exc:
        raise OfficialCatalogError("invalid source date/time") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() != _LOCAL_OFFSET:
        raise OfficialCatalogError("ambiguous source timestamp or non-ART offset")
    if timestamp.second or timestamp.microsecond:
        raise OfficialCatalogError("source window must be represented at minute precision")
    return timestamp


def _source_url(value: object) -> str:
    if type(value) is not str or len(value) > 180 or any(ord(c) <= 32 for c in value):
        raise OfficialCatalogError("invalid official-source URL")
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise OfficialCatalogError("unparseable official-source URL") from exc
    if (
        parsed.scheme != "https"
        or parsed.netloc != "www.bocajuniors.com.ar"
        or not _SOURCE_PATH.fullmatch(parsed.path)
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or parsed.geturl() != value
    ):
        raise OfficialCatalogError("source is not an exact public Boca notice URL")
    return value


def _window(raw: object, kickoff: datetime) -> CategoryWindow:
    obj = _object(raw, _WINDOW_FIELDS)
    category, area, rule = (obj["member_category"], obj["seat_area"], obj["close_rule"])
    if (
        type(category) is not str
        or category not in _CATEGORIES
        or type(area) is not str
        or area not in _AREAS
        or type(rule) is not str
        or rule not in _CLOSE_RULES
    ):
        raise OfficialCatalogError("unrecognized member category or sector")
    opens_at = _local_datetime(obj["opens_at"])
    if not opens_at < kickoff:
        raise OfficialCatalogError("source window opens after event kickoff")
    closes_raw = obj["closes_at"]
    closes_at = _local_datetime(closes_raw) if closes_raw is not None else None
    if (rule == "timestamp") != (closes_at is not None):
        raise OfficialCatalogError("closing rule contradicts exact closing time")
    if closes_at is not None and not (opens_at < closes_at <= kickoff):
        raise OfficialCatalogError("closing timestamp is not between open and kickoff")
    # The set membership above is a runtime guard for the Literal types.
    return CategoryWindow(
        member_category=category,  # type: ignore[arg-type]
        seat_area=area,  # type: ignore[arg-type]
        opens_at=opens_at,
        closes_at=closes_at,
        close_rule=rule,  # type: ignore[arg-type]
    )


def _admission_claim(obj: dict[str, object]) -> tuple[AdmissionChannelClaim, str | None]:
    if obj["version"] == "official-notice-observation-v1":
        # Existing observations cannot silently inherit any provider.
        return "UNKNOWN", None
    claim = obj["admission_channel_claim"]
    excerpt = obj["admission_channel_excerpt"]
    if type(claim) is not str or claim not in ("BOCA_SOCIOS", "CONMEBOL", "UNKNOWN"):
        raise OfficialCatalogError("unsupported public admission channel assertion")
    if claim == "UNKNOWN":
        if excerpt is not None:
            raise OfficialCatalogError("unknown channel cannot provide asserted channel proof")
    elif (
        type(excerpt) is not str
        or not 20 <= len(excerpt) <= 320
        or any(ord(character) < 32 or ord(character) == 127 for character in excerpt)
    ):
        raise OfficialCatalogError("missing, oversized or malformed public channel excerpt")
    else:
        lowered = excerpt.casefold()
        if claim == "BOCA_SOCIOS" and ("boca socios" not in lowered or "conmebol" in lowered):
            raise OfficialCatalogError("Boca Socios channel claim lacks textual evidence")
        if claim == "CONMEBOL" and (
            "conmebol" not in lowered or "plataforma" not in lowered or "boca socios" in lowered
        ):
            raise OfficialCatalogError("CONMEBOL external-channel claim lacks textual evidence")
    # Assertions remain UNVERIFIED until independent provenance is checked.
    return claim, excerpt  # type: ignore[return-value]


def load_observed_notice(raw: str) -> OfficialNotice:
    """Validate a small **offline** reviewed observation; always UNVERIFIED.

    No metadata from this envelope can authorize a Boca interaction or be
    trusted as a live admission window. Provenance strings are assertions,
    not a signature or proof that any URL was actually retrieved.
    """
    if type(raw) is not str:
        raise OfficialCatalogError("source observation must be text")
    try:
        raw_size = len(raw.encode("utf-8"))
    except UnicodeError as exc:
        raise OfficialCatalogError("source observation is not UTF-8") from exc
    if raw_size > _MAX_ENVELOPE_BYTES:
        raise OfficialCatalogError("source observation exceeds private input budget")
    try:
        decoded = json.loads(raw, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    except (ValueError, TypeError) as exc:
        raise OfficialCatalogError("source observation JSON is invalid") from exc
    if not isinstance(decoded, dict):
        raise OfficialCatalogError("source observation must be a JSON object")
    version = decoded.get("version")
    if version == "official-notice-observation-v1":
        obj = _object(decoded, _TOP_FIELDS)
    elif version == "official-notice-observation-v2":
        obj = _object(decoded, _TOP_FIELDS_V2)
    else:
        raise OfficialCatalogError("unsupported source observation version")
    channel_claim, channel_excerpt = _admission_claim(obj)
    url = _source_url(obj["source_url"])
    published_raw = obj["published_on"]
    if type(published_raw) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", published_raw):
        raise OfficialCatalogError("publication date not explicitly recorded")
    try:
        published_on = date.fromisoformat(published_raw)
    except ValueError as exc:
        raise OfficialCatalogError("publication date is invalid") from exc
    observed_at = _local_datetime(obj["observed_at"])
    if published_on > observed_at.date():
        raise OfficialCatalogError("claim predates publication")
    digest, key, title = obj["source_sha256"], obj["event_key"], obj["title"]
    if (
        type(digest) is not str
        or not _DIGEST.fullmatch(digest)
        or type(key) is not str
        or not _EVENT_KEY.fullmatch(key)
        or type(title) is not str
        or not 8 <= len(title) <= 120
        or any(ord(character) < 32 for character in title)
    ):
        raise OfficialCatalogError("source hash, event key or public title is malformed")
    kickoff_at = _local_datetime(obj["kickoff_at"])
    windows_raw = obj["windows"]
    if not isinstance(windows_raw, list) or len(windows_raw) > _MAX_WINDOWS:
        raise OfficialCatalogError("source windows not bounded")
    windows = tuple(_window(window, kickoff_at) for window in windows_raw)
    pairs = [(window.member_category, window.seat_area) for window in windows]
    if len(pairs) != len(set(pairs)):
        raise OfficialCatalogError("duplicate or conflicting source category and sector")
    return OfficialNotice(
        source_url=url,
        published_on=published_on,
        observed_at=observed_at,
        source_sha256=digest,
        event_key=key,
        title=title,
        kickoff_at=kickoff_at,
        windows=windows,
        admission_channel_claim=channel_claim,
        admission_channel_excerpt=channel_excerpt,
    )


def build_observed_catalog(notices: Iterable[OfficialNotice]) -> tuple[OfficialNotice, ...]:
    """Bound, sort and de-duplicate informational observations without activating events.

    This is purely an offline data projection. Callers must not transform its
    entries into provider event IDs, bot commands or eligibility assertions.
    """
    # Do not materialize an unbounded caller-provided generator before applying
    # the catalog limit. The 21st item is enough to fail closed.
    items = tuple(islice(notices, _MAX_NOTICES + 1))
    if len(items) > _MAX_NOTICES:
        raise OfficialCatalogError("observation catalog exceeds bounded capacity")
    keys = [item.event_key for item in items]
    urls = [item.source_url for item in items]
    if len(keys) != len(set(keys)) or len(urls) != len(set(urls)):
        raise OfficialCatalogError("duplicate or contradictory event observations")
    return tuple(sorted(items, key=lambda item: (item.kickoff_at, item.event_key)))


def assess_official_notice(notice: OfficialNotice, *, at: datetime) -> OfficialNoticeAssessment:
    """Timestamped informational status, never a live provider/eligibility signal."""
    if at.tzinfo is None or at.utcoffset() is None or at < notice.observed_at:
        raise OfficialCatalogError("observation clock or timezone is uncertain")
    return OfficialNoticeAssessment(
        source_url=notice.source_url,
        event_key=notice.event_key,
        title=notice.title,
        phase="HISTORICAL" if at >= notice.kickoff_at else "UPCOMING_UNVERIFIED",
        windows_count=len(notice.windows),
    )
