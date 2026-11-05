"""One anonymous, bounded public *club news* GET for a PR-only diagnostic.

No Boca Socios account, Queue-it, login, browser, ticket operation, host file,
or runtime JSONL is accessed. This source-health receipt deliberately cannot
establish official API/feed availability or any live purchase eligibility.
"""

from __future__ import annotations

import hashlib
import json
import re
import ssl
import sys
import unicodedata
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib import error, request

OFFICIAL_NEWS_URL = "https://www.bocajuniors.com.ar/noticias/boca-defensa-informacion-al-socio"
_MAX_HTML_BYTES = 1_000_000
_TIMEOUT_SECONDS = 8.0
_IGNORED_TAGS = frozenset({"head", "script", "style", "noscript", "svg", "template"})
_REQUIRED_MARKERS = {
    "article_title": "Boca-Defensa",
    "published_date": "November 3, 2026",
    "kickoff_date": "7 de noviembre",
    "kickoff_time": "17.30",
    "channel_mention": "Boca Socios",
    "active_category": "Socios activos e interior",
    "adherent_category": "Socios adherentes",
    "subscribed_category": "Confirmación de abonados",
    "solidarity_category": "Abono solidario",
    "vital_category": "SOCIOS VITALICIOS",
    "stated_deadline": "23:59",
}


class _NoRedirect(request.HTTPRedirectHandler):
    """Deny any second request, even toward another path of the same domain."""

    def redirect_request(
        self,
        _req: request.Request,
        _fp: object,
        _code: int,
        _msg: str,
        _headers: object,
        _newurl: str,
    ) -> None:
        return None


class _PublicBody(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.has_html = False
        self.has_body = False
        self._in_body = False
        self._ignored: list[str] = []
        self._text: list[str] = []

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
            self._text.append(data)

    def visible(self) -> str:
        if not self.has_html or not self.has_body or self._ignored:
            return ""
        return _normalize(" ".join(self._text))


def _normalize(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).casefold()
    without_marks = "".join(
        character for character in folded if not unicodedata.combining(character)
    )
    return " ".join(re.split(r"[\s\u200b]+", without_marks))


def analyze_public_html(payload: bytes) -> dict[str, bool]:
    """Return short yes/no observations; no raw public text escapes in receipt."""
    default = {key: False for key in _REQUIRED_MARKERS}
    if type(payload) is not bytes or not 0 < len(payload) <= _MAX_HTML_BYTES:
        return default
    try:
        parser = _PublicBody()
        parser.feed(payload.decode("utf-8"))
        parser.close()
        visible = parser.visible()
    except (UnicodeError, ValueError, AssertionError):
        return default
    return {key: _normalize(fragment) in visible for key, fragment in _REQUIRED_MARKERS.items()}


def _parse_server_date(raw: str | None) -> str | None:
    if raw is None or len(raw) > 90:
        return None
    try:
        value = parsedate_to_datetime(raw)
        if value.tzinfo is None:
            return None
        return value.astimezone(UTC).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def observe_public_news(*, now: datetime | None = None) -> dict[str, object]:
    """Single GET with TLS verification; external failure is an advisory receipt."""
    if now is None:
        now = datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("source diagnostic timestamp requires timezone")
    receipt: dict[str, object] = {
        "schema": "boca-public-news-receipt-v1",
        "source_url": OFFICIAL_NEWS_URL,
        "observed_at_utc": now.astimezone(UTC).isoformat(),
        "http_status": None,
        "content_length": None,
        "source_sha256": None,
        "server_date_utc": None,
        "state": "SOURCE_DEGRADED",
        "reason": "transport_unavailable",
        "markers": {key: False for key in _REQUIRED_MARKERS},
        "request_count": 1,
        "tls_policy": "PYTHON_DEFAULT_CA_HOSTNAME_VERIFIED",
        "redirects_followed": 0,
        "credentials_sent": False,
        "feed_verified": False,
        "availability_verified": False,
        "actionable": False,
    }
    opener = request.build_opener(
        request.ProxyHandler({}),
        _NoRedirect(),
        request.HTTPSHandler(context=ssl.create_default_context()),
    )
    public_request = request.Request(
        OFFICIAL_NEWS_URL,
        headers={"Accept": "text/html", "User-Agent": "BocaPublicNewsReceipt/1.0"},
        method="GET",
    )
    try:
        with opener.open(public_request, timeout=_TIMEOUT_SECONDS) as response:
            receipt["http_status"] = response.status
            if response.status != 200:
                receipt["reason"] = "http_non_200"
                return receipt
            if response.geturl() != OFFICIAL_NEWS_URL:
                receipt["reason"] = "redirect_or_location_changed"
                return receipt
            content_type = response.headers.get("Content-Type", "").lower().split(";", 1)[0].strip()
            if content_type != "text/html":
                receipt["reason"] = "wrong_content_type"
                return receipt
            length_header = response.headers.get("Content-Length")
            if length_header is not None:
                if not length_header.isdecimal() or int(length_header) > _MAX_HTML_BYTES:
                    receipt["reason"] = "declared_body_too_large_or_invalid"
                    return receipt
            payload = response.read(_MAX_HTML_BYTES + 1)
            if not 0 < len(payload) <= _MAX_HTML_BYTES:
                receipt["reason"] = "body_empty_or_oversized"
                return receipt
            if length_header is not None and int(length_header) != len(payload):
                receipt["reason"] = "body_length_mismatch"
                return receipt
            receipt["content_length"] = len(payload)
            receipt["source_sha256"] = hashlib.sha256(payload).hexdigest()
            receipt["server_date_utc"] = _parse_server_date(response.headers.get("Date"))
            markers = analyze_public_html(payload)
            receipt["markers"] = markers
            if all(markers.values()):
                receipt["state"] = "PUBLIC_PAGE_OBSERVED_UNVERIFIED"
                receipt["reason"] = "public_content_markers_present_only"
            else:
                receipt["state"] = "CONTENT_UNVERIFIED"
                receipt["reason"] = "public_content_markers_missing"
    except error.HTTPError as exc:
        receipt["http_status"] = exc.code
        receipt["reason"] = "http_non_200"
    except (error.URLError, OSError, ValueError, UnicodeError, TimeoutError):
        # Redact exception details: they could contain a proxy URL or token.
        receipt["reason"] = "transport_unavailable"
    return receipt


def main() -> None:
    if len(sys.argv) != 1:
        raise SystemExit("no source URLs or request parameters accepted")
    print(json.dumps(observe_public_news(), sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
