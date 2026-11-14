"""Separate current observer ZIP and exact successor evidence; offline only."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from test_r294_promotion_runner import NOW, inputs, runner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import boca_protected_memfd_bootstrap as bootstrap  # noqa: E402
import build_protected_boca_bundle as builder  # noqa: E402


def import_only(path: Path, module: str) -> None:
    # Importing code neither invokes host attestors nor acquires a lease.
    check = subprocess.run(  # noqa: S603 - fixed executable and offline ZIP
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            "import importlib,sys; sys.path.insert(0,sys.argv[1]); importlib.import_module(sys.argv[2])",
            str(path),
            module,
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert check.returncode == 0, check.stderr


def test_current_observer_has_exact_separate_importable_readonly_bundle(tmp_path: Path) -> None:
    one, two = tmp_path / "one.pyz", tmp_path / "two.pyz"
    digest = builder.build(ROOT, one, current_retained_observe=True)
    assert builder.build(ROOT, two, current_retained_observe=True) == digest
    raw = one.read_bytes()
    bootstrap.verify(raw, digest, current_retained_observe=True)
    with zipfile.ZipFile(one) as archive:
        assert set(archive.namelist()) == bootstrap.CURRENT_RETAINED_ENTRIES
        assert "boca_socios/host_boca_current_retained.py" in archive.namelist()
        assert "boca_socios/host_boca_pair_upgrade.py" not in archive.namelist()
        assert "compose.beta.yaml" not in archive.namelist()
        assert not any("browser/" in name for name in archive.namelist())
        assert b"boca-current-retained-resource-observe" in archive.read("__main__.py")
    for wrong in (
        {},
        {"retained_observe": True},
        {"binding_observe": True},
        {"pair_upgrade": True},
    ):
        with pytest.raises(ValueError):
            bootstrap.verify(raw, digest, **wrong)
    import_only(one, "boca_socios.host_boca_current_retained")


def test_successor_bundle_carries_current_stop_and_original_creators(tmp_path: Path) -> None:
    gh, argv, folder = inputs(tmp_path, stopped=True)
    runner.attest_runner(*argv, github=gh, release_catalog=gh, now=NOW)
    target = tmp_path / "upgrade.pyz"
    digest = builder.build(ROOT, target, pair_upgrade=True, pair_upgrade_release_dir=folder)
    bootstrap.verify(target.read_bytes(), digest, pair_upgrade=True)
    with zipfile.ZipFile(target) as archive:
        assert set(archive.namelist()) == bootstrap.PAIR_UPGRADE_ENTRIES
        assert archive.read("release/boca-retained-observation.receipt") == gh.retained_raw
        assert archive.read("release/retained-proof.json") == b'{"state":"NO_GO"}\n'
    import_only(target, "boca_socios.host_boca_successor_assembly_v3")


def test_current_runner_verification_imports_without_any_site_packages() -> None:
    check = subprocess.run(  # noqa: S603 - isolated stdlib-only imports; no host entrypoint
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            "import sys; sys.path[:0]=sys.argv[1:]; "
            "import boca_socios.host_boca_current_retained; import attest_current_pair_v2",
            str(ROOT / "src"),
            str(ROOT / "scripts"),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert check.returncode == 0, check.stderr
