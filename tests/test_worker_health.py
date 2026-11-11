"""Public health boundary, independent of browser engine implementation."""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def health_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from boca_socios.browser import worker_health

    for name, value in (
        ("memory.max", str(768 * 1024**2)),
        ("pids.max", "128"),
        ("cpu.max", "100000 100000"),
    ):
        (tmp_path / name).write_text(value)
    monkeypatch.setattr(worker_health.os, "geteuid", lambda: 10002)
    monkeypatch.setattr(worker_health.os, "getegid", lambda: 10002)
    monkeypatch.setattr(socket, "if_nameindex", lambda: [(1, "lo"), (2, "eth0")])
    return worker_health, tmp_path


def test_worker_health_accepts_only_public_kernel_and_socket_contract(
    health_boundary, monkeypatch: pytest.MonkeyPatch
) -> None:
    health, cgroup = health_boundary
    checked: list[Path] = []
    monkeypatch.setattr(health, "socket_identity", lambda path: checked.append(path))
    health.check_worker_health(root=cgroup)
    assert checked == [Path("/run/boca-browser-ipc/synthetic.sock")]
    assert not any(
        module in sys.modules
        for module in (
            "boca_socios.browser.on_demand",
            "boca_socios.browser.synthetic",
            "boca_socios.browser.ipc_worker",
        )
    )


@pytest.mark.parametrize("uid,gid", [(0, 10002), (10002, 10001)])
def test_worker_health_refuses_other_identity(health_boundary, monkeypatch, uid: int, gid: int):
    health, cgroup = health_boundary
    monkeypatch.setattr(health.os, "geteuid", lambda: uid)
    monkeypatch.setattr(health.os, "getegid", lambda: gid)
    with pytest.raises(health.WorkerBoundaryError):
        health.check_worker_health(root=cgroup)


@pytest.mark.parametrize(
    "name,value", [("memory.max", "max"), ("pids.max", "129"), ("cpu.max", "101 100")]
)
def test_worker_health_rejects_unbounded_cgroups(health_boundary, name: str, value: str) -> None:
    health, cgroup = health_boundary
    (cgroup / name).write_text(value)
    with pytest.raises(health.WorkerBoundaryError):
        health.check_worker_health(root=cgroup)


@pytest.mark.parametrize(
    "interfaces",
    [
        [],
        [(0, "lo"), (2, "eth0")],
        [(1, "lo")],
        [(1, "eth0")],
        [(1, "lo"), (2, "eth0"), (3, "eth1")],
    ],
)
def test_worker_health_requires_exactly_loopback_and_one_egress(
    health_boundary, monkeypatch, interfaces
):
    health, cgroup = health_boundary
    monkeypatch.setattr(socket, "if_nameindex", lambda: interfaces)
    with pytest.raises(health.WorkerBoundaryError):
        health.check_worker_health(root=cgroup)


def test_worker_health_missing_socket_returns_failure_without_echoing_error(
    health_boundary, monkeypatch, capsys
) -> None:
    health, cgroup = health_boundary

    def missing(_path: Path) -> None:
        raise health.SyntheticIPCError("sensitive-test-exception")

    monkeypatch.setattr(health, "socket_identity", missing)
    with pytest.raises(health.SyntheticIPCError):
        health.check_worker_health(root=cgroup)
    check = health.check_worker_health
    monkeypatch.setattr(health, "check_worker_health", lambda: check(root=cgroup))
    assert health.main() == 1
    captured = capsys.readouterr()
    assert "sensitive-test-exception" not in captured.out + captured.err


def test_health_cli_failure_does_not_import_navigation_or_emit_diagnostics():
    # The import barrier rejects a future regression before any navigation module executes.
    snippet = """
import importlib.abc
import os
import runpy
import sys

class PublicOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname in {
            'boca_socios.browser.on_demand', 'boca_socios.browser.synthetic',
            'boca_socios.browser.ipc_worker'
        }:
            raise AssertionError('public healthcheck imported navigation')

sys.meta_path.insert(0, PublicOnly())
os.geteuid = lambda: 0
runpy.run_module('boca_socios.browser.worker_health', run_name='__main__')
"""
    result = subprocess.run(  # noqa: S603 - fixed local interpreter and public module
        [sys.executable, "-c", snippet], capture_output=True, check=False, timeout=5
    )
    assert result.returncode == 1
    assert result.stdout == b"" and result.stderr == b""
