"""Bind a *pre-captured* public HTML page to an unverified offline notice.

This module has no network, filesystem, credential, or browser access. It can
prove only that supplied bytes match a claimed digest and contain the reviewer's
quoted text, NOT that those bytes came from the declared official URL, that
the excerpts were correctly interpreted, or that admission is currently open.
An independent trusted HTTPS capture receipt and owner review remain required.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from itertools import islice

from .official_catalog import (
    OfficialCatalogError,
    OfficialNotice,
    build_observed_catalog,
    load_observed_notice,
)

_MAX_CAPTURES = 20
_MAX_HTML_BYTES = 1_000_000
_MAX_CLAIM_BYTES = 16_384
_MAX_JSONL_BYTES = _MAX_CAPTURES * (_MAX_CLAIM_BYTES + 1)
_IGNORED_TAGS = frozenset({"script", "style", "noscript", "svg", "template"})


class OfflineCaptureError(OfficialCatalogError):
    """Incomplete, contradictory or oversized pre-captured public evidence."""


@dataclass(frozen=True)
class OfflineCapture:
    """Owner-reviewed claim plus quoted evidence in *provided*, not fetched, HTML."""

    source_html: bytes
    notice_json: str
    title_excerpt: str
    publication_excerpt: str
    kickoff_excerpt: str
    window_excerpts: tuple[str, ...]


class _VisiblePublicText(HTMLParser):
    """Extract bounded human-visible text without using scripts as evidence."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.has_html = False
        self.has_body = False
        self._in_body = False
        self._ignored: list[str] = []
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "html":
            self.has_html = True
        if tag == "body":
            self.has_body = True
            self._in_body = True
        attributes = dict(attrs)
        if (
            tag in _IGNORED_TAGS
            or "hidden" in attributes
            or attributes.get("aria-hidden") == "true"
            or "display:none" in (attributes.get("style") or "").replace(" ", "").lower()
        ):
            self._ignored.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._ignored and self._ignored[-1] == tag:
            self._ignored.pop()
        if tag == "body":
            self._in_body = False

    def handle_data(self, data: str) -> None:
        if self._in_body and not self._ignored:
            self._chunks.append(data)

    def visible(self) -> str:
        if not self.has_html or not self.has_body or self._ignored:
            raise OfflineCaptureError("public capture document structure invalid")
        return _normalize(" ".join(self._chunks))


def _normalize(value: str) -> str:
    return " ".join(re.split(r"[\s\u200b]+", unicodedata.normalize("NFKC", value))).casefold()


def _excerpt_present(public_text: str, excerpt: object) -> None:
    if (
        type(excerpt) is not str
        or not 12 <= len(excerpt) <= 320
        or any(ord(character) < 32 or ord(character) == 127 for character in excerpt)
    ):
        raise OfflineCaptureError("public capture excerpt malformed")
    observed = _normalize(excerpt)
    if len(observed) < 12 or observed not in public_text:
        raise OfflineCaptureError("public capture excerpt absent from visible text")


def _bind_capture(capture: OfflineCapture) -> tuple[OfficialNotice, dict[str, object]]:
    if (
        not isinstance(capture, OfflineCapture)
        or type(capture.source_html) is not bytes
        or not 0 < len(capture.source_html) <= _MAX_HTML_BYTES
        or type(capture.notice_json) is not str
    ):
        raise OfflineCaptureError("public capture type or size invalid")
    try:
        encoded_claim = capture.notice_json.encode("utf-8")
        html_text = capture.source_html.decode("utf-8")
    except UnicodeError:
        raise OfflineCaptureError("public capture is not UTF-8") from None
    if not 0 < len(encoded_claim) <= _MAX_CLAIM_BYTES:
        raise OfflineCaptureError("public capture claim capacity exceeded")
    try:
        notice = load_observed_notice(capture.notice_json)
    except OfficialCatalogError:
        raise OfflineCaptureError("public capture claim contract invalid") from None
    actual_digest = hashlib.sha256(capture.source_html).hexdigest()
    if not hmac.compare_digest(actual_digest, notice.source_sha256):
        raise OfflineCaptureError("public capture digest does not match source assertion")
    visible = _VisiblePublicText()
    try:
        visible.feed(html_text)
        visible.close()
        text = visible.visible()
    except (ValueError, AssertionError):
        raise OfflineCaptureError("public capture HTML invalid") from None
    for excerpt in (
        capture.title_excerpt,
        capture.publication_excerpt,
        capture.kickoff_excerpt,
    ):
        _excerpt_present(text, excerpt)
    if _normalize(notice.title) not in _normalize(capture.title_excerpt):
        raise OfflineCaptureError("public capture title claim is not evidenced by excerpt")
    if type(capture.window_excerpts) is not tuple or len(capture.window_excerpts) != len(
        notice.windows
    ):
        raise OfflineCaptureError("public capture window excerpt count invalid")
    for excerpt in capture.window_excerpts:
        _excerpt_present(text, excerpt)
    if notice.admission_channel_excerpt is not None:
        _excerpt_present(text, notice.admission_channel_excerpt)
    # Strict parsing already rejects duplicate/extra keys and all unsupported
    # claims. This reserialization contains only data from that validated claim.
    claim = json.loads(capture.notice_json)
    assert isinstance(claim, dict)
    return notice, claim


def build_official_snapshot_jsonl(captures: Iterable[OfflineCapture]) -> str:
    """Produce canonical JSONL; no file or network writes and no trust upgrade."""
    bounded = tuple(islice(captures, _MAX_CAPTURES + 1))
    if len(bounded) > _MAX_CAPTURES:
        raise OfflineCaptureError("public capture capacity exceeded")
    pairs = tuple(_bind_capture(capture) for capture in bounded)
    try:
        catalog = build_observed_catalog(notice for notice, _claim in pairs)
    except OfficialCatalogError:
        raise OfflineCaptureError("public capture duplicated or contradictory") from None
    claims = {notice.event_key: claim for notice, claim in pairs}
    lines = [
        json.dumps(
            claims[notice.event_key], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        for notice in catalog
    ]
    result = "\n".join(lines) + ("\n" if lines else "")
    if len(result.encode("utf-8")) > _MAX_JSONL_BYTES or any(
        len(line.encode("utf-8")) > _MAX_CLAIM_BYTES for line in lines
    ):
        raise OfflineCaptureError("public capture JSONL capacity exceeded")
    return result
