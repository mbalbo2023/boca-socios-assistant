"""R34: one reviewed Telegram host ZIP, never an activation authority."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
import zipfile
from dataclasses import asdict
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
            | {"__main__.py", telegram_bundle.NETWORK_PROJECTION_NAME}
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


@pytest.mark.parametrize("installed", [False, True])
def test_on_demand_profile_executes_from_isolated_archive(tmp_path: Path, installed: bool) -> None:
    """Exercise lazy imports using the actual shipped ZIP, without the checkout."""
    from test_host_telegram_postcutover import _on_demand_fake, _pins

    archive = tmp_path / "telegram.pyz"
    telegram_bundle.build(ROOT, archive, installed=installed)
    pins = _pins()
    observed = _on_demand_fake(tmp_path)
    payload = json.dumps(
        {"pins": asdict(pins), "fields": [[list(k), v] for k, v in observed.fields.items()]}
    )
    program = """
import json, sys
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
from boca_socios.host_telegram_postcutover import _stopped_controller_boundary
from boca_socios.host_lifecycle_rootless_adapter import (
    RootlessLifecycleProbe, ReviewedInstalledPair,
)
from boca_socios.host_first_deploy import _browser_worker_egress_network, PreflightError
data = json.load(sys.stdin)
pins = SimpleNamespace(**data['pins'])
values = {tuple(k): v for k, v in data['fields']}
class Reader:
    def field(self, kind, ident, name):
        return values[kind, ident, name]
reader = Reader()
assert _stopped_controller_boundary(reader, pins) is True
pair = ReviewedInstalledPair(pins.browser_attempt, pins.controller_config_hash,
                             pins.worker_config_hash)
probe = RootlessLifecycleProbe(pair, reader, on_demand=True)
probe._service_boundary(pins.worker_id, 'browser-worker', pins.worker_image)
for invalid in ({}, {'foreign': {}},
                {'boca-socios_boca_browser_egress': {'IPAddress': '127.0.0.1'}},
                {'boca-socios_boca_browser_egress': {'IPAddress': ''}}):
    try:
        _browser_worker_egress_network(invalid)
    except PreflightError:
        pass
    else:
        raise AssertionError('unsafe egress accepted')
assert 'boca_socios.host_boca_transaction' not in sys.modules
assert 'boca_socios.host_boca_cutover' not in sys.modules
print('R295_TELEGRAM_PROFILE_IMPORT_READY')
"""
    result = subprocess.run(  # noqa: S603 - fixed offline program and generated archive
        [sys.executable, "-I", "-S", "-B", "-c", program, str(archive)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "R295_TELEGRAM_PROFILE_IMPORT_READY\n"
    assert result.stderr == ""


def test_network_projection_keeps_canonical_nodes_without_deploy_entrypoints(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "telegram.pyz"
    telegram_bundle.build(ROOT, archive)
    with zipfile.ZipFile(archive) as packed:
        projected = ast.parse(packed.read("boca_socios/host_first_deploy.py"))
        assert sum(entry.file_size for entry in packed.infolist()) <= 450_000
    original = ast.parse((ROOT / "src/boca_socios/host_first_deploy.py").read_bytes())

    def key(node: ast.stmt) -> str | None:
        if isinstance(node, ast.Import) and len(node.names) == 1:
            return node.names[0].name
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            return target.id if isinstance(target, ast.Name) else None
        return node.name if isinstance(node, (ast.ClassDef, ast.FunctionDef)) else None

    expected = {
        "ipaddress",
        "BROWSER_EGRESS_BRIDGE",
        "PreflightError",
        "_browser_worker_egress_network",
    }
    assert len(projected.body) == len(expected)
    assert {key(node) for node in projected.body} == expected
    canonical = {key(node): ast.dump(node) for node in original.body if key(node) in expected}
    assert {key(node): ast.dump(node) for node in projected.body} == canonical


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
