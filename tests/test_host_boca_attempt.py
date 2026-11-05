"""No-host attempt producer for first/beta/update and cleanup #323."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from boca_socios import host_boca_attempt as attempt
from boca_socios import host_boca_cleanup as cleanup

RUN = "41897569929"
SOURCE = "a" * 40
BASE_SHA = "b" * 64
CONTROLLER = "c" * 64


def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    monkeypatch.setattr(attempt, "MARKER_DIR", tmp_path)
    monkeypatch.setattr(attempt, "EXPECTED_UID", os.geteuid())
    monkeypatch.setattr(cleanup, "LEASE_DIR", tmp_path)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())


@pytest.mark.parametrize(
    ("operation", "label"),
    [
        ("first-install", "boca.socios.install-attempt"),
        ("beta-install", "boca.socios.beta-install-attempt"),
        ("update", "boca.socios.update-attempt"),
    ],
)
def test_reviewed_label_overlay_only_controller_and_source(
    operation: str,
    label: str,
) -> None:
    identity, overlay = attempt.intended(operation, RUN, SOURCE, BASE_SHA, None)
    assert identity.overlay_sha == hashlib.sha256(overlay).hexdigest()
    assert overlay == (
        b"name: boca-socios\nservices:\n  controller:\n    labels:\n"
        + f'      {label}: "{RUN}"\n'.encode()
        + f'      boca.socios.source-sha: "{SOURCE}"\n'.encode()
    )
    assert b"ports:" not in overlay
    assert b"volumes:" not in overlay
    assert b"network:" not in overlay


def test_success_receipt_exclusive_marker_preserves_exact_installed_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _setup(monkeypatch, tmp_path)
    intent, overlay = attempt.intended("beta-install", RUN, SOURCE, BASE_SHA, None)
    with cleanup.protected_boca_job_lease(RUN) as lease:
        digest = attempt.begin(intent, lease=lease)
        assert (
            digest
            == hashlib.sha256(
                (tmp_path / f"boca-postdeploy-{RUN}-intent.json").read_bytes()
            ).hexdigest()
        )
        assert attempt.read_intent(RUN, lease=lease) == (intent, digest)
        result = attempt.Result(RUN, digest, "SUCCESS", CONTROLLER, CONTROLLER)
        attempt.finish(result, lease=lease)
        assert attempt.read_result(RUN, lease=lease) == result
        assert attempt.cleanup_ids(result, lease=lease) == (
            frozenset({CONTROLLER}),
            frozenset(),
        )
        with pytest.raises(attempt.AttemptError, match="exclusive attempt marker"):
            attempt.begin(intent, lease=lease)
        assert hashlib.sha256(overlay).hexdigest() == intent.overlay_sha


def test_failed_attempt_only_explicit_created_id_is_retired(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _setup(monkeypatch, tmp_path)
    intent, _ = attempt.intended("first-install", RUN, SOURCE, BASE_SHA, None)
    with cleanup.protected_boca_job_lease(RUN) as lease:
        digest = attempt.begin(intent, lease=lease)
        result = attempt.Result(RUN, digest, "FAILURE", CONTROLLER, None)
        attempt.finish(result, lease=lease)
        assert attempt.cleanup_ids(result, lease=lease) == (
            frozenset(),
            frozenset({CONTROLLER}),
        )


def test_missing_result_is_no_go_no_guessed_retirement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _setup(monkeypatch, tmp_path)
    intent, _ = attempt.intended("beta-install", RUN, SOURCE, BASE_SHA, None)
    with cleanup.protected_boca_job_lease(RUN) as lease:
        attempt.begin(intent, lease=lease)
        with pytest.raises(attempt.AttemptError, match="marker absent"):
            attempt.read_result(RUN, lease=lease)


def test_forged_result_cannot_supply_different_retirement_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _setup(monkeypatch, tmp_path)
    intent, _ = attempt.intended("first-install", RUN, SOURCE, BASE_SHA, None)
    with cleanup.protected_boca_job_lease(RUN) as lease:
        digest = attempt.begin(intent, lease=lease)
        result = attempt.Result(RUN, digest, "FAILURE", CONTROLLER, None)
        attempt.finish(result, lease=lease)
        forged = attempt.Result(RUN, digest, "FAILURE", "d" * 64, None)
        with pytest.raises(attempt.AttemptError, match="forged"):
            attempt.cleanup_ids(forged, lease=lease)


def test_marker_symlink_fails_closed_and_never_follows_foreign_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _setup(monkeypatch, tmp_path)
    foreign = tmp_path / "foreign"
    foreign.write_text("do-not-read")
    (tmp_path / f"boca-postdeploy-{RUN}-intent.json").symlink_to(foreign)
    with cleanup.protected_boca_job_lease(RUN) as lease:
        with pytest.raises(attempt.AttemptError, match="marker absent/unsafe"):
            attempt.read_intent(RUN, lease=lease)
    assert foreign.read_text() == "do-not-read"


def test_update_requires_separate_exact_legacy_retirement_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _setup(monkeypatch, tmp_path)
    intent, _ = attempt.intended("update", RUN, SOURCE, BASE_SHA, "d" * 64)
    with cleanup.protected_boca_job_lease(RUN) as lease:
        digest = attempt.begin(intent, lease=lease)
        result = attempt.Result(RUN, digest, "SUCCESS", CONTROLLER, CONTROLLER)
        attempt.finish(result, lease=lease)
        with pytest.raises(attempt.AttemptError, match="physical NO_GO"):
            attempt.cleanup_ids(result, lease=lease)


def test_forged_intent_coordinates_cannot_create_marker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _setup(monkeypatch, tmp_path)
    valid, _ = attempt.intended("first-install", RUN, SOURCE, BASE_SHA, None)
    invalid = attempt.Intent(
        valid.attempt_id,
        valid.operation,
        SOURCE,
        BASE_SHA,
        "z" * 64,
        None,
    )
    with cleanup.protected_boca_job_lease(RUN) as lease:
        with pytest.raises(attempt.AttemptError, match="coordinates invalid"):
            attempt.begin(invalid, lease=lease)
    assert not (tmp_path / f"boca-postdeploy-{RUN}-intent.json").exists()
