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
    step_name: str = "Observe bridge netfilter kernel hints without host changes",
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    ssh = bin_dir / "ssh"
    ssh.write_text(
        '#!/bin/sh\ncat >/dev/null\nprintf "%s" "$FIXTURE_STDOUT"\n'
        'printf "%s" "$FIXTURE_STDERR" >&2\nexit "$FIXTURE_RC"\n'
    )
    ssh.chmod(0o700)
    script = textwrap.dedent(_step(step_name).split("        run: |\n", 1)[1])
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


def _module_catalogue(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "modules"
    release = root / "6.8.0-test"
    release.mkdir(parents=True)
    builtin = release / "modules.builtin"
    dependencies = release / "modules.dep"
    builtin.write_bytes(b"")
    dependencies.write_bytes(b"")
    disabled = tmp_path / "modules_disabled"
    disabled.write_text("0\n")
    return root, builtin, disabled


def test_module_catalogue_distinguishes_builtin_listed_and_absent(tmp_path: Path) -> None:
    root, builtin, disabled = _module_catalogue(tmp_path)
    dependencies = builtin.with_name("modules.dep")
    snapshot = lambda: rootless._kernel_module_availability_snapshot(  # noqa: E731
        root, disabled, "6.8.0-test"
    )
    assert snapshot() == ("not_listed", "0")
    builtin.write_bytes(b"kernel/net/bridge/br_netfilter.ko\n")
    assert snapshot() == ("builtin", "0")
    builtin.write_bytes(b"")
    dependencies.write_bytes(
        b"kernel/net/bridge/br_netfilter.ko.zst: kernel/net/core/some_module.ko.zst\n"
    )
    assert snapshot() == ("listed", "0")
    builtin.write_bytes(b"kernel/net/bridge/br_netfilter.ko\n")
    assert snapshot() == ("inconsistent", "0")
    disabled.write_text("1\n")
    assert snapshot() == ("inconsistent", "1")


def test_module_catalogue_refuses_false_names_missing_or_untrusted_paths(
    tmp_path: Path,
) -> None:
    root, builtin, disabled = _module_catalogue(tmp_path)
    dependencies = builtin.with_name("modules.dep")
    dependencies.write_bytes(
        b"kernel/net/bridge/not_br_netfilter.ko: kernel/net/core/valid.ko\n"
        b"kernel/net/bridge/br_netfilter_extra.ko: kernel/net/core/valid.ko\n"
    )
    assert rootless._kernel_module_availability_snapshot(root, disabled, "6.8.0-test") == (
        "not_listed",
        "0",
    )
    dependencies.unlink()
    dependencies.symlink_to(tmp_path / "untrusted")
    assert rootless._kernel_module_availability_snapshot(root, disabled, "6.8.0-test") == (
        "unknown",
        "0",
    )
    assert rootless._kernel_module_availability_snapshot(root, disabled, "../outside") == (
        "unknown",
        "0",
    )
    disabled.unlink()
    disabled.symlink_to(tmp_path / "untrusted")
    assert rootless._kernel_module_availability_snapshot(root, disabled, "6.8.0-test") == (
        "unknown",
        "unreadable",
    )


@pytest.mark.parametrize("hit_in", ["builtin", "dependencies"])
def test_module_catalogue_does_not_trust_one_index_when_other_missing(
    tmp_path: Path, hit_in: str
) -> None:
    root, builtin, disabled = _module_catalogue(tmp_path)
    dependencies = builtin.with_name("modules.dep")
    if hit_in == "builtin":
        builtin.write_bytes(b"kernel/net/bridge/br_netfilter.ko\n")
        dependencies.unlink()
    else:
        dependencies.write_bytes(b"kernel/net/bridge/br_netfilter.ko.zst: \n")
        builtin.unlink()
    assert rootless._kernel_module_availability_snapshot(root, disabled, "6.8.0-test") == (
        "unknown",
        "0",
    )


@pytest.mark.parametrize("malformed_in", ["builtin", "dependencies", "truncated"])
def test_module_catalogue_does_not_trust_hit_when_other_index_malformed(
    tmp_path: Path, malformed_in: str
) -> None:
    root, builtin, disabled = _module_catalogue(tmp_path)
    dependencies = builtin.with_name("modules.dep")
    builtin.write_bytes(b"kernel/net/bridge/br_netfilter.ko\n")
    dependencies.write_bytes(b"kernel/net/bridge/br_netfilter.ko.zst: \n")
    if malformed_in == "builtin":
        builtin.write_bytes(b"not-a-valid-module-record\n")
    elif malformed_in == "dependencies":
        dependencies.write_bytes(b"kernel/net/bridge/br_netfilter.ko.zst\n")
    else:
        dependencies.write_bytes(b"kernel/net/bridge/br_netfilter.ko.zst: ")
    assert rootless._kernel_module_availability_snapshot(root, disabled, "6.8.0-test") == (
        "unknown",
        "0",
    )


def test_module_catalogue_bounded_regular_reads(tmp_path: Path) -> None:
    root, builtin, disabled = _module_catalogue(tmp_path)
    dependencies = builtin.with_name("modules.dep")
    dependencies.write_bytes(b"z" * (4 * 1024 * 1024 + 1))
    assert rootless._kernel_module_availability_snapshot(root, disabled, "6.8.0-test") == (
        "unknown",
        "0",
    )
    dependencies.unlink()
    os.mkfifo(dependencies)
    assert rootless._kernel_module_availability_snapshot(root, disabled, "6.8.0-test") == (
        "unknown",
        "0",
    )
    disabled.write_text("INVALID\n")
    assert rootless._kernel_module_availability_snapshot(root, disabled, "6.8.0-test") == (
        "unknown",
        "invalid",
    )


def test_kernel_availability_inspect_has_only_identity_and_bounded_reads(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(rootless, "_identity", lambda: calls.append("identity"))
    monkeypatch.setattr(
        rootless,
        "_kernel_module_availability_snapshot",
        lambda *_a: calls.append("read") or ("listed", "0"),
    )
    for name in ("_command", "_start_stopped_daemon", "prepare", "stop_test"):
        monkeypatch.setattr(rootless, name, lambda *_a, **_k: pytest.fail("effect"))
    rootless.kernel_availability_inspect(SHA)
    assert calls == ["identity", "read"]
    assert capsys.readouterr().out == (
        f"BOCA_KERNEL_AVAIL state=OBSERVED source_sha={SHA}"
        " index=listed modules_disabled=0 write_ops=none\n"
    )
    with pytest.raises(rootless.SetupError, match="invalid_kernel_inspect_coordinates"):
        rootless.kernel_availability_inspect("not-a-sha")


def test_protected_availability_step_is_readonly_and_canonical(tmp_path: Path) -> None:
    name = "Inspect kernel module catalogue and load policy without changes"
    step = _step(name)
    assert "if: inputs.operation == 'infrastructure-inspect'" in step
    assert "python3 - kernel-availability-inspect" in step
    assert "timeout --signal=TERM --kill-after=5s 60s ssh " in step
    for forbidden in ("modprobe", "sysctl -w", "iptables ", "docker ", "sudo "):
        assert forbidden not in step
    receipt = (
        f"BOCA_KERNEL_AVAIL state=OBSERVED source_sha={SHA}"
        " index=listed modules_disabled=0 write_ops=none\n"
    )
    run = _run_kernel_step(tmp_path, receipt=receipt, step_name=name)
    assert run.returncode == 0, run.stderr
    assert receipt in (tmp_path / "summary").read_text()


@pytest.mark.parametrize(
    ("receipt", "code", "error"),
    [
        ("PRIVATE_SENTINEL", 0, ""),
        (
            f"BOCA_KERNEL_AVAIL state=OBSERVED source_sha={'b' * 40} index=listed modules_disabled=0 write_ops=none\n",
            0,
            "",
        ),
        (
            f"BOCA_KERNEL_AVAIL state=OBSERVED source_sha={SHA} index=loadable modules_disabled=0 write_ops=none\n",
            0,
            "",
        ),
        (
            f"BOCA_KERNEL_AVAIL state=OBSERVED source_sha={SHA} index=builtin modules_disabled=0 write_ops=none\n",
            2,
            "PRIVATE_SENTINEL",
        ),
    ],
)
def test_protected_availability_step_withholds_untrusted_receipts(
    tmp_path: Path, receipt: str, code: int, error: str
) -> None:
    run = _run_kernel_step(
        tmp_path,
        receipt=receipt,
        code=code,
        error=error,
        step_name="Inspect kernel module catalogue and load policy without changes",
    )
    assert run.returncode == 1
    combined = run.stdout + run.stderr + (tmp_path / "summary").read_text()
    assert "state=INDETERMINATE" in combined
    assert "PRIVATE_SENTINEL" not in combined
