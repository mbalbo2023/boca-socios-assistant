"""Restart a stopped, previously reviewed dedicated Boca daemon only."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import call, patch

import pytest

from boca_socios import host_rootless_setup as host

HOME = Path("/home/boca-deploy")
SHA = "a" * 40
CONTAINER = "b" * 64


def _metadata(*, count: int = 1) -> str:
    return json.dumps(
        {
            "SecurityOptions": ["name=rootless"],
            "DockerRootDir": str(HOME.joinpath(*host.DATA)),
            "CgroupVersion": "2",
            "CgroupDriver": "systemd",
            "Driver": "overlay2",
            "Containers": count,
        }
    )


def _container(service: str = "controller", *, running: bool = False) -> str:
    return json.dumps(
        {
            "Id": CONTAINER,
            "Name": f"/boca-socios-{service}-1",
            "Config": {
                "Labels": {
                    "com.docker.compose.project": "boca-socios",
                    "com.docker.compose.service": service,
                    "com.docker.compose.container-number": "1",
                }
            },
            "State": {"Running": running},
        }
    )


def _ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "_identity", lambda: HOME)
    monkeypatch.setattr(host, "_directory", lambda *_args, **_kwargs: 3)
    monkeypatch.setattr(host.os, "close", lambda _fd: None)
    monkeypatch.setattr(host, "_socket", lambda _path: None)
    monkeypatch.setattr(host, "_read_private", lambda *_args: None)
    monkeypatch.setattr(host, "_entry", lambda *_args: None)
    monkeypatch.setattr(host.os, "access", lambda *_args: False)
    monkeypatch.setattr(host, "_stop_service_state", lambda _home: "inactive")


def test_start_existing_validates_exact_install_and_stopped_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ready(monkeypatch)
    with patch.object(
        host,
        "_command",
        side_effect=[
            "yes",
            "",
            "ActiveState=active\nSubState=running",
            _metadata(),
            CONTAINER,
            _container(),
        ],
    ) as command:
        host.start_existing(SHA)
    assert call(HOME, "/usr/bin/systemctl", "--user", "start", "docker.service", timeout=50) in command.call_args_list
    assert all("stop" not in invocation.args for invocation in command.call_args_list)


def test_start_existing_rejects_missing_enablement_before_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ready(monkeypatch)
    monkeypatch.setattr(host, "_entry", lambda *_args: None)
    with patch.object(host, "_command") as command:
        with pytest.raises(host.SetupError):
            host.start_existing(SHA)
    assert all("start" not in invocation.args for invocation in command.call_args_list)


def test_start_existing_rejects_unknown_container_after_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ready(monkeypatch)
    monkeypatch.setattr(host, "_verified_enablement", lambda _home: None)
    with patch.object(
        host,
        "_command",
        side_effect=["yes", "", "ActiveState=active\nSubState=running", _metadata(), CONTAINER, _container("other")],
    ) as command:
        with pytest.raises(host.SetupError, match="unknown_container_preserved_no_stop"):
            host.start_existing(SHA)
    assert all("stop" not in invocation.args for invocation in command.call_args_list)


def test_start_existing_rejects_active_service_before_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ready(monkeypatch)
    monkeypatch.setattr(host, "_verified_enablement", lambda _home: None)
    monkeypatch.setattr(host, "_stop_service_state", lambda _home: "active")
    with patch.object(host, "_command", return_value="yes") as command:
        with pytest.raises(host.SetupError, match="already_active"):
            host.start_existing(SHA)
    assert all("start" not in invocation.args for invocation in command.call_args_list)
