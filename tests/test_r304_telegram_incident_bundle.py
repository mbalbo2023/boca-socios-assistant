"""Incident archive mode is independently bounded and mutually exclusive."""

import hashlib
import importlib
import io
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from test_r304_telegram_incident_readonly import RUN, WORKFLOW, scenario
from test_r304_telegram_incident_workflow import classification_from_real_step
from test_r307_telegram_incident_continuation import CURRENT, current_scenario

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
bootstrap = importlib.import_module("boca_protected_memfd_bootstrap")
builder = importlib.import_module("build_protected_boca_bundle")


def test_incident_bundle_exclusive_bounds_and_exact_closure():
    assert (ROOT / "src/boca_socios/host_telegram_incident_readonly.py").stat().st_size <= 24000
    assert builder.TELEGRAM_INCIDENT_MAX_SOURCE_BYTES == 900000
    assert builder.TELEGRAM_INCIDENT_MAX_ARCHIVE_BYTES == 320000
    assert len(bootstrap.TELEGRAM_INCIDENT_ENTRIES) == 29
    assert "boca_socios/telegram_maintenance_contract.py" in bootstrap.TELEGRAM_INCIDENT_ENTRIES
    with pytest.raises(ValueError, match="exclusive"):
        builder.build(
            ROOT,
            Path("/unreachable/incident.pyz"),
            telegram_incident_observe=True,
            binding_observe=True,
        )


def test_incident_source_cap_never_inherits_full_cutover_compaction(tmp_path):
    for relative in builder.TELEGRAM_INCIDENT_SOURCES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"pass\n")
    oversized = tmp_path / "src/boca_socios/host_boca_cleanup.py"
    oversized.write_bytes(b"#" + b" " * 899997 + b"\n")
    with pytest.raises(ValueError, match="total exceeds"):
        builder.build(tmp_path, tmp_path / "no-incident.pyz", telegram_incident_observe=True)
    assert not (tmp_path / "no-incident.pyz").exists()


def test_incident_real_zip_cli_and_workflow_classify_complete_and_incomplete(tmp_path, monkeypatch):
    bundle = tmp_path / "incident.pyz"
    digest = builder.build(ROOT, bundle, telegram_incident_observe=True)
    raw = bundle.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest
    bootstrap.verify(raw, digest, telegram_incident_observe=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        assert len(package.infolist()) == 29
        assert set(package.namelist()) == bootstrap.TELEGRAM_INCIDENT_ENTRIES
        source_bytes = sum(entry.file_size for entry in package.infolist())
        assert source_bytes <= 900000 and len(raw) <= 320000
        assert (
            package.read("boca_socios/host_telegram_incident_readonly.py")
            == (ROOT / "src/boca_socios/host_telegram_incident_readonly.py").read_bytes()
        )
    for options in ({"binding_observe": True}, {"telegram_installed": True}):
        with pytest.raises(ValueError, match="allowlist"):
            bootstrap.verify(raw, digest, **options)
    with pytest.raises(ValueError, match="SHA/size"):
        bootstrap.verify(raw, "0" * 64, telegram_incident_observe=True)
    observer, _ = current_scenario(monkeypatch)
    complete = observer.observe(RUN, WORKFLOW, CURRENT)
    observer, _ = current_scenario(monkeypatch, fault="binding")
    incomplete = observer.observe(RUN, WORKFLOW, CURRENT)
    observer, _ = scenario(monkeypatch)
    historical = observer.observe(RUN, WORKFLOW)
    assert observer.verify(historical, RUN, WORKFLOW) == historical
    command = [
        sys.executable,
        "-I",
        "-S",
        "-B",
        "-c",
        "import sys; sys.path.insert(0,sys.argv.pop(1)); "
        "from boca_socios.host_telegram_incident_readonly import main; raise SystemExit(main())",
        str(bundle),
        "verify",
        RUN,
        WORKFLOW,
    ]
    for receipt, expected in ((complete, 0), (incomplete, 3)):
        result = subprocess.run(  # noqa: S603 - stdlib-only ZIP and synthetic receipt
            command, input=receipt, cwd=tmp_path, capture_output=True, check=False, timeout=10
        )
        assert result.returncode == expected and result.stdout == receipt and not result.stderr
    result = subprocess.run(  # noqa: S603 - current CLI rejects historical coordinates
        command, input=historical, cwd=tmp_path, capture_output=True, check=False, timeout=10
    )
    assert result.returncode == 3 and result.stdout != historical and not result.stderr
    for index, (receipt, remote_rc, expected, canonical) in enumerate(
        (
            (complete, 0, 0, True),
            (incomplete, 3, 1, True),
            (complete, 255, 1, False),
            (incomplete, 0, 1, False),
            (b"PRIVATE_UNTRUSTED\n", 0, 1, False),
            (complete.replace(WORKFLOW.encode(), b"b" * 40), 0, 1, False),
            (historical, 0, 1, False),
        )
    ):
        status, summary = classification_from_real_step(
            bundle, receipt, remote_rc, tmp_path / str(index), RUN, WORKFLOW
        )
        assert status == expected
        assert summary == receipt if canonical else b"phase=TRANSPORT reason=UNVERIFIED" in summary
        assert b"PRIVATE_UNTRUSTED" not in summary
    print(
        f"R304_PACKAGE path={bundle} entries=29 source_bytes={source_bytes} "
        f"zip_bytes={len(raw)} sha256={digest}"
    )
