"""SHA-pinned binding reader has one inert entrypoint and exact source closure."""

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


def test_binding_zip_is_deterministic_separate_no_cutover_dispatch(tmp_path):
    one = tmp_path / "binding-a.pyz"
    two = tmp_path / "binding-b.pyz"
    digest = builder.build(ROOT, one, binding_observe=True)
    assert builder.build(ROOT, two, binding_observe=True) == digest
    raw = one.read_bytes()
    assert raw == two.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest
    assert len(raw) <= builder.BINDING_MAX_ARCHIVE_BYTES
    bootstrap.verify(raw, digest, binding_observe=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        names = set(package.namelist())
        assert names == bootstrap.BINDING_ENTRIES
        assert "boca_socios/host_boca_binding_observe.py" in names
        assert "boca_socios/host_on_demand_service.py" in names
        assert "boca_socios/host_boca_pair_observe.py" in names
        assert "boca_socios/host_boca_transaction.py" not in names
        assert "boca_socios/host_boca_cutover.py" not in names
        assert "boca_socios/host_worker_w1.py" not in names
        assert "compose.yaml" not in names
        assert not any("browser/" in name for name in names)
        assert b"boca-binding-observe" in package.read("__main__.py")
    # The ZIP imports successfully in a sandbox as an unprivileged user but
    # never attests host state, since it must be UID10001 at the droplet.
    result = subprocess.run(  # noqa: S603 - fixed offline ZIP selftest arguments
        [sys.executable, "-I", "-B", str(one), "boca-binding-observe", "43066120206"],
        check=False,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 3
    assert result.stdout.startswith(b"BOCA_INSTALLED_BINDING state=NO_GO")
    assert b"Traceback" not in result.stderr


def test_binding_zip_cannot_be_reinterpreted_as_pair_or_full_cutover(tmp_path):
    one = tmp_path / "binding.pyz"
    digest = builder.build(ROOT, one, binding_observe=True)
    raw = one.read_bytes()
    for wrong in ({"pair_observe": True}, {"census": True}, {}):
        with pytest.raises(ValueError):
            bootstrap.verify(raw, digest, **wrong)
    with pytest.raises(ValueError):
        bootstrap.verify(raw, "0" * 64, binding_observe=True)
    with pytest.raises(ValueError):
        builder.build(ROOT, tmp_path / "bad.pyz", binding_observe=True, pair_observe=True)
