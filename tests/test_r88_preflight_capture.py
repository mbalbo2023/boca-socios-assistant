"""R88 preflight runner capture: real protected Bash, fake GH/SSH, no host access.

The simulated SSH is a local program. No Actions are dispatched, no Docker is
started, and no network connection is made by this test module.
"""

from __future__ import annotations

import base64
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from test_ci_parallel_pytest_contract import assert_required_ci_covers

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "boca-first-deploy.yml"
HOST_STEP = "Preflight exact dual GHCR image and rootless worker boundary without PREPARE"
VERIFY_STEP = "Require exact Boca rootless worker preflight receipt and bounded cleanup"
SOURCE = "a" * 40
CID = "b" * 64


def _bash(step: str) -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    marker = f"      - name: {step}\n"
    assert text.count(marker) == 1
    block = text.split(marker, 1)[1].split("\n      - name:", 1)[0]
    assert "        run: |\n" in block
    return textwrap.dedent(block.split("        run: |\n", 1)[1])


def _pass_receipt() -> bytes:
    return (
        f"BOCA_CUTOVER_WORKER_PREFLIGHT state=PASS source_sha={SOURCE} "
        "images=VERIFIED worker_boundary=VERIFIED cleanup=VERIFIED "
        "original=RUNNING port=127.0.0.1:8443 ipc_worker=NOT_TESTED "
        "prepared_go=UNCONSUMED foreign=UNTOUCHED\n"
    ).encode("ascii")


def _failure_receipt() -> bytes:
    return (
        "BOCA_CUTOVER_WORKER_PREFLIGHT state=NO_GO failed_phase=CLEANUP "
        "cleanup=INDETERMINATE primary_failed_phase=NONE cleanup_failed_stage=STOP "
        "stop_failure_cause=NONZERO\n"
    ).encode("ascii")


def _fake_host_env(tmp_path: Path, *, output: bytes, code: int = 0) -> dict[str, str]:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "if sys.argv[1:3] != ['api', 'repos/mbalbo2023/boca-socios-assistant/git/ref/heads/main']:\n"
        "    raise SystemExit(11)\n"
        "print(json.dumps({'ref':'refs/heads/main', 'object': {'type':'commit', 'sha':os.environ['BOCA_SOURCE_SHA']}}))\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o700)
    fake_ssh = fake_bin / "ssh"
    fake_ssh.write_text(
        "#!/usr/bin/env python3\n"
        "import base64,os,resource,sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['FAKE_SSH_CALLED']).write_text('called')\n"
        "Path(os.environ['FAKE_SSH_LIMIT']).write_text(str(resource.getrlimit(resource.RLIMIT_FSIZE)[0]))\n"
        "s=os.fstat(1)\n"
        "Path(os.environ['FAKE_SSH_MODE']).write_text(f'{s.st_mode & 0o777},{s.st_nlink}')\n"
        "sys.stdout.buffer.write(base64.b64decode(os.environ['FAKE_SSH_OUTPUT']))\n"
        "sys.stderr.write('PRIVATE_SSH_ERROR_SHOULD_NEVER_BE_LOGGED')\n"
        "raise SystemExit(int(os.environ['FAKE_SSH_EXIT']))\n",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o700)
    env = dict(os.environ)
    env.update(
        PATH=f"{fake_bin}:{os.environ['PATH']}",
        RUNNER_TEMP=str(tmp_path),
        GITHUB_ENV=str(tmp_path / "runner-env"),
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"),
        GITHUB_REPOSITORY="mbalbo2023/boca-socios-assistant",
        GITHUB_RUN_ID="99999999999",
        GITHUB_SHA=SOURCE,
        BOCA_SOURCE_SHA=SOURCE,
        BOCA_IMAGE_REF="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "c" * 64,
        BOCA_BROWSER_IMAGE_REF="ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
        + "d" * 64,
        BOCA_LEGACY_SOURCE_SHA="e" * 40,
        BOCA_LEGACY_IMAGE_REF="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "f" * 64,
        BOCA_LEGACY_CONTROLLER_ID=CID,
        FAKE_SSH_OUTPUT=base64.b64encode(output).decode("ascii"),
        FAKE_SSH_EXIT=str(code),
        FAKE_SSH_CALLED=str(tmp_path / "ssh.called"),
        FAKE_SSH_LIMIT=str(tmp_path / "ssh.limit"),
        FAKE_SSH_MODE=str(tmp_path / "ssh.mode"),
    )
    return env


def _run(
    step: str, env: dict[str, str], *, timeout: float = 20
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - real extracted Bash with local SSH/GH doubles
        ("bash", "-c", "set -euo pipefail\n" + _bash(step)),  # noqa: S607
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


@pytest.mark.parametrize(
    ("response", "ssh_exit", "expected_host_success"),
    [
        (_pass_receipt(), 0, True),
        (_failure_receipt(), 3, False),
        (b"PRIVATE_HOST_PAYLOAD\n" * 1024, 0, False),
    ],
    ids=["canonical-pass", "typed-no-go", "hostile-stream-exceeds-limit"],
)
def test_r88_ssh_stdout_is_bounded_in_private_file_and_finally_removed(
    tmp_path: Path, response: bytes, ssh_exit: int, expected_host_success: bool
) -> None:
    env = _fake_host_env(tmp_path, output=response, code=ssh_exit)
    host = _run(HOST_STEP, env)
    assert (host.returncode == 0) is expected_host_success, (host.stdout, host.stderr)
    assert (tmp_path / "ssh.called").read_text(encoding="ascii") == "called"
    assert (tmp_path / "ssh.limit").read_text(encoding="ascii") == "8192"
    assert (tmp_path / "ssh.mode").read_text(encoding="ascii") == "384,1"  # 0600, one link
    assert "PRIVATE_HOST_PAYLOAD" not in host.stdout + host.stderr
    assert "PRIVATE_SSH_ERROR_SHOULD_NEVER_BE_LOGGED" not in host.stdout + host.stderr

    candidates = list(tmp_path.glob("boca-worker-preflight.????????"))
    assert len(candidates) == 1
    private_dir = candidates[0]
    assert private_dir.stat().st_mode & 0o777 == 0o700
    receipt = private_dir / "receipt"
    assert receipt.is_file() and not receipt.is_symlink()
    assert receipt.stat().st_size <= 8192
    assert env["GITHUB_ENV"] is not None
    assert (tmp_path / "runner-env").read_text(encoding="utf-8") == (
        f"BOCA_PREFLIGHT_RECEIPT={receipt}\n"
    )

    env["BOCA_PREFLIGHT_RECEIPT"] = str(receipt)
    env["BOCA_PREFLIGHT_DISPATCH_OUTCOME"] = "success"
    env["BOCA_PREFLIGHT_HOST_OUTCOME"] = "success" if host.returncode == 0 else "failure"
    terminal = _run(VERIFY_STEP, env)
    assert (terminal.returncode == 0) is expected_host_success, (terminal.stdout, terminal.stderr)
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    if expected_host_success:
        assert _pass_receipt().decode("ascii") in summary
    else:
        assert "state=NO_GO host=UNVERIFIED" in summary
        assert "no_retry=1" in summary
        if response == _failure_receipt():
            assert "cleanup_failed_stage_claim=STOP" in summary
            assert "stop_failure_cause_claim=NONZERO" in summary
    assert not receipt.exists() and not private_dir.exists()


def test_r88_preplanted_fixed_path_symlink_never_receives_host_stdout(tmp_path: Path) -> None:
    sentinel = tmp_path / "user-sentinel"
    sentinel.write_bytes(b"DO_NOT_TOUCH")
    (tmp_path / "boca-worker-preflight.receipt").symlink_to(sentinel)
    env = _fake_host_env(tmp_path, output=_pass_receipt())
    host = _run(HOST_STEP, env)
    assert host.returncode == 0, (host.stdout, host.stderr)
    assert sentinel.read_bytes() == b"DO_NOT_TOUCH"
    assert (tmp_path / "boca-worker-preflight.receipt").is_symlink()


def test_r88_file_limit_failure_stops_before_ssh_and_reports_no_go(tmp_path: Path) -> None:
    env = _fake_host_env(tmp_path, output=_pass_receipt())
    startup = tmp_path / "bash-startup"
    startup.write_text("ulimit() { return 1; }\n", encoding="ascii")
    env["BASH_ENV"] = str(startup)
    host = _run(HOST_STEP, env)
    assert host.returncode != 0
    assert not (tmp_path / "ssh.called").exists()
    private_dir = next(tmp_path.glob("boca-worker-preflight.????????"))
    env["BOCA_PREFLIGHT_RECEIPT"] = str(private_dir / "receipt")
    env["BOCA_PREFLIGHT_HOST_OUTCOME"] = "failure"
    env["BOCA_PREFLIGHT_DISPATCH_OUTCOME"] = "success"
    terminal = _run(VERIFY_STEP, env)
    assert terminal.returncode != 0
    assert "state=NO_GO host=UNVERIFIED" in (tmp_path / "summary.md").read_text()
    assert not private_dir.exists()


def test_r88_terminal_does_not_follow_or_delete_symlink_target(tmp_path: Path) -> None:
    private_dir = tmp_path / "boca-worker-preflight.abcdefgh"
    private_dir.mkdir(mode=0o700)
    sentinel = tmp_path / "user-sentinel"
    sentinel.write_bytes(_pass_receipt())
    (private_dir / "receipt").symlink_to(sentinel)
    env = _fake_host_env(tmp_path, output=b"")
    env.update(
        BOCA_PREFLIGHT_RECEIPT=str(private_dir / "receipt"),
        BOCA_PREFLIGHT_HOST_OUTCOME="success",
        BOCA_PREFLIGHT_DISPATCH_OUTCOME="success",
    )
    terminal = _run(VERIFY_STEP, env)
    assert terminal.returncode != 0
    assert "state=NO_GO host=UNVERIFIED" in (tmp_path / "summary.md").read_text()
    assert sentinel.read_bytes() == _pass_receipt()
    assert not private_dir.exists()


def test_r88_failed_ssh_does_not_follow_symlink_to_blocking_pipe(tmp_path: Path) -> None:
    private_dir = tmp_path / "boca-worker-preflight.abcdefgh"
    private_dir.mkdir(mode=0o700)
    pipe = tmp_path / "never-read"
    os.mkfifo(pipe)
    (private_dir / "receipt").symlink_to(pipe)
    env = _fake_host_env(tmp_path, output=b"")
    env.update(
        BOCA_PREFLIGHT_RECEIPT=str(private_dir / "receipt"),
        BOCA_PREFLIGHT_HOST_OUTCOME="failure",
        BOCA_PREFLIGHT_DISPATCH_OUTCOME="success",
    )
    terminal = _run(VERIFY_STEP, env, timeout=2)
    assert terminal.returncode == 1
    assert "state=NO_GO host=UNVERIFIED" in (tmp_path / "summary.md").read_text()
    assert not private_dir.exists()


def test_r88_terminal_rejects_traversal_hidden_inside_eight_glob_chars(
    tmp_path: Path,
) -> None:
    """Bash `?` also matches `/`; don't allow an apparently matching path to escape."""
    (tmp_path / "boca-worker-preflight.abc").mkdir()
    outside = tmp_path / "x"
    outside.mkdir()
    victim = outside / "receipt"
    victim.write_bytes(_pass_receipt())
    # The middle substring `abc/../x` is exactly eight characters, including
    # two slashes, so a raw Bash `????????` pattern can traverse to `x`.
    crafted = tmp_path / "boca-worker-preflight.abc" / ".." / "x" / "receipt"
    env = _fake_host_env(tmp_path, output=b"")
    env.update(
        BOCA_PREFLIGHT_RECEIPT=str(crafted),
        BOCA_PREFLIGHT_HOST_OUTCOME="success",
        BOCA_PREFLIGHT_DISPATCH_OUTCOME="success",
    )
    terminal = _run(VERIFY_STEP, env)
    assert terminal.returncode == 1
    assert "state=NO_GO host=UNVERIFIED" in (tmp_path / "summary.md").read_text()
    assert victim.read_bytes() == _pass_receipt()
    assert outside.is_dir()


def test_r88_denied_dispatch_stays_pre_ssh_and_without_host_claim(tmp_path: Path) -> None:
    env = _fake_host_env(tmp_path, output=b"")
    env.update(
        BOCA_PREFLIGHT_RECEIPT="",
        BOCA_PREFLIGHT_HOST_OUTCOME="skipped",
        BOCA_PREFLIGHT_DISPATCH_OUTCOME="failure",
    )
    terminal = _run(VERIFY_STEP, env)
    assert terminal.returncode == 1
    assert (tmp_path / "summary.md").read_text(encoding="ascii") == (
        "BOCA_CUTOVER_WORKER_PREFLIGHT state=NO_GO dispatch_gate=NOT_PASSED "
        "ssh=NOT_ATTEMPTED_BY_RUN no_retry=1\n"
    )
    assert not (tmp_path / "ssh.called").exists()


def test_r88_preflight_contract_test_is_required_by_protected_pr_validation() -> None:
    assert_required_ci_covers(
        "tests/test_r88_preflight_capture.py",
        "tests/test_r88_stop_diagnostics.py",
    )
