"""Protected host acceptance must accept only a bounded synthetic receipt."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from boca_socios import host_first_deploy as host

PASS = (
    "BOCA_SYNTHETIC_ACCEPTANCE state=PASS scope=container_loopback "
    "requests=21 median_ms=1.00 p95_ms=2.00 elapsed_ms=100.00 "
    "cpu_ms=30.00 process_peak_rss_kib=15000 scratch_bytes=12345 "
    "members=1 intents=1 notices=1 tls=verified engine=off "
    "site=not_contacted telegram=not_sent"
)


@pytest.mark.parametrize(
    "changed",
    [
        PASS + "\nprivate=secret",
        PASS.replace("state=PASS", "state=NO_GO"),
        PASS.replace("scope=container_loopback", "scope=owner_data"),
        PASS.replace("requests=21", "requests=17"),
        PASS.replace("requests=21", "requests=65"),
        PASS.replace("p95_ms=2.00", "p95_ms=nan"),
        PASS.replace("median_ms=1.00", "median_ms=3.00"),
        PASS.replace("elapsed_ms=100.00", "elapsed_ms=1.00"),
        PASS.replace("cpu_ms=30.00", "cpu_ms=120001.00"),
        PASS.replace("process_peak_rss_kib=15000", "process_peak_rss_kib=262145"),
        PASS.replace("scratch_bytes=12345", "scratch_bytes=99999999"),
        PASS.replace("scratch_bytes=12345", "scratch_bytes=8388609"),
        PASS.replace("intents=1", "intents=2"),
        PASS.replace("engine=off", "engine=on"),
        PASS.replace("telegram=not_sent", "telegram=sent"),
        "BOCA_SYNTHETIC_ACCEPTANCE state=NO_GO reason=synthetic_probe_failed",
        "",
    ],
)
def test_host_acceptance_receipt_rejects_missing_oversize_or_false_proof(changed: str) -> None:
    with pytest.raises(host.PreflightError):
        host._validate_beta_acceptance_receipt(changed)


def test_host_acceptance_receipt_is_one_exact_bounded_line() -> None:
    assert host._validate_beta_acceptance_receipt(PASS) == PASS


def test_host_probe_runs_only_in_twice_validated_controller(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source_sha = "a" * 40
    image = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64
    container = "c" * 64
    status_calls: list[str] = []
    commands: list[tuple[str, ...]] = []
    capacity = SimpleNamespace(
        stage_free_bytes=8 * 1024**3,
        docker_free_bytes=8 * 1024**3,
        stage_inodes=100000,
        docker_inodes=100000,
    )

    def status(*_args: str) -> tuple[SimpleNamespace, SimpleNamespace]:
        status_calls.append("checked")
        return SimpleNamespace(container_id=container), capacity

    def run(*args: str) -> str:
        commands.append(args)
        assert args == (
            "docker",
            "exec",
            "--user",
            "10001:10001",
            container,
            "python",
            "-m",
            "boca_socios.acceptance.host_probe",
        )
        return PASS

    monkeypatch.setattr(host, "_beta_acceptance_status", status)
    monkeypatch.setattr(host, "_run", run)
    monkeypatch.setattr(host, "_validate_storage_continuity", lambda *_args: None)
    host._beta_acceptance_phase(
        image, source_sha, "d" * 64, "https://boca.example.test:8443", "owner"
    )
    assert status_calls == ["checked", "checked"]
    assert len(commands) == 1
    output = capsys.readouterr().out
    assert f"BOCA_BETA_ACCEPTANCE state=PASS source_sha={source_sha} image={image}" in output
    assert "scope=container_loopback" in output and "members=1 intents=1 notices=1" in output


def test_postflight_container_change_discards_probe_pass(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    images = iter((SimpleNamespace(container_id="c" * 64), SimpleNamespace(container_id="d" * 64)))
    capacity = SimpleNamespace(
        stage_free_bytes=8 * 1024**3,
        docker_free_bytes=8 * 1024**3,
        stage_inodes=100000,
        docker_inodes=100000,
    )
    monkeypatch.setattr(host, "_beta_acceptance_status", lambda *_args: (next(images), capacity))
    monkeypatch.setattr(host, "_run", lambda *_args: PASS)
    monkeypatch.setattr(host, "_validate_storage_continuity", lambda *_args: None)
    with pytest.raises(host.PreflightError):
        host._beta_acceptance_phase(
            "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64,
            "a" * 40,
            "d" * 64,
            "https://boca.example.test:8443",
            "owner",
        )
    assert "state=PASS" not in capsys.readouterr().out


def test_unknown_installed_volume_refuses_probe_before_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = host.HostSnapshot(
        arch="x86_64",
        uid=10001,
        available_memory_kib=900000,
        available_disk_bytes=8 * 1024**3,
        available_inodes=100000,
        docker_disk_bytes=8 * 1024**3,
        docker_inodes=100000,
        root_ready=True,
        boca_containers=True,
        boca_volume=True,
        boca_network=True,
        cpu_headroom=1.0,
    )
    monkeypatch.setattr(host, "_verify_beta_compose", lambda *_args: None)
    monkeypatch.setattr(host, "collect_snapshot", lambda **_kwargs: snapshot)
    monkeypatch.setattr(
        host,
        "_names",
        lambda kind, _filter: (
            {host.OWNER_VOLUME, host.KEY_VOLUME, "boca-socios_unknown"}
            if kind == "volume"
            else {"a" * 64}
        ),
    )
    monkeypatch.setattr(
        host, "collect_diagnostic", lambda *_args, **_kwargs: pytest.fail("diagnostic reached")
    )
    with pytest.raises(host.PreflightError, match="namespace differs"):
        host._beta_acceptance_status(
            "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64,
            "a" * 40,
            "d" * 64,
            "https://boca.example.test:8443",
            "owner",
        )


@pytest.mark.parametrize(
    ("memory_kib", "cpu_headroom", "network_id", "accepted"),
    [
        (600 * 1024, 0.3, "a" * 64, True),
        (500 * 1024, 0.3, "a" * 64, False),
        (600 * 1024, 0.2, "a" * 64, False),
        (600 * 1024, 0.3, "b" * 64, False),
    ],
)
def test_installed_headroom_and_network_id_are_checked_without_preinstall_threshold(
    monkeypatch: pytest.MonkeyPatch,
    memory_kib: int,
    cpu_headroom: float,
    network_id: str,
    accepted: bool,
) -> None:
    image = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64
    snapshot = host.HostSnapshot(
        arch="x86_64",
        uid=10001,
        available_memory_kib=memory_kib,
        available_disk_bytes=8 * 1024**3,
        available_inodes=100000,
        docker_disk_bytes=8 * 1024**3,
        docker_inodes=100000,
        root_ready=True,
        boca_containers=True,
        boca_volume=True,
        boca_network=True,
        cpu_headroom=cpu_headroom,
    )
    diagnostic = SimpleNamespace(container_id="c" * 64, network_id=network_id)
    capacity = SimpleNamespace(
        stage_free_bytes=8 * 1024**3,
        docker_free_bytes=8 * 1024**3,
        stage_inodes=100000,
        docker_inodes=100000,
    )
    monkeypatch.setattr(host, "_verify_beta_compose", lambda *_args: None)
    monkeypatch.setattr(host, "collect_snapshot", lambda **_kwargs: snapshot)
    monkeypatch.setattr(
        host,
        "_names",
        lambda kind, _filter: (
            {host.OWNER_VOLUME, host.KEY_VOLUME, host.DATA_VOLUME}
            if kind == "volume"
            else {"a" * 64}
        ),
    )
    for name in ("_validate_owner_volume", "_validate_key_volume", "_validate_data_volume"):
        monkeypatch.setattr(host, name, lambda: None)
    commands: list[tuple[str, ...]] = []

    def run(*args: str, **_kwargs: object) -> str:
        commands.append(args)
        if args[:3] == ("docker", "network", "ls"):
            assert args == (
                "docker",
                "network",
                "ls",
                "--no-trunc",
                "-q",
                "--filter",
                "name=^boca-socios_",
            )
            return "a" * 64
        return ""

    monkeypatch.setattr(host, "_run", run)
    monkeypatch.setattr(host, "collect_diagnostic", lambda *_args, **_kwargs: diagnostic)
    monkeypatch.setattr(host, "_beta_loopback_health", lambda *_args: None)
    monkeypatch.setattr(host, "_storage_snapshot", lambda: capacity)
    monkeypatch.setattr(host, "_validate_storage_capacity", lambda *_args: None)

    def operation() -> tuple[object, object]:
        return host._beta_acceptance_status(
            image, "a" * 40, "d" * 64, "https://boca.example.test:8443", "owner"
        )

    if accepted:
        assert operation() == (diagnostic, capacity)
        assert any(args[:3] == ("docker", "network", "ls") for args in commands)
    else:
        with pytest.raises(host.PreflightError):
            operation()


def test_protected_workflow_runs_probe_then_boca_only_stop_in_one_job() -> None:
    workflow = Path(".github/workflows/boca-first-deploy.yml").read_text(encoding="utf-8")
    assert "beta-acceptance" in workflow
    assert 'test "$BOCA_BETA_ENV_READY" = ready' in workflow
    assert "python scripts/check_release_run.py" in workflow
    assert "python scripts/check_beta_deploy_contract.py" in workflow
    assert workflow.index("Recheck current main before BETA acceptance") < workflow.index(
        "Invoke bounded synthetic BETA acceptance"
    )
    assert workflow.index(
        "Validate immutable inputs and successful matching release"
    ) < workflow.index("Mark protected BETA acceptance host attempt")
    assert workflow.index("Configure pinned SSH host key and dedicated identity") < workflow.index(
        "Mark protected BETA acceptance host attempt"
    )
    assert workflow.index("Recheck current main before BETA acceptance") < workflow.index(
        "Mark protected BETA acceptance host attempt"
    )
    assert workflow.index("Invoke bounded synthetic BETA acceptance") < workflow.index(
        "Stop positively identified Boca services after BETA acceptance"
    )
    assert "if: always() && inputs.operation == 'beta-acceptance'" in workflow
    assert "steps.boca_beta_acceptance_attempt.outputs.started == 'true'" in workflow
    assert "python3 - stop-test" in workflow


def test_acceptance_dispatch_rejects_stale_source_missing_markers_or_site_envelope() -> None:
    workflow = Path(".github/workflows/boca-first-deploy.yml").read_text(encoding="utf-8")
    gate = workflow.split(
        "      - name: Require verified protected environment and matching main commit\n", 1
    )[1].split("      - name:", 1)[0]
    script = textwrap.dedent(gate.split("        run: |\n", 1)[1])
    environment = {
        **os.environ,
        "GITHUB_RUN_ATTEMPT": "1",
        "BOCA_SOURCE_SHA": "a" * 40,
        "GITHUB_SHA": "a" * 40,
        "BOCA_SERVICE": "controller",
        "BOCA_BUDGET": "0.5cpu-256m-64pids",
        "BOCA_OPERATION": "beta-acceptance",
        "BOCA_HOST_READONLY_ENV_READY": "",
        "BOCA_DEPLOY_ENV_READY": "ready",
        "BOCA_BETA_ENV_READY": "ready",
        "BOCA_BETA_PANEL_ORIGIN": "https://boca.example.test:8443",
        "BOCA_BETA_OWNER_SUBJECT": "owner",
        "BOCA_IMAGE_REF": "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64,
        "BOCA_RELEASE_RUN_ID": "12345",
        "BOCA_SITE_ENVELOPE": "",
    }

    def status() -> int:
        return subprocess.run(
            ["/usr/bin/bash", "-e", "-o", "pipefail"],
            input=script,
            text=True,
            capture_output=True,
            env=environment,
            timeout=3,
            check=False,
        ).returncode  # noqa: S603 - isolated shell gate only

    assert status() == 0
    for field, changed in (
        ("GITHUB_SHA", "c" * 40),
        ("GITHUB_RUN_ATTEMPT", "2"),
        ("BOCA_BETA_ENV_READY", ""),
        ("BOCA_DEPLOY_ENV_READY", ""),
        ("BOCA_RELEASE_RUN_ID", ""),
        ("BOCA_IMAGE_REF", ""),
        ("BOCA_SITE_ENVELOPE", "ciphertext"),
    ):
        original = environment[field]
        environment[field] = changed
        assert status() != 0, field
        environment[field] = original


@pytest.mark.parametrize("extra", ["", "\nprivate=secret"])
def test_workflow_accepts_only_exact_host_receipt(tmp_path: Path, extra: str) -> None:
    workflow = Path(".github/workflows/boca-first-deploy.yml").read_text(encoding="utf-8")
    step = workflow.split("      - name: Invoke bounded synthetic BETA acceptance\n", 1)[1].split(
        "      - name:", 1
    )[0]
    script = textwrap.dedent(step.split("        run: |\n", 1)[1])
    source_sha = "a" * 40
    image = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64
    receipt = (
        f"BOCA_BETA_ACCEPTANCE state=PASS source_sha={source_sha} image={image} "
        + PASS.removeprefix("BOCA_SYNTHETIC_ACCEPTANCE state=PASS ")
        + " stage_free_mib=8192 docker_free_mib=8192 stage_inodes=100000 docker_inodes=100000"
        + extra
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_ssh = fake_bin / "ssh"
    fake_ssh.write_text('#!/bin/sh\nprintf "%s\\n" "$BOCA_TEST_RECEIPT"\n', encoding="utf-8")
    fake_ssh.chmod(0o700)
    (tmp_path / "boca-ssh").mkdir()
    (tmp_path / "boca-beta-compose.sha").write_text("d" * 64, encoding="ascii")
    summary = tmp_path / "summary"
    result = subprocess.run(
        ["/usr/bin/bash", "-e", "-o", "pipefail"],
        input=script,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(summary),
            "BOCA_SOURCE_SHA": source_sha,
            "BOCA_IMAGE_REF": image,
            "BOCA_BETA_PANEL_ORIGIN": "https://boca.example.test:8443",
            "BOCA_BETA_OWNER_SUBJECT": "owner",
            "BOCA_TEST_RECEIPT": receipt,
        },
        timeout=5,
        check=False,
    )  # noqa: S603 - isolated shell with fake SSH binary
    assert (result.returncode == 0) is (extra == "")
    written = summary.read_text(encoding="utf-8")
    assert ("NO_GO" in written) is (extra != "")
    assert "private=secret" not in written


def test_main_drift_after_probe_still_runs_proven_boca_stop(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/boca-first-deploy.yml").read_text(encoding="utf-8")
    step = workflow.split(
        "      - name: Stop positively identified Boca services after BETA acceptance\n", 1
    )[1].split("      - name:", 1)[0]
    script = textwrap.dedent(step.split("        run: |\n", 1)[1])
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name, code in {
        "gh": '#!/bin/sh\nprintf "{}\\n"\n',
        "python": "#!/bin/sh\nexit 1\n",  # a stale current-main check
        "ssh": (
            "#!/bin/sh\n"
            'touch "$BOCA_TEST_STOP_CALL"\n'
            'printf "BOCA_STOP_TEST state=STOPPED source_sha=%s containers=1 data=preserved\\n" '
            '"$BOCA_SOURCE_SHA"\n'
        ),
    }.items():
        path = fake_bin / name
        path.write_text(code, encoding="utf-8")
        path.chmod(0o700)
    (tmp_path / "boca-ssh").mkdir()
    summary = tmp_path / "summary"
    stop_called = tmp_path / "stop-called"
    source_sha = "a" * 40
    result = subprocess.run(
        ["/usr/bin/bash", "-e", "-o", "pipefail"],
        input=script,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(summary),
            "GITHUB_REPOSITORY": "mbalbo2023/boca-socios-assistant",
            "BOCA_SOURCE_SHA": source_sha,
            "BOCA_TEST_STOP_CALL": str(stop_called),
        },
        timeout=5,
        check=False,
    )  # noqa: S603 - isolated shell with fake GitHub and SSH binaries
    assert result.returncode != 0
    assert stop_called.exists()
    written = summary.read_text(encoding="utf-8")
    assert "main changed" in written
    assert f"BOCA_STOP_TEST state=STOPPED source_sha={source_sha}" in written
