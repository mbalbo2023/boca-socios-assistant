"""All HTML fixtures are synthetic; no network or official capture is performed."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from boca_socios.events.official_article_observation import build_boca_defensa_offline_jsonl
from boca_socios.events.official_capture_binding import OfflineCaptureError
from boca_socios.events.official_catalog import load_observed_notice
from boca_socios.events.official_news_receipt import OFFICIAL_NEWS_URL


def _fixture() -> bytes:
    return (
        "<html><body><h1>Boca-Defensa: Información al socio</h1>"
        "<p>November 3, 2026</p>"
        "<p>Boca vuelve a jugar en casa este sábado 7 de noviembre a las "
        "17.30 hs ante Defensa y Justicia por la fecha 16 del Torneo Clausura.</p>"
        "<p>Para alentar al equipo desde la tribuna, las socias y los socios "
        "deberán adquirir su adicional a través de Boca Socios, de acuerdo "
        "con el siguiente cronograma.</p>"
        "<h2>GENERALES</h2>"
        "<p>Socios activos e interior: desde el 03/11 a las 13 hs.</p>"
        "<p>Socios adherentes: desde el 04/11 a las 17 hs.</p>"
        "<h2>PLATEAS</h2>"
        "<p>Confirmación de abonados: desde el 03/11 a las 14 hs "
        "hasta el 06/11 a las 23:59 hs.</p>"
        "<p>Abono solidario: desde el 03/11 a las 14 hs "
        "hasta la apertura del estadio.</p>"
        "<h2>SOCIOS VITALICIOS</h2>"
        "<p>Reserva de plateas y generales: desde el 04/11 a las 14 hs.</p>"
        "</body></html>"
    ).encode()


_OBSERVED = datetime(2026, 11, 5, 11, 13, 59, tzinfo=UTC)


def test_offline_extractor_preserves_five_public_windows_without_actionability() -> None:
    source = _fixture()
    jsonl = build_boca_defensa_offline_jsonl(source, observed_at=_OBSERVED)
    assert jsonl.endswith("\n") and jsonl.count("\n") == 1
    claim = json.loads(jsonl)
    notice = load_observed_notice(jsonl.strip())
    assert claim["version"] == "official-notice-observation-v2"
    assert claim["source_url"] == OFFICIAL_NEWS_URL
    assert claim["observed_at"] == "2026-11-05T08:13-03:00"
    assert notice.verification_state == "SOURCE_OBSERVED_UNVERIFIED"
    assert notice.actionable is False
    assert notice.admission_channel_claim == "BOCA_SOCIOS"
    assert [(w.member_category, w.seat_area, w.close_rule) for w in notice.windows] == [
        ("activos_interior", "generales", "unspecified"),
        ("adherentes", "generales", "unspecified"),
        ("abonados", "plateas", "timestamp"),
        ("abono_solidario", "plateas", "stadium_open"),
        ("vitalicios", "plateas_y_generales", "unspecified"),
    ]
    assert notice.windows[2].closes_at.isoformat() == "2026-11-06T23:59:00-03:00"
    assert notice.windows[3].closes_at is None
    assert len(notice.source_sha256) == 64


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("desde el 03/11 a las 13 hs", "desde el 03/11 a las 30 hs"),
        ("7 de noviembre", "8 de noviembre"),
        ("17.30 hs", "19.30 hs"),
        ("November 3, 2026", "November 4, 2026"),
        ("Boca Socios", "CONMEBOL"),
        ("hasta la apertura del estadio", "hasta el cierre"),
        ("hasta el 06/11 a las 23:59 hs", "hasta el 06/11 a las 32:59 hs"),
        ("h2>PLATEAS", "h2>GENERALS"),
        ("Socios adherentes: desde", "Socios adherentes: hasta"),
        ("<h2>SOCIOS VITALICIOS</h2>", ""),
    ],
)
def test_changed_or_ambiguous_official_article_does_not_invent_schedule(old: str, new: str) -> None:
    source = _fixture().decode("utf-8").replace(old, new)
    with pytest.raises(OfflineCaptureError):
        build_boca_defensa_offline_jsonl(source.encode("utf-8"), observed_at=_OBSERVED)


def test_duplicate_window_or_shuffled_sections_does_not_pass() -> None:
    source = _fixture().decode("utf-8")
    duplicate = source.replace(
        "<h2>PLATEAS</h2>",
        "<p>Socios activos e interior: desde el 03/11 a las 13 hs.</p><h2>PLATEAS</h2>",
    )
    with pytest.raises(OfflineCaptureError):
        build_boca_defensa_offline_jsonl(duplicate.encode(), observed_at=_OBSERVED)
    shuffled = source.replace(
        "<p>Socios adherentes: desde el 04/11 a las 17 hs.</p>",
        "<p>Reserva de plateas y generales: desde el 04/11 a las 14 hs.</p>",
    )
    with pytest.raises(OfflineCaptureError):
        build_boca_defensa_offline_jsonl(shuffled.encode(), observed_at=_OBSERVED)


def test_script_or_hidden_fields_are_not_visible_source_evidence() -> None:
    source = _fixture().decode("utf-8")
    phrase = "<p>Socios adherentes: desde el 04/11 a las 17 hs.</p>"
    scripts = source.replace(phrase, "<script>" + phrase + "</script>")
    with pytest.raises(OfflineCaptureError):
        build_boca_defensa_offline_jsonl(scripts.encode(), observed_at=_OBSERVED)
    hidden = source.replace(phrase, "<p hidden>Socios adherentes: desde el 04/11 a las 17 hs.</p>")
    with pytest.raises(OfflineCaptureError):
        build_boca_defensa_offline_jsonl(hidden.encode(), observed_at=_OBSERVED)


@pytest.mark.parametrize(
    ("body", "clock"),
    [
        (b"", _OBSERVED),
        (b"\xff", _OBSERVED),
        (b"x" * 1_000_001, _OBSERVED),
        (_fixture(), datetime(2026, 11, 5, 11, 13)),
        (_fixture(), datetime(2026, 11, 2, 11, 13, tzinfo=UTC)),
    ],
)
def test_rejects_invalid_input_bounds_clock_and_prepublication(
    body: bytes, clock: datetime
) -> None:
    with pytest.raises(OfflineCaptureError):
        build_boca_defensa_offline_jsonl(body, observed_at=clock)


def test_result_does_not_publish_real_credentials_or_trigger_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _deny(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("unexpected network request")

    monkeypatch.setattr("socket.socket.connect", _deny)
    result = build_boca_defensa_offline_jsonl(_fixture(), observed_at=_OBSERVED)
    assert "password" not in result
    assert "ticket_intent" not in result
    assert "availability_verified" not in result
