"""Offline filesystem tests; never touch host ROOT or execute protected modules."""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path

import pytest

from boca_socios import host_cutover_stage as stage

ATTEMPT = "41897569929"
LEGACY_ID = "1" * 64
LEGACY_SHA = "a" * 40
TARGET_SHA = "b" * 40
TARGET_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "d" * 64
WORKER_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "e" * 64
LEGACY = b"services:\n  controller:\n    image: old\n"
BASE = b"services:\n  controller:\n    image: new\n"
OVERLAY = b"services:\n  browser-worker:\n    network_mode: none\n"
SECCOMP = b'{"defaultAction":"SCMP_ACT_ERRNO"}'
CANDIDATE_ID = "2" * 64
WORKER_ID = "3" * 64


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(stage, "ROOT", tmp_path)
    monkeypatch.setattr(stage, "UID", os.geteuid())
    monkeypatch.setattr(stage, "GID", os.getegid())
    tmp_path.chmod(0o700)
    original = tmp_path / "compose.beta.yaml"
    original.write_bytes(LEGACY)
    original.chmod(0o600)
    return tmp_path


def _init() -> None:
    stage.initialize(
        ATTEMPT,
        LEGACY_ID,
        LEGACY_SHA,
        _sha(LEGACY),
        TARGET_SHA,
        TARGET_IMAGE,
        WORKER_IMAGE,
        _sha(BASE),
        _sha(OVERLAY),
        _sha(SECCOMP),
    )


def _upload_all() -> None:
    for name, contents in (("base", BASE), ("overlay", OVERLAY), ("seccomp", SECCOMP)):
        stage.upload(name, _sha(contents), ATTEMPT, _sha(LEGACY), io.BytesIO(contents))


def test_cutover_stages_private_child_without_changing_original_inode(staging: Path) -> None:
    live = staging / "compose.beta.yaml"
    identity = (live.stat().st_dev, live.stat().st_ino)
    _init()
    _upload_all()
    verified = stage.verify(ATTEMPT, _sha(LEGACY))
    assert stage.read_verified(ATTEMPT, _sha(LEGACY), "seccomp") == SECCOMP
    assert verified == staging / f"cutover-a-{ATTEMPT}"
    assert live.read_bytes() == LEGACY
    assert (live.stat().st_dev, live.stat().st_ino) == identity
    assert set(path.name for path in staging.iterdir()) == {"compose.beta.yaml", verified.name}
    assert set(path.name for path in verified.iterdir()) == {
        stage.MARKER,
        *(value[0] for value in stage.FILES.values()),
    }
    assert all((path.stat().st_mode & 0o777) == 0o600 for path in verified.iterdir())


def test_historical_0644_compose_is_authenticated_without_mutating_live_inode(
    staging: Path,
) -> None:
    """The historical scp -p installation may leave its reviewed legacy file 0644."""
    live = staging / "compose.beta.yaml"
    live.chmod(0o644)
    before = live.stat()
    _init()
    _upload_all()
    stage.verify(ATTEMPT, _sha(LEGACY))
    after = live.stat()
    assert live.read_bytes() == LEGACY
    assert (after.st_dev, after.st_ino, after.st_mode, after.st_ctime_ns) == (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_ctime_ns,
    )
    child = staging / f"cutover-a-{ATTEMPT}"
    assert all((entry.stat().st_mode & 0o777) == 0o600 for entry in child.iterdir())
    stage.promote_accepted(ATTEMPT, _sha(LEGACY), CANDIDATE_ID, WORKER_ID)
    stage.finalize_promoted(ATTEMPT, _sha(LEGACY), CANDIDATE_ID, WORKER_ID)
    assert live.read_bytes() == BASE
    assert all((entry.stat().st_mode & 0o777) == 0o600 for entry in staging.iterdir())


@pytest.mark.parametrize("unsafe_mode", [0o640, 0o444, 0o664, 0o755, 0o4644])
def test_legacy_0644_exception_rejects_all_other_unreviewed_modes(
    staging: Path, unsafe_mode: int
) -> None:
    """Accept the observed historical 0644 only, never group writes or special bits."""
    live = staging / "compose.beta.yaml"
    live.chmod(unsafe_mode)
    before = live.read_bytes()
    with pytest.raises(stage.StageError, match="inode/owner/mode unsafe"):
        _init()
    assert live.read_bytes() == before
    assert not (staging / f"cutover-a-{ATTEMPT}").exists()


@pytest.mark.parametrize("slot", ["marker", "base", "overlay", "seccomp"])
def test_historical_0644_exception_never_applies_to_new_staged_files(
    staging: Path, slot: str
) -> None:
    (staging / "compose.beta.yaml").chmod(0o644)
    _init()
    _upload_all()
    child = staging / f"cutover-a-{ATTEMPT}"
    filename = stage.MARKER if slot == "marker" else stage.FILES[slot][0]
    (child / filename).chmod(0o644)
    with pytest.raises(stage.StageError, match="inode/owner/mode unsafe"):
        stage.verify(ATTEMPT, _sha(LEGACY))


def test_historical_0644_compose_still_requires_exact_reviewed_digest(staging: Path) -> None:
    live = staging / "compose.beta.yaml"
    live.chmod(0o644)
    live.write_bytes(LEGACY + b"\n# mutated\n")
    with pytest.raises(stage.StageError, match="SHA differs"):
        _init()
    assert not (staging / f"cutover-a-{ATTEMPT}").exists()


def test_stage_allows_same_byte_compose_when_source_and_images_are_distinct(
    staging: Path,
) -> None:
    """A code/image upgrade need not rewrite the unchanged production Compose file."""
    live = staging / "compose.beta.yaml"
    original_inode = (live.stat().st_dev, live.stat().st_ino)
    stage.initialize(
        ATTEMPT,
        LEGACY_ID,
        LEGACY_SHA,
        _sha(LEGACY),
        TARGET_SHA,
        TARGET_IMAGE,
        WORKER_IMAGE,
        _sha(LEGACY),
        _sha(OVERLAY),
        _sha(SECCOMP),
    )
    for slot, blob in (("base", LEGACY), ("overlay", OVERLAY), ("seccomp", SECCOMP)):
        stage.upload(slot, _sha(blob), ATTEMPT, _sha(LEGACY), io.BytesIO(blob))
    verified = stage.verify(ATTEMPT, _sha(LEGACY))
    assert stage.read_verified(ATTEMPT, _sha(LEGACY), "base") == LEGACY
    assert verified.name == f"cutover-a-{ATTEMPT}"
    assert live.read_bytes() == LEGACY
    assert (live.stat().st_dev, live.stat().st_ino) == original_inode


@pytest.mark.parametrize("invalid_role", ["legacy_equals_overlay", "overlay_equals_seccomp"])
def test_stage_rejects_noncompose_digest_collisions_before_mkdir(
    staging: Path, invalid_role: str
) -> None:
    """Retain genuinely independent overlay/seccomp slots and immutable original."""
    overlay = _sha(LEGACY) if invalid_role == "legacy_equals_overlay" else _sha(OVERLAY)
    seccomp = overlay if invalid_role == "overlay_equals_seccomp" else _sha(SECCOMP)
    with pytest.raises(stage.StageError, match="independent"):
        stage.initialize(
            ATTEMPT,
            LEGACY_ID,
            LEGACY_SHA,
            _sha(LEGACY),
            TARGET_SHA,
            TARGET_IMAGE,
            WORKER_IMAGE,
            _sha(LEGACY),
            overlay,
            seccomp,
        )
    assert not (staging / f"cutover-a-{ATTEMPT}").exists()
    assert (staging / "compose.beta.yaml").read_bytes() == LEGACY


def test_stage_rejects_mutated_base_bytes_even_with_compose_reuse(
    staging: Path,
) -> None:
    """Distinct source/image provenance does not bypass exact uploaded digest."""
    stage.initialize(
        ATTEMPT,
        LEGACY_ID,
        LEGACY_SHA,
        _sha(LEGACY),
        TARGET_SHA,
        TARGET_IMAGE,
        WORKER_IMAGE,
        _sha(LEGACY),
        _sha(OVERLAY),
        _sha(SECCOMP),
    )
    with pytest.raises(stage.StageError, match="altered"):
        stage.upload("base", _sha(LEGACY), ATTEMPT, _sha(LEGACY), io.BytesIO(BASE))
    child = staging / f"cutover-a-{ATTEMPT}"
    assert {item.name for item in child.iterdir()} == {stage.MARKER}
    assert (staging / "compose.beta.yaml").read_bytes() == LEGACY


def test_stage_duplicate_run_stops_without_overwriting_attempt(staging: Path) -> None:
    _init()
    before = (staging / "compose.beta.yaml").read_bytes()
    with pytest.raises(stage.StageError):
        _init()
    assert (staging / "compose.beta.yaml").read_bytes() == before
    assert set(path.name for path in (staging / f"cutover-a-{ATTEMPT}").iterdir()) == {stage.MARKER}


def test_stage_refuses_unrecognized_root_object_before_creation(staging: Path) -> None:
    (staging / "some-other-app.txt").write_text("foreign")
    with pytest.raises(stage.StageError, match="root"):
        _init()
    assert not (staging / f"cutover-a-{ATTEMPT}").exists()


@pytest.mark.parametrize("slot", ["base", "overlay", "seccomp"])
def test_stage_rejects_wrong_bytes_and_does_not_create_file(staging: Path, slot: str) -> None:
    _init()
    with pytest.raises(stage.StageError, match="altered"):
        stage.upload(slot, "1" * 64, ATTEMPT, _sha(LEGACY), io.BytesIO(b"wrong"))
    child = staging / f"cutover-a-{ATTEMPT}"
    assert set(item.name for item in child.iterdir()) == {stage.MARKER}


def test_stage_quarantines_partial_transfer_and_never_resumes_blind(staging: Path) -> None:
    _init()
    child = staging / f"cutover-a-{ATTEMPT}"
    interrupted = child / f".cutover-base-{ATTEMPT}.part"
    interrupted.write_bytes(BASE[:4])
    interrupted.chmod(0o600)
    with pytest.raises(stage.StageError, match="residue"):
        stage.upload("base", _sha(BASE), ATTEMPT, _sha(LEGACY), io.BytesIO(BASE))
    with pytest.raises(stage.StageError, match="residue"):
        stage.verify(ATTEMPT, _sha(LEGACY))
    assert interrupted.read_bytes() == BASE[:4]


def test_stage_refuses_live_inode_replacement_even_at_same_sha(staging: Path) -> None:
    _init()
    live = staging / "compose.beta.yaml"
    replacement = staging / "original-replacement.tmp"
    replacement.write_bytes(LEGACY)
    replacement.chmod(0o600)
    replacement.replace(live)
    with pytest.raises(stage.StageError, match="inode"):
        stage.upload("base", _sha(BASE), ATTEMPT, _sha(LEGACY), io.BytesIO(BASE))


def test_stage_refuses_symlink_in_any_reviewed_slot(staging: Path) -> None:
    _init()
    child = staging / f"cutover-a-{ATTEMPT}"
    (child / "compose.beta.yaml").symlink_to(staging / "compose.beta.yaml")
    with pytest.raises(stage.StageError):
        stage.verify(ATTEMPT, _sha(LEGACY))


def test_stage_refuses_unknown_read_slot(staging: Path) -> None:
    _init()
    _upload_all()
    with pytest.raises(stage.StageError, match="slot"):
        stage.read_verified(ATTEMPT, _sha(LEGACY), "owner-key")


def test_stage_refuses_tampered_marker_without_renaming_original(staging: Path) -> None:
    _init()
    marker = staging / f"cutover-a-{ATTEMPT}" / stage.MARKER
    raw = marker.read_bytes()
    marker.write_bytes(raw.replace(TARGET_SHA.encode(), LEGACY_SHA.encode()))
    marker.chmod(0o600)
    with pytest.raises(stage.StageError):
        stage.upload("base", _sha(BASE), ATTEMPT, _sha(LEGACY), io.BytesIO(BASE))
    assert (staging / "compose.beta.yaml").read_bytes() == LEGACY


@pytest.mark.parametrize("bad_attempt", ["0", "foo", "0001", "1/../../foo", "1" * 21])
def test_stage_rejects_non_run_attempt_before_open(staging: Path, bad_attempt: str) -> None:
    with pytest.raises(stage.StageError, match="attempt"):
        stage.initialize(
            bad_attempt,
            LEGACY_ID,
            LEGACY_SHA,
            _sha(LEGACY),
            TARGET_SHA,
            TARGET_IMAGE,
            WORKER_IMAGE,
            _sha(BASE),
            _sha(OVERLAY),
            _sha(SECCOMP),
        )
    assert set(path.name for path in staging.iterdir()) == {"compose.beta.yaml"}


def test_promote_is_durable_fix_forward_only_then_removes_exact_stage(staging: Path) -> None:
    _init()
    _upload_all()
    stage.promote_accepted(ATTEMPT, _sha(LEGACY), CANDIDATE_ID, WORKER_ID)
    child = staging / f"cutover-a-{ATTEMPT}"
    assert set(path.name for path in staging.iterdir()) == {
        "compose.beta.yaml",
        "compose.beta.browser.yaml",
        "seccomp_profile.json",
        child.name,
    }
    assert (staging / "compose.beta.yaml").read_bytes() == BASE
    assert (staging / "compose.beta.browser.yaml").read_bytes() == OVERLAY
    assert (staging / "seccomp_profile.json").read_bytes() == SECCOMP
    assert (child / stage.COMMIT_INTENT).read_bytes() == (child / stage.COMMIT_RESULT).read_bytes()
    assert all(
        name not in {"compose.beta.legacy.yaml", "backup", ".bak"} for name in os.listdir(staging)
    )
    with pytest.raises(stage.StageError):
        stage.verify(ATTEMPT, _sha(LEGACY))
    with pytest.raises(stage.StageError):
        stage.discard_recovered(ATTEMPT, _sha(LEGACY))
    stage.finalize_promoted(ATTEMPT, _sha(LEGACY), CANDIDATE_ID, WORKER_ID)
    assert not child.exists()
    assert set(path.name for path in staging.iterdir()) == {
        "compose.beta.yaml",
        "compose.beta.browser.yaml",
        "seccomp_profile.json",
    }
    assert all((path.stat().st_mode & 0o777) == 0o600 for path in staging.iterdir())


@pytest.mark.parametrize("complete", [False, True])
def test_recovered_legacy_discards_only_reviewed_staged_files(
    staging: Path, complete: bool
) -> None:
    _init()
    if complete:
        _upload_all()
    else:
        stage.upload("base", _sha(BASE), ATTEMPT, _sha(LEGACY), io.BytesIO(BASE))
    stage.discard_recovered(ATTEMPT, _sha(LEGACY))
    assert set(path.name for path in staging.iterdir()) == {"compose.beta.yaml"}
    assert (staging / "compose.beta.yaml").read_bytes() == LEGACY


def test_partial_or_unknown_stage_residue_is_quarantined(staging: Path) -> None:
    _init()
    child = staging / f"cutover-a-{ATTEMPT}"
    (child / f".cutover-base-{ATTEMPT}.part").write_bytes(b"incomplete")
    with pytest.raises(stage.StageError, match="unknown/partial residue"):
        stage.discard_recovered(ATTEMPT, _sha(LEGACY))
    assert (child / stage.MARKER).exists()
    assert (staging / "compose.beta.yaml").read_bytes() == LEGACY


@pytest.mark.parametrize("wrong", ["legacy", "worker", "candidate"])
def test_promotion_requires_three_distinct_exact_ids(staging: Path, wrong: str) -> None:
    _init()
    _upload_all()
    values = {
        "legacy": (LEGACY_ID, WORKER_ID),
        "worker": (CANDIDATE_ID, LEGACY_ID),
        "candidate": (CANDIDATE_ID, CANDIDATE_ID),
    }
    with pytest.raises(stage.StageError, match="IDs invalid"):
        stage.promote_accepted(ATTEMPT, _sha(LEGACY), *values[wrong])
    assert (staging / "compose.beta.yaml").read_bytes() == LEGACY
    assert not (staging / f"cutover-a-{ATTEMPT}" / stage.COMMIT_INTENT).exists()


def test_interrupted_promotion_keeps_durable_intent_and_no_unsafe_retry(
    staging: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init()
    _upload_all()
    real_replace = stage.os.replace
    writes = [0]

    def lose_receipt_after_one_replace(*args: object, **kwargs: object) -> None:
        writes[0] += 1
        if writes[0] == 2:
            raise OSError("synthetic metadata I/O loss")
        real_replace(*args, **kwargs)

    monkeypatch.setattr(stage.os, "replace", lose_receipt_after_one_replace)
    with pytest.raises(stage.StageError, match="outcome uncertain"):
        stage.promote_accepted(ATTEMPT, _sha(LEGACY), CANDIDATE_ID, WORKER_ID)
    child = staging / f"cutover-a-{ATTEMPT}"
    assert (child / stage.COMMIT_INTENT).exists()
    assert not (child / stage.COMMIT_RESULT).exists()
    assert (staging / "compose.beta.yaml").read_bytes() == BASE
    assert (staging / "compose.beta.browser.yaml").exists() is False
    with pytest.raises(stage.StageError):
        stage.discard_recovered(ATTEMPT, _sha(LEGACY))
    with pytest.raises(stage.StageError):
        stage.finalize_promoted(ATTEMPT, _sha(LEGACY), CANDIDATE_ID, WORKER_ID)
    assert (child / stage.COMMIT_INTENT).exists()


def test_promotion_refuses_foreign_root_object_before_overlay_replace(
    staging: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init()
    _upload_all()
    real_replace = stage.os.replace
    calls = [0]
    foreign = staging / "other-service-do-not-touch.txt"

    def inject_after_first(*args: object, **kwargs: object) -> None:
        real_replace(*args, **kwargs)
        calls[0] += 1
        if calls[0] == 1:
            foreign.write_text("preserve unrelated service")

    monkeypatch.setattr(stage.os, "replace", inject_after_first)
    with pytest.raises(stage.StageError, match="unexpected object"):
        stage.promote_accepted(ATTEMPT, _sha(LEGACY), CANDIDATE_ID, WORKER_ID)
    assert foreign.read_text() == "preserve unrelated service"
    assert (staging / "compose.beta.yaml").read_bytes() == BASE
    assert (staging / f"cutover-a-{ATTEMPT}" / stage.COMMIT_INTENT).exists()
    assert (staging / "compose.beta.browser.yaml").exists() is False
