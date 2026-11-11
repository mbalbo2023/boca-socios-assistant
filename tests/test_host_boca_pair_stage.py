"""Dedicated Boca-rootless R179 staging; unrelated old dirs are untouched."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from boca_socios import host_boca_pair_stage as stage_pair
from boca_socios import host_cutover_stage as older


def _sources() -> stage_pair.PairSources:
    base = b"services:\n  controller:\n    image: example\n"
    overlay = b"services:\n  browser-worker:\n    image: example\n"
    seccomp = b'{"defaultAction":"SCMP_ACT_ERRNO","syscalls":[]}\n'
    return stage_pair.PairSources(
        base=base,
        overlay=overlay,
        seccomp=seccomp,
        original_compose_sha=hashlib.sha256(b"legacy compose").hexdigest(),
        base_sha=hashlib.sha256(base).hexdigest(),
        overlay_sha=hashlib.sha256(overlay).hexdigest(),
        seccomp_sha=hashlib.sha256(seccomp).hexdigest(),
    )


@pytest.fixture
def root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    target = tmp_path / "boca"
    target.mkdir(mode=0o700)
    (target / "compose.beta.yaml").write_bytes(b"legacy compose")
    (target / "compose.beta.yaml").chmod(0o600)
    # Historical stages MAY remain; never change or remove them to make GO.
    (target / "cutover-a-42806447101").mkdir(mode=0o700)
    monkeypatch.setattr(older, "ROOT", target)
    monkeypatch.setattr(older, "UID", os.geteuid())
    monkeypatch.setattr(older, "GID", os.getegid())
    return target


def test_stage_creates_exact_private_child_with_verified_bytes(root: Path) -> None:
    sources = _sources()
    directory = stage_pair.prepare("43080012345", sources)
    assert directory == root / "cutover-a-43080012345"
    assert stage_pair.verify("43080012345", sources) == directory
    assert (directory / "compose.beta.yaml").read_bytes() == sources.base
    assert (directory / "compose.beta.browser.yaml").read_bytes() == sources.overlay
    assert (directory / "seccomp_profile.json").read_bytes() == sources.seccomp
    assert (root / "cutover-a-42806447101").is_dir()


def test_attempt_is_exclusive_and_never_overwrites_existing(root: Path) -> None:
    sources = _sources()
    stage_pair.prepare("43080012345", sources)
    with pytest.raises(older.StageError):
        stage_pair.prepare("43080012345", sources)
    assert stage_pair.verify("43080012345", sources) == root / "cutover-a-43080012345"


def test_stage_refuses_original_file_change_before_effects(root: Path) -> None:
    (root / "compose.beta.yaml").write_bytes(b"different")
    with pytest.raises(older.StageError):
        stage_pair.prepare("43080012345", _sources())
    assert not (root / "cutover-a-43080012345").exists()


def test_stage_refuses_symlinked_historical_compose(root: Path) -> None:
    (root / "compose.beta.yaml").unlink()
    (root / "compose.beta.yaml").symlink_to("cutover-a-42806447101")
    with pytest.raises(older.StageError):
        stage_pair.prepare("43080012345", _sources())


def test_bad_artifact_sha_prevents_even_initial_directory(root: Path) -> None:
    from dataclasses import replace

    sources = replace(_sources(), overlay_sha="a" * 64)
    with pytest.raises(older.StageError):
        stage_pair.prepare("43080012345", sources)
    assert not (root / "cutover-a-43080012345").exists()


def test_verified_stage_detects_post_write_tampering(root: Path) -> None:
    sources = _sources()
    directory = stage_pair.prepare("43080012345", sources)
    (directory / "seccomp_profile.json").write_bytes(b"tampered")
    with pytest.raises(older.StageError):
        stage_pair.verify("43080012345", sources)


def test_refuses_unexpected_child_file_without_deleting_it(root: Path) -> None:
    sources = _sources()
    directory = stage_pair.prepare("43080012345", sources)
    (directory / "foreign").write_bytes(b"do not touch")
    with pytest.raises(older.StageError):
        stage_pair.verify("43080012345", sources)
    assert (directory / "foreign").read_bytes() == b"do not touch"
