"""The protected kernel hint is read-only and never admits owner enrollment."""

from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

from boca_socios import host_rootless_setup as rootless

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40


def _step(name: str) -> str:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    return workflow.split("      - name: " + name + "\n", 1)[1].split("      - name:", 1)[0]


def _run_kernel_step(
    tmp_path: Path,
    *,
    receipt: str,
    code: int = 0,
    error: str = "",
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    ssh = bin_dir / "ssh"
    ssh.write_text(
        '#!/bin/sh\ncat >/dev/null\nprintf "%s" "$FIXTURE_STDOUT"\n'
        'printf "%s" "$FIXTURE_STDERR" >&2\nexit "$FIXTURE_RC"\n'
    )
    ssh.chmod(0o700)
    script = textwrap.dedent(
        _step("Observe bridge netfilter kernel hints without host changes").split(
            "        run: |\n", 1
        )[1]
    )
    return subprocess.run(  # noqa: S603 - fake SSH, not a host invocation
        ["/bin/bash", "-e", "-o", "pipefail", "-c", script],
        cwd=ROOT,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
            "BOCA_SOURCE_SHA": SHA,
            "FIXTURE_STDOUT": receipt,
            "FIXTURE_STDERR": error,
            "FIXTURE_RC": str(code),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )


def test_kernel_snapshot_with_present_module_and_enabled_bridge(tmp_path: Path) -> None:
    module = tmp_path / "module"
    module.mkdir()
    setting = tmp_path / "bridge-nf-call-iptables"
    setting.write_text("1\n")
    assert rootless._kernel_bridge_snapshot(module, setting) == ("present", "1")
    setting.write_text("0\n")
    assert rootless._kernel_bridge_snapshot(module, setting) == ("present", "0")


def test_kernel_snapshot_unknowns_do_not_become_green(tmp_path: Path) -> None:
    module = tmp_path / "module"
    setting = tmp_path / "bridge-nf-call-iptables"
    assert rootless._kernel_bridge_snapshot(module, setting) == ("absent", "unavailable")
    setting.write_text("incorrect\n")
    assert rootless._kernel_bridge_snapshot(module, setting) == ("absent", "invalid")
    module.symlink_to(tmp_path, target_is_directory=True)
    setting.unlink()
    setting.symlink_to(tmp_path / "private")
    assert rootless._kernel_bridge_snapshot(module, setting) == ("unknown", "unreadable")


def test_kernel_snapshot_refuses_fifo_without_blocking(tmp_path: Path) -> None:
    module = tmp_path / "module"
    setting = tmp_path / "bridge-nf-call-iptables"
    os.mkfifo(setting)
    assert rootless._kernel_bridge_snapshot(module, setting) == ("absent", "invalid")


def test_kernel_inspect_only_checks_dedicated_identity_and_snapshot(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(rootless, "_identity", lambda: calls.append("identity"))
    monkeypatch.setattr(
        rootless,
        "_kernel_bridge_snapshot",
        lambda *_a: calls.append("kernel") or ("absent", "unavailable"),
    )
    for name in ("_command", "_start_stopped_daemon", "prepare", "stop_test"):
        monkeypatch.setattr(rootless, name, lambda *_a, **_k: pytest.fail("unexpected effect"))
    rootless.kernel_bridge_inspect(SHA)
    captured = capsys.readouterr()
    assert calls == ["identity", "kernel"]
    assert captured.out == (
        f"BOCA_KERNEL_BRIDGE state=OBSERVED source_sha={SHA} module=absent "
        "nf_call_iptables=unavailable write_ops=none\n"
    )
    assert captured.err == ""
    with pytest.raises(rootless.SetupError, match="invalid_kernel_inspect_coordinates"):
        rootless.kernel_bridge_inspect("invalid")


def test_protected_inspection_has_only_allowlisted_readonly_kernel_step() -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    assert "infrastructure-inspect" in workflow
    step = _step("Observe bridge netfilter kernel hints without host changes")
    assert "if: inputs.operation == 'infrastructure-inspect'" in step
    assert "python3 - kernel-bridge-inspect" in step
    assert "< src/boca_socios/host_rootless_setup.py" in step
    assert "timeout --signal=TERM --kill-after=5s 60s ssh " in step
    assert "umask 077" in step and "ulimit -f 4" in step
    assert "BOCA_KERNEL_BRIDGE state=OBSERVED" in step
    for forbidden in (
        "modprobe",
        "sysctl -w",
        "iptables ",
        "nft ",
        "docker ",
        "sudo ",
        "tee ",
        "GITHUB_OUTPUT",
    ):
        assert forbidden not in step
    assert re.search(r"module=\(present\|absent\|unknown\)", step)
    assert "write_ops=none" in step


def test_protected_kernel_step_accepts_only_canonical_hint(tmp_path: Path) -> None:
    receipt = (
        f"BOCA_KERNEL_BRIDGE state=OBSERVED source_sha={SHA} module=absent "
        "nf_call_iptables=unavailable write_ops=none\n"
    )
    result = _run_kernel_step(tmp_path, receipt=receipt)
    assert result.returncode == 0, result.stderr
    assert result.stdout == receipt
    summary = (tmp_path / "summary").read_text()
    assert receipt in summary
    assert "no ICC=false admission verdict" in summary


@pytest.mark.parametrize(
    ("receipt", "code", "error"),
    [
        ("", 0, ""),
        ("PRIVATE_SENTINEL", 0, ""),
        (
            f"BOCA_KERNEL_BRIDGE state=OBSERVED source_sha={'b' * 40} module=absent nf_call_iptables=unavailable write_ops=none\n",
            0,
            "",
        ),
        (
            f"BOCA_KERNEL_BRIDGE state=OBSERVED source_sha={SHA} module=present nf_call_iptables=2 write_ops=none\n",
            0,
            "",
        ),
        (
            f"BOCA_KERNEL_BRIDGE state=OBSERVED source_sha={SHA} module=present nf_call_iptables=1 write_ops=none\n",
            1,
            "",
        ),
        ("", 255, "PRIVATE_SENTINEL"),
    ],
)
def test_protected_kernel_step_fail_closed_without_leak(
    tmp_path: Path, receipt: str, code: int, error: str
) -> None:
    result = _run_kernel_step(tmp_path, receipt=receipt, code=code, error=error)
    assert result.returncode == 1
    summary = (tmp_path / "summary").read_text()
    assert "state=INDETERMINATE" in summary
    assert "PRIVATE_SENTINEL" not in summary + result.stdout + result.stderr
