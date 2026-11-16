"""G3b V3 protected bundle is disjoint from historic host-only binding."""

import hashlib
import importlib.util
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


def _load(name: str):
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


memfd = _load("boca_protected_memfd_bootstrap")
builder = _load("build_protected_boca_bundle")


def test_separate_v3_bundle_variant(tmp_path: Path) -> None:
    # The W tool package must have its own selector and exact entrypoint.
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(  # noqa: S603 - fixed, reviewed local builder CLI
        [
            sys.executable,
            str(root / "scripts/build_protected_boca_bundle.py"),
            "--public-recipient-metadata-observe",
            str(root),
            str(tmp_path / "public-recipient.pyz"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    artifact = tmp_path / "public-recipient.pyz"
    assert artifact.is_file()
    raw = artifact.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    with zipfile.ZipFile(artifact) as archive:
        items = archive.infolist()
        assert len(items) == len(memfd.PUBLIC_RECIPIENT_METADATA_ENTRIES)
        assert {item.filename for item in items} == memfd.PUBLIC_RECIPIENT_METADATA_ENTRIES
        assert "boca_socios/host_telegram_status.py" not in archive.namelist()
        assert "boca_socios/host_telegram_cli.py" not in archive.namelist()
        assert 0 < sum(item.file_size for item in items) <= 900_000
        assert 0 < len(raw) <= 320_000
        assert b"boca-public-recipient-metadata-observe" in archive.read("__main__.py")
    memfd.verify(raw, digest, public_recipient_metadata_observe=True)
    with pytest.raises(ValueError):
        memfd.verify(raw, digest, binding_observe=True)
    with pytest.raises(ValueError):
        memfd.verify(raw, "0" * 64, public_recipient_metadata_observe=True)
    with pytest.raises(ValueError):
        memfd.verify(raw, digest, public_recipient_metadata_observe=True, binding_observe=True)
    assert builder.BINDING_MAIN != builder.PUBLIC_RECIPIENT_METADATA_MAIN
    assert len(builder.PUBLIC_RECIPIENT_METADATA_SOURCES) == len(builder.BINDING_SOURCES) + 1


def test_historical_binding_bundle_does_not_admit_v3(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(  # noqa: S603 - fixed, reviewed local builder CLI
        [
            sys.executable,
            str(root / "scripts/build_protected_boca_bundle.py"),
            "--binding-observe",
            "--public-recipient-metadata-observe",
            str(root),
            str(tmp_path / "invalid.pyz"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode != 0
    assert not (tmp_path / "invalid.pyz").exists()
