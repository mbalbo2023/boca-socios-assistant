"""RCA #275: dedicated rootless bridge probe, never a BETA deployment."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from boca_socios import host_first_deploy as host

SHA = "b" * 40
COMPOSE_SHA = "c" * 64


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("iptables v1.8: Permission denied", "firewall"),
        ("failed to add nftables rules", "firewall"),
        ("could not find an available, non-overlapping IPv4 address pool", "ipam_exhausted"),
        ("Pool overlaps with other one on this address space", "ipam_overlap"),
        ("network with name boca-socios_owner_enroll_private already exists", "already_exists"),
        ("operation not permitted", "permission"),
        ("invalid argument", "invalid_config"),
        ("driver bridge not supported", "unsupported"),
        ("arbitrary sensitive Docker diagnostics", "unclassified"),
    ],
)
def test_probe_only_classifies_known_docker_errors(message: str, code: str) -> None:
    underlying = subprocess.CalledProcessError(
        1,
        ("docker", "network", "create", "boca-socios_owner_enroll_private"),
        stderr=message,
    )
    try:
        raise host.PreflightError("Boca command failed") from underlying
    except host.PreflightError as error:
        assert host._network_probe_error(error) == code


def _probe_environment(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"network": False, "commands": []}

    def names(kind: str, *_args: str) -> set[str]:
        if kind == "volume":
            return {host.OWNER_VOLUME}
        assert kind == "network"
        return {host.ENROLL_NETWORK} if state["network"] else set()

    monkeypatch.setattr(host, "_names", names)
    monkeypatch.setattr(host, "_site_daemon_empty", lambda: None)
    monkeypatch.setattr(host, "collect_snapshot", lambda: object())
    monkeypatch.setattr(host, "validate_site_snapshot", lambda *_args, **_kw: None)
    monkeypatch.setattr(host, "_validate_owner_volume", lambda: None)
    monkeypatch.setattr(host, "_storage_snapshot", lambda: object())
    monkeypatch.setattr(host, "_validate_storage_capacity", lambda *_args: None)
    monkeypatch.setattr(
        host, "_owner_enroll_network", lambda *_args: (
            None if state["network"] else pytest.fail("no network to validate")
        ),
    )
    return state


def test_network_probe_creates_only_exact_boca_bridge_and_cleans(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    state = _probe_environment(monkeypatch)

    def run(*args: str, **kwargs: object) -> str:
        assert not kwargs
        state["commands"].append(args)
        if args[:3] == ("docker", "network", "create"):
            assert args[-1] == host.ENROLL_NETWORK
            assert "--driver" in args
            assert "bridge" in args
            for option, value in host.ENROLL_NETWORK_OPTIONS.items():
                assert (option + "=" + value) in args
            assert "com.docker.compose.project=boca-socios" in args
            assert "com.docker.compose.network=owner_enroll_private" in args
            state["network"] = True
            return "a" * 64
        if args == ("docker", "network", "rm", host.ENROLL_NETWORK):
            assert state["network"] is True
            state["network"] = False
            return host.ENROLL_NETWORK
        pytest.fail(f"unexpected query {args}")

    monkeypatch.setattr(host, "_run", run)
    host._network_probe()
    assert state["network"] is False
    assert len(state["commands"]) == 2
    assert capsys.readouterr().out == (
        "BOCA_NETWORK_PROBE result=PASS reason=none cleanup=VERIFIED\n"
    )


def test_network_probe_classifies_real_denial_without_raw_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    state = _probe_environment(monkeypatch)

    def run(*args: str, **_kw: object) -> str:
        state["commands"].append(args)
        failure = subprocess.CalledProcessError(
            1, args,
            stderr="iptables denied; SECRET_DO_NOT_LOG",
        )
        raise host.PreflightError("docker network failed") from failure

    monkeypatch.setattr(host, "_run", run)
    with pytest.raises(host.PreflightError, match="Boca network probe NO_GO"):
        host._network_probe()
    out = capsys.readouterr()
    assert "result=NO_GO reason=firewall cleanup=VERIFIED" in out.out
    assert "SECRET" not in out.out + out.err
    assert state["network"] is False


def test_network_probe_does_not_remove_unverified_network(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    state = _probe_environment(monkeypatch)
    def run(*args: str, **_kw: object) -> str:
        state["commands"].append(args)
        assert args[:3] == ("docker", "network", "create")
        state["network"] = True
        raise host.PreflightError("network create failed")

    monkeypatch.setattr(host, "_run", run)
    monkeypatch.setattr(
        host, "_owner_enroll_network",
        lambda *_args: (_ for _ in ()).throw(host.PreflightError("unverified identity")),
    )
    with pytest.raises(host.PreflightError, match="Boca network probe NO_GO"):
        host._network_probe()
    assert len(state["commands"]) == 1
    assert "cleanup=INDETERMINATE" in capsys.readouterr().out


def test_network_probe_refuses_nonempty_network_inventory_before_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _probe_environment(monkeypatch)
    monkeypatch.setattr(
        host,
        "_names",
        lambda kind, *_args: ({host.OWNER_VOLUME} if kind == "volume" else {"foreign"}),
    )
    monkeypatch.setattr(host, "_run", lambda *_args: pytest.fail("side effect"))
    with pytest.raises(host.PreflightError, match="namespace"):
        host._network_probe()


def test_network_probe_rejects_private_context_before_daemon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host, "_validate_docker_boundary", lambda: pytest.fail("daemon"))
    with pytest.raises(host.PreflightError, match="unexpected"):
        host.phase(
            "network-probe", "", SHA, COMPOSE_SHA,
            enroll_digest="not-allowed",
        )


def test_network_probe_uses_same_protected_workflow_with_daemon_stop() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
    ).read_text(encoding="utf-8")
    assert "network-probe" in workflow
    assert "Boca rootless network probe" in workflow
    assert "BOCA_NETWORK_PROBE result=" in workflow
    assert "if: always() && inputs.operation == 'network-probe'" in workflow
    assert "src/boca_socios/host_rootless_setup.py" in workflow
    assert "src/boca_socios/host_first_deploy.py" in workflow
    assert "--network=host" not in workflow
    assert "docker system prune" not in workflow
