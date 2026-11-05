"""Public HTML capture binding remains entirely offline and unverified."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios.events.official_capture_binding import (
    OfflineCapture,
    OfflineCaptureError,
    build_official_snapshot_jsonl,
)
from boca_socios.events.official_catalog import load_observed_notice
from boca_socios.events.official_snapshot import OFFICIAL_SNAPSHOT_NAME, load_official_snapshot

FAKE_PUBLIC_HTML = b"""<!doctype html><html lang="es"><body><main><article>
<h1>Boca ante rival completamente ficticio</h1>
<p>November 3, 2026</p>
<p>El domingo 7 de noviembre de 2026 a las 17.30 horas se juega la simulacion.</p>
<p>Socios activos e interior: desde el 03/11 a las 13 hs.</p>
<p>Para esta simulacion el canal mencionado es Boca Socios, sin disponibilidad real.</p>
</article></main><script>NO ES PRUEBA DE HORARIOS</script></body></html>"""


def _claim(number: int = 1, *, capture: bytes = FAKE_PUBLIC_HTML) -> dict[str, object]:
    return {
        "version": "official-notice-observation-v2",
        "source_url": f"https://www.bocajuniors.com.ar/noticias/ejemplo-no-publicado-{number:02d}",
        "published_on": "2026-11-03",
        "observed_at": "2026-11-04T18:00:00-03:00",
        "source_sha256": hashlib.sha256(capture).hexdigest(),
        "event_key": f"partido-ficticio-{number:02d}",
        "title": "Boca ante rival completamente ficticio",
        "kickoff_at": "2026-11-07T17:30:00-03:00",
        "windows": [
            {
                "member_category": "activos_interior",
                "seat_area": "generales",
                "opens_at": "2026-11-03T13:00:00-03:00",
                "closes_at": None,
                "close_rule": "unspecified",
            }
        ],
        "admission_channel_claim": "BOCA_SOCIOS",
        "admission_channel_excerpt": (
            "Para esta simulacion el canal mencionado es Boca Socios, sin disponibilidad real."
        ),
    }


def _capture(number: int = 1, *, html: bytes = FAKE_PUBLIC_HTML) -> OfflineCapture:
    return OfflineCapture(
        source_html=html,
        notice_json=json.dumps(_claim(number, capture=html)),
        title_excerpt="Boca ante rival completamente ficticio",
        publication_excerpt="November 3, 2026",
        kickoff_excerpt="El domingo 7 de noviembre de 2026 a las 17.30 horas",
        window_excerpts=("Socios activos e interior: desde el 03/11 a las 13 hs.",),
    )


def test_capture_proof_bind_to_bytes_and_keep_no_operational_authority() -> None:
    lines = build_official_snapshot_jsonl((_capture(),))
    assert lines.endswith("\n") and lines.count("\n") == 1
    notice = load_observed_notice(lines.strip())
    assert notice.source_sha256 == hashlib.sha256(FAKE_PUBLIC_HTML).hexdigest()
    assert notice.verification_state == "SOURCE_OBSERVED_UNVERIFIED"
    assert notice.actionable is False
    assert notice.admission_channel_claim == "BOCA_SOCIOS"


def test_canonical_output_sorted_and_idempotent_without_file_io() -> None:
    captures = (_capture(2), _capture(1))
    result = build_official_snapshot_jsonl(captures)
    assert result == build_official_snapshot_jsonl(captures)
    records = [json.loads(line) for line in result.strip().split("\n")]
    assert [record["event_key"] for record in records] == [
        "partido-ficticio-01",
        "partido-ficticio-02",
    ]
    assert all("token" not in record and "password" not in record for record in records)


def test_empty_capture_selection_yields_empty_jsonl_without_fake_event() -> None:
    assert build_official_snapshot_jsonl(()) == ""


def test_generated_synthetic_jsonl_is_accepted_by_strict_offline_reader(tmp_path: Path) -> None:
    snapshot = tmp_path / OFFICIAL_SNAPSHOT_NAME
    snapshot.write_text(build_official_snapshot_jsonl((_capture(),)), encoding="utf-8")
    snapshot.chmod(0o600)
    notices = load_official_snapshot(snapshot)
    assert len(notices) == 1
    assert notices[0].verification_state == "SOURCE_OBSERVED_UNVERIFIED"
    assert notices[0].actionable is False


def test_unbound_or_tampered_capture_digest_is_rejected() -> None:
    capture = _capture()
    altered = replace(capture, source_html=FAKE_PUBLIC_HTML + b" ")
    with pytest.raises(OfflineCaptureError, match="digest"):
        build_official_snapshot_jsonl((altered,))


@pytest.mark.parametrize(
    ("field", "wrong_quote"),
    [
        ("title_excerpt", "un titulo ausente de esta captura"),
        ("publication_excerpt", "December 1, 2027"),
        ("kickoff_excerpt", "El domingo 20 de diciembre a las 20 horas"),
        ("window_excerpts", ("Socios adherentes desde el 05/11",)),
    ],
)
def test_unseen_claim_evidence_never_generates_jsonl(field: str, wrong_quote: object) -> None:
    capture = replace(_capture(), **{field: wrong_quote})
    with pytest.raises(OfflineCaptureError, match="excerpt"):
        build_official_snapshot_jsonl((capture,))


def test_script_only_html_text_does_not_count_as_source_evidence() -> None:
    only_script = (
        b"<html><body><script>Boca ante rival completamente ficticio"
        b" November 3, 2026 El domingo 7 de noviembre de 2026 a las 17.30 horas"
        b" Socios activos e interior: desde el 03/11 a las 13 hs."
        b" Para esta simulacion el canal mencionado es Boca Socios, sin disponibilidad real."
        b"</script><main>Otro texto distinto</main></body></html>"
    )
    capture = _capture(html=only_script)
    with pytest.raises(OfflineCaptureError, match="excerpt"):
        build_official_snapshot_jsonl((capture,))


@pytest.mark.parametrize(
    "hidden_fragment",
    [
        "<section hidden>Boca ante rival completamente ficticio</section>",
        '<section aria-hidden="true">Boca ante rival completamente ficticio</section>',
        '<section style="display: none">Boca ante rival completamente ficticio</section>',
    ],
)
def test_hidden_html_text_does_not_count_as_reviewable_evidence(hidden_fragment: str) -> None:
    html = FAKE_PUBLIC_HTML.replace(
        b"<h1>Boca ante rival completamente ficticio</h1>",
        hidden_fragment.encode("utf-8"),
    )
    with pytest.raises(OfflineCaptureError, match="excerpt"):
        build_official_snapshot_jsonl((_capture(html=html),))


def test_claim_title_must_be_supported_by_visible_title_excerpt() -> None:
    changed = json.loads(_capture().notice_json)
    changed["title"] = "Otra noticia ficticia que no figura en el titulo"
    with pytest.raises(OfflineCaptureError, match="title claim"):
        build_official_snapshot_jsonl((replace(_capture(), notice_json=json.dumps(changed)),))


def test_claimed_channel_must_also_appear_in_readable_source_text() -> None:
    html = FAKE_PUBLIC_HTML.replace(b"Boca Socios", b"canal no definido")
    capture = _capture(html=html)
    with pytest.raises(OfflineCaptureError, match="excerpt"):
        build_official_snapshot_jsonl((capture,))


def test_channel_or_source_contract_remains_fail_closed() -> None:
    capture = _capture()
    fake = json.loads(capture.notice_json)
    fake["admission_channel_claim"] = "LIVE_BOOKING"
    with pytest.raises(OfflineCaptureError):
        build_official_snapshot_jsonl((replace(capture, notice_json=json.dumps(fake)),))
    fake = json.loads(capture.notice_json)
    fake["source_url"] = "https://bocasocios.bocajuniors.com.ar/ingresar"
    with pytest.raises(OfflineCaptureError):
        build_official_snapshot_jsonl((replace(capture, notice_json=json.dumps(fake)),))


@pytest.mark.parametrize(
    "html",
    [b"", b"plain text only", b"\xff<main>invalid UTF8</main>", b"x" * 1_100_000],
)
def test_untrusted_capture_format_or_size_is_bounded(html: bytes) -> None:
    with pytest.raises(OfflineCaptureError):
        build_official_snapshot_jsonl((_capture(html=html),))


def test_duplicate_claims_and_twenty_first_capture_are_rejected() -> None:
    capture = _capture()
    with pytest.raises(OfflineCaptureError):
        build_official_snapshot_jsonl((capture, capture))
    with pytest.raises(OfflineCaptureError, match="capacity"):
        build_official_snapshot_jsonl(_capture(i) for i in range(1, 22))


def test_unbounded_producer_is_not_advanced_past_first_excess_capture() -> None:
    seen: list[int] = []

    def captures() -> object:
        for index in range(1, 30):
            seen.append(index)
            if index > 21:
                raise AssertionError("producer advanced beyond fixed budget")
            yield _capture(index)

    with pytest.raises(OfflineCaptureError, match="capacity"):
        build_official_snapshot_jsonl(captures())
    assert seen == list(range(1, 22))
