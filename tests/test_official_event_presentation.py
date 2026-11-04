"""Offline presentation of synthetic event notices, never Boca provider data."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from boca_socios.events.official_catalog import OfficialCatalogError, load_observed_notice
from boca_socios.events.official_presentation import (
    export_observed_catalog_json,
    render_observed_catalog_html,
)


def _notice(*, title: str = "Partido Sintético de Boca", key: str = "boca-ejemplo-2026"):
    return load_observed_notice(
        json.dumps(
            {
                "version": "official-notice-observation-v1",
                "source_url": "https://www.bocajuniors.com.ar/noticias/ejemplo-sintetico-no-publicado",
                "published_on": "2026-11-03",
                "observed_at": "2026-11-04T17:00:00-03:00",
                "source_sha256": "b" * 64,
                "event_key": key,
                "title": title,
                "kickoff_at": "2026-11-07T17:30:00-03:00",
                "windows": [
                    {
                        "member_category": "abonados",
                        "seat_area": "plateas",
                        "opens_at": "2026-11-03T14:00:00-03:00",
                        "closes_at": "2026-11-06T23:59:00-03:00",
                        "close_rule": "timestamp",
                    },
                    {
                        "member_category": "abono_solidario",
                        "seat_area": "plateas",
                        "opens_at": "2026-11-03T14:00:00-03:00",
                        "closes_at": None,
                        "close_rule": "stadium_open",
                    },
                ],
            }
        )
    )


def _cut() -> datetime:
    return datetime.fromisoformat("2026-11-04T18:35:00-03:00")


def test_offline_json_exports_source_observation_age_and_never_claims_live_feed() -> None:
    body = json.loads(export_observed_catalog_json([_notice()], at=_cut()))
    assert body["schema"] == "boca-official-observations-info-v1"
    assert body["source_mode"] == "OFFLINE_PREOBSERVED_ONLY"
    assert body["as_of_art"] == "2026-11-04T18:35:00-03:00"
    assert body["live_feed"] is False
    assert body["availability_verified"] is False
    assert body["admission_channel_verified"] is False
    assert body["actionable"] is False
    event = body["events"][0]
    assert event["source"]["url"].startswith("https://www.bocajuniors.com.ar/noticias/")
    assert event["source"]["published_on"] == "2026-11-03"
    assert event["source"]["observed_at"] == "2026-11-04T17:00:00-03:00"
    assert event["source"]["sha256_asserted"] == "b" * 64
    assert event["observation_age_minutes"] == 95
    assert event["verification_state"] == "SOURCE_OBSERVED_UNVERIFIED"
    assert event["phase"] == "UPCOMING_UNVERIFIED"
    assert event["actionable"] is False
    assert event["windows"][0]["exact_close_time_published"] is True
    assert event["windows"][1]["exact_close_time_published"] is False
    assert event["windows"][1]["closes_at"] is None


def test_accessible_html_fragment_has_provenance_legend_dates_and_no_commands() -> None:
    html = render_observed_catalog_html([_notice()], at=_cut())
    assert '<section aria-labelledby="boca-observed-catalog">' in html
    assert '<h2 id="boca-observed-catalog">' in html
    assert '<h3 id="boca-observed-boca-ejemplo-2026">' in html
    assert 'datetime="2026-11-04T17:00:00-03:00"' in html
    assert "hace 95 minutos" in html
    assert "sin verificación en vivo" in html
    assert "no verificado en vivo" in html
    assert "No confirma disponibilidad, elegibilidad" in html
    assert "El canal de admisión no está verificado" in html
    assert 'href="https://www.bocajuniors.com.ar/noticias/ejemplo-sintetico-no-publicado"' in html
    assert "Abonados — plateas" in html
    assert "23:59 ART" in html
    assert "apertura del estadio, sin hora exacta publicada" in html
    assert not any(unsafe in html.lower() for unsafe in ("<script", "<button", "<form", "<iframe"))


def test_html_escapes_untrusted_title_without_loss_of_source_caution() -> None:
    malicious = '<img src=x onerror="alert(1)"> Partido'
    html = render_observed_catalog_html([_notice(title=malicious)], at=_cut())
    assert "<img" not in html
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt; Partido" in html
    assert "sin verificación en vivo" in html


def test_empty_catalog_is_explicitly_not_a_live_source() -> None:
    json_body = json.loads(export_observed_catalog_json([], at=_cut()))
    assert json_body["events"] == []
    assert json_body["live_feed"] is False
    html = render_observed_catalog_html([], at=_cut())
    assert "No hay avisos oficiales observados cargados" in html
    assert "No confirma disponibilidad" in html


def test_observation_age_is_not_converted_to_freshness_or_operable_signal() -> None:
    notice = _notice()
    recent = json.loads(
        export_observed_catalog_json([notice], at=datetime.fromisoformat("2026-11-04T17:00-03:00"))
    )["events"][0]
    historical = json.loads(
        export_observed_catalog_json([notice], at=datetime.fromisoformat("2026-11-08T18:00-03:00"))
    )["events"][0]
    assert recent["observation_age_minutes"] == 0
    assert recent["verification_state"] == "SOURCE_OBSERVED_UNVERIFIED"
    assert historical["phase"] == "HISTORICAL"
    assert historical["observation_age_minutes"] > 4000
    assert historical["actionable"] is False
    assert "reference historical" not in render_observed_catalog_html([notice], at=_cut())
    assert "referencia histórica" in render_observed_catalog_html(
        [notice], at=datetime.fromisoformat("2026-11-08T18:00-03:00")
    )


def test_naive_and_pre_observation_clocks_rejected_consistently() -> None:
    notice = _notice()
    with pytest.raises(OfficialCatalogError):
        export_observed_catalog_json([notice], at=datetime.fromisoformat("2026-11-04T17:01"))
    with pytest.raises(OfficialCatalogError):
        render_observed_catalog_html(
            [notice], at=datetime.fromisoformat("2026-11-04T16:59:00-03:00")
        )


def test_duplicate_observations_cannot_be_displayed_as_two_matches() -> None:
    notice = _notice()
    with pytest.raises(OfficialCatalogError):
        export_observed_catalog_json([notice, notice], at=_cut())
    with pytest.raises(OfficialCatalogError):
        render_observed_catalog_html([notice, notice], at=_cut())
