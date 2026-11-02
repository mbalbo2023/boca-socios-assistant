"""Regression checks for sanitized output and the privileged runner boundary."""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.observe_public_home import HOST, sanitized_resources

ROOT = Path(__file__).resolve().parents[1]


def test_dependency_inventory_removes_sensitive_url_components_and_external_targets() -> None:
    assert sanitized_resources(
        [
            {"kind": "script", "url": "/_next/static/app.js?token=private#fragment"},
            {"kind": "script", "url": "https://other.invalid/app.js?secret=yes"},
            {"kind": "img", "url": f"https://name:private@{HOST}/image.png"},
            {"kind": "link", "url": "javascript:alert(1)"},
            {"kind": "script", "url": "/_next/static/app.js"},
        ]
    ) == [{"kind": "script", "url": f"https://{HOST}/_next/static/app.js"}]
    assert sanitized_resources([{"kind": "script", "url": "/x"}] * 65) == []


def test_wrapper_refuses_non_actions_context_before_docker_or_network() -> None:
    result = subprocess.run(  # noqa: S603 - fixed local script, no valid Actions context
        ["/bin/bash", str(ROOT / "scripts/run_public_observer_isolated.sh"), "--one-get"],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        timeout=3,
        check=False,
    )
    assert result.returncode != 0
    assert result.stdout == b""


def test_runner_namespace_has_no_dns_loopback_or_host_gateway_exception() -> None:
    script = (ROOT / "scripts/run_public_observer_isolated.sh").read_text()
    assert '"$(readlink "/proc/$pid/ns/net")" != "$(readlink /proc/self/ns/net)"' in script
    assert "--net iptables-restore" in script and "--net ip6tables-restore" in script
    assert script.count(":OUTPUT DROP") == 2
    assert "-A OUTPUT -d $proxy_ip/32 -p tcp --dport 18080" in script
    assert "-A OUTPUT -o lo" not in script
    assert "--publish" not in script and "--network host" not in script
    assert script.index('"$gateway" pre') < script.index("--isolated-one-get")
    assert script.index('"$gateway" post') > script.index("--isolated-one-get")
    assert "ipv4_count >= 4 && ipv6_count >= 1" in script
    assert "ipv4_count >= pre_ipv4_count + 4 && ipv6_count >= pre_ipv6_count + 1" in script


def test_manual_modes_are_exclusive_and_pr_job_cannot_call_public_observer() -> None:
    workflow = (ROOT / ".github/workflows/boca-source-status.yml").read_text()
    assert "inputs.mode == 'http-status'" in workflow
    assert (
        "github.event_name == 'workflow_dispatch' && inputs.mode == 'chromium-one-get'" in workflow
    )
    assert "if: github.event_name == 'pull_request'" in workflow
    assert "scripts/run_public_observer_isolated.sh --offline-check" in workflow
    assert "scripts/run_public_observer_isolated.sh --one-get" in workflow
    assert "secrets." not in workflow and "ssh " not in workflow
    assert "format('boca-source-status-pr-{0}', github.event.pull_request.number)" in workflow
    assert "|| 'boca-source-status'" in workflow
