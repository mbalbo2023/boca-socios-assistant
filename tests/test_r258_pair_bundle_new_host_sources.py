"""R258 physical pair transport must contain the reviewed R255/R257 readers."""

from __future__ import annotations

import ast
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

REVIEWED_PAIR_HOST_MODULES = (
    "boca_socios/host_boca_prepark_expected_v2.py",
    "boca_socios/host_boca_rootless_mapped_custody.py",
    "boca_socios/host_boca_technical_terminal_bridge_v3.py",
    "boca_socios/host_boca_guarded_successor_backend_v4.py",
)


def _reviewed_pair(tmp_path: Path) -> tuple[Path, bytes, str]:
    path = tmp_path / "pair-r258.pyz"
    digest = builder.build(ROOT, path, pair_upgrade=True)
    raw = path.read_bytes()
    bootstrap.verify(raw, digest, pair_upgrade=True)
    return path, raw, digest


def test_r258_new_readers_are_importable_from_the_exact_verified_memfd_archive(
    tmp_path: Path,
) -> None:
    path, raw, digest = _reviewed_pair(tmp_path)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = set(archive.namelist())
        assert names == bootstrap.PAIR_UPGRADE_ENTRIES
        assert set(REVIEWED_PAIR_HOST_MODULES) <= names
        assert not any("synthetic.py" in name or "ipc_worker.py" in name for name in names)
        assert len(raw) <= 480_000
        assert sum(item.file_size for item in archive.infolist()) <= 1_500_000
        for name in REVIEWED_PAIR_HOST_MODULES:
            original = (ROOT / "src" / name).read_bytes()
            bundled = archive.read(name)
            # Comment-only compaction must not change executable semantics or lines.
            assert ast.dump(ast.parse(bundled)) == ast.dump(ast.parse(original))
            assert compile(bundled, name, "exec") == compile(original, name, "exec")
            assert bundled.count(b"\n") == original.count(b"\n")

    check = subprocess.run(  # noqa: S603 - reviewed ZIP, isolated local Python, imports only
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from boca_socios.host_boca_prepark_expected_v2 "
            "import capture_prepark_expected_seed; "
            "from boca_socios.host_boca_rootless_mapped_custody "
            "import observe_boca_mapped_file_custody; "
            "from boca_socios.host_boca_technical_terminal_bridge_v3 "
            "import OneShotTechnicalTerminalBridge; "
            "from boca_socios.host_boca_guarded_successor_backend_v4 "
            "import GuardedTechnicalSuccessorBackend; "
            "assert callable(capture_prepark_expected_seed); "
            "assert callable(observe_boca_mapped_file_custody); "
            "assert callable(OneShotTechnicalTerminalBridge); "
            "assert callable(GuardedTechnicalSuccessorBackend)",
            str(path),
        ],
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert (check.returncode, check.stdout, check.stderr) == (0, b"", b"")
    again = tmp_path / "pair-r258-again.pyz"
    assert builder.build(ROOT, again, pair_upgrade=True) == digest
    assert again.read_bytes() == raw


@pytest.mark.parametrize("missing", REVIEWED_PAIR_HOST_MODULES)
def test_r258_recomputed_zip_hash_cannot_hide_a_missing_reviewed_host_module(
    tmp_path: Path, missing: str
) -> None:
    _, raw, _ = _reviewed_pair(tmp_path)
    modified = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(raw)) as trusted,
        zipfile.ZipFile(modified, "w", compression=zipfile.ZIP_DEFLATED) as tampered,
    ):
        for entry in trusted.infolist():
            if entry.filename != missing:
                tampered.writestr(entry, trusted.read(entry.filename))
    changed = modified.getvalue()
    assert len(changed) < 480_000
    with pytest.raises(ValueError, match="allowlist"):
        bootstrap.verify(changed, hashlib.sha256(changed).hexdigest(), pair_upgrade=True)


def test_r258_pair_rejects_exactly_one_byte_above_1500000_even_with_matching_digest(
    tmp_path: Path,
) -> None:
    _, raw, _ = _reviewed_pair(tmp_path)
    modified = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(raw)) as original,
        zipfile.ZipFile(modified, "w", compression=zipfile.ZIP_DEFLATED) as changed,
    ):
        for entry in original.infolist():
            data = original.read(entry.filename)
            if entry.filename == "boca_socios/host_boca_pair_upgrade_cli.py":
                # Other members must remain nonempty; exact aggregate +1.
                others = sum(
                    i.file_size for i in original.infolist() if i.filename != entry.filename
                )
                data = b"#" * (1_500_001 - others)
            changed.writestr(entry, data)
    tampered = modified.getvalue()
    with zipfile.ZipFile(io.BytesIO(tampered)) as archive:
        assert sum(item.file_size for item in archive.infolist()) == 1_500_001
    assert len(tampered) < 480_000
    with pytest.raises(ValueError, match="allowlist|size"):
        bootstrap.verify(tampered, hashlib.sha256(tampered).hexdigest(), pair_upgrade=True)


def test_r258_pair_rejects_high_ratio_zip_bomb_with_recomputed_digest(tmp_path: Path) -> None:
    _, raw, _ = _reviewed_pair(tmp_path)
    modified = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(raw)) as original,
        zipfile.ZipFile(modified, "w", compression=zipfile.ZIP_DEFLATED) as changed,
    ):
        for entry in original.infolist():
            data = original.read(entry.filename)
            if entry.filename.endswith(".py"):
                data = b"X" * len(data)
            changed.writestr(entry, data)
    tampered = modified.getvalue()
    with zipfile.ZipFile(io.BytesIO(tampered)) as archive:
        expanded = sum(item.file_size for item in archive.infolist())
    assert expanded <= 1_500_000
    assert expanded > len(tampered) * 8
    with pytest.raises(ValueError, match="compression ratio"):
        bootstrap.verify(tampered, hashlib.sha256(tampered).hexdigest(), pair_upgrade=True)


def test_r258_pair_preserves_50000_source_bytes_for_variable_authenticated_receipts(
    tmp_path: Path,
) -> None:
    _, raw, _ = _reviewed_pair(tmp_path)
    modified = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(raw)) as original,
        zipfile.ZipFile(modified, "w", compression=zipfile.ZIP_DEFLATED) as changed,
    ):
        others = sum(
            item.file_size
            for item in original.infolist()
            if item.filename != "boca_socios/host_boca_pair_upgrade_cli.py"
        )
        for entry in original.infolist():
            data = original.read(entry.filename)
            if entry.filename == "boca_socios/host_boca_pair_upgrade_cli.py":
                data = b"#" * (1_450_001 - others)
            changed.writestr(entry, data)
    tampered = modified.getvalue()
    with zipfile.ZipFile(io.BytesIO(tampered)) as archive:
        assert sum(item.file_size for item in archive.infolist()) == 1_450_001
    assert len(tampered) < 480_000
    with pytest.raises(ValueError, match="reserve"):
        bootstrap.verify(tampered, hashlib.sha256(tampered).hexdigest(), pair_upgrade=True)


def test_r258_pair_compacts_comments_before_exhausting_authenticated_receipt_reserve(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Force the reserve path with otherwise-valid source; no executable text
    # may change to make a physical evidence receipt fit.
    monkeypatch.setattr(builder, "PAIR_UPGRADE_MIN_SOURCE_RESERVE", 80_000, raising=False)
    target = tmp_path / "reserve-compacted.pyz"
    digest = builder.build(ROOT, target, pair_upgrade=True)
    raw = target.read_bytes()
    bootstrap.verify(raw, digest, pair_upgrade=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert sum(info.file_size for info in archive.infolist()) <= 1_500_000 - 80_000
        assert any(
            archive.read(path.removeprefix("src/")) != (ROOT / path).read_bytes()
            for path in builder.PAIR_UPGRADE_SOURCES
            if path.endswith(".py")
        )
