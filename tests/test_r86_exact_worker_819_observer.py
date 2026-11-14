"""R86: inspect only the physical #819 worker without expanding recovery authority."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from test_ci_parallel_pytest_contract import assert_required_ci_covers

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts import host_cutover_worker_inspect as observer  # noqa: E402
from scripts import host_cutover_worker_recovery as recovery  # noqa: E402

ATTEMPT = "42353468231"
SOURCE = "0538b3fb29cc0245a8387b7023c394883d0ea9a8"
BROWSER = (
    "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
    "d740c610d032aa20fecff1602cc96e49fd63c597c49855990a9bc081a6998619"
)
LEGACY_ID = "27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793"
LEGACY_SOURCE = "cabce9f1e452e63ded115f447559a358dc0f4d1b"
LEGACY_IMAGE = (
    "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:"
    "cf6e4266cfcfea0c07fa31301d59c7aaa3b9c2fefb9f6843baddd208cacd3b59"
)
CID = "8d" * 32


def _rootless(monkeypatch: pytest.MonkeyPatch, seccomp: str = "ABSENT") -> None:
    monkeypatch.setattr(observer.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(observer.os, "getegid", lambda: 10001)
    monkeypatch.setattr(
        observer,
        "_runtime_stat",
        lambda name: "PRESENT_OWNED" if name == "docker.sock" else seccomp,
    )


def _simulate(
    monkeypatch: pytest.MonkeyPatch,
    *,
    present: bool,
    running: bool = False,
    image: str = BROWSER,
    source: str = SOURCE,
) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []

    def docker(*args: str) -> str:
        calls.append(args)
        if args[0] == "ps":
            assert args == (
                "ps",
                "-a",
                "-q",
                "--no-trunc",
                "--filter",
                f"name=^/boca-socios-cutover-preflight-{ATTEMPT}$",
            )
            return CID if present else ""
        assert args[0:2] == ("inspect", "--format") and len(args) == 4
        if args[3] == CID:
            assert present
            if args[2] == observer.INSPECT_FULL_JSON_LENGTH:
                return "54321"
            assert args[2] == observer.INSPECT_NO_HEALTH
            return json.dumps(
                {
                    "id": CID,
                    "name": f"/boca-socios-cutover-preflight-{ATTEMPT}",
                    "image_ref": image,
                    "revision": source,
                    "project": "boca-socios",
                    "attempt": ATTEMPT,
                    "running": running,
                    "health": None,
                    "ports": {},
                }
            )
        assert args[3] == LEGACY_ID and args[2] == observer.INSPECT
        return json.dumps(
            {
                "id": LEGACY_ID,
                "name": "/boca-socios-controller-1",
                "image_ref": LEGACY_IMAGE,
                "revision": LEGACY_SOURCE,
                "project": "boca-socios",
                "attempt": None,
                "running": True,
                "health": "healthy",
                "ports": {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]},
            }
        )

    monkeypatch.setattr(observer, "_docker", docker)
    return calls


@pytest.mark.parametrize("running", [True, False])
def test_r86_exact_pin_worker_is_observed_readonly(
    monkeypatch: pytest.MonkeyPatch, running: bool
) -> None:
    _rootless(monkeypatch, seccomp="PRESENT_OWNED")
    calls = _simulate(monkeypatch, present=True, running=running)

    record = observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)

    assert record["probe"] == "PRESENT_PIN_MATCH"
    assert record["probe_id"] == CID
    assert record["probe_running"] is running
    assert record["seccomp"] == "PRESENT_OWNED"
    assert record["original"] == "RUNNING_HEALTHY"
    assert record["original_port"] == "LOOPBACK_8443"
    assert record["observer_writes"] == 0
    assert record["foreign_resources_touched"] is False
    assert record["cutover_authorized"] is False
    assert len(calls) == 4
    assert set(command[0] for command in calls) == {"ps", "inspect"}
    assert observer.verify(observer.canonical(record) + b"\n", ATTEMPT, LEGACY_ID) == record


def test_r86_absent_probe_does_not_authorize_cutover(monkeypatch: pytest.MonkeyPatch) -> None:
    _rootless(monkeypatch)
    calls = _simulate(monkeypatch, present=False)

    record = observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)

    assert record["probe"] == "ABSENT"
    assert record["probe_id"] is None
    assert record["seccomp"] == "ABSENT"
    assert record["original"] == "RUNNING_HEALTHY"
    assert record["cutover_authorized"] is False
    assert len(calls) == 2
    assert observer.verify(observer.canonical(record) + b"\n", ATTEMPT, LEGACY_ID) == record


@pytest.mark.parametrize("invalid", [("wrong image", "image"), ("wrong SHA", "source")])
def test_r86_wrong_worker_pin_fails_closed(
    monkeypatch: pytest.MonkeyPatch, invalid: tuple[str, str]
) -> None:
    _rootless(monkeypatch)
    kwargs = {"image": BROWSER + "x"} if invalid[1] == "image" else {"source": "a" * 40}
    calls = _simulate(monkeypatch, present=True, **kwargs)

    record = observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)

    assert record["probe"] == "PRESENT_UNVERIFIED"
    assert record["probe_id"] is None
    assert record["probe_running"] is None
    assert record["original"] == "RUNNING_HEALTHY"
    assert record["cutover_authorized"] is False
    assert len(calls) == 4


def test_r86_incident_map_is_fixed_and_recovery_targets_unchanged() -> None:
    assert observer.KNOWN_FAILED_PROBES[ATTEMPT] == (SOURCE, BROWSER)
    assert observer.KNOWN_FAILED_PROBES["42329475083"][0] == (
        "92624ed6b7e75c6010f59670c866df00a29766dd"
    )
    assert observer.KNOWN_FAILED_PROBES["42341290485"][0] == (
        "1199c46fee8053e637b220ad9365ce3af15eb8e5"
    )
    with pytest.raises(observer.InspectError, match="COORDINATES"):
        observer.observe("42353468232", LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)
    with pytest.raises(recovery.RecoveryError, match="UNREVIEWED_TARGET"):
        recovery._known_target(
            recovery.RecoveryTarget(
                ATTEMPT, CID, SOURCE, BROWSER, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE
            )
        )


def test_r86_workflow_reuses_bounded_readonly_path_and_rejects_other_modes() -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    case = workflow.split("            cutover-a-worker-inspect)\n", 1)[1].split(
        "              ;;", 1
    )[0]
    assert '42353468231) test "$BOCA_PROTECTED_ACTION_CONTEXT" = 42353468231' in case
    assert 'test -z "$BOCA_IMAGE_REF"' in case
    assert 'test -z "$BOCA_BROWSER_IMAGE_REF"' in case
    assert 'test -z "$BOCA_RELEASE_RUN_ID"' in case
    assert 'test -z "$BOCA_SOURCE_SHA_SUBMITTED"' in case
    assert "BOCA-R86-WORKER-819-READONLY" in workflow
    assert_required_ci_covers("tests/test_r86_exact_worker_819_observer.py")
    inspect = workflow.split(
        "      - name: Inspect one failed Boca worker probe READ_ONLY by exact identity", 1
    )[1]
    inspect = inspect.split("      - name:", 1)[0]
    assert "< scripts/host_cutover_worker_inspect.py" in inspect
    assert "scripts/host_cutover_worker_inspect.py verify" in inspect
    assert "umask 077" in inspect
    assert 'mktemp -d "$RUNNER_TEMP/boca-worker-readonly-inspect.' in inspect
    assert "ulimit -f 4 || exit 99" in inspect
    for forbidden in ("docker stop", "docker rm", "docker pull", "docker run", "docker exec"):
        assert forbidden not in inspect
    # R87 adds a separately gated stopped-only recovery for the observed CID;
    # it must never change this R86 inspector's read-only host contract.
    recovery = (ROOT / "scripts/host_cutover_worker_recovery.py").read_text()
    assert '"42353468231"' in recovery and '"host-819": TARGET_819' in recovery
    assert "docker container rm" not in inspect


def _inspection_step() -> str:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    heading = "      - name: Inspect one failed Boca worker probe READ_ONLY by exact identity\n"
    assert workflow.count(heading) == 1
    section = workflow.split(heading, 1)[1].split("\n      - name:", 1)[0]
    return textwrap.dedent(section.split("        run: |\n", 1)[1])


def _fake_ssh_env(tmp_path: Path, *, raw: bytes, exit_code: int = 0) -> dict[str, str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_ssh = fake_bin / "ssh"
    fake_ssh.write_text(
        "#!/usr/bin/env python3\n"
        "import os,resource,sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['FAKE_SSH_MARKER']).write_text('invoked')\n"
        "Path(os.environ['FAKE_SSH_LIMIT']).write_text(str(resource.getrlimit(resource.RLIMIT_FSIZE)[0]))\n"
        "Path(os.environ['FAKE_SSH_MODE']).write_text(str(os.fstat(1).st_mode & 0o777))\n"
        "sys.stdout.buffer.write(Path(os.environ['FAKE_SSH_PAYLOAD']).read_bytes())\n"
        "sys.stderr.write('PRIVATE_SSH_ERROR_NEVER_PRINT')\n"
        "raise SystemExit(int(os.environ['FAKE_SSH_CODE']))\n",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o700)
    raw_file = tmp_path / "fake-receipt"
    raw_file.write_bytes(raw)
    env = dict(os.environ)
    env.update(
        PATH=str(fake_bin) + os.pathsep + env["PATH"],
        RUNNER_TEMP=str(tmp_path),
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary"),
        BOCA_PROTECTED_ACTION_CONTEXT=ATTEMPT,
        BOCA_LEGACY_CONTROLLER_ID=LEGACY_ID,
        BOCA_LEGACY_SOURCE_SHA=LEGACY_SOURCE,
        BOCA_LEGACY_IMAGE_REF=LEGACY_IMAGE,
        FAKE_SSH_MARKER=str(tmp_path / "ssh.called"),
        FAKE_SSH_LIMIT=str(tmp_path / "ssh.limit"),
        FAKE_SSH_MODE=str(tmp_path / "ssh.mode"),
        FAKE_SSH_PAYLOAD=str(raw_file),
        FAKE_SSH_CODE=str(exit_code),
    )
    return env


def _run_fake_workflow(tmp_path: Path, *, raw: bytes, exit_code: int = 0):
    result = subprocess.run(  # noqa: S603 - real workflow Bash, fake SSH only
        ["/usr/bin/bash", "-e"],
        input=_inspection_step(),
        text=True,
        cwd=ROOT,
        env=_fake_ssh_env(tmp_path, raw=raw, exit_code=exit_code),
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert (tmp_path / "ssh.called").read_text() == "invoked"
    assert (tmp_path / "ssh.limit").read_text() == "4096"
    assert (tmp_path / "ssh.mode").read_text() == "384"  # 0600 on private receipt
    assert list(tmp_path.glob("boca-worker-readonly-inspect.*")) == []
    assert "PRIVATE_SSH_ERROR_NEVER_PRINT" not in result.stdout + result.stderr
    return result, (tmp_path / "summary").read_text()


def test_r86_real_bash_accepts_exact_bounded_readonly_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _rootless(monkeypatch)
    _simulate(monkeypatch, present=False)
    record = observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)
    result, summary = _run_fake_workflow(tmp_path, raw=observer.canonical(record) + b"\n")

    assert result.returncode == 0, result.stderr
    assert f"BOCA_WORKER_INSPECT state=READ_ONLY_NO_GO attempt={ATTEMPT}" in summary
    assert '"observer_writes":0' in summary
    assert '"cutover_authorized":false' in summary


@pytest.mark.parametrize(
    ("raw", "exit_code", "expected"),
    [
        (b"BOCA_WORKER_INSPECT state=READ_ONLY_NO_GO\n", 255, "SSH_255"),
        (b"PRIVATE_HOST_DATA" * 512, 0, "HOST_EXIT_NONZERO"),
        (b"{}\n", 0, "NO_GO"),
    ],
)
def test_r86_real_bash_fails_closed_on_transport_overflow_or_fake_receipt(
    tmp_path: Path, raw: bytes, exit_code: int, expected: str
) -> None:
    result, summary = _run_fake_workflow(tmp_path, raw=raw, exit_code=exit_code)

    assert result.returncode != 0
    assert expected in summary + result.stderr
    assert "PRIVATE_HOST_DATA" not in summary + result.stdout + result.stderr
