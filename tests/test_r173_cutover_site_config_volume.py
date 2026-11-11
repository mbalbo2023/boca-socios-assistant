"""R173 regressions: exclusive SITE_URL volume follows the cutover attempt.

All Docker responses are synthetic.  No daemon, browser, or external site runs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boca_socios import host_first_deploy as host
from test_host_cutover_adapter import (
    ATTEMPT,
    _prepare_worker,
    _worker_preparation_fake,
)


def test_worker_preparation_creates_site_config_before_creating_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _worker_preparation_fake(monkeypatch)
    original_run = host._run
    original_ipc = host._browser_create_ipc_volume
    events: list[str] = []

    def ipc(image: str, attempt: str) -> None:
        events.append("ipc")
        original_ipc(image, attempt)

    def config(image: str, attempt: str) -> None:
        assert image.endswith("sha256:" + "e" * 64)
        assert attempt == ATTEMPT
        events.append("site_config")

    def run(*args: str, **kwargs: object) -> str:
        if args[:2] == ("docker", "create"):
            events.append("worker_create")
        return original_run(*args, **kwargs)

    monkeypatch.setattr(host, "_browser_create_ipc_volume", ipc)
    monkeypatch.setattr(host, "_browser_create_site_config_volume", config)
    monkeypatch.setattr(host, "_run", run)

    assert _prepare_worker()
    assert events == ["ipc", "site_config", "worker_create"]


def test_cutover_rejects_preexisting_site_config_before_any_new_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _worker_preparation_fake(monkeypatch)
    original_names = host._names
    monkeypatch.setattr(
        host,
        "_names",
        lambda kind, pattern: (
            {host.BROWSER_SITE_CONFIG_VOLUME}
            if kind == "volume" and "boca_site_config" in pattern
            else original_names(kind, pattern)
        ),
    )
    monkeypatch.setattr(
        host, "_cutover_create_browser_egress", lambda *_: pytest.fail("created egress")
    )
    monkeypatch.setattr(host, "_browser_create_ipc_volume", lambda *_: pytest.fail("created IPC"))
    with pytest.raises(host.PreflightError, match="SITE_URL.*already exists"):
        _prepare_worker()


def test_site_config_cleanup_requires_boca_identity_and_no_container_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exists = True
    events: list[str] = []

    def names(kind: str, expression: str) -> set[str]:
        assert kind == "volume" and expression == f"name=^{host.BROWSER_SITE_CONFIG_VOLUME}$"
        return {host.BROWSER_SITE_CONFIG_VOLUME} if exists else set()

    def verify(attempt: str) -> None:
        assert attempt == ATTEMPT
        events.append("identity")

    def run(*args: str, **_kwargs: object) -> str:
        nonlocal exists
        if args[:3] == ("docker", "ps", "-a"):
            assert args[-1] == f"volume={host.BROWSER_SITE_CONFIG_VOLUME}"
            events.append("attachments")
            return ""
        if args[:3] == ("docker", "volume", "rm"):
            assert args[-1] == host.BROWSER_SITE_CONFIG_VOLUME
            events.append("remove")
            exists = False
            return host.BROWSER_SITE_CONFIG_VOLUME
        pytest.fail(f"unexpected Docker command: {args}")

    monkeypatch.setattr(host, "_names", names)
    monkeypatch.setattr(host, "_browser_validate_site_config_volume", verify)
    monkeypatch.setattr(host, "_run", run)
    host._cutover_compensate_site_config_volume(ATTEMPT)
    assert events == ["identity", "attachments", "identity", "remove"]


def test_worker_compensation_cleans_config_only_after_worker_and_before_ipc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    monkeypatch.setattr(host, "_cutover_worker_name_id", lambda: None)
    monkeypatch.setattr(
        host,
        "_cutover_compensate_site_config_volume",
        lambda _: order.append("site"),
        raising=False,
    )
    monkeypatch.setattr(host, "_cutover_compensate_ipc", lambda _: order.append("ipc"))
    monkeypatch.setattr(
        host, "_cutover_compensate_browser_egress", lambda _: order.append("egress")
    )
    host._cutover_compensate_worker(
        "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "e" * 64,
        "b" * 40,
        ATTEMPT,
        "c" * 64,
        b"synthetic",
    )
    assert order == ["site", "ipc", "egress"]


@pytest.mark.parametrize("attached", ["a" * 64, "unverified-id", "two\ncontainers"])
def test_site_config_attached_or_ambiguous_cannot_be_removed(
    monkeypatch: pytest.MonkeyPatch, attached: str
) -> None:
    monkeypatch.setattr(host, "_names", lambda *_: {host.BROWSER_SITE_CONFIG_VOLUME})
    monkeypatch.setattr(host, "_browser_validate_site_config_volume", lambda _: None)

    def run(*args: str, **_kwargs: object) -> str:
        if args[:3] == ("docker", "ps", "-a"):
            return attached
        pytest.fail("attempted removal of an attached or unverified volume")

    monkeypatch.setattr(host, "_run", run)
    with pytest.raises(host.PreflightError, match="attached|unverified"):
        host._cutover_compensate_site_config_volume(ATTEMPT)


@pytest.mark.parametrize("field", ["Name", "Driver", "Scope", "Mountpoint", "Labels"])
def test_site_config_volume_rejects_drift_before_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, field: str
) -> None:
    mount = tmp_path / "volumes" / host.BROWSER_SITE_CONFIG_VOLUME / "_data"
    mount.mkdir(parents=True)
    record: dict[str, object] = {
        "Name": host.BROWSER_SITE_CONFIG_VOLUME,
        "Driver": "local",
        "Scope": "local",
        "Options": None,
        "Mountpoint": str(mount),
        "Labels": {
            "com.docker.compose.project": host.PROJECT,
            "com.docker.compose.volume": "boca_site_config",
            host.BROWSER_ATTEMPT_LABEL: ATTEMPT,
        },
    }
    record[field] = "foreign" if field != "Labels" else {"foreign": "value"}
    monkeypatch.setattr(host, "_checked_docker_storage_dir", lambda: tmp_path)
    monkeypatch.setattr(host, "_run", lambda *_: json.dumps(record))
    with pytest.raises(host.PreflightError, match="SITE_URL volume"):
        host._browser_validate_site_config_volume(ATTEMPT)
