"""R252 protected pair transport must carry its actual read-only V2 witness."""

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


def test_r252_pair_archive_includes_exact_postflight_v2_module_and_imports_offline(
    tmp_path: Path,
) -> None:
    target = tmp_path / "r252-pair.pyz"
    digest = builder.build(ROOT, target, pair_upgrade=True)
    raw = target.read_bytes()
    bootstrap.verify(raw, digest, pair_upgrade=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = set(archive.namelist())
        assert names == bootstrap.PAIR_UPGRADE_ENTRIES
        assert "boca_socios/host_boca_postflight_sources_v2.py" in names
        assert "boca_socios/host_boca_success_bridge_v2.py" in names
        assert "boca_socios/host_boca_upgrade_postflight_runtime.py" in names
        assert not any("synthetic.py" in item or "ipc_worker.py" in item for item in names)
        assert len(raw) <= 480_000
        assert sum(info.file_size for info in archive.infolist()) <= 1_400_000

    check = subprocess.run(  # noqa: S603 - exact local Python interpreter and reviewed ZIP
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from boca_socios.host_boca_postflight_sources_v2 "
            "import build_protected_postflight_sources; "
            "from boca_socios.host_boca_success_bridge_v2 "
            "import prepare_success_cleanup; "
            "assert callable(build_protected_postflight_sources); "
            "assert callable(prepare_success_cleanup)",
            str(target),
        ],
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert (check.returncode, check.stdout, check.stderr) == (0, b"", b"")


def test_r252_pair_source_cap_is_strict_and_runner_host_match(tmp_path: Path) -> None:
    assert builder.PAIR_UPGRADE_MAX_SOURCE_BYTES == bootstrap.PAIR_UPGRADE_MAX_UNCOMPRESSED
    assert builder.PAIR_UPGRADE_MAX_SOURCE_BYTES == 1_400_000
    assert builder.PAIR_UPGRADE_MAX_ARCHIVE_BYTES == bootstrap.PAIR_UPGRADE_MAX_ZIP == 480_000

    original = tmp_path / "original.pyz"
    builder.build(ROOT, original, pair_upgrade=True)
    poisoned = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(original.read_bytes())) as trusted,
        zipfile.ZipFile(poisoned, mode="w", compression=zipfile.ZIP_DEFLATED) as untrusted,
    ):
        for entry in trusted.infolist():
            data = trusted.read(entry.filename)
            if entry.filename == "boca_socios/host_boca_pair_upgrade_cli.py":
                data = b"#" * (bootstrap.PAIR_UPGRADE_MAX_UNCOMPRESSED + 1)
            untrusted.writestr(entry, data)
    raw = poisoned.getvalue()
    assert len(raw) < bootstrap.PAIR_UPGRADE_MAX_ZIP
    with pytest.raises(ValueError, match="allowlist|size"):
        bootstrap.verify(raw, hashlib.sha256(raw).hexdigest(), pair_upgrade=True)


def test_r252_pair_compacts_only_comments_when_forced_over_a_tighter_bound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    first = tmp_path / "uncompacted.pyz"
    builder.build(ROOT, first, pair_upgrade=True)
    with zipfile.ZipFile(first) as archive:
        raw_total = sum(item.file_size for item in archive.infolist())
        assert all(
            archive.read(rel.removeprefix("src/")) == (ROOT / rel).read_bytes()
            for rel in builder.PAIR_UPGRADE_SOURCES
        )

    monkeypatch.setattr(builder, "PAIR_UPGRADE_MAX_SOURCE_BYTES", raw_total - 1)
    second = tmp_path / "compacted.pyz"
    builder.build(ROOT, second, pair_upgrade=True)
    with zipfile.ZipFile(second) as archive:
        changed = []
        for rel in builder.PAIR_UPGRADE_SOURCES:
            if not rel.endswith(".py"):
                continue
            original = (ROOT / rel).read_bytes()
            packaged = archive.read(rel.removeprefix("src/"))
            assert compile(packaged, rel, "exec") == compile(original, rel, "exec")
            assert packaged.count(b"\n") == original.count(b"\n")
            if packaged != original:
                changed.append(rel)
        assert changed, "Fallback must actually strip comments without changing execution"
        assert sum(item.file_size for item in archive.infolist()) <= raw_total - 1
