"""Offline import acceptance: synthetic bytes, disposable owner directory, no host."""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios.events.host_official_notice_import import (
    OfficialImportError,
    ReviewedOfficialArtifactPin,
    hold_official_snapshot_replace_lease,
    import_reviewed_official_artifact,
)
from boca_socios.events.official_news_receipt import OFFICIAL_NEWS_URL
from boca_socios.events.official_snapshot import OFFICIAL_SNAPSHOT_NAME, load_official_snapshot

_UTC_OBSERVED = "2026-11-05T12:41:50.606388+00:00"
_SOURCE_SHA = "b" * 64  # Entirely fictional test source, NOT the real article receipt.
_ARTICLE = "Boca-Defensa: Información al socio"
_OTHER_EXCERPT = (
    "Las socias y los socios deberán adquirir su adicional a través de Boca Socios, "
    "de acuerdo con el siguiente cronograma revisado"
)


def _notice(*, title: str = _ARTICLE) -> dict[str, object]:
    return {
        "version": "official-notice-observation-v2",
        "source_url": OFFICIAL_NEWS_URL,
        "published_on": "2026-11-03",
        "observed_at": "2026-11-05T09:41-03:00",
        "source_sha256": _SOURCE_SHA,
        "event_key": "boca-defensa-y-justicia-20261107",
        "title": title,
        "kickoff_at": "2026-11-07T17:30-03:00",
        "windows": [
            {
                "member_category": category,
                "seat_area": area,
                "opens_at": opens,
                "closes_at": closes,
                "close_rule": rule,
            }
            for category, area, opens, closes, rule in (
                ("activos_interior", "generales", "2026-11-03T13:00-03:00", None, "unspecified"),
                ("adherentes", "generales", "2026-11-04T17:00-03:00", None, "unspecified"),
                (
                    "abonados",
                    "plateas",
                    "2026-11-03T14:00-03:00",
                    "2026-11-06T23:59-03:00",
                    "timestamp",
                ),
                (
                    "abono_solidario",
                    "plateas",
                    "2026-11-03T14:00-03:00",
                    None,
                    "stadium_open",
                ),
                (
                    "vitalicios",
                    "plateas_y_generales",
                    "2026-11-04T14:00-03:00",
                    None,
                    "unspecified",
                ),
            )
        ],
        "admission_channel_claim": "BOCA_SOCIOS",
        "admission_channel_excerpt": (
            "Las socias y los socios deberán adquirir su adicional a través de Boca Socios, "
            "de acuerdo con el siguiente cronograma"
        ),
    }


def _fixture(
    *,
    title: str = _ARTICLE,
    notice_changes: dict[str, object] | None = None,
    receipt_changes: dict[str, object] | None = None,
    extra_entries: dict[str, bytes] | None = None,
) -> tuple[bytes, ReviewedOfficialArtifactPin, bytes]:
    notice = {**_notice(title=title), **(notice_changes or {})}
    jsonl = (json.dumps(notice, sort_keys=True, ensure_ascii=False) + "\n").encode()
    receipt: dict[str, object] = {
        "schema": "boca-public-news-receipt-v1",
        "source_url": OFFICIAL_NEWS_URL,
        "observed_at_utc": _UTC_OBSERVED,
        "http_status": 200,
        "content_length": 76_355,
        "source_sha256": _SOURCE_SHA,
        "server_date_utc": None,
        "state": "PUBLIC_PAGE_OBSERVED_UNVERIFIED",
        "reason": "public_content_markers_present_only",
        "markers": {
            key: True
            for key in (
                "article_title",
                "published_date",
                "kickoff_date",
                "kickoff_time",
                "channel_mention",
                "active_category",
                "adherent_category",
                "subscribed_category",
                "solidarity_category",
                "vital_category",
                "stated_deadline",
            )
        },
        "request_count": 1,
        "tls_policy": "PYTHON_DEFAULT_CA_HOSTNAME_VERIFIED",
        "redirects_followed": 0,
        "credentials_sent": False,
        "feed_verified": False,
        "availability_verified": False,
        "actionable": False,
        "offline_snapshot_state": "EXTRACTED_UNVERIFIED",
        "offline_snapshot_reason": "public_article_fields_bound",
    }
    receipt.update(receipt_changes or {})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "boca-official-news-receipt.json", json.dumps(receipt, sort_keys=True).encode()
        )
        archive.writestr("boca-official-news-catalog.jsonl", jsonl)
        for name, payload in (extra_entries or {}).items():
            archive.writestr(name, payload)
    blob = buffer.getvalue()
    pin = ReviewedOfficialArtifactPin(
        artifact_url=(
            "https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/"
            "42029320757/artifacts/13414624349"
        ),
        artifact_sha256=hashlib.sha256(blob).hexdigest(),
        snapshot_sha256=hashlib.sha256(jsonl).hexdigest(),
        source_url=OFFICIAL_NEWS_URL,
        source_sha256=_SOURCE_SHA,
        observed_at_utc=_UTC_OBSERVED,
    )
    return blob, pin, jsonl


def _call(tmp_path: Path, blob: bytes, pin: ReviewedOfficialArtifactPin) -> object:
    return import_reviewed_official_artifact(tmp_path, artifact_zip=blob, reviewed_pin=pin)


def _target(tmp_path: Path) -> Path:
    return tmp_path / OFFICIAL_SNAPSHOT_NAME


def _no_staging_residue(tmp_path: Path) -> None:
    assert not list(tmp_path.glob(".boca-official-import-*.tmp"))


def test_one_exact_reviewed_artifact_publishes_atomically_into_existing_boca_directory(
    tmp_path: Path,
) -> None:
    blob, pin, jsonl = _fixture()
    report = _call(tmp_path, blob, pin)
    target = _target(tmp_path)
    assert report.outcome == "CREATED"
    assert report.snapshot_sha256 == hashlib.sha256(jsonl).hexdigest()
    assert report.source_url == OFFICIAL_NEWS_URL
    assert report.actionable is False
    assert target.read_bytes() == jsonl
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.stat().st_nlink == 1
    (notice,) = load_official_snapshot(target)
    assert notice.verification_state == "SOURCE_OBSERVED_UNVERIFIED"
    assert notice.actionable is False and len(notice.windows) == 5
    _no_staging_residue(tmp_path)


def test_identical_replay_is_idempotent_without_lease_or_rewrite(tmp_path: Path) -> None:
    blob, pin, _ = _fixture()
    _call(tmp_path, blob, pin)
    before = _target(tmp_path).stat()
    again = _call(tmp_path, blob, pin)
    assert again.outcome == "UNCHANGED"
    assert _target(tmp_path).stat() == before
    _no_staging_residue(tmp_path)


def test_existing_different_snapshot_never_overwritten_without_exact_lease(
    tmp_path: Path,
) -> None:
    first, pin, original = _fixture()
    second, second_pin, _ = _fixture(notice_changes={"admission_channel_excerpt": _OTHER_EXCERPT})
    _call(tmp_path, first, pin)
    with pytest.raises(OfficialImportError, match="lease"):
        _call(tmp_path, second, second_pin)
    assert _target(tmp_path).read_bytes() == original
    _no_staging_residue(tmp_path)


def test_exact_prior_digest_and_active_lease_allow_atomic_replace(tmp_path: Path) -> None:
    first, first_pin, old_bytes = _fixture()
    second, second_pin, new_bytes = _fixture(
        notice_changes={"admission_channel_excerpt": _OTHER_EXCERPT}
    )
    _call(tmp_path, first, first_pin)
    with hold_official_snapshot_replace_lease(
        tmp_path, expected_current_sha256=hashlib.sha256(old_bytes).hexdigest()
    ) as lease:
        report = import_reviewed_official_artifact(
            tmp_path, artifact_zip=second, reviewed_pin=second_pin, replace_lease=lease
        )
    assert report.outcome == "REPLACED"
    assert _target(tmp_path).read_bytes() == new_bytes
    assert len(load_official_snapshot(_target(tmp_path))) == 1
    _no_staging_residue(tmp_path)


def test_released_lease_or_foreign_directory_cannot_authorize_replace(tmp_path: Path) -> None:
    first, pin, original = _fixture()
    second, second_pin, _ = _fixture(notice_changes={"admission_channel_excerpt": _OTHER_EXCERPT})
    _call(tmp_path, first, pin)
    with hold_official_snapshot_replace_lease(
        tmp_path, expected_current_sha256=hashlib.sha256(original).hexdigest()
    ) as lease:
        foreign = tmp_path / "foreign"
        foreign.mkdir()
        with pytest.raises(OfficialImportError):
            import_reviewed_official_artifact(
                foreign, artifact_zip=second, reviewed_pin=second_pin, replace_lease=lease
            )
    with pytest.raises(OfficialImportError, match="lease"):
        import_reviewed_official_artifact(
            tmp_path, artifact_zip=second, reviewed_pin=second_pin, replace_lease=lease
        )
    assert _target(tmp_path).read_bytes() == original


def test_wrong_or_stale_digest_and_contended_lease_fail_closed(tmp_path: Path) -> None:
    blob, pin, original = _fixture()
    _call(tmp_path, blob, pin)
    with pytest.raises(OfficialImportError, match="digest"):
        with hold_official_snapshot_replace_lease(tmp_path, expected_current_sha256="0" * 64):
            pass
    with hold_official_snapshot_replace_lease(
        tmp_path, expected_current_sha256=hashlib.sha256(original).hexdigest()
    ):
        with pytest.raises(OfficialImportError, match="lease"):
            with hold_official_snapshot_replace_lease(
                tmp_path, expected_current_sha256=hashlib.sha256(original).hexdigest()
            ):
                pass


@pytest.mark.parametrize(
    "pin_change",
    [
        {"artifact_sha256": "0" * 64},
        {"snapshot_sha256": "0" * 64},
        {"source_url": "https://www.ejemplo.invalid/noticias/falso"},
        {"source_sha256": "0" * 64},
        {"observed_at_utc": "2026-11-04T12:41:50.606388+00:00"},
        {"artifact_url": "https://github.com/otro/proyecto/actions/runs/1/artifacts/2"},
        {
            "artifact_url": "https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/1/artifacts/2?token=1"
        },
    ],
)
def test_exact_artifact_source_time_hash_and_url_pins_fail_closed(
    tmp_path: Path, pin_change: dict[str, str]
) -> None:
    blob, pin, _ = _fixture()
    with pytest.raises(OfficialImportError):
        _call(tmp_path, blob, replace(pin, **pin_change))
    assert not _target(tmp_path).exists()
    _no_staging_residue(tmp_path)


@pytest.mark.parametrize(
    "receipt_change",
    [
        {"observed_at_utc": "2026-11-04T12:41:50.606388+00:00"},
        {"source_sha256": "0" * 64},
        {"availability_verified": True},
        {"actionable": True},
        {"request_count": 2},
        {"offline_snapshot_state": "NO_EVENTOS_VERIFICADOS"},
        {"http_status": 302},
        {"markers": {"article_title": True}},
    ],
)
def test_receipt_cannot_promote_claims_or_mismatch_review(
    tmp_path: Path, receipt_change: dict[str, object]
) -> None:
    blob, pin, _ = _fixture(receipt_changes=receipt_change)
    with pytest.raises(OfficialImportError):
        _call(tmp_path, blob, pin)
    assert not _target(tmp_path).exists()


@pytest.mark.parametrize(
    "notice_change",
    [
        {"source_url": "https://www.bocajuniors.com.ar/noticias/otra-noticia"},
        {"source_sha256": "0" * 64},
        {"observed_at": "2026-11-04T09:41-03:00"},
        {"event_key": "partido-inventado"},
        {"title": "Otra noticia ficticia"},
        {"kickoff_at": "2026-11-08T17:30-03:00"},
        {"windows": []},
        {"admission_channel_claim": "CONMEBOL"},
    ],
)
def test_only_five_windows_of_one_known_public_article_are_accepted(
    tmp_path: Path, notice_change: dict[str, object]
) -> None:
    blob, pin, _ = _fixture(notice_changes=notice_change)
    with pytest.raises(OfficialImportError):
        _call(tmp_path, blob, pin)
    assert not _target(tmp_path).exists()


@pytest.mark.parametrize(
    "extra",
    [
        {"../secrets": b"x"},
        {"nested/boca-official-news-catalog.jsonl": b"x"},
        {"third.json": b"x"},
    ],
)
def test_zip_has_exactly_two_allowlisted_files_no_path_escape(
    tmp_path: Path, extra: dict[str, bytes]
) -> None:
    blob, pin, _ = _fixture(extra_entries=extra)
    with pytest.raises(OfficialImportError):
        _call(tmp_path, blob, pin)
    assert list(tmp_path.iterdir()) == []


def test_zip_budget_rejected_before_any_data_directory_mutation(tmp_path: Path) -> None:
    blob, pin, _ = _fixture()
    huge = blob + b"x" * 200_000
    with pytest.raises(OfficialImportError):
        _call(tmp_path, huge, replace(pin, artifact_sha256=hashlib.sha256(huge).hexdigest()))
    assert list(tmp_path.iterdir()) == []


def test_symlink_directory_and_target_are_not_followed(tmp_path: Path) -> None:
    blob, pin, _ = _fixture()
    real = tmp_path / "private"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(OfficialImportError):
        _call(alias, blob, pin)
    forbidden = _target(real)
    forbidden.symlink_to(tmp_path / "outside")
    with pytest.raises(OfficialImportError):
        _call(real, blob, pin)
    assert forbidden.is_symlink()


def test_unsafe_existing_target_is_never_replaced_even_with_other_valid_pin(
    tmp_path: Path,
) -> None:
    blob, pin, _ = _fixture()
    unsafe = _target(tmp_path)
    unsafe.write_text("untrusted", encoding="utf-8")
    unsafe.chmod(0o644)
    with pytest.raises(OfficialImportError):
        _call(tmp_path, blob, pin)
    assert unsafe.read_text(encoding="utf-8") == "untrusted"


def test_os_exclusive_creation_failure_leaves_no_partial_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blob, pin, _ = _fixture()
    real_link = os.link

    def deny_publish(*args: object, **kwargs: object) -> None:
        raise FileExistsError("simulated concurrent creator")

    monkeypatch.setattr(os, "link", deny_publish)
    with pytest.raises(OfficialImportError):
        _call(tmp_path, blob, pin)
    monkeypatch.setattr(os, "link", real_link)
    assert not _target(tmp_path).exists()
    _no_staging_residue(tmp_path)
