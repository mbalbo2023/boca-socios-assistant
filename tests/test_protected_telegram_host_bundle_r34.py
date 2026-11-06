"""R34: one reviewed Telegram host ZIP, never an activation authority."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_protected_telegram_bundle as telegram_bundle  # noqa: E402


def test_exact_allowlisted_closure_is_deterministic_and_separate_from_cutover(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.pyz"
    second = tmp_path / "second.pyz"
    digest = telegram_bundle.build(ROOT, first)
    assert digest == telegram_bundle.build(ROOT, second)
    assert digest == hashlib.sha256(first.read_bytes()).hexdigest()
    assert first.read_bytes() == second.read_bytes()
    assert first.stat().st_size < telegram_bundle.MAX_ARCHIVE_BYTES
    with zipfile.ZipFile(first) as archive:
        expected = (
            {source.removeprefix("src/") for source in telegram_bundle.SOURCES}
            | set(telegram_bundle.PRIVATE_INITIALIZERS)
            | {"__main__.py"}
        )
        assert set(archive.namelist()) == expected
        assert not any("browser/" in entry for entry in expected)
        assert not any("compose." in entry for entry in expected)
        assert not any("release-image" in entry for entry in expected)
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())


def test_host_import_closure_is_available_but_activation_has_no_dispatch(tmp_path: Path) -> None:
    archive = tmp_path / "telegram.pyz"
    telegram_bundle.build(ROOT, archive)
    selftest = subprocess.run(  # noqa: S603 - fixed archive, local process only
        [sys.executable, "-I", "-B", str(archive), "selftest"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert selftest.returncode == 0, selftest.stderr
    assert selftest.stdout.strip() == (
        "BOCA_TELEGRAM_HOST state=CODE_ONLY_CLOSURE_READY host=untouched sender=OFF"
    )
    for attempted in (("activate",), (), ("selftest", "activate")):
        forbidden = subprocess.run(  # noqa: S603 - fixed archive, local process only
            [sys.executable, "-I", "-B", str(archive), *attempted],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert forbidden.returncode == 2
        assert forbidden.stdout.strip() == (
            "BOCA_TELEGRAM_HOST state=NO_GO reason=protected_activation_not_wired sender=OFF"
        )
        assert forbidden.stderr == ""


def test_existing_target_never_overwritten(tmp_path: Path) -> None:
    target = tmp_path / "protected.pyz"
    target.write_bytes(b"owner data")
    with pytest.raises(ValueError, match="fresh"):
        telegram_bundle.build(ROOT, target)
    assert target.read_bytes() == b"owner data"


def test_source_symlink_rejected_without_overriding_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "real.py"
    source.write_text("print('safe')\n", encoding="utf-8")
    (tmp_path / "link.py").symlink_to(source)
    monkeypatch.setattr(telegram_bundle, "SOURCES", ("link.py",))
    destination = tmp_path / "protected.pyz"
    with pytest.raises(ValueError, match="symlink"):
        telegram_bundle.build(tmp_path, destination)
    assert not destination.exists()


def test_oversized_source_rejected_before_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "big.py"
    source.write_bytes(b"X" * (telegram_bundle.MAX_SOURCE_BYTES + 1))
    monkeypatch.setattr(telegram_bundle, "SOURCES", ("big.py",))
    destination = tmp_path / "protected.pyz"
    with pytest.raises(ValueError, match="oversized"):
        telegram_bundle.build(tmp_path, destination)
    assert not destination.exists()
