"""A proposed host probe may touch only disposable loopback synthetic state."""

import socket
from pathlib import Path

from boca_socios.acceptance import host_probe
from boca_socios.acceptance.host_probe import ProbeReceipt, _run_probe, main


def test_verified_tls_journey_is_disposable_and_uses_only_loopback(
    tmp_path: Path, monkeypatch
) -> None:
    actual_db = tmp_path / "production-boca.sqlite3"
    actual_key = tmp_path / "production-key"
    actual_owner = tmp_path / "production-owner"
    for file in (actual_db, actual_key, actual_owner):
        file.write_bytes(b"sentinel-must-remain-untouched")
    monkeypatch.setenv("BOCA_DB_PATH", str(actual_db))
    monkeypatch.setenv("BOCA_MASTER_KEY_FILE", str(actual_key))
    monkeypatch.setenv("BOCA_PASSKEY_CREDENTIAL_ID_FILE", str(actual_owner))
    monkeypatch.setenv("BOCA_SITE_BRIDGE_MODE", "poll")
    destinations: list[tuple[str, int]] = []
    original = socket.create_connection

    def loopback_only(address: tuple[str, int], timeout: float):
        destinations.append(address)
        assert address[0] == "127.0.0.1"
        return original(address, timeout=timeout)

    monkeypatch.setattr(socket, "create_connection", loopback_only)
    receipt = _run_probe(tmp_path)
    assert receipt.requests >= 18
    assert receipt.median_ms > 0 and receipt.p95_ms > 0
    assert receipt.intents == receipt.members == receipt.notices == 1
    assert receipt.cpu_ms >= 0 and receipt.process_peak_rss_kib > 0
    assert 0 < receipt.scratch_bytes <= 8 * 1024 * 1024
    assert destinations and {host for host, _port in destinations} == {"127.0.0.1"}
    assert all(
        file.read_bytes() == b"sentinel-must-remain-untouched"
        for file in (actual_db, actual_key, actual_owner)
    )
    assert sorted(item.name for item in tmp_path.iterdir()) == sorted(
        (actual_db.name, actual_key.name, actual_owner.name)
    )


def test_cli_refuses_wrong_identity_and_engine_before_creating_material(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr("boca_socios.acceptance.host_probe.os.geteuid", lambda: 0)
    monkeypatch.setenv("BOCA_RUNTIME_MODE", "simulation")
    monkeypatch.setenv("BOCA_ENGINE_MODE", "off")
    assert main() == 1
    assert "state=NO_GO" in capsys.readouterr().out
    monkeypatch.setattr("boca_socios.acceptance.host_probe.os.geteuid", lambda: 10001)
    monkeypatch.setenv("BOCA_ENGINE_MODE", "on")
    assert main() == 1
    assert "state=NO_GO" in capsys.readouterr().out


def test_cli_pass_receipt_uses_fixed_tmp(monkeypatch, capsys) -> None:
    monkeypatch.setattr(host_probe.os, "geteuid", lambda: 10001)
    for key, value in {
        "BOCA_ENVIRONMENT": "staging",
        "BOCA_RUNTIME_MODE": "simulation",
        "BOCA_ENGINE_MODE": "off",
        "BOCA_DB_PATH": "/data/boca.sqlite3",
    }.items():
        monkeypatch.setenv(key, value)
    roots: list[Path] = []

    def fake_probe(root: Path) -> ProbeReceipt:
        roots.append(root)
        return ProbeReceipt(21, 1.0, 2.0, 100.0, 30.0, 15000, 12345, 1, 1, 1)

    monkeypatch.setattr(host_probe, "_run_probe", fake_probe)
    assert main() == 0
    line = capsys.readouterr().out
    assert roots == [Path("/tmp")]  # noqa: S108 - verifies fixed container tmpfs
    assert "state=PASS scope=container_loopback" in line
    assert "members=1 intents=1 notices=1" in line
