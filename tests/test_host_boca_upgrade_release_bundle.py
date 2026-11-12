"""R244 protected memfd bundle carries only runner-authenticated release data."""

from __future__ import annotations

import hashlib
import io
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from boca_socios import host_boca_upgrade_release_bridge as bridge
from boca_socios.host_boca_pair_upgrade_plan import CandidateRelease
from test_host_boca_upgrade_release_auth import BROWSER, CONTROLLER, RUN, SOURCE, FakeGitHub

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import boca_protected_memfd_bootstrap as bootstrap  # noqa: E402
import build_protected_boca_bundle as builder  # noqa: E402


def _authenticated_directory(tmp_path: Path) -> Path:
    github = FakeGitHub()
    candidate = CandidateRelease(SOURCE, RUN, CONTROLLER, BROWSER)
    ctrl = github.payloads["controller-release"]
    browser = github.payloads["paired-release"]
    proof = bridge.authenticate_runner_release(candidate, ctrl, browser, github)
    folder = tmp_path / "release"
    folder.mkdir(mode=0o700)
    (folder / "boca-release-manifest.json").write_bytes(ctrl)
    (folder / "boca-browser-release-manifest.json").write_bytes(browser)
    (folder / "runner-proof.json").write_bytes(proof)
    return folder


def test_bundle_carries_authenticated_dual_artifacts_and_bootstrap_checks_allowlist(
    tmp_path: Path,
) -> None:
    evidence = _authenticated_directory(tmp_path)
    target = tmp_path / "reviewed.pyz"
    digest = builder.build(ROOT, target, pair_upgrade=True, pair_upgrade_release_dir=evidence)
    bootstrap.verify(target.read_bytes(), digest, pair_upgrade=True)
    with zipfile.ZipFile(io.BytesIO(target.read_bytes())) as archive:
        assert set(archive.namelist()) == bootstrap.PAIR_UPGRADE_ENTRIES
        assert (
            archive.read("release/runner-proof.json")
            == (evidence / "runner-proof.json").read_bytes()
        )
        assert bridge.verify_bundled_release(
            archive.read("release/runner-proof.json"),
            archive.read("release/boca-release-manifest.json"),
            archive.read("release/boca-browser-release-manifest.json"),
            CandidateRelease(SOURCE, RUN, CONTROLLER, BROWSER),
        )
        assert not any("token" in name or name.endswith(".env") for name in archive.namelist())


@pytest.mark.parametrize("change", ["contaminated", "extra", "symlink", "mismatch"])
def test_bundle_rejects_untrusted_release_folder_before_writing_zip(
    tmp_path: Path, change: str
) -> None:
    evidence = _authenticated_directory(tmp_path)
    if change == "contaminated":
        (evidence / "boca-browser-release-manifest.json").write_bytes(b'{"state":"forged"}\n')
    elif change == "extra":
        (evidence / "untrusted-token.env").write_text("never bundle")
    elif change == "symlink":
        path = evidence / "runner-proof.json"
        path.unlink()
        path.symlink_to(evidence / "boca-release-manifest.json")
    else:
        (evidence / "runner-proof.json").write_bytes(
            (evidence / "runner-proof.json")
            .read_bytes()
            .replace(SOURCE.encode(), ("f" * 40).encode())
        )
    target = tmp_path / "not-authorized.pyz"
    with pytest.raises(ValueError):
        builder.build(ROOT, target, pair_upgrade=True, pair_upgrade_release_dir=evidence)
    assert not target.exists()


def test_ineligible_bundle_never_recovers_legacy_one_shot_upgrade(tmp_path: Path) -> None:
    target = tmp_path / "ineligible.pyz"
    digest = builder.build(ROOT, target, pair_upgrade=True)
    bootstrap.verify(target.read_bytes(), digest, pair_upgrade=True)
    with zipfile.ZipFile(io.BytesIO(target.read_bytes())) as archive:
        assert b'"state":"NO_GO"' in archive.read("release/runner-proof.json")
    result = subprocess.run(  # noqa: S603 - checked fixture ZIP + fixed offline interpreter
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            (ROOT / "scripts/boca_protected_memfd_bootstrap.py").read_text(),
            digest,
            "boca-pair-upgrade-apply",
            "999999",
            SOURCE,
            CONTROLLER,
            BROWSER,
            RUN,
        ],
        input=target.read_bytes(),
        capture_output=True,
        timeout=12,
        check=False,
    )
    assert result.returncode == 3
    assert result.stdout.startswith(b"BOCA_PAIR_UPGRADE ")
    assert b'"state":"NO_GO"' in result.stdout
    assert b'"cleanup":"INDETERMINATE"' in result.stdout
    assert not result.stderr
    assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
