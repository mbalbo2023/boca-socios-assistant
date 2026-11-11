"""READ_ONLY pair observer never inherits full Cutover payload or dispatch."""

from __future__ import annotations

import hashlib
import io
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import boca_protected_memfd_bootstrap as bootstrap  # noqa: E402
import build_protected_boca_bundle as builder  # noqa: E402


def test_pair_observe_zip_is_deterministic_allowlisted_and_separate(tmp_path):
    first = tmp_path / "pair-one.pyz"
    second = tmp_path / "pair-two.pyz"
    digest = builder.build(ROOT, first, pair_observe=True)
    assert builder.build(ROOT, second, pair_observe=True) == digest
    raw = first.read_bytes()
    assert second.read_bytes() == raw
    assert digest == hashlib.sha256(raw).hexdigest()
    assert len(raw) <= builder.PAIR_MAX_ARCHIVE_BYTES
    bootstrap.verify(raw, digest, pair_observe=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
        names = frozenset(bundle.namelist())
        assert names == bootstrap.PAIR_ENTRIES
        assert names > bootstrap.CENSUS_ENTRIES
        assert "boca_socios/host_boca_pair_observe.py" in names
        assert "boca_socios/host_cutover_inventory_observe.py" in names
        assert "boca_socios/host_first_deploy.py" not in names
        assert "boca_socios/host_boca_transaction.py" not in names
        assert "compose.yaml" not in names
        assert not any(name.startswith("boca_socios/browser/") for name in names)
        assert b"boca-pair-observe" in bundle.read("__main__.py")


def test_pair_observe_zip_cannot_be_reinterpreted_as_census_or_cutover(tmp_path):
    path = tmp_path / "pair.pyz"
    digest = builder.build(ROOT, path, pair_observe=True)
    raw = path.read_bytes()
    with pytest.raises(ValueError):
        bootstrap.verify(raw, digest, census=True)
    with pytest.raises(ValueError):
        bootstrap.verify(raw, digest)
    with pytest.raises(ValueError):
        bootstrap.verify(raw, "0" * 64, pair_observe=True)
    with pytest.raises(ValueError):
        builder.build(ROOT, tmp_path / "bad.pyz", pair_observe=True, census=True)
