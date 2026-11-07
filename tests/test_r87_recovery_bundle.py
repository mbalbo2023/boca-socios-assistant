"""Run the R87 recovery mode via the real hashed 7-file memfd ZIP offline.

The host handler is deliberately synthetic: never Docker or SSH.
"""

from __future__ import annotations

import hashlib
import io
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from scripts import boca_protected_memfd_bootstrap as bootstrap  # noqa: E402
from scripts import build_protected_boca_bundle as builder  # noqa: E402

from test_r82_recovery_bundle import (  # noqa: E402
    EXPECTED_RECOVERY_ENTRIES,
    _boot,
    _fixture_root,
)

R87_MODE = "cutover-worker-819-recover"
FAKE = (
    "def main(argv):\n"
    "    if argv == ['host-819']:\n"
    "        print('BOCA_R87_SYNTHETIC host=UNTOUCHED target=819')\n"
    "        return 0\n"
    "    if argv == ['host-827']:\n"
    "        print('BOCA_R87_SYNTHETIC host=UNTOUCHED target=827')\n"
    "        return 0\n"
    "    if argv == ['host']:\n"
    "        print('BOCA_R87_SYNTHETIC host=UNTOUCHED target=795')\n"
    "        return 0\n"
    "    if argv == ['host-807']:\n"
    "        print('BOCA_R87_SYNTHETIC host=UNTOUCHED target=807')\n"
    "        return 0\n"
    "    return 3\n"
).encode("ascii")


def _bundle(tmp_path: Path) -> tuple[bytes, str]:
    fixture = _fixture_root(tmp_path)
    (fixture / "scripts/host_cutover_worker_recovery.py").write_bytes(FAKE)
    target = tmp_path / "recover-r87.pyz"
    digest = builder.build(fixture, target, worker_recovery=True)
    return target.read_bytes(), digest


@pytest.mark.parametrize(
    ("mode", "target"),
    [
        ("cutover-worker-recover", "795"),
        ("cutover-worker-807-recover", "807"),
        (R87_MODE, "819"),
        ("cutover-worker-827-recover", "827"),
    ],
)
def test_r87_hashed_memfd_selects_only_exact_fixed_host_handler(
    tmp_path: Path, mode: str, target: str
) -> None:
    raw, digest = _bundle(tmp_path)
    result = _boot(raw, digest, mode)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result.stdout == f"BOCA_R87_SYNTHETIC host=UNTOUCHED target={target}\n".encode()
    assert result.stderr == b""


@pytest.mark.parametrize("extra", [("--force",), ("42353468231",), ("a" * 64,)])
def test_r87_rejects_host_supplied_coordinates_before_handler(
    tmp_path: Path, extra: tuple[str, ...]
) -> None:
    raw, digest = _bundle(tmp_path)
    result = _boot(raw, digest, R87_MODE, *extra)
    assert result.returncode != 0
    assert b"BOCA_R87_SYNTHETIC" not in result.stdout


def test_r87_recovery_archive_seven_only_sha_exact_and_not_full_cutover(tmp_path: Path) -> None:
    raw, digest = _bundle(tmp_path)
    assert digest == hashlib.sha256(raw).hexdigest()
    assert len(raw) <= 128_000
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert set(archive.namelist()) == EXPECTED_RECOVERY_ENTRIES
        assert len(archive.namelist()) == 7
        assert archive.read("scripts/host_cutover_worker_recovery.py") == FAKE
    bootstrap.verify(raw, digest, recovery=True)
    with pytest.raises(ValueError):
        bootstrap.verify(raw, digest, recovery=False)


@pytest.mark.parametrize("mode", ["cutover-worker-820-recover", "cutover-a-apply", "shell"])
def test_r87_unknown_mode_rejected_even_with_valid_archive(tmp_path: Path, mode: str) -> None:
    raw, digest = _bundle(tmp_path)
    result = _boot(raw, digest, mode)
    assert result.returncode != 0
    assert b"BOCA_R87_SYNTHETIC" not in result.stdout


def test_r87_production_recovery_archive_has_new_pin_without_historical_cross_pollution(
    tmp_path: Path,
) -> None:
    target = tmp_path / "actual-recovery.pyz"
    digest = builder.build(ROOT, target, worker_recovery=True)
    raw = target.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest
    bootstrap.verify(raw, digest, recovery=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert set(archive.namelist()) == EXPECTED_RECOVERY_ENTRIES
        assert b"42353468231" in archive.read("scripts/host_cutover_worker_recovery.py")
        assert b"cutover-worker-819-recover" in archive.read("__main__.py")
        assert b"42368541950" in archive.read("scripts/host_cutover_worker_recovery.py")
        assert b"cutover-worker-827-recover" in archive.read("__main__.py")
    with pytest.raises(ValueError):
        bootstrap.verify(raw, digest, recovery=False)
