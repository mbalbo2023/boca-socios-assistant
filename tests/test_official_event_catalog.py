"""Offline-only official-source envelope contract; all example facts are invented."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from boca_socios.events.official_catalog import (
    OfficialCatalogError,
    assess_official_notice,
    build_observed_catalog,
    load_observed_notice,
)

# Synthetic illustration only: this slug/match does not claim an actual Boca event.
ARTICLE = "https://www.bocajuniors.com.ar/noticias/ejemplo-sintetico-no-publicado"


def envelope() -> dict[str, object]:
    return {
        "version": "official-notice-observation-v1",
        "source_url": ARTICLE,
        "published_on": "2026-11-03",
        "observed_at": "2026-11-04T18:00:00-03:00",
        "source_sha256": "a" * 64,
        "event_key": "boca-partido-prueba-2026-11-07",
        "title": "Boca Juniors vs Rival Sintético",
        "kickoff_at": "2026-11-07T17:30:00-03:00",
        "windows": [
            {
                "member_category": "activos_interior",
                "seat_area": "generales",
                "opens_at": "2026-11-03T13:00:00-03:00",
                "closes_at": None,
                "close_rule": "unspecified",
            },
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


def encoded(document: dict[str, object] | None = None) -> str:
    return json.dumps(document or envelope(), ensure_ascii=False)


def test_official_notice_requires_provenance_and_is_not_an_actionable_match() -> None:
    notice = load_observed_notice(encoded())
    assert notice.source_url == ARTICLE
    assert notice.source_sha256 == "a" * 64
    assert notice.kickoff_at.isoformat() == "2026-11-07T17:30:00-03:00"
    assert len(notice.windows) == 3
    assert notice.windows[2].close_rule == "stadium_open"
    assert notice.windows[2].closes_at is None
    assert notice.verification_state == "SOURCE_OBSERVED_UNVERIFIED"
    assert notice.actionable is False
    assert notice.admission_channel_claim == "UNKNOWN"  # v1 defaults fail-closed
    assert notice.admission_channel_excerpt is None
    projection = assess_official_notice(notice, at=datetime.fromisoformat("2026-11-04T19:00-03:00"))
    assert projection.phase == "UPCOMING_UNVERIFIED"
    assert projection.actionable is False
    assert projection.windows_count == 3


def test_elapsed_event_is_not_promoted_to_live_or_fresh() -> None:
    notice = load_observed_notice(encoded())
    later = assess_official_notice(notice, at=datetime.fromisoformat("2026-11-08T20:00-03:00"))
    assert later.phase == "HISTORICAL"
    assert later.actionable is False


def test_pre_observation_query_refuses_false_timestamp_provenance() -> None:
    notice = load_observed_notice(encoded())
    with pytest.raises(OfficialCatalogError):
        assess_official_notice(notice, at=datetime.fromisoformat("2026-11-04T17:00-03:00"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_url", "https://bocajuniors.com.ar.evil.example/noticias/partido"),
        ("source_url", "http://www.bocajuniors.com.ar/noticias/partido"),
        ("source_url", "https://www.bocajuniors.com.ar:443/noticias/partido"),
        ("source_url", "https://www.bocajuniors.com.ar/noticias/partido?q=x"),
        ("source_url", "https://www.bocajuniors.com.ar/noticias/partido\n"),
        ("source_url", "https://[invalid-ipv6/noticias/partido"),
        ("source_url", "https://www.bocajuniors.com.ar/ingresar"),
        ("source_url", "https://www.bocajuniors.com.ar/noticias/partido#fragment"),
        ("source_sha256", "digest-missing"),
        ("published_on", "ayer"),
        ("observed_at", "2026-11-04T18:00:00"),
        ("observed_at", "2026-11-02T17:00:00-03:00"),
        ("observed_at", "2026-11-04 18:00:00-03:00"),
        ("kickoff_at", "2026-11-07T17:30:00Z"),
        ("kickoff_at", "2026-11-07T17:30:00"),
        ("event_key", "../danger"),
        ("title", ""),
    ],
)
def test_external_source_bypasses_or_incomplete_facts_fail_closed(
    field: str, value: object
) -> None:
    raw = envelope()
    raw[field] = value
    with pytest.raises(OfficialCatalogError):
        load_observed_notice(encoded(raw))


@pytest.mark.parametrize(
    "change",
    [
        {"member_category": "no_identificado"},
        {"seat_area": "vip"},
        {"opens_at": "2026-11-08T13:00:00-03:00"},
        {"opens_at": "2026-11-03T13:00:00Z"},
        {"closes_at": "2026-11-03T12:00:00-03:00", "close_rule": "timestamp"},
        {"closes_at": None, "close_rule": "timestamp"},
        {"closes_at": "2026-11-04T12:00:00-03:00", "close_rule": "unspecified"},
        {"close_rule": "automatic_purchase"},
    ],
)
def test_category_schedule_ambiguity_or_unsound_bounds_fail_closed(
    change: dict[str, object],
) -> None:
    raw = envelope()
    windows = raw["windows"]
    assert isinstance(windows, list)
    windows[0].update(change)
    with pytest.raises(OfficialCatalogError):
        load_observed_notice(encoded(raw))


def test_duplicate_category_sector_and_unknown_fields_rejected() -> None:
    raw = envelope()
    windows = raw["windows"]
    assert isinstance(windows, list)
    windows.append(dict(windows[0]))
    with pytest.raises(OfficialCatalogError):
        load_observed_notice(encoded(raw))
    raw = envelope()
    raw["token"] = "should-never-go-here"
    with pytest.raises(OfficialCatalogError):
        load_observed_notice(encoded(raw))


def test_duplicate_json_keys_and_nonfinite_numbers_rejected() -> None:
    raw = encoded()
    with pytest.raises(OfficialCatalogError):
        load_observed_notice(raw.replace('"version":', '"version":"shadow", "version":', 1))
    with pytest.raises(OfficialCatalogError):
        load_observed_notice(raw.replace('"windows":', '"untrusted": NaN, "windows":', 1))


def test_size_count_and_timestamp_limits_bounded() -> None:
    with pytest.raises(OfficialCatalogError):
        load_observed_notice("x" * 20_000)
    with pytest.raises(OfficialCatalogError):
        load_observed_notice("\ud800")
    raw = envelope()
    windows = raw["windows"]
    assert isinstance(windows, list)
    windows.extend(dict(windows[0], member_category="adherentes") for _ in range(20))
    with pytest.raises(OfficialCatalogError):
        load_observed_notice(encoded(raw))
    notice = load_observed_notice(encoded())
    future = notice.observed_at + timedelta(days=1)
    assert assess_official_notice(notice, at=future).phase == "UPCOMING_UNVERIFIED"
    with pytest.raises(OfficialCatalogError):
        assess_official_notice(notice, at=datetime.now(UTC).replace(tzinfo=None))


def test_empty_windows_are_honestly_unknown_not_open_for_admission() -> None:
    raw = envelope()
    raw["windows"] = []
    notice = load_observed_notice(encoded(raw))
    assert notice.windows == ()
    assert (
        assess_official_notice(notice, at=datetime.fromisoformat("2026-11-04T19:00-03:00")).phase
        == "UPCOMING_UNVERIFIED"
    )
    assert notice.actionable is False


def test_multiple_observations_ordered_without_promoting_to_operable_events() -> None:
    later = envelope()
    later["event_key"] = "boca-prueba-segunda-2026-11-08"
    later["source_url"] = "https://www.bocajuniors.com.ar/noticias/segundo-ejemplo-sintetico"
    later["kickoff_at"] = "2026-11-08T17:30:00-03:00"
    catalog = build_observed_catalog(
        (load_observed_notice(encoded(later)), load_observed_notice(encoded()))
    )
    assert tuple(item.event_key for item in catalog) == (
        "boca-partido-prueba-2026-11-07",
        "boca-prueba-segunda-2026-11-08",
    )
    assert all(item.actionable is False for item in catalog)


def test_catalog_deduplication_and_size_gate_are_fail_closed() -> None:
    notice = load_observed_notice(encoded())
    with pytest.raises(OfficialCatalogError):
        build_observed_catalog((notice, notice))
    with pytest.raises(OfficialCatalogError):
        build_observed_catalog(notice for _ in range(21))


def test_catalog_limit_stops_reading_source_at_first_excess_item() -> None:
    notice = load_observed_notice(encoded())
    seen = 0

    def oversized_stream():
        nonlocal seen
        for _ in range(21):
            seen += 1
            yield notice
        raise AssertionError("catalog consumed beyond the bounded 21st observation")

    with pytest.raises(OfficialCatalogError, match="bounded capacity"):
        build_observed_catalog(oversized_stream())
    assert seen == 21


@pytest.mark.parametrize(
    ("channel", "excerpt"),
    [
        (
            "BOCA_SOCIOS",
            "Las socias y los socios deberán adquirir su adicional a través de Boca Socios.",
        ),
        (
            "CONMEBOL",
            "La Conmebol abrirá la venta prioritaria exclusivamente por su plataforma de tickets.",
        ),
        ("UNKNOWN", None),
    ],
)
def test_v2_channel_claim_is_only_a_source_excerpt_assertion(
    channel: str, excerpt: str | None
) -> None:
    raw = envelope()
    raw.update(
        {
            "version": "official-notice-observation-v2",
            "admission_channel_claim": channel,
            "admission_channel_excerpt": excerpt,
        }
    )
    notice = load_observed_notice(encoded(raw))
    assert notice.admission_channel_claim == channel
    assert notice.admission_channel_excerpt == excerpt
    assert notice.verification_state == "SOURCE_OBSERVED_UNVERIFIED"
    assert notice.actionable is False


@pytest.mark.parametrize(
    ("channel", "excerpt"),
    [
        ("BOCA_SOCIOS", None),
        ("BOCA_SOCIOS", "Sólo por una plataforma del tercero, sin nombre público"),
        ("CONMEBOL", "Sólo plataforma externa, club independiente"),
        ("CONMEBOL", "Conmebol habilita la venta de entradas, sin más detalles"),
        ("BOCA_SOCIOS", "Boca Socios o Conmebol: todavía sin definir la plataforma."),
        ("CONMEBOL", "Conmebol y Boca Socios: plataforma de admisión sin aclarar."),
        ("UNKNOWN", "A través de Boca Socios exclusivamente."),
        ("UNKNOWN", ""),
        ("FAKE_PLATFORM", "A través de Fake Platform"),
    ],
)
def test_v2_rejects_channel_claims_without_bounded_consistent_quote(
    channel: str, excerpt: str | None
) -> None:
    raw = envelope()
    raw.update(
        {
            "version": "official-notice-observation-v2",
            "admission_channel_claim": channel,
            "admission_channel_excerpt": excerpt,
        }
    )
    with pytest.raises(OfficialCatalogError):
        load_observed_notice(encoded(raw))


def test_v1_rejects_injected_channel_and_v2_requires_complete_claim() -> None:
    raw = envelope()
    raw["admission_channel_claim"] = "BOCA_SOCIOS"
    with pytest.raises(OfficialCatalogError):
        load_observed_notice(encoded(raw))
    raw["version"] = "official-notice-observation-v2"
    with pytest.raises(OfficialCatalogError):
        load_observed_notice(encoded(raw))
