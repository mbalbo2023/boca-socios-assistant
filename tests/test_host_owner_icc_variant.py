"""Issue #275: preserve probes while enabling Boca-only owner enrollment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from boca_socios import host_first_deploy as host

SHA = "d" * 40
COMPOSE_SHA = "c" * 64


def _empty_owner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    state: dict[str, Any] = {"network": False, "commands": [], "validated": []}
    monkeypatch.setattr(host, "ROOT", tmp_path)
    monkeypatch.setattr(host, "_safe_dir", lambda *_args: True)
    monkeypatch.setattr(host, "_site_daemon_empty", lambda: None)
    monkeypatch.setattr(host, "collect_snapshot", lambda: object())
    monkeypatch.setattr(host, "validate_site_snapshot", lambda *_args, **_kw: None)
    monkeypatch.setattr(host, "_validate_owner_volume", lambda: None)
    monkeypatch.setattr(host, "_storage_snapshot", lambda: object())
    monkeypatch.setattr(host, "_validate_storage_capacity", lambda *_args: None)

    def names(kind: str, *_args: str) -> set[str]:
        if kind == "volume":
            return {host.OWNER_VOLUME}
        assert kind == "network"
        return {host.ENROLL_NETWORK} if state["network"] else set()

    def checked_network(container: str, *, icc_true: bool = False) -> None:
        assert container == ""
        assert icc_true is True
        assert state["network"]
        state["validated"].append(icc_true)

    monkeypatch.setattr(host, "_names", names)
    monkeypatch.setattr(host, "_owner_enroll_network", checked_network)
    return state


def test_icc_true_probe_is_single_unused_boca_network_and_is_removed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    state = _empty_owner(monkeypatch, tmp_path)

    def run(*args: str, **kwargs: object) -> str:
        assert not kwargs
        state["commands"].append(args)
        if args[:3] == ("docker", "network", "create"):
            assert args[-1] == host.ENROLL_NETWORK
            assert "--driver" in args and "bridge" in args
            assert "com.docker.network.bridge.enable_icc=true" in args
            assert "com.docker.network.bridge.enable_icc=false" not in args
            assert "com.docker.network.bridge.enable_ip_masquerade=false" in args
            assert "com.docker.network.bridge.host_binding_ipv4=127.0.0.1" in args
            assert "com.docker.compose.project=boca-socios" in args
            assert "com.docker.compose.network=owner_enroll_private" in args
            state["network"] = True
            return "a" * 64
        assert args == ("docker", "network", "rm", host.ENROLL_NETWORK)
        assert state["network"]
        state["network"] = False
        return host.ENROLL_NETWORK

    monkeypatch.setattr(host, "_run", run)
    host._network_probe(icc_true=True)
    assert state["network"] is False
    assert state["validated"] == [True, True]
    assert len(state["commands"]) == 2
    assert (
        capsys.readouterr().out == "BOCA_NETWORK_PROBE result=PASS reason=none cleanup=VERIFIED\n"
    )


def test_icc_true_probe_rejects_private_context_before_any_daemon_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host, "_validate_docker_boundary", lambda: pytest.fail("daemon"))
    with pytest.raises(host.PreflightError, match="unexpected"):
        host.phase("network-probe-icc-true", "", SHA, COMPOSE_SHA, enroll_digest="forbidden")


@pytest.mark.parametrize("tamper", ["none", "icc_false", "foreign_peer", "foreign_label"])
def test_icc_true_inspect_requires_exact_unused_boca_network(
    monkeypatch: pytest.MonkeyPatch, tamper: str
) -> None:
    network: dict[str, Any] = {
        "Name": host.ENROLL_NETWORK,
        "Driver": "bridge",
        "Internal": False,
        "Options": dict(host.PROBE_ICC_TRUE_OPTIONS),
        "Labels": {
            "com.docker.compose.project": host.PROJECT,
            "com.docker.compose.network": "owner_enroll_private",
        },
        "Containers": {},
    }
    if tamper == "icc_false":
        network["Options"] = dict(host.ENROLL_NETWORK_OPTIONS)
    elif tamper == "foreign_peer":
        network["Containers"] = {"foreign": {}}
    elif tamper == "foreign_label":
        network["Labels"] = {"com.docker.compose.project": "foreign"}

    def run(*args: str) -> str:
        assert args == (
            "docker",
            "network",
            "inspect",
            "--format",
            "{{json .}}",
            host.ENROLL_NETWORK,
        )
        return json.dumps(network)

    monkeypatch.setattr(host, "_names", lambda kind, *_args: {host.ENROLL_NETWORK})
    monkeypatch.setattr(host, "_run", run)
    if tamper == "none":
        host._owner_enroll_network("", icc_true=True)
    else:
        with pytest.raises(host.PreflightError, match="network isolation unverified"):
            host._owner_enroll_network("", icc_true=True)


def test_valid_icc_true_phase_cannot_change_owner_enrollment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[bool] = []
    monkeypatch.setattr(host, "_validate_coordinates", lambda *_args, **_kw: None)
    monkeypatch.setattr(host, "_validate_docker_boundary", lambda: None)
    monkeypatch.setattr(host, "_network_probe", lambda *, icc_true=False: seen.append(icc_true))
    host.phase("network-probe-icc-true", "", SHA, COMPOSE_SHA)
    assert seen == [True]


def test_icc_true_probe_and_real_owner_use_only_private_boca_bridges() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/boca-first-deploy.yml").read_text(encoding="utf-8")
    source = (root / "src/boca_socios/host_first_deploy.py").read_text(encoding="utf-8")
    assert "network-probe-icc-true" in workflow
    assert "network-probe-icc-true-cleanup" in workflow
    assert "network-probe-icc-true" in source
    assert "startsWith(inputs.operation, 'network-probe')" in workflow
    assert "BOCA_NETWORK_PROBE result=" in workflow
    assert "com.docker.network.bridge.enable_icc=false" in source  # legacy probe
    assert "com.docker.network.bridge.enable_icc=true" in source  # owner start
    assert "com.docker.network.bridge.enable_icc=true" in workflow  # owner smoke
    assert "--network=host" not in workflow
    assert "docker system prune" not in workflow
