"""RCA #275: never mistake a broad Docker firewall failure for a proven cause."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from boca_socios import host_first_deploy as host


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (
            "iptables v1.8.7 (nf_tables): table 'nat' is incompatible, use 'nft' tool.",
            "firewall_backend_mismatch",
        ),
        (
            "iptables v1.8.11 (legacy): can't initialize iptables table 'nat': Table does not exist",
            "firewall_table_missing",
        ),
        (
            "iptables --wait -A FORWARD -j DOCKER: No chain/target/match by that name",
            "firewall_chain_missing",
        ),
        (
            "iptables v1.8.7 (nf_tables): CHAIN_ADD failed (Operation not supported): chain FORWARD",
            "firewall_chain_add_unsupported",
        ),
        (
            "iptables v1.8.7 (nf_tables): Couldn't process rule: Operation not supported",
            "firewall_operation_unsupported",
        ),
        (
            "iptables: stat /proc/sys/net/bridge/bridge-nf-call-iptables: no such file or directory",
            "firewall_bridge_netfilter_unavailable",
        ),
        (
            "iptables: bridge-nf-call-iptables disabled (unspecified)",
            "firewall_unsupported",
        ),
        (
            "iptables: Could not fetch rule set generation id: Permission denied",
            "firewall_permission",
        ),
        (
            "failed to add nftables rules: netlink: Operation not permitted",
            "firewall_permission",
        ),
        (
            "iptables v1.8: Fatal: can't open lock file /run/xtables.lock: Permission denied",
            "firewall_lock_denied",
        ),
        (
            "iptables: Couldn't load match 'set':No such file or directory",
            "firewall_match_unavailable",
        ),
        (
            "iptables -t filter -I FORWARD -j ACCEPT failed with exit status 1",
            "firewall",
        ),
        (
            "network with name boca-socios_owner_enroll_private already exists",
            "already_exists",
        ),
        ("Error: operation not permitted", "permission"),
        ("unrecognized private host error text", "unclassified"),
    ],
)
def test_rootless_firewall_subreason_is_fixed_code(stderr: str, expected: str) -> None:
    error = subprocess.CalledProcessError(
        1,
        ("docker", "network", "create", "boca-socios_owner_enroll_private"),
        stderr=stderr + "\nPRIVATE_DATA_MUST_NOT_BE_PRINTED",
    )
    try:
        raise host.PreflightError("Docker network operation failed") from error
    except host.PreflightError as exc:
        category = host._network_probe_error(exc)
    assert category == expected
    assert "PRIVATE_" not in category


@pytest.mark.parametrize(
    "unsafe",
    [
        "iptables " + "x" * 4096,
        "\x00iptables permission denied",
    ],
)
def test_oversized_or_malformed_diagnostics_never_leak(unsafe: str) -> None:
    error = subprocess.CalledProcessError(1, ("docker", "network", "create"), stderr=unsafe)
    try:
        raise host.PreflightError("redacted") from error
    except host.PreflightError as exc:
        assert host._network_probe_error(exc) == "unclassified"


def test_protected_workflow_accepts_only_bounded_subreason_receipts() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
    ).read_text(encoding="utf-8")
    step = workflow.split(
        "- name: Boca rootless network probe without app image or published port"
    )[1]
    step = step.split("- name: Always verify absence", 1)[0]
    assert "firewall_backend_mismatch" in step
    assert "firewall_table_missing" in step
    assert "firewall_chain_missing" in step
    assert "firewall_chain_add_unsupported" in step
    assert "firewall_operation_unsupported" in step
    assert "firewall_match_unavailable" in step
    assert "firewall_bridge_netfilter_unavailable" in step
    assert "firewall_unsupported" in step
    assert "firewall_permission" in step
    assert "firewall_lock_denied" in step
    assert "2>/dev/null" in step
    assert "printf '%s\\n' \"$receipt\"" in step


def test_rootless_network_probe_never_changes_the_global_firewall() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
    ).read_text(encoding="utf-8")
    assert "iptables -F" not in workflow
    assert "update-alternatives --set" not in workflow
    assert "docker system prune" not in workflow
    assert "if: always() && inputs.operation == 'network-probe'" in workflow
