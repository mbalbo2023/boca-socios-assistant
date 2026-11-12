"""R189 real output framing, typed rejection and redacted runner integration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from dataclasses import replace
from pathlib import Path

import pytest

from test_host_boca_retained_resources import (
    IPC,
    RUN,
    SITE,
    inventory,
    module,
    pair_receipt,
    snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
SECRET = "private-token-must-never-appear"


def failure(phase="IPC_IDENTITY", run=RUN):
    return (
        b"BOCA_RETAINED_RESOURCES_FAILURE "
        + json.dumps(
            {
                "schema": 1,
                "state": "NO_GO",
                "observation_run_id": run,
                "phase": phase,
                "observer_writes": 0,
                "successor_apply_authorized": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )


def mock_metadata(monkeypatch, target, raw_root):
    observer = module()
    monkeypatch.setattr(observer, "_PATHS", {IPC: target})

    def docker(*args):
        if args[0] == "info":
            assert args == ("info", "--format", "{{json .DockerRootDir}}")
            return raw_root
        assert args[0:2] == ("volume", "inspect") and args[-1] == IPC
        return (
            json.dumps(
                {
                    "name": IPC,
                    "driver": "local",
                    "scope": "local",
                    "options": None,
                    "mountpoint": str(target),
                }
            )
            + "\n"
        )

    monkeypatch.setattr(observer.cleanup, "_docker", docker)


def test_docker_root_json_with_real_cli_newline_allows_exact_metadata(tmp_path, monkeypatch):
    target = tmp_path / "volume"
    target.mkdir()
    mock_metadata(monkeypatch, target, json.dumps(str(module()._ROOT)) + "\n")
    before = module()._identity(IPC)
    assert len(before) == 64 and module()._identity(IPC) == before
    target.rename(tmp_path / "retained")
    target.mkdir()
    assert module()._identity(IPC) != before


@pytest.mark.parametrize(
    "raw",
    [
        '"/foreign"\n',
        '"/home/boca-deploy/.local/share/docker "\n',
        '" /home/boca-deploy/.local/share/docker"\n',
        '"/home/boca-deploy/.local/share/docker/"\n',
        '"/home/boca-deploy/.local/share/docker"\n"/foreign"\n',
        "/home/boca-deploy/.local/share/docker\n",
        "null\n",
        "[]\n",
        "{}\n",
    ],
)
def test_root_parser_rejects_wrong_or_nonexact_json_before_metadata(tmp_path, monkeypatch, raw):
    mock_metadata(monkeypatch, tmp_path / "absent", raw)
    with pytest.raises(module().ResourceNoGo):
        module()._identity(IPC)


def test_json_root_does_not_relax_symlink_ancestor_rejection(tmp_path, monkeypatch):
    target = tmp_path / "real"
    target.mkdir()
    (target / "volume").mkdir()
    (tmp_path / "alias").symlink_to(target, target_is_directory=True)
    mock_metadata(
        monkeypatch, tmp_path / "alias" / "volume", json.dumps(str(module()._ROOT)) + "\n"
    )
    with pytest.raises(OSError):
        module()._identity(IPC)


@pytest.mark.parametrize(
    ("damage", "phase"),
    [
        ("inventory", "INVENTORY"),
        ("pair", "PAIR"),
        ("ipc", "IPC_IDENTITY"),
        ("site", "SITE_IDENTITY"),
        ("labels", "IPC_IDENTITY"),
        ("egress", "EGRESS"),
        ("image", "IMAGE_PROVENANCE"),
        ("alias", "IMAGE_PROVENANCE"),
        ("control", "CONTROL_IDENTITY"),
        ("schema", "SNAPSHOT_VALIDATION"),
    ],
)
def test_snapshot_reports_fixed_phase_without_exception_or_metadata(damage, phase):
    observer = module()
    inv = inventory()

    def explode():
        raise ValueError(SECRET)

    def identity(name):
        if (damage, name) in (
            ("ipc", IPC),
            ("site", SITE),
            ("control", "control_socket_directory"),
        ):
            explode()
        return "1" * 64 if damage != "schema" else SECRET

    if damage == "labels":
        inv = replace(
            inv, volumes=(replace(inv.volumes[0], labels=((SECRET, SECRET),)), inv.volumes[1])
        )
    if damage == "egress":
        inv = replace(inv, networks=(replace(inv.networks[0], attached_ids=("9" * 64,)),))
    if damage == "alias":
        inv = replace(inv, images=(*inv.images[:2], replace(inv.images[2], references=(SECRET,))))
    with pytest.raises(observer.ResourceNoGo) as caught:
        observer.snapshot(
            RUN,
            inventory_reader=lambda: explode() if damage == "inventory" else inv,
            pair_reader=lambda _: explode() if damage == "pair" else pair_receipt(),
            identity_reader=identity,
            revision_reader=lambda _: (
                explode() if damage == "image" else observer.installed.SOURCE_SHA
            ),
        )
    assert getattr(caught.value, "phase", None) == phase
    assert SECRET not in str(caught.value)


def test_double_read_drift_has_its_own_failure_phase():
    first, second = snapshot(), snapshot()
    second["control_socket_directory_inode_sha256"] = "9" * 64
    values = iter((first, second))
    with pytest.raises(module().ResourceNoGo) as caught:
        module().observe(RUN, snapshot_reader=lambda _: next(values))
    assert getattr(caught.value, "phase", None) == "DRIFT"


def test_host_main_serializes_only_typed_phase_not_exception_details(monkeypatch, capsys):
    observer = module()

    def rejected(_):
        # Exercise the actual snapshot phase wrapping and host serializer.
        return observer.snapshot(
            RUN, inventory_reader=lambda: (_ for _ in ()).throw(ValueError(SECRET))
        )

    monkeypatch.setattr(observer, "observe", rejected)
    monkeypatch.setattr(sys, "argv", ["observer", "host", RUN])
    assert observer.main() == 3
    captured = capsys.readouterr()
    assert captured.out.encode() == failure("INVENTORY")
    assert captured.err == ""


@pytest.mark.parametrize(
    "raw",
    [
        failure().rstrip(),
        failure().replace(b'"schema":1', b'"schema":true'),
        failure().replace(b'"schema":1', b'"schema":1,"schema":1'),
        failure().replace(
            b'"state":"NO_GO"', b'"state":"NO_GO","private":"' + SECRET.encode() + b'"'
        ),
        failure() + SECRET.encode() * 100,
        b"BOCA_RETAINED_RESOURCES_FAILURE []\n",
    ],
)
def test_failure_parser_rejects_noncanonical_or_extended_frames(raw):
    receipt, rc = module().report(RUN, 3, raw, b"")
    assert rc != 0 and receipt == failure("TRANSPORT_UNVERIFIED")


@pytest.mark.parametrize("raw", [b"", b"bad receipt " + SECRET.encode()])
def test_runner_rejects_missing_or_bad_success_even_with_remote_zero(raw):
    receipt, rc = module().report(RUN, 0, raw, b"")
    assert rc != 0 and receipt == failure("RECEIPT_UNVERIFIED")


@pytest.mark.parametrize(
    ("raw", "remote_rc", "stderr", "phase"),
    [
        (failure(), 3, b"", "IPC_IDENTITY"),
        (failure("PAIR"), 3, b"", "PAIR"),
        (failure("invented-private-secret"), 3, b"", "TRANSPORT_UNVERIFIED"),
        (failure(run="123"), 3, b"", "TRANSPORT_UNVERIFIED"),
        (failure() + failure(), 3, b"", "TRANSPORT_UNVERIFIED"),
        (b"", 255, SECRET.encode(), "TRANSPORT_UNVERIFIED"),
        (b"", 124, b"", "TRANSPORT_UNVERIFIED"),
        (b"", 1, b"BOCA_BUNDLE state=NO_GO reason=hash_or_host_runtime\n", "BUNDLE_UNVERIFIED"),
        (
            b"",
            1,
            b"BOCA_BUNDLE state=NO_GO reason=hash_or_host_runtime\n" + SECRET.encode(),
            "TRANSPORT_UNVERIFIED",
        ),
        (failure(), 0, b"", "RECEIPT_UNVERIFIED"),
    ],
)
def test_runner_failure_classifier_keeps_nonzero_status_and_only_fixed_categories(
    tmp_path, raw, remote_rc, stderr, phase
):
    receipt, error = tmp_path / "receipt", tmp_path / "stderr"
    receipt.write_bytes(raw)
    error.write_bytes(stderr)
    result = subprocess.run(  # noqa: S603 - fixed local module with test-owned inputs
        [
            sys.executable,
            "-m",
            "boca_socios.host_boca_retained_resources",
            "report",
            RUN,
            str(remote_rc),
            str(receipt),
            str(error),
        ],
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode != 0
    assert result.stdout == failure(phase)
    assert result.stderr == b""
    assert SECRET.encode() not in result.stdout


@pytest.mark.parametrize("remote_rc", [0, 1, 3, 255])
def test_workflow_executes_real_step_and_never_accepts_success_with_remote_failure(
    tmp_path, remote_rc
):
    raw = module().observe(RUN, snapshot_reader=lambda _: snapshot()).decode()
    result, summary = run_step(tmp_path, remote_rc, raw, SECRET if remote_rc else "")
    assert (result.returncode == 0) is (remote_rc == 0)
    if remote_rc:
        assert '"phase":"TRANSPORT_UNVERIFIED"' in summary
        assert '"state":"READ_ONLY"' not in summary
    else:
        assert '"state":"READ_ONLY"' in summary
    assert SECRET not in summary + result.stdout + result.stderr


def test_workflow_preserves_typed_host_failure_in_summary(tmp_path):
    result, summary = run_step(tmp_path, 3, failure("SITE_IDENTITY").decode(), "")
    assert result.returncode != 0
    assert summary == failure("SITE_IDENTITY").decode()
    assert "STABLE" not in summary


def run_step(tmp_path, remote_rc, stdout, stderr):
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    step = workflow.split("      - name: Observe retained Boca resource provenance READ_ONLY\n", 1)[
        1
    ].split("      - name:", 1)[0]
    script = textwrap.dedent(step.split("        run: |\n", 1)[1])
    summary = tmp_path / "summary"
    summary.touch()
    # These command-boundary fakes run the actual workflow Bash body and actual
    # builder/verifier. No SSH, Docker, credential or network operation is made.
    setup = """
gh() { printf '%s\\n' '{"ref":"refs/heads/main","object":{"type":"commit","sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}'; }
ssh() { printf '%s' "$TEST_STDOUT"; printf '%s' "$TEST_STDERR" >&2; return "$TEST_REMOTE_RC"; }
timeout() { shift 3; "$@"; }
"""
    result = subprocess.run(  # noqa: S603 - reviewed Bash step with fake network commands
        ["/bin/bash", "-c", setup + script],
        cwd=ROOT,
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_RUN_ID": RUN,
            "GITHUB_REPOSITORY": "mbalbo2023/boca-socios-assistant",
            "BOCA_SOURCE_SHA": "a" * 40,
            "GITHUB_STEP_SUMMARY": str(summary),
            "TEST_STDOUT": stdout,
            "TEST_STDERR": stderr,
            "TEST_REMOTE_RC": str(remote_rc),
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    return result, summary.read_text()
