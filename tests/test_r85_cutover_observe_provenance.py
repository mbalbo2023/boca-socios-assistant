"""R85: future Cutover observation failures are categorised without leaking stderr.

Actual runner Bash runs against a disposable fake SSH. No real host or Docker.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SCRIPT = ROOT / "scripts/check_cutover_observe_diagnostic.py"
WORKFLOW = ROOT / ".github/workflows/boca-first-deploy.yml"
LEGACY_SHA = "b" * 40
TARGET_SHA = "a" * 40
LEGACY_ID = "d" * 64
LEGACY_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "c" * 64
TARGET_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "e" * 64
BROWSER_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "f" * 64


def _module():
    assert SCRIPT.is_file(), "R85 reviewed failure diagnostic is missing"
    spec = importlib.util.spec_from_file_location("check_cutover_observe_diagnostic", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ready() -> bytes:
    return (
        f"BOCA_CUTOVER_A_OBSERVE state=READY legacy_sha={LEGACY_SHA} legacy_id={LEGACY_ID} "
        f"legacy_image={LEGACY_IMAGE} target_sha={TARGET_SHA} "
        f"target_image={TARGET_IMAGE} browser_image={BROWSER_IMAGE} "
        "original=RUNNING port=127.0.0.1:8443 worker=absent "
        "owner=preserved key=preserved data=preserved effects=none\n"
    ).encode("ascii")


@pytest.mark.parametrize(
    ("code", "expected_class"),
    [(124, "TIMEOUT"), (137, "TIMEOUT"), (255, "SSH_255")],
)
def test_transport_codes_override_untrusted_stderr(code: int, expected_class: str) -> None:
    diagnostic = _module()
    result, report = diagnostic.classify(
        code, _ready(), b"BOCA_NO_GO: invalid private owner origin\nPRIVATE_TOKEN=do_not_print\n"
    )
    assert result != 0
    assert f"class={expected_class}" in report
    assert "PRIVATE_TOKEN" not in report and "OWNER_CONTEXT" not in report
    assert "state=NO_GO" in report and "host=UNVERIFIED" in report
    assert "cutover=NO_GO" in report and "no_retry=1" in report


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("cutover A historical and target release identities are unproven", "RELEASE_IDENTITY"),
        ("invalid private owner origin", "OWNER_CONTEXT"),
        ("staged BETA Compose differs from reviewed file", "LEGACY_COMPOSE"),
        ("insufficient Boca staging or rootless Docker storage", "STORAGE"),
        ("dedicated Boca daemon contains an unexpected container", "DOCKER_INVENTORY"),
        ("cutover A original controller is not healthy", "CONTROLLER_HEALTH"),
        ("BETA host SSH-loopback HTTP unavailable", "LOOPBACK_HTTP"),
        ("Boca browser staging contains unexpected files", "STAGING"),
        ("Docker Engine >=28 required for private localhost publication", "DOCKER_VERSION"),
    ],
)
def test_only_exact_existing_host_failures_have_public_codes(message: str, reason: str) -> None:
    diagnostic = _module()
    result, report = diagnostic.classify(1, b"", f"BOCA_NO_GO: {message}\n".encode())
    assert result != 0
    assert f"class=HOST_VALIDATION reason={reason}" in report
    assert message not in report


@pytest.mark.parametrize(
    "stderr",
    [
        b"",
        b"BOCA_NO_GO: unknown dynamic /srv/boca-socios/private\n",
        b"BOCA_NO_GO: invalid private owner origin\nsecret=LEAK\n",
        b"BOCA_NO_GO: invalid private owner origin\nBOCA_NO_GO: invalid private owner origin\n",
        b"prefix BOCA_NO_GO: invalid private owner origin\n",
        b"BOCA_NO_GO: invalid private owner origin suffix\n",
        b"BOCA_NO_GO: invalid private owner origin\r\n",
        b"BOCA_NO_GO: invalid private owner origin\x00\n",
        b"BOCA_NO_GO: invalid private owner origin\x1b[31m\n",
        "BOCA_NO_GO: inválido secreto\n".encode(),
        b"BOCA_NO_GO: invalid private owner origin\n" + b"x" * 4096,
    ],
)
def test_unknown_host_messages_fail_closed_without_raw_text(stderr: bytes) -> None:
    result, report = _module().classify(1, b"", stderr)
    assert result != 0
    assert "class=UNVERIFIED reason=UNVERIFIED" in report
    assert b"LEAK" not in report.encode() and b"/srv/" not in report.encode()
    assert "cutover=NO_GO no_retry=1" in report


@pytest.mark.parametrize("code", [1, 2, 3, 7, 123, 254])
def test_nonzero_stdout_or_unrecognised_exit_cannot_forge_ready(code: int) -> None:
    result, report = _module().classify(
        code, _ready(), b"BOCA_NO_GO: invalid private owner origin\n"
    )
    assert result != 0
    assert "class=UNVERIFIED reason=UNVERIFIED" in report
    assert "state=READY" not in report


@pytest.mark.parametrize(
    ("stdout", "stderr", "accepted"),
    [
        (_ready(), b"", True),
        (_ready(), b"WARNING private host path\n", False),
        (b"", b"", False),
        (b"BOCA_CUTOVER_A_OBSERVE state=READY\n", b"", False),
        (_ready()[:-2] + b"\n", b"", False),
        (_ready()[:-1] + b"X\n", b"", False),
        (_ready() + b"SECOND_LINE\n", b"", False),
        (b"BOCA_CUTOVER_A_OBSERVE state=READY \xff\n", b"", False),
        (b"BOCA_CUTOVER_A_OBSERVE state=READY\r\n", b"", False),
    ],
)
def test_zero_exit_only_admits_bounded_single_ascii_ready_for_pin_verifier(
    stdout: bytes, stderr: bytes, accepted: bool
) -> None:
    code, report = _module().classify(0, stdout, stderr)
    assert (code == 0) is accepted
    if accepted:
        assert report == ""
    else:
        assert "state=NO_GO" in report and "class=UNVERIFIED" in report


@pytest.mark.parametrize("link_kind", ["symbolic", "hard", "oversized"])
def test_runner_file_reader_rejects_unsafe_capture(
    tmp_path: Path, link_kind: str, capsys: pytest.CaptureFixture[str]
) -> None:
    diagnostic = _module()
    output = tmp_path / "stdout"
    output.write_bytes(b"")
    error = tmp_path / "stderr"
    raw = b"BOCA_NO_GO: invalid private owner origin\n"
    if link_kind == "symbolic":
        target = tmp_path / "target"
        target.write_bytes(raw)
        error.symlink_to(target)
    elif link_kind == "hard":
        target = tmp_path / "target"
        target.write_bytes(raw)
        os.link(target, error)
    else:
        error.write_bytes(raw + b"x" * 2048)
    assert diagnostic.main(["1", str(output), str(error)]) != 0
    captured = capsys.readouterr()
    assert "class=UNVERIFIED" in captured.out
    assert "invalid private owner origin" not in captured.out
    assert captured.err == ""


def _step() -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    heading = (
        "      - name: Observe original RUNNING singleton for cutover A without host effects\n"
    )
    assert workflow.count(heading) == 1
    fragment = workflow.split(heading, 1)[1].split("\n      - name:", 1)[0]
    return textwrap.dedent(fragment.split("        run: |\n", 1)[1])


def test_protected_cutover_review_executes_r85_observer_regressions() -> None:
    """The deployment workflow must exercise its own changed Bash before SSH."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    heading = "      - name: Validate protected Cutover A, Option B ZIP and cleanup offline only\n"
    assert workflow.count(heading) == 1
    command = workflow.split(heading, 1)[1].split("\n      - name:", 1)[0]
    assert "tests/test_r85_cutover_observe_provenance.py" in command


def _fake_ssh_env(tmp_path: Path, *, code: int, stdout: bytes = b"", stderr: bytes = b""):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ssh = fake_bin / "ssh"
    ssh.write_text(
        "#!/usr/bin/env python3\n"
        "import os,resource,sys\n"
        "from pathlib import Path\n"
        "with Path(os.environ['FAKE_SSH_MARKER']).open('a') as dst: dst.write('ssh\\n')\n"
        "Path(os.environ['FAKE_SSH_LIMIT']).write_text(str(resource.getrlimit(resource.RLIMIT_FSIZE)[0]))\n"
        "s1,s2=os.fstat(1),os.fstat(2)\n"
        "Path(os.environ['FAKE_SSH_CAPTURE']).write_text(f'{s1.st_mode & 0o777},{s2.st_mode & 0o777},{s1.st_nlink},{s2.st_nlink}')\n"
        "sys.stdout.buffer.write(os.environ['FAKE_SSH_OUT'].encode('latin1'))\n"
        "sys.stderr.buffer.write(os.environ['FAKE_SSH_ERR'].encode('latin1'))\n"
        "raise SystemExit(int(os.environ['FAKE_SSH_RC']))\n",
        encoding="utf-8",
    )
    ssh.chmod(0o700)
    (tmp_path / "boca-cutover-legacy-compose.sha").write_text("0" * 64 + "\n")
    env = dict(os.environ)
    env.update(
        PATH=str(fake_bin) + os.pathsep + env["PATH"],
        RUNNER_TEMP=str(tmp_path),
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"),
        BOCA_LEGACY_SOURCE_SHA=LEGACY_SHA,
        BOCA_LEGACY_IMAGE_REF=LEGACY_IMAGE,
        BOCA_LEGACY_CONTROLLER_ID=LEGACY_ID,
        BOCA_SOURCE_SHA=TARGET_SHA,
        BOCA_IMAGE_REF=TARGET_IMAGE,
        BOCA_BROWSER_IMAGE_REF=BROWSER_IMAGE,
        BOCA_BETA_PANEL_ORIGIN="http://localhost:8443",
        BOCA_BETA_OWNER_SUBJECT="synthetic_owner",
        FAKE_SSH_RC=str(code),
        FAKE_SSH_OUT=stdout.decode("latin1"),
        FAKE_SSH_ERR=stderr.decode("latin1"),
        FAKE_SSH_MARKER=str(tmp_path / "ssh.calls"),
        FAKE_SSH_LIMIT=str(tmp_path / "ssh.rlimit"),
        FAKE_SSH_CAPTURE=str(tmp_path / "ssh.capture-permissions"),
    )
    return env


@pytest.mark.parametrize(
    ("code", "stderr", "expected_class"),
    [
        (1, b"BOCA_NO_GO: invalid private owner origin\n", "HOST_VALIDATION"),
        (1, b"BOCA_NO_GO: invalid private owner origin\nTOKEN=private\n", "UNVERIFIED"),
        (124, b"", "TIMEOUT"),
        (137, b"", "TIMEOUT"),
        (255, b"ssh internal private diagnostics\n", "SSH_255"),
        (3, b"BOCA_NO_GO: invalid private owner origin\n", "UNVERIFIED"),
    ],
)
def test_real_workflow_step_one_fake_ssh_and_safe_terminal_no_go(
    tmp_path: Path, code: int, stderr: bytes, expected_class: str
) -> None:
    env = _fake_ssh_env(tmp_path, code=code, stderr=stderr)
    result = subprocess.run(  # noqa: S603 - actual workflow body only, fake SSH on PATH
        ["/usr/bin/bash", "-e"],
        input=_step(),
        text=True,
        cwd=ROOT,
        env=env,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode != 0
    assert (tmp_path / "ssh.calls").read_text() == "ssh\n"
    summary = (tmp_path / "summary.md").read_text()
    assert f"class={expected_class}" in summary
    assert "state=NO_GO" in summary and "no_retry=1" in summary
    assert "invalid private owner origin" not in summary
    assert "TOKEN=private" not in summary + result.stdout + result.stderr
    assert not (tmp_path / "boca-cutover-a-observe.stderr").exists()


def test_real_workflow_valid_ready_preserves_exact_success_summary(tmp_path: Path) -> None:
    assert len(_ready()) == 710  # Independent reviewed host-format arithmetic.
    env = _fake_ssh_env(tmp_path, code=0, stdout=_ready())
    result = subprocess.run(  # noqa: S603 - known local Bash body, fake SSH only
        ["/usr/bin/bash", "-e"],
        input=_step(),
        text=True,
        cwd=ROOT,
        env=env,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "ssh.calls").read_text() == "ssh\n"
    assert (tmp_path / "summary.md").read_text() == (
        "BOCA_CUTOVER_A_OBSERVE state=READY legacy_id="
        + LEGACY_ID
        + " original=RUNNING worker=absent effects=none; "
        + "physical cutover remains NO_GO pending separate reviewed adapter.\n"
    )
    assert not (tmp_path / "boca-cutover-a-observe.stderr").exists()


@pytest.mark.parametrize(
    ("payload", "expected_reason"),
    [
        (_ready()[:-1] + b"X\n", "UNVERIFIED"),
        (_ready()[:-2] + b"\n", "UNVERIFIED"),
        (
            _ready().replace(f"legacy_sha={LEGACY_SHA}".encode(), b"legacy_sha=" + b"9" * 40),
            "INVALID_READY",
        ),
        (
            _ready().replace(f"legacy_id={LEGACY_ID}".encode(), b"legacy_id=" + b"9" * 64),
            "INVALID_READY",
        ),
        (
            _ready().replace(
                f"browser_image={BROWSER_IMAGE}".encode(),
                b"browser_image=" + BROWSER_IMAGE[:-1].encode() + b"9",
            ),
            "INVALID_READY",
        ),
    ],
)
def test_real_workflow_rejects_oversize_truncated_or_wrong_pins_with_no_go_receipt(
    tmp_path: Path, payload: bytes, expected_reason: str
) -> None:
    env = _fake_ssh_env(tmp_path, code=0, stdout=payload)
    result = subprocess.run(  # noqa: S603 - test-only fake SSH on PATH
        ["/usr/bin/bash", "-e"],
        input=_step(),
        text=True,
        cwd=ROOT,
        env=env,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode != 0
    assert (tmp_path / "ssh.calls").read_text() == "ssh\n"
    summary = (tmp_path / "summary.md").read_text()
    assert "state=NO_GO" in summary and f"reason={expected_reason}" in summary
    assert "state=READY" not in summary
    assert not (tmp_path / "boca-cutover-a-observe.stderr").exists()


@pytest.mark.parametrize(
    "payload",
    [
        _ready().replace(f"legacy_sha={LEGACY_SHA}".encode(), b"legacy_sha=" + b"9" * 40),
        _ready().replace(f"legacy_id={LEGACY_ID}".encode(), b"legacy_id=" + b"9" * 64),
        _ready().replace(
            f"target_image={TARGET_IMAGE}".encode(),
            b"target_image=" + TARGET_IMAGE[:-1].encode() + b"9",
        ),
    ],
)
def test_real_workflow_wrong_pins_are_no_go_with_python_assertions_disabled(
    tmp_path: Path, payload: bytes
) -> None:
    """CI must not trust assertion checks that `PYTHONOPTIMIZE=1` removes."""
    env = _fake_ssh_env(tmp_path, code=0, stdout=payload)
    env["PYTHONOPTIMIZE"] = "1"
    result = subprocess.run(  # noqa: S603 - actual Bash with synthetic SSH only
        ["/usr/bin/bash", "-e"],
        input=_step(),
        text=True,
        cwd=ROOT,
        env=env,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode != 0
    assert "state=NO_GO" in (tmp_path / "summary.md").read_text()
    assert "state=READY" not in (tmp_path / "summary.md").read_text()


def test_real_workflow_bounded_file_writes_on_oversized_host_output(tmp_path: Path) -> None:
    env = _fake_ssh_env(tmp_path, code=1, stderr=b"X" * 28_000)
    result = subprocess.run(  # noqa: S603 - fake SSH in controlled temp PATH
        ["/usr/bin/bash", "-e"],
        input=_step(),
        text=True,
        cwd=ROOT,
        env=env,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode != 0
    assert (tmp_path / "ssh.calls").read_text() == "ssh\n"
    assert int((tmp_path / "ssh.rlimit").read_text()) <= 8192
    assert (tmp_path / "ssh.capture-permissions").read_text() == "384,384,1,1"
    assert not list(tmp_path.glob("boca-cutover-a-observe.*"))
    assert "class=UNVERIFIED" in (tmp_path / "summary.md").read_text()


def test_real_workflow_denies_ssh_if_runner_file_limit_cannot_be_set(tmp_path: Path) -> None:
    """Bash `errexit` is suppressed by `(...) || rc=$?`; check the limit itself."""
    env = _fake_ssh_env(tmp_path, code=0, stdout=_ready())
    startup = tmp_path / "bash-startup.sh"
    startup.write_text("ulimit() { return 1; }\n", encoding="utf-8")
    env["BASH_ENV"] = str(startup)
    result = subprocess.run(  # noqa: S603 - local Bash with intercepted ulimit/SSH
        ["/usr/bin/bash", "-e"],
        input=_step(),
        text=True,
        cwd=ROOT,
        env=env,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode != 0
    assert not (tmp_path / "ssh.calls").exists(), "SSH must never start unbounded"
    summary = (tmp_path / "summary.md").read_text()
    assert "state=NO_GO" in summary and "cutover=NO_GO" in summary


def test_real_workflow_bounded_stdout_on_oversized_host_output(tmp_path: Path) -> None:
    env = _fake_ssh_env(tmp_path, code=1, stdout=b"Y" * 28_000)
    result = subprocess.run(  # noqa: S603 - fake SSH on disposable test PATH
        ["/usr/bin/bash", "-e"],
        input=_step(),
        text=True,
        cwd=ROOT,
        env=env,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode != 0
    assert (tmp_path / "ssh.calls").read_text() == "ssh\n"
    assert int((tmp_path / "ssh.rlimit").read_text()) <= 8192
    assert (tmp_path / "ssh.capture-permissions").read_text() == "384,384,1,1"
    assert not list(tmp_path.glob("boca-cutover-a-observe.*"))
    assert "class=UNVERIFIED" in (tmp_path / "summary.md").read_text()


def test_real_workflow_captures_cannot_overwrite_preplanted_runner_symlinks(
    tmp_path: Path,
) -> None:
    """A prepared runner path must not redirect raw private SSH output."""
    protected = tmp_path / "do-not-overwrite.txt"
    protected.write_text("preserved", encoding="utf-8")
    (tmp_path / "boca-cutover-a-observe.receipt").symlink_to(protected)
    (tmp_path / "boca-cutover-a-observe.stderr").symlink_to(protected)
    env = _fake_ssh_env(tmp_path, code=1, stderr=b"BOCA_NO_GO: invalid private owner origin\n")
    result = subprocess.run(  # noqa: S603 - fake SSH local runner only
        ["/usr/bin/bash", "-e"],
        input=_step(),
        text=True,
        cwd=ROOT,
        env=env,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode != 0
    assert protected.read_text(encoding="utf-8") == "preserved"
    assert "state=NO_GO" in (tmp_path / "summary.md").read_text()
