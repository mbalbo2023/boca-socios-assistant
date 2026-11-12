"""Regression contract for Boca-only owner enrollment ICC compatibility (#275).

This test deliberately does not launch the real site or read owner browser blackboxes.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from boca_socios import host_cleanup as cleanup
from boca_socios import host_first_deploy as host


def test_owner_network_options_do_not_change_legacy_diagnostics() -> None:
    flag = "com.docker.network.bridge.enable_icc"
    assert host.ENROLL_NETWORK_OPTIONS[flag] == "false"
    assert host.PROBE_ICC_TRUE_OPTIONS[flag] == "true"
    assert host.OWNER_ENROLL_NETWORK_OPTIONS == host.PROBE_ICC_TRUE_OPTIONS
    assert cleanup.ENROLL_NETWORK_OPTIONS == host.OWNER_ENROLL_NETWORK_OPTIONS
    assert host.OWNER_ENROLL_NETWORK_OPTIONS == {
        **host.ENROLL_NETWORK_OPTIONS,
        flag: "true",
    }
    assert (
        host.OWNER_ENROLL_NETWORK_OPTIONS["com.docker.network.bridge.enable_ip_masquerade"]
        == "false"
    )
    assert (
        host.OWNER_ENROLL_NETWORK_OPTIONS["com.docker.network.bridge.host_binding_ipv4"]
        == "127.0.0.1"
    )


def test_owner_enrollment_changes_only_its_private_docker_network() -> None:
    source = inspect.getsource(host._owner_enroll_start)
    assert '"com.docker.network.bridge.enable_icc=true"' in source
    assert '"com.docker.network.bridge.enable_icc=false"' not in source
    assert '_owner_enroll_network("", icc_true=True)' in source
    for forbidden in ("modprobe", "iptables", "sysctl", "--network=host"):
        assert forbidden not in source


def test_owner_enrollment_smoke_matches_real_private_network() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    segment = workflow.split("Smoke disposable Chrome listener and offline staged owner import", 1)[
        1
    ].split("Exercise sealed Telegram custody", 1)[0]
    assert "--opt com.docker.network.bridge.enable_icc=true" in segment
    assert '"com.docker.network.bridge.enable_icc":"true"' in segment
    assert "--opt com.docker.network.bridge.enable_ip_masquerade=false" in segment
    assert "--opt com.docker.network.bridge.host_binding_ipv4=127.0.0.1" in segment
    assert "--publish 127.0.0.1:8443:8443/tcp" in segment
