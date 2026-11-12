"""R179 rootless SQLite observer and effectful pair-upgrade ZIPs are disjoint."""

from __future__ import annotations

import hashlib
import io
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import boca_protected_memfd_bootstrap as bootstrap  # noqa: E402
import build_protected_boca_bundle as builder  # noqa: E402


@pytest.mark.parametrize("variant", ["sqlite_observe", "pair_upgrade"])
def test_r179_bundle_is_deterministic_sha_pinned_and_separate(tmp_path: Path, variant: str) -> None:
    a = tmp_path / f"{variant}-a.pyz"
    b = tmp_path / f"{variant}-b.pyz"
    mode = {variant: True}
    digest = builder.build(ROOT, a, **mode)
    assert builder.build(ROOT, b, **mode) == digest
    assert a.read_bytes() == b.read_bytes()
    assert hashlib.sha256(a.read_bytes()).hexdigest() == digest
    bootstrap.verify(a.read_bytes(), digest, **mode)
    with zipfile.ZipFile(io.BytesIO(a.read_bytes())) as package:
        entries = set(package.namelist())
        expected = (
            bootstrap.SQLITE_OBSERVE_ENTRIES
            if variant == "sqlite_observe"
            else bootstrap.PAIR_UPGRADE_ENTRIES
        )
        assert entries == expected
        assert "boca_socios/host_boca_sqlite_identity.py" in entries
        assert "boca_socios/host_boca_pair_observe.py" in entries
        assert "boca_socios/host_boca_pair_upgrade_cli.py" in entries
        assert not any("browser/" in name for name in entries)
        assert "boca_socios/host_worker_w1.py" not in entries
        if variant == "sqlite_observe":
            assert "compose.beta.browser.yaml" not in entries
            assert "boca_socios/host_boca_pair_upgrade_backend.py" not in entries
            assert b"boca-sqlite-inode-observe" in package.read("__main__.py")
        else:
            assert "compose.beta.browser.yaml" in entries
            assert "boca_socios/host_boca_pair_upgrade_backend.py" in entries
            assert "boca_socios/host_on_demand_replace.py" in entries
            assert b"boca-pair-upgrade-apply" in package.read("__main__.py")


def test_r179_variants_cannot_be_reinterpreted_or_reused(tmp_path: Path) -> None:
    for mode in ("sqlite_observe", "pair_upgrade"):
        target = tmp_path / f"{mode}.pyz"
        digest = builder.build(ROOT, target, **{mode: True})
        raw = target.read_bytes()
        for forbidden in ({}, {"binding_observe": True}, {"pair_observe": True}):
            with pytest.raises(ValueError):
                bootstrap.verify(raw, digest, **forbidden)
        with pytest.raises(ValueError):
            bootstrap.verify(raw, "0" * 64, **{mode: True})
    with pytest.raises(ValueError):
        builder.build(ROOT, tmp_path / "both.pyz", sqlite_observe=True, pair_upgrade=True)


@pytest.mark.parametrize("variant", ["sqlite_observe", "pair_upgrade"])
def test_r179_verified_memfd_zip_actually_imports_entrypoint(tmp_path: Path, variant: str) -> None:
    """Catch incomplete ZIP import graphs before any physical Boca operation."""
    target = tmp_path / "entrypoint.pyz"
    digest = builder.build(ROOT, target, **{variant: True})
    args = (
        ["boca-sqlite-inode-observe", "999999"]
        if variant == "sqlite_observe"
        else [
            "boca-pair-upgrade-apply",
            "999999",
            "invalid-sha",
            "invalid-ref",
            "invalid-ref",
            "1",
            "2",  # Explicit prior observer run; never default or reuse APPLY.
        ]
    )
    runner = subprocess.run(  # noqa: S603 - constant Python interpreter/checked ZIP
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            (ROOT / "scripts/boca_protected_memfd_bootstrap.py").read_text(),
            digest,
            *args,
        ],
        input=target.read_bytes(),
        capture_output=True,
        timeout=15,
        check=False,
    )
    prefix = b"BOCA_SQLITE_IDENTITY " if variant == "sqlite_observe" else b"BOCA_PAIR_UPGRADE "
    assert runner.returncode == 3
    assert runner.stdout.startswith(prefix)
    assert runner.stdout.endswith(b"\n") and runner.stdout.count(b"\n") == 1
    assert b'"state":"NO_GO"' in runner.stdout
    assert not runner.stderr


def test_pair_upgrade_zip_can_import_late_systemd_binding_dependency(tmp_path: Path) -> None:
    """Exercise the dependency imported only after both candidates are accepted."""
    target = tmp_path / "pair-upgrade.pyz"
    builder.build(ROOT, target, pair_upgrade=True)
    code = (
        "import sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from boca_socios.host_boca_cutover import candidate_check\n"
        "assert callable(candidate_check)\n"
    )
    result = subprocess.run(  # noqa: S603 - isolated reviewed Python ZIP, no host effects
        [sys.executable, "-I", "-B", "-c", code, str(target)],
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")


def test_pair_upgrade_zip_derives_systemd_runtime_archive_from_its_memfd(
    tmp_path: Path,
) -> None:
    """An on-demand binding must not require the omitted effectful Cutover CLI."""
    target = tmp_path / "pair-upgrade.pyz"
    digest = builder.build(ROOT, target, pair_upgrade=True)
    code = (
        "import hashlib,io,os,sys,zipfile\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from boca_socios import host_on_demand_service as service\n"
        "raw=Path(sys.argv[1]).read_bytes()\n"
        "fd=os.memfd_create('boca-offline-binding-test', 0)\n"
        "assert os.write(fd,raw)==len(raw)\n"
        "sys.argv[0]=f'/proc/self/fd/{fd}'\n"
        "runtime=service._bundle(None)\n"
        "assert runtime==service._bundle(hashlib.sha256(raw).hexdigest())\n"
        "with zipfile.ZipFile(io.BytesIO(runtime)) as zip_source:\n"
        "    assert set(zip_source.namelist())=={*service._RUNTIME_FILES,'__main__.py'}\n"
        "try:\n"
        "    service._bundle('0'*64)\n"
        "except ValueError:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('incorrect bundle digest admitted')\n"
        "sys.argv[0]=sys.argv[1]\n"
        "try:\n"
        "    service._bundle(None)\n"
        "except ValueError:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('untrusted non-memfd source admitted')\n"
    )
    result = subprocess.run(  # noqa: S603 - isolated in-memory ZIP transformation only
        [sys.executable, "-I", "-B", "-c", code, str(target)],
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert digest == hashlib.sha256(target.read_bytes()).hexdigest()
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")
