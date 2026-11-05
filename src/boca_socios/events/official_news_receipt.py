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
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib import error, request

from .official_catalog import OfficialCatalogError, load_observed_notice

OFFICIAL_NEWS_URL = "https://www.bocajuniors.com.ar/noticias/boca-defensa-informacion-al-socio"
_MAX_HTML_BYTES = 1_000_000
_TIMEOUT_SECONDS = 8.0
_IGNORED_TAGS = frozenset({"head", "script", "style", "noscript", "svg", "template"})
_ART = timezone(timedelta(hours=-3))
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


def observe_public_news(
    *, now: datetime | None = None, with_offline_snapshot: bool = False
) -> dict[str, object]:
    """Single GET; optionally bind same ephemeral HTML bytes to offline JSONL.

    The optional JSONL is transport data for an isolated PR-only runner. It is
    NOT an official availability/feed assertion and must be split from the
    redacted receipt before uploading artifacts or writing job summaries.
    """
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
    if with_offline_snapshot:
        receipt.update(
            offline_snapshot_state="NO_EVENTOS_VERIFICADOS",
            offline_snapshot_reason="public_source_unavailable",
            offline_snapshot_jsonl=None,
        )
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
                if with_offline_snapshot:
                    # Import lazily: the pure article extractor uses the URL
                    # constant defined by this module; no secondary GET.
                    from .official_article_observation import build_boca_defensa_offline_jsonl
                    from .official_capture_binding import OfflineCaptureError

                    try:
                        receipt["offline_snapshot_jsonl"] = build_boca_defensa_offline_jsonl(
                            payload, observed_at=now
                        )
                        receipt["offline_snapshot_state"] = "EXTRACTED_UNVERIFIED"
                        receipt["offline_snapshot_reason"] = "public_article_fields_bound"
                    except OfflineCaptureError:
                        receipt["offline_snapshot_reason"] = "article_semantics_unverified"
            else:
                receipt["state"] = "CONTENT_UNVERIFIED"
                receipt["reason"] = "public_content_markers_missing"
                if with_offline_snapshot:
                    receipt["offline_snapshot_reason"] = "public_content_unverified"
    except error.HTTPError as exc:
        receipt["http_status"] = exc.code
        receipt["reason"] = "http_non_200"
    except (error.URLError, OSError, ValueError, UnicodeError, TimeoutError):
        # Redact exception details: they could contain a proxy URL or token.
        receipt["reason"] = "transport_unavailable"
    return receipt


def split_public_observation_envelope(
    envelope: Mapping[str, object],
) -> tuple[dict[str, object], str | None]:
    """Validate same-GET URL/SHA/time binding; redact JSONL from receipt.

    This is a pure artifact finalizer for an ephemeral Actions runner. It has
    no storage or network I/O and never upgrades an observation to eligibility.
    Invalid cross-file provenance fails rather than uploading a mismatched
    source receipt and event schedule.
    """
    if not isinstance(envelope, dict) or "offline_snapshot_jsonl" not in envelope:
        raise ValueError("public observation envelope absent")
    receipt = dict(envelope)
    jsonl = receipt.pop("offline_snapshot_jsonl")
    if (
        receipt.get("schema") != "boca-public-news-receipt-v1"
        or receipt.get("source_url") != OFFICIAL_NEWS_URL
        or receipt.get("request_count") != 1
        or receipt.get("redirects_followed") != 0
        or receipt.get("credentials_sent") is not False
        or receipt.get("actionable") is not False
        or receipt.get("availability_verified") is not False
        or receipt.get("feed_verified") is not False
        or receipt.get("state")
        not in ("PUBLIC_PAGE_OBSERVED_UNVERIFIED", "CONTENT_UNVERIFIED", "SOURCE_DEGRADED")
        or receipt.get("offline_snapshot_state")
        not in ("EXTRACTED_UNVERIFIED", "NO_EVENTOS_VERIFICADOS")
        or receipt.get("tls_policy") != "PYTHON_DEFAULT_CA_HOSTNAME_VERIFIED"
    ):
        raise ValueError("public observation receipt contract invalid")
    if jsonl is None:
        if receipt["offline_snapshot_state"] != "NO_EVENTOS_VERIFICADOS":
            raise ValueError("public observation source status contradictory")
        return receipt, None
    if (
        type(jsonl) is not str
        or not 0 < len(jsonl.encode("utf-8")) <= 16_384
        or jsonl.count("\n") != 1
        or not jsonl.endswith("\n")
        or "\r" in jsonl
        or receipt["offline_snapshot_state"] != "EXTRACTED_UNVERIFIED"
        or receipt["state"] != "PUBLIC_PAGE_OBSERVED_UNVERIFIED"
        or receipt.get("http_status") != 200
        or type(receipt.get("content_length")) is not int
        or not 0 < receipt["content_length"] <= _MAX_HTML_BYTES
    ):
        raise ValueError("public observation JSONL structure invalid")
    try:
        notice = load_observed_notice(jsonl[:-1])
        observed_utc = datetime.fromisoformat(str(receipt["observed_at_utc"]))
        if observed_utc.tzinfo is None or observed_utc.utcoffset() is None:
            raise ValueError("public observation timezone missing")
        article_observed = observed_utc.astimezone(_ART).replace(second=0, microsecond=0)
    except (OfficialCatalogError, TypeError, ValueError, OverflowError):
        raise ValueError("public observation data invalid") from None
    if (
        notice.source_url != receipt["source_url"]
        or notice.source_sha256 != receipt.get("source_sha256")
        or notice.observed_at != article_observed
        or len(notice.windows) != 5
        or notice.admission_channel_claim != "BOCA_SOCIOS"
        or notice.actionable is not False
    ):
        raise ValueError("public article SHA, URL or window provenance mismatch")
    return receipt, jsonl


def main() -> None:
    if sys.argv[1:] not in ([], ["--emit-offline-observation"]):
        raise SystemExit("no source URLs or request parameters accepted")
    print(
        json.dumps(
            observe_public_news(with_offline_snapshot=len(sys.argv) == 2),
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
