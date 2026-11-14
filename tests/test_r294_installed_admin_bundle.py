"""Administration has a separate sealed transport, without deploy entrypoints."""

import zipfile
from pathlib import Path

import pytest

from test_r294_current_retained_bundle import ROOT, bootstrap, builder, import_only


def test_admin_and_current_status_use_one_exact_bounded_bundle(tmp_path: Path):
    target = tmp_path / "admin.pyz"
    digest = builder.build(ROOT, target, installed_admin=True)
    raw = target.read_bytes()
    bootstrap.verify(raw, digest, installed_admin=True)
    with zipfile.ZipFile(target) as archive:
        assert set(archive.namelist()) == bootstrap.INSTALLED_ADMIN_ENTRIES
        assert "boca_socios/host_boca_installed_admin.py" in archive.namelist()
        assert "boca_socios/host_on_demand_status.py" in archive.namelist()
        assert "compose.beta.yaml" not in archive.namelist()
        assert "boca_socios/host_boca_pair_upgrade.py" not in archive.namelist()
        assert not any("browser/" in name for name in archive.namelist())
        main = archive.read("__main__.py")
        assert b"boca-installed-status-observe" in main
        assert b"boca-installed-admin-provision" in main
        assert b"controller" not in main
    for wrong in ({}, {"binding_observe": True}, {"current_retained_observe": True}):
        with pytest.raises(ValueError):
            bootstrap.verify(raw, digest, **wrong)
    import_only(target, "boca_socios.host_boca_installed_admin")
    import_only(target, "boca_socios.host_on_demand_status")
