"""Offline contract: the released, dormant browser uses the AF_UNIX listener."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_lifecycle_runtime_reports_ipc_server_as_expected_worker_command() -> None:
    spec = importlib.util.spec_from_file_location(
        "boca_r173_browser_lifecycle_probe", ROOT / "scripts/check_browser_lifecycle_runtime.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    record = {
        "Config": {
            "Cmd": ["python", "-m", "boca_socios.browser.ipc_server"],
            "Entrypoint": None,
            "Env": [],
        },
        "HostConfig": {},
        "State": {"Running": False, "Status": "exited"},
        "NetworkSettings": {"Networks": {}, "Ports": {}},
    }
    assert (
        module.inspection_summary(record, service="browser-worker")["worker_command_matches"]
        is True
    )
    record["Config"]["Cmd"] = ["python", "-m", "boca_socios.browser.ipc_worker"]
    assert (
        module.inspection_summary(record, service="browser-worker")["worker_command_matches"]
        is False
    )
