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
