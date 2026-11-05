"""Synthetic, zero-network checks for one anonymous public club-news GET."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from urllib import request

import pytest

from boca_socios.events.official_catalog import load_observed_notice
from boca_socios.events.official_news_receipt import (
    OFFICIAL_NEWS_URL,
    _NoRedirect,
    analyze_public_html,
    observe_public_news,
    split_public_observation_envelope,
)

SYNTHETIC_ARTICLE = b"""<!doctype html><html><head>
<script>NO usar guiones en pruebas</script></head><body><main>
<h1>Boca-Defensa: Informacion al socio</h1><time>November 3, 2026</time>
<p>Se anuncia el 7 de noviembre a las 17.30, en una prueba inventada.</p>
<p>El adicional a traves de Boca Socios corresponde a un ensayo imaginario.</p>
<h2>GENERALES</h2><p>Socios activos e interior desde 03/11 13 hs.</p>
<p>Socios adherentes desde 04/11 17 hs.</p>
<h2>PLATEAS</h2><p>Confirmacion de abonados hasta 06/11 23:59 hs.</p>
<p>Abono solidario hasta la apertura del estadio.</p>
<h2>SOCIOS VITALICIOS</h2><p>Desde 04/11 14 hs.</p>
</main></body></html>"""
SYNTHETIC_MAIN = SYNTHETIC_ARTICLE.split(b"<main>", 1)[1].split(b"</main>", 1)[0]

SYNTHETIC_REVIEWED_ARTICLE = (
    "<html><body><h1>Boca-Defensa: Información al socio</h1>"
    "<p>November 3, 2026</p>"
    "<p>Boca vuelve a jugar en casa este sábado 7 de noviembre a las 17.30 hs "
    "ante Defensa y Justicia por la fecha 16 del Torneo Clausura.</p>"
    "<p>Para alentar al equipo desde la tribuna, las socias y los socios deberán "
    "adquirir su adicional a través de Boca Socios, de acuerdo con el siguiente "
    "cronograma.</p>"
    "<h2>GENERALES</h2>"
    "<p>Socios activos e interior: desde el 03/11 a las 13 hs.</p>"
    "<p>Socios adherentes: desde el 04/11 a las 17 hs.</p>"
    "<h2>PLATEAS</h2>"
    "<p>Confirmación de abonados: desde el 03/11 a las 14 hs "
    "hasta el 06/11 a las 23:59 hs.</p>"
    "<p>Abono solidario: desde el 03/11 a las 14 hs hasta la apertura del estadio.</p>"
    "<h2>SOCIOS VITALICIOS</h2>"
    "<p>Reserva de plateas y generales: desde el 04/11 a las 14 hs.</p>"
    "</body></html>"
).encode()


class _FakeResponse:
    def __init__(self, content: bytes, *, status: int = 200, final_url: str = OFFICIAL_NEWS_URL):
        self._content = content
        self.status = status
        self._final_url = final_url
        self.read_count = 0
        self.headers = Message()
        self.headers.add_header("Content-Type", "text/html; charset=utf-8")
        self.headers.add_header("Content-Length", str(len(content)))
        self.headers.add_header("Date", "Thu, 05 Nov 2026 04:00:00 GMT")

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, amount: int) -> bytes:
        assert amount <= 1_000_001
        self.read_count += 1
        return self._content[:amount]

    def geturl(self) -> str:
        return self._final_url


def test_single_public_https_get_receipt_has_real_byte_digest_and_no_private_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_response = _FakeResponse(SYNTHETIC_ARTICLE)
    intercepted: list[request.Request] = []
    handlers: list[object] = []

    class FakeOpener:
        def open(self, url: request.Request, *, timeout: float) -> _FakeResponse:
            intercepted.append(url)
            assert 0 < timeout <= 10
            return fake_response

    def fake_build_opener(*args: object) -> FakeOpener:
        handlers.extend(args)
        return FakeOpener()

    monkeypatch.setattr(request, "build_opener", fake_build_opener)
    result = observe_public_news(now=datetime(2026, 11, 5, 4, 0, tzinfo=UTC))
    assert result["state"] == "PUBLIC_PAGE_OBSERVED_UNVERIFIED"
    assert result["source_sha256"] == hashlib.sha256(SYNTHETIC_ARTICLE).hexdigest()
    assert result["content_length"] == len(SYNTHETIC_ARTICLE)
    assert result["request_count"] == 1 and fake_response.read_count == 1
    assert len(intercepted) == 1 and intercepted[0].full_url == OFFICIAL_NEWS_URL
    assert intercepted[0].get_header("Cookie") is None
    assert intercepted[0].get_header("Authorization") is None
    assert any(
        isinstance(handler, request.ProxyHandler) and not handler.proxies for handler in handlers
    )
    assert any(isinstance(handler, request.HTTPSHandler) for handler in handlers)
    assert any(isinstance(handler, _NoRedirect) for handler in handlers)
    assert "texto" not in result and "html" not in result
    assert result["actionable"] is False and result["feed_verified"] is False
    json.dumps(result)


def test_changed_content_is_reported_without_any_false_availability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeOpener:
        def open(self, _url: request.Request, *, timeout: float) -> _FakeResponse:
            return _FakeResponse(b"<html><body>Otra noticia publica.</body></html>")

    monkeypatch.setattr(request, "build_opener", lambda *_handlers: FakeOpener())
    result = observe_public_news(now=datetime(2026, 11, 5, 4, 0, tzinfo=UTC))
    assert result["state"] == "CONTENT_UNVERIFIED"
    assert result["source_sha256"] is not None
    assert any(not present for present in result["markers"].values())
    assert result["actionable"] is False


@pytest.mark.parametrize(
    "bad_document",
    [
        b"<html><body><script>" + SYNTHETIC_MAIN + b"</script></body></html>",
        b"<html><body><main hidden>" + SYNTHETIC_MAIN + b"</main></body></html>",
        b"\xff<html><body>Malformed source.</body></html>",
        b"not html",
    ],
)
def test_only_visible_utf8_html_body_can_support_markers(bad_document: bytes) -> None:
    assert not all(analyze_public_html(bad_document).values())


def test_redirect_handler_denies_all_redirects_without_followup() -> None:
    redirected = _NoRedirect().redirect_request(
        request.Request(OFFICIAL_NEWS_URL),  # noqa: S310 - fixed official HTTPS URL
        None,
        302,
        "found",
        SimpleNamespace(),
        "https://bocasocios.bocajuniors.com.ar/login",
    )
    assert redirected is None


def test_oversized_response_or_changed_location_is_explicit_degradation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeOpener:
        def __init__(self, response: _FakeResponse) -> None:
            self.response = response

        def open(self, _url: request.Request, *, timeout: float) -> _FakeResponse:
            return self.response

    for broken in [
        _FakeResponse(b"x" * 1_000_002),
        _FakeResponse(SYNTHETIC_ARTICLE, final_url="https://example.org/fake"),
    ]:
        monkeypatch.setattr(
            request, "build_opener", lambda *_handlers, capture=broken: FakeOpener(capture)
        )
        receipt = observe_public_news(now=datetime(2026, 11, 5, 4, 0, tzinfo=UTC))
        assert receipt["state"] == "SOURCE_DEGRADED"
        assert receipt["actionable"] is False
        assert receipt["source_sha256"] is None


def test_failed_network_does_not_expose_exception_or_fake_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeOpener:
        def open(self, _url: request.Request, *, timeout: float) -> _FakeResponse:
            raise OSError("Secret token ABC123 must never be logged")

    monkeypatch.setattr(request, "build_opener", lambda *_handlers: FakeOpener())
    receipt = observe_public_news(now=datetime(2026, 11, 5, 4, 0, tzinfo=UTC))
    assert receipt["state"] == "SOURCE_DEGRADED"
    assert receipt["reason"] == "transport_unavailable"
    assert receipt["source_sha256"] is None
    assert "ABC123" not in json.dumps(receipt)


def test_one_public_get_mints_matching_redacted_receipt_and_nonactionable_jsonl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _FakeResponse(SYNTHETIC_REVIEWED_ARTICLE)
    calls = 0

    class FakeOpener:
        def open(self, requested: request.Request, *, timeout: float) -> _FakeResponse:
            nonlocal calls
            calls += 1
            assert requested.full_url == OFFICIAL_NEWS_URL and 0 < timeout <= 8
            return response

    monkeypatch.setattr(request, "build_opener", lambda *_handlers: FakeOpener())
    envelope = observe_public_news(
        now=datetime(2026, 11, 5, 4, 22, 37, tzinfo=UTC), with_offline_snapshot=True
    )
    redacted, jsonl = split_public_observation_envelope(envelope)
    assert calls == 1 and response.read_count == 1
    assert redacted["state"] == "PUBLIC_PAGE_OBSERVED_UNVERIFIED"
    assert redacted["offline_snapshot_state"] == "EXTRACTED_UNVERIFIED"
    assert "offline_snapshot_jsonl" not in redacted
    assert jsonl is not None and jsonl.endswith("\n") and jsonl.count("\n") == 1
    assert len(jsonl.encode()) < 16_384
    notice = json.loads(jsonl)
    assert notice["source_url"] == redacted["source_url"] == OFFICIAL_NEWS_URL
    assert notice["source_sha256"] == redacted["source_sha256"]
    assert notice["observed_at"] == "2026-11-05T01:22-03:00"
    assert load_observed_notice(jsonl.strip()).actionable is False
    assert notice["admission_channel_claim"] == "BOCA_SOCIOS"
    assert len(notice["windows"]) == 5
    assert redacted["availability_verified"] is False
    assert redacted["feed_verified"] is False


def test_non_matching_official_public_page_yields_receipt_but_no_jsonl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeOpener:
        def open(self, _requested: request.Request, *, timeout: float) -> _FakeResponse:
            return _FakeResponse(SYNTHETIC_ARTICLE)

    monkeypatch.setattr(request, "build_opener", lambda *_handlers: FakeOpener())
    report = observe_public_news(
        now=datetime(2026, 11, 5, 4, 22, tzinfo=UTC), with_offline_snapshot=True
    )
    receipt, jsonl = split_public_observation_envelope(report)
    assert receipt["state"] == "PUBLIC_PAGE_OBSERVED_UNVERIFIED"
    assert receipt["offline_snapshot_state"] == "NO_EVENTOS_VERIFICADOS"
    assert receipt["offline_snapshot_reason"] == "article_semantics_unverified"
    assert jsonl is None


def test_invalid_artifact_binding_is_rejected_not_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeOpener:
        def open(self, _requested: request.Request, *, timeout: float) -> _FakeResponse:
            return _FakeResponse(SYNTHETIC_REVIEWED_ARTICLE)

    monkeypatch.setattr(request, "build_opener", lambda *_handlers: FakeOpener())
    report = observe_public_news(
        now=datetime(2026, 11, 5, 4, 22, tzinfo=UTC), with_offline_snapshot=True
    )
    for change in (
        {"source_sha256": "0" * 64},
        {"source_url": "https://evil.invalid/news"},
        {"observed_at_utc": "2026-11-04T04:22:00+00:00"},
        {"availability_verified": True},
        {"state": "SOURCE_DEGRADED"},
    ):
        with pytest.raises(ValueError):
            split_public_observation_envelope({**report, **change})
    malformed = {**report, "offline_snapshot_jsonl": "{garbage}\n"}
    with pytest.raises(ValueError):
        split_public_observation_envelope(malformed)


def test_public_artifact_workflow_one_get_two_bounded_files_never_host() -> None:
    workflow = Path(".github/workflows/boca-official-news-receipt.yml").read_text(encoding="utf-8")
    assert "--emit-offline-observation" in workflow
    assert "boca-official-news-catalog.jsonl" in workflow
    assert "split_public_observation_envelope" in workflow
    assert "src/boca_socios/events/official_article_observation.py" in workflow
    assert "tests/test_official_news_receipt.py" in workflow
    assert "  workflow_dispatch:" not in workflow and "  schedule:" not in workflow
    assert "boca-first-deploy" not in workflow and "ssh " not in workflow


def test_diagnostic_workflow_has_only_pr_runner_scope_and_no_host_dispatch() -> None:
    workflow = Path(".github/workflows/boca-official-news-receipt.yml").read_text(encoding="utf-8")
    assert "  pull_request:" in workflow
    assert "  workflow_dispatch:" not in workflow
    assert "  push:" not in workflow
    assert "  schedule:" not in workflow
    assert "    runs-on: ubuntu-24.04" in workflow
    assert "      contents: write" not in workflow
    assert "      id-token: write" not in workflow
    assert "    environment:" not in workflow
    assert "github.event.pull_request.head.repo.full_name == github.repository" in workflow
    assert "python3 -m boca_socios.events.official_news_receipt" in workflow
    assert "boca-first-deploy" not in workflow
    assert "ssh " not in workflow
