"""Same-run readback authenticates the dispatch, marker and finite public projection."""

from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from boca_socios import host_boca_cutover_cli as cli
from boca_socios.host_boca_cutover import CutoverPlan
from test_host_boca_cutover_cli import _plan

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = b"reviewed synthetic bundle"
DIGEST = hashlib.sha256(BUNDLE).hexdigest()
GO = "e" * 64
CID = "9" * 64
SECRET = "SYNTHETIC_PRIVATE_MARKER"


def token(plan: CutoverPlan, *, v3: bool = True) -> str:
    return cli.encode_invocation(plan, bundle_sha256=DIGEST, go_binding_sha256=GO, dispatch_v3=v3)


def test_recover_exact_observation_after_container_was_removed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from boca_socios import host_cutover_capture_readback as readback

    plan = _plan()
    monkeypatch.setattr(cli, "_bundle_digest", lambda: DIGEST)
    calls = []

    def read(approved: CutoverPlan) -> tuple[str, str]:
        calls.append(approved)
        return CID, "PERMISSION_ERROR"

    monkeypatch.setattr(readback.custody, "read_before_cleanup", read)
    assert readback.run_host(token(plan), approved_go_binding_sha256=GO) == 0
    out, err = capsys.readouterr()
    assert calls == [plan] and not err and CID not in out and plan.owner_subject not in out
    line = readback.verify(out.encode("ascii"), plan.attempt_id, plan.target_sha)
    assert "worker_stderr_observation=PERMISSION_ERROR" in line
    assert "state=NO_GO" in line and "cleanup=UNVERIFIED" in line
    assert f"/actions/runs/{plan.attempt_id}" in line and f"/commit/{plan.target_sha}" in line


@pytest.mark.parametrize("reason", ["legacy", "wrong-go", "wrong-zip", "malformed"])
def test_invalid_replay_is_rejected_before_any_private_read(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], reason: str
) -> None:
    from boca_socios import host_cutover_capture_readback as readback

    monkeypatch.setattr(
        cli, "_bundle_digest", lambda: "0" * 64 if reason == "wrong-zip" else DIGEST
    )
    monkeypatch.setattr(
        readback.custody, "read_before_cleanup", lambda _: pytest.fail("unexpected private read")
    )
    encoded = SECRET if reason == "malformed" else token(_plan(), v3=reason != "legacy")
    approval = "a" * 64 if reason == "wrong-go" else GO
    assert readback.run_host(encoded, approved_go_binding_sha256=approval) == 3
    out, err = capsys.readouterr()
    assert not out and not err


@pytest.mark.parametrize("fault", ["missing", "arbitrary-value", "another-cid"])
def test_bad_private_marker_never_exposes_its_value(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fault: str
) -> None:
    from boca_socios import host_cutover_capture_readback as readback

    plan = _plan()
    monkeypatch.setattr(cli, "_bundle_digest", lambda: DIGEST)

    def read(_plan: CutoverPlan) -> tuple[str, str]:
        if fault == "missing":
            raise ValueError(SECRET)
        return (plan.legacy_id, "EMPTY") if fault == "another-cid" else (CID, SECRET)

    monkeypatch.setattr(readback.custody, "read_before_cleanup", read)
    assert readback.run_host(token(plan), approved_go_binding_sha256=GO) == 3
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "mutation",
    ["wrong-run", "wrong-sha", "unknown", "extra", "duplicate", "truncated", "long", "nonascii"],
)
def test_runner_rejects_mismatched_or_untrusted_wire_text(mutation: str) -> None:
    from boca_socios import host_cutover_capture_readback as readback

    plan = _plan()
    line = (
        f"BOCA_WORKER_CAPTURE_V1 run={plan.attempt_id} sha={plan.target_sha} observation=EMPTY\n"
    ).encode()
    raw = {
        "wrong-run": line.replace(plan.attempt_id.encode(), b"1"),
        "wrong-sha": line.replace(plan.target_sha.encode(), b"a" * 40),
        "unknown": line.replace(b"EMPTY", SECRET.encode()),
        "extra": line.replace(b"EMPTY", b"EMPTY private=" + SECRET.encode()),
        "duplicate": line * 2,
        "truncated": line[:-1],
        "long": line + b"x" * 300,
        "nonascii": line.replace(b"EMPTY", b"\xff"),
    }[mutation]
    with pytest.raises(ValueError) as fault:
        readback.verify(raw, plan.attempt_id, plan.target_sha)
    assert SECRET not in str(fault.value)


def test_reviewed_shell_command_binds_both_modes_to_the_same_dispatch(tmp_path: Path) -> None:
    plan = _plan()
    env = {
        "GITHUB_RUN_ID": plan.attempt_id,
        "GITHUB_SHA": plan.target_sha,
        "BOCA_SOURCE_SHA": plan.target_sha,
        "RUNNER_TEMP": str(tmp_path),
        "PYTHONPATH": str(ROOT / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    def dispatch(mode: str, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - reviewed local script and fixed test modes
            [
                sys.executable,
                str(ROOT / "scripts/check_cutover_a_go.py"),
                "--dispatch-command",
                mode,
            ],
            env=environment,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )

    (tmp_path / "boca-cutover-a-review.pyz").write_bytes(BUNDLE)
    (tmp_path / "boca-cutover-a-invocation.token").write_text(token(plan) + "\n")
    (tmp_path / "boca-cutover-a-approved.digest").write_text(GO + "\n")
    for mode in ("cutover-a-dispatch-v3", "cutover-a-capture-readback-v3"):
        built = dispatch(mode, env)
        assert built.returncode == 0 and not built.stderr
        assert shlex.split(built.stdout) == [
            f"BOCA_CUTOVER_A_DISPATCH_BINDING_SHA256={GO}",
            "python3",
            "-c",
            (ROOT / "scripts/boca_protected_memfd_bootstrap.py").read_text(),
            DIGEST,
            mode,
            token(plan),
        ]
    for changed in (
        {**env, "GITHUB_RUN_ID": "7"},
        {**env, "GITHUB_SHA": "0" * 40},
        {**env, "BOCA_SOURCE_SHA": "f" * 40},
    ):
        rejected = dispatch("cutover-a-capture-readback-v3", changed)
        assert rejected.returncode == 1 and not rejected.stdout
        assert rejected.stderr == "BOCA_CUTOVER_A_DISPATCH_COMMAND state=NO_GO\n"
    assert dispatch("caller-selected-mode", env).returncode != 0


def test_same_action_reads_once_only_after_an_attempted_failed_apply() -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    apply, tail = workflow.split("      - name: Read the same failed worker capture", 1)
    block, rest = tail.split("      - name:", 1)
    assert "capture_readback=true" in apply.split('if [[ "$host_ssh_rc" -ne 0 ]]; then')[-1]
    assert "steps.cutover_host_apply.outputs.capture_readback == 'true'" in block
    assert "steps.cutover_go_preflight.outcome == 'success'" in block
    assert "steps.cutover_host_apply.outcome == 'failure'" in block
    assert "!cancelled()" in block and "inputs.operation == 'cutover-a-apply'" in block
    assert "cutover-a-capture-readback-v3" in block and "cutover-a-dispatch-v3" not in block
    assert block.count(" ssh ") == 1 and "2>/dev/null" in block and "set -euo pipefail" in block
    assert "tee -a" in block and "`" not in block and 'exit "$host_ssh_rc"' in apply
    assert rest.startswith(" Fail closed on absent or ambiguous Cutover A host terminal receipt")


@pytest.mark.parametrize(
    ("ssh_status", "wire_ok", "verified"), [(0, True, True), (255, True, False), (0, False, False)]
)
def test_action_validates_entire_ssh_pipeline_before_publishing(
    tmp_path: Path, ssh_status: int, wire_ok: bool, verified: bool
) -> None:
    from boca_socios import host_cutover_capture_readback as readback

    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    step = workflow.split("      - name: Read the same failed worker capture", 1)[1]
    script = textwrap.dedent(step.split("        run: |\n", 1)[1].split("      - name:", 1)[0])
    plan = _plan()
    wire = f"BOCA_WORKER_CAPTURE_V1 run={plan.attempt_id} sha={plan.target_sha} observation=EMPTY\n"
    summary = tmp_path / "job-summary"
    (tmp_path / "boca-cutover-a-review.pyz").write_bytes(BUNDLE)
    # No network command runs. The transport can deliver a complete plausible line and still fail.
    doubles = """
python3() {
  if [[ "$1" == "scripts/check_cutover_a_go.py" ]]; then printf 'fixed-command\\n';
  else command "$TEST_PYTHON" "$@"; fi
}
timeout() {
  printf '%s' "$TEST_WIRE"
  printf '%s' "$TEST_PRIVATE" >&2
  return "$TEST_STATUS"
}
"""
    result = subprocess.run(  # noqa: S603 - reviewed workflow step, offline shell doubles
        ["/bin/bash", "-c", doubles + script],
        env={
            "PATH": os.defpath,
            "PYTHONPATH": str(ROOT / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "GITHUB_RUN_ID": plan.attempt_id,
            "GITHUB_SHA": plan.target_sha,
            "GITHUB_STEP_SUMMARY": str(summary),
            "RUNNER_TEMP": str(tmp_path),
            "TEST_PYTHON": sys.executable,
            "TEST_WIRE": wire if wire_ok else wire + SECRET,
            "TEST_PRIVATE": SECRET,
            "TEST_STATUS": str(ssh_status),
        },
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    expected = (
        readback.verify(wire.encode(), plan.attempt_id, plan.target_sha)
        if verified
        else "BOCA_WORKER_CAPTURE_READBACK state=NO_GO receipt=UNVERIFIED cleanup=UNVERIFIED retry=NO_GO"
    )
    assert result.returncode == (0 if verified else 1) and not result.stderr
    assert result.stdout == summary.read_text() == expected + "\n"
