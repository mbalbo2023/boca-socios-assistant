"""R253 same-lease physical producer imports must survive protected memfd ZIP."""

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

REQUIRED_R253_MODULES = (
    "boca_socios/host_boca_durable_technical_postflight_v2.py",
    "boca_socios/host_boca_postflight_volume_attestor_v2.py",
    "boca_socios/host_boca_successor_assembly_v3.py",
)


def test_r253_pair_bundle_has_only_reviewed_physical_producers(tmp_path: Path) -> None:
    target = tmp_path / "pair-r253.pyz"
    digest = builder.build(ROOT, target, pair_upgrade=True)
    raw = target.read_bytes()
    bootstrap.verify(raw, digest, pair_upgrade=True)

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = set(archive.namelist())
        assert names == bootstrap.PAIR_UPGRADE_ENTRIES
        assert set(REQUIRED_R253_MODULES) <= names
        assert not any("synthetic.py" in item or "ipc_worker.py" in item for item in names)
        assert len(raw) <= 480_000
        assert sum(info.file_size for info in archive.infolist()) <= 1_400_000

    isolated = subprocess.run(  # noqa: S603 - fixed local Python interpreter, ZIP import only
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            "import sys; sys.path.insert(0,sys.argv[1]); "
            "from boca_socios.host_boca_durable_technical_postflight_v2 "
            "import OneShotDurableTechnicalPostflightV2; "
            "from boca_socios.host_boca_postflight_volume_attestor_v2 "
            "import ProductionBocaVolumeAttestor; "
            "from boca_socios.host_boca_successor_assembly_v3 "
            "import prepare_inert_same_lease; "
            "assert callable(OneShotDurableTechnicalPostflightV2); "
            "assert callable(ProductionBocaVolumeAttestor); "
            "assert callable(prepare_inert_same_lease)",
            str(target),
        ],
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert (isolated.returncode, isolated.stdout, isolated.stderr) == (0, b"", b"")


def test_r253_pair_cannot_smuggle_an_extra_source_even_with_recomputed_digest(
    tmp_path: Path,
) -> None:
    target = tmp_path / "trusted.pyz"
    builder.build(ROOT, target, pair_upgrade=True)
    tainted = io.BytesIO()
    with (
        zipfile.ZipFile(target) as trusted,
        zipfile.ZipFile(tainted, "w", compression=zipfile.ZIP_DEFLATED) as modified,
    ):
        for entry in trusted.infolist():
            modified.writestr(entry, trusted.read(entry.filename))
        modified.writestr("boca_socios/browser/ipc_worker.py", b"not allowed")
    raw = tainted.getvalue()
    assert len(raw) < bootstrap.PAIR_UPGRADE_MAX_ZIP
    with pytest.raises(ValueError, match="allowlist"):
        bootstrap.verify(raw, hashlib.sha256(raw).hexdigest(), pair_upgrade=True)
