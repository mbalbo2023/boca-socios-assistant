"""Offline extraction of the exact Boca–Defensa public announcement.

Only an already captured, bounded HTML document is accepted.  The caller is
responsible for the independent TLS/HTTP source receipt; this parser cannot
authenticate the origin of supplied bytes or determine ticket availability.
No network, browser, filesystem, controller or member-account access exists.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from re import Match

from .official_capture_binding import (
    OfflineCapture,
    OfflineCaptureError,
    _VisiblePublicText,
    build_official_snapshot_jsonl,
)
from .official_news_receipt import OFFICIAL_NEWS_URL

_ART = timezone(timedelta(hours=-3))
_EXPECTED_TITLE = "Boca-Defensa: Información al socio"
_EVENT_KEY = "boca-defensa-y-justicia-20261107"
_MAX_HTML_BYTES = 1_000_000

_PUBLICATION = re.compile(r"november (?P<day>\d{1,2}), (?P<year>\d{4})")
_KICKOFF = re.compile(
    r"boca vuelve a jugar en casa este sábado (?P<day>\d{1,2}) "
    r"de noviembre a las (?P<hour>\d{1,2})\.(?P<minute>\d{2}) "
    r"hs ante defensa y justicia"
)
_CHANNEL = re.compile(
    r"las socias y los socios deberán adquirir su adicional a través de "
    r"boca socios, de acuerdo con el siguiente cronograma"
)
_WINDOWS = (
    (
        "activos_interior",
        "generales",
        re.compile(
            r"socios activos e interior: desde el (?P<day>\d{2})/"
            r"(?P<month>\d{2}) a las (?P<hour>\d{1,2}) hs"
        ),
        "unspecified",
    ),
    (
        "adherentes",
        "generales",
        re.compile(
            r"socios adherentes: desde el (?P<day>\d{2})/"
            r"(?P<month>\d{2}) a las (?P<hour>\d{1,2}) hs"
        ),
        "unspecified",
    ),
    (
        "abonados",
        "plateas",
        re.compile(
            r"confirmación de abonados: desde el (?P<day>\d{2})/"
            r"(?P<month>\d{2}) a las (?P<hour>\d{1,2}) hs hasta el "
            r"(?P<close_day>\d{2})/(?P<close_month>\d{2}) a las "
            r"(?P<close_hour>\d{1,2}):(?P<close_minute>\d{2}) hs"
        ),
        "timestamp",
    ),
    (
        "abono_solidario",
        "plateas",
        re.compile(
            r"abono solidario: desde el (?P<day>\d{2})/(?P<month>\d{2}) "
            r"a las (?P<hour>\d{1,2}) hs hasta la apertura del estadio"
        ),
        "stadium_open",
    ),
    (
        "vitalicios",
        "plateas_y_generales",
        re.compile(
            r"reserva de plateas y generales: desde el (?P<day>\d{2})/"
            r"(?P<month>\d{2}) a las (?P<hour>\d{1,2}) hs"
        ),
        "unspecified",
    ),
)


def _one(text: str, pattern: re.Pattern[str]) -> Match[str]:
    found = tuple(pattern.finditer(text))
    if len(found) != 1:
        raise OfflineCaptureError("official article field absent or ambiguous")
    return found[0]


def _local(year: int, month: int, day: int, hour: int, minute: int = 0) -> str:
    try:
        return datetime(year, month, day, hour, minute, tzinfo=_ART).isoformat(timespec="minutes")
    except ValueError:
        raise OfflineCaptureError("official article date or hour invalid") from None


def _visible(source_html: bytes) -> str:
    if type(source_html) is not bytes or not 0 < len(source_html) <= _MAX_HTML_BYTES:
        raise OfflineCaptureError("official article payload invalid or oversized")
    try:
        source_text = source_html.decode("utf-8")
    except UnicodeError:
        raise OfflineCaptureError("official article payload not UTF-8") from None
    parser = _VisiblePublicText()
    try:
        parser.feed(source_text)
        parser.close()
        # The actual public article inserts U+200D before GENERALES. This is
        # a zero-width *format* codepoint, not a word or category delimiter:
        # discard only this observed character, retaining all other exact
        # category/heading checks (and hashing the untouched source bytes).
        visible = parser.visible().replace("\u200d", "")
    except (ValueError, AssertionError):
        raise OfflineCaptureError("official article HTML invalid") from None
    if _EXPECTED_TITLE.casefold() not in visible:
        raise OfflineCaptureError("official article identity not established")
    return visible


def build_boca_defensa_offline_jsonl(source_html: bytes, *, observed_at: datetime) -> str:
    """Build one non-actionable JSONL observation from *provided* public HTML.

    The exact article grammar is intentionally narrow. A new publication,
    changed template or inconsistent window is an explicit failure requiring
    source review, not a guessed schedule. The -03:00 timestamp is an ART
    presentation assumption: the source article does not certify its timezone.
    """
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
        raise OfflineCaptureError("source observation clock unavailable")
    if observed_at.utcoffset() is None:
        raise OfflineCaptureError("source observation timezone unavailable")
    local_observed = observed_at.astimezone(_ART).replace(second=0, microsecond=0)
    text = _visible(source_html)
    publication = _one(text, _PUBLICATION)
    kickoff = _one(text, _KICKOFF)
    channel = _one(text, _CHANNEL)
    if (int(publication["year"]), int(publication["day"]), int(kickoff["day"])) != (
        2026,
        3,
        7,
    ):
        raise OfflineCaptureError("article identity disagrees with fixed event evidence")
    kickoff_hour, kickoff_minute = int(kickoff["hour"]), int(kickoff["minute"])
    if (kickoff_hour, kickoff_minute) != (17, 30):
        raise OfflineCaptureError("article kickoff differs from reviewed source")
    published_on = "2026-11-03"
    if local_observed.date().isoformat() < published_on:
        raise OfflineCaptureError("source observation precedes publication")

    matches: list[Match[str]] = []
    windows: list[dict[str, object]] = []
    for category, area, pattern, close_rule in _WINDOWS:
        match = _one(text, pattern)
        matches.append(match)
        opens = _local(2026, int(match["month"]), int(match["day"]), int(match["hour"]))
        closes: str | None = None
        if close_rule == "timestamp":
            closes = _local(
                2026,
                int(match["close_month"]),
                int(match["close_day"]),
                int(match["close_hour"]),
                int(match["close_minute"]),
            )
        windows.append(
            {
                "member_category": category,
                "seat_area": area,
                "opens_at": opens,
                "closes_at": closes,
                "close_rule": close_rule,
            }
        )
    # The club's text has distinct GENERAL, PLATEA and VITALICIOS sections.
    # A shuffled or duplicated sentence should not silently inherit a sector.
    ordered = [match.start() for match in matches]
    if ordered != sorted(ordered):
        raise OfflineCaptureError("official article category order ambiguous")
    for start, stop, heading in (
        (channel.end(), matches[0].start(), "generales"),
        (matches[1].end(), matches[2].start(), "plateas"),
        (matches[3].end(), matches[4].start(), "socios vitalicios"),
    ):
        if text[start:stop].strip(" .") != heading:
            raise OfflineCaptureError("official category heading absent or ambiguous")

    claim = {
        "version": "official-notice-observation-v2",
        "source_url": OFFICIAL_NEWS_URL,
        "published_on": published_on,
        "observed_at": local_observed.isoformat(timespec="minutes"),
        "source_sha256": hashlib.sha256(source_html).hexdigest(),
        "event_key": _EVENT_KEY,
        "title": _EXPECTED_TITLE,
        "kickoff_at": _local(2026, 11, 7, kickoff_hour, kickoff_minute),
        "windows": windows,
        "admission_channel_claim": "BOCA_SOCIOS",
        "admission_channel_excerpt": channel.group(0),
    }
    capture = OfflineCapture(
        source_html=source_html,
        notice_json=json.dumps(claim, ensure_ascii=False, separators=(",", ":")),
        title_excerpt=_EXPECTED_TITLE,
        publication_excerpt=publication.group(0),
        kickoff_excerpt=kickoff.group(0),
        window_excerpts=tuple(match.group(0) for match in matches),
    )
    return build_official_snapshot_jsonl((capture,))
