"""R244 protected memfd bundle carries only runner-authenticated release data."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from boca_socios import host_boca_current_pair_v2 as current
from boca_socios import host_boca_upgrade_observation_bridge as observation
from boca_socios import host_boca_upgrade_release_bridge as bridge
from boca_socios.host_boca_pair_upgrade_plan import CandidateRelease
from test_host_boca_upgrade_release_auth import BROWSER, CONTROLLER, RUN, SOURCE
from test_host_boca_upgrade_retained_bridge import PAIR_RUN, RETAINED_RUN
from test_r247_runner_current_pair_v2 import NOW, _inputs_for_runner, runner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import boca_protected_memfd_bootstrap as bootstrap  # noqa: E402
import build_protected_boca_bundle as builder  # noqa: E402


def _authenticated_directory(tmp_path: Path) -> Path:
    github, catalog, args, folder = _inputs_for_runner(tmp_path)
    runner.attest_runner(*args, github=github, release_catalog=catalog, now=NOW)
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
        for module in (
            "boca_socios/host_boca_upgrade_same_lease.py",
            "boca_socios/host_boca_upgrade_postflight.py",
            "boca_socios/host_boca_cleanup_v2.py",
            "boca_socios/host_boca_upgrade_postflight_runtime.py",
            "boca_socios/host_boca_upgrade_cleanup_runtime.py",
            "boca_socios/host_boca_upgrade_successor_runtime.py",
        ):
            assert module in archive.namelist()
        assert (
            archive.read("release/runner-proof.json")
            == (evidence / "runner-proof.json").read_bytes()
        )
        coords = json.loads(archive.read("release/runner-proof.json"))
        assert bridge.verify_bundled_release(
            archive.read("release/runner-proof.json"),
            archive.read("release/boca-release-manifest.json"),
            archive.read("release/boca-browser-release-manifest.json"),
            CandidateRelease(
                coords["source_sha"],
                coords["release_run_id"],
                coords["controller_ref"],
                coords["worker_ref"],
            ),
        )
        pair_proof = json.loads(archive.read("release/observation-proof.json"))
        assert observation.verify_bundled_observation(
            archive.read("release/observation-proof.json"),
            archive.read("release/boca-pair-observation.receipt"),
            coords["source_sha"],
            pair_proof["observer_run_id"],
            pair_proof["apply_attempt_id"],
            coords["release_run_id"],
        )["old_attempt_id"]
        assert archive.read("release/retained-proof.json") == b'{"state":"NO_GO"}\n'
        v2 = current.verify_current_pair_v2(archive.read("release/current-pair-v2.receipt"))
        assert v2["apply_authorized"] is False
        assert v2["previous_pair_source_sha"] == pair_proof["old_source_sha"]
        assert v2["historical_resource_custody"]["original_observation_run"]
        assert not any("token" in name or name.endswith(".env") for name in archive.namelist())
    imported = subprocess.run(  # noqa: S603 - fixed local Python, checked ZIP
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from boca_socios import host_boca_upgrade_same_lease, host_boca_upgrade_postflight; "
            "from boca_socios import host_boca_upgrade_postflight_runtime, host_boca_upgrade_cleanup_runtime; "
            "from boca_socios import host_boca_upgrade_successor_runtime",
            str(target),
        ],
        capture_output=True,
        text=True,
        timeout=12,
        check=False,
    )
    assert imported.returncode == 0, imported.stderr


@pytest.mark.parametrize(
    "change",
    [
        "contaminated",
        "extra",
        "symlink",
        "mismatch",
        "observation_tamper",
        "observation_symlink",
        "retained_tamper",
        "retained_symlink",
    ],
)
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
    elif change == "observation_tamper":
        (evidence / "boca-pair-observation.receipt").write_bytes(b'{"state":"forged"}\n')
    elif change == "observation_symlink":
        path = evidence / "observation-proof.json"
        path.unlink()
        path.symlink_to(evidence / "boca-release-manifest.json")
    elif change == "retained_tamper":
        (evidence / "boca-retained-observation.receipt").write_bytes(b'{"forged":true}\n')
    elif change == "retained_symlink":
        path = evidence / "retained-proof.json"
        path.unlink()
        path.symlink_to(evidence / "observation-proof.json")
    else:
        source = json.loads((evidence / "runner-proof.json").read_bytes())["source_sha"]
        (evidence / "runner-proof.json").write_bytes(
            (evidence / "runner-proof.json")
            .read_bytes()
            .replace(source.encode(), ("f" * 40).encode())
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
        assert b'"state":"NO_GO"' in archive.read("release/observation-proof.json")
        assert b'"state":"NO_GO"' in archive.read("release/retained-proof.json")
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
            PAIR_RUN,
            RETAINED_RUN,
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
