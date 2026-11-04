"""Offline policy for the one protected, new-only browser IPC BETA operation."""

from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/boca-first-deploy.yml"


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _step(name: str) -> str:
    return _workflow().split(f"      - name: {name}\n", 1)[1].split("      - name:", 1)[0]


def test_browser_option_is_separately_gated_without_weakening_legacy_operations() -> None:
    workflow = _workflow()
    assert "beta-browser-install" in workflow.split("options: [", 1)[1].split("]", 1)[0]
    assert "browser_image_ref:" in workflow
    assert "BOCA_BROWSER_IMAGE_REF: ${{ inputs.browser_image_ref }}" in workflow
    assert "BOCA_BROWSER_ENV_READY: ${{ vars.BOCA_BROWSER_ENV_READY }}" in workflow
    assert "options: [0.5cpu-256m-64pids, 1.5cpu-1024m-192pids, 1.75cpu-1152m-224pids]" in workflow
    gate = _step("Require verified protected environment and matching main commit")
    for proof in (
        'test "$GITHUB_RUN_ATTEMPT" = 1',
        'test "$BOCA_SOURCE_SHA" = "$GITHUB_SHA"',
        'test "$BOCA_SERVICE" = controller',
        'if [[ "$BOCA_OPERATION" = beta-browser-install ]]; then',
        'test "$BOCA_BUDGET" = 1.5cpu-1024m-192pids',
        'test "$BOCA_BUDGET" = 0.5cpu-256m-64pids',
        'if [[ "$BOCA_OPERATION" != beta-browser-* && "$BOCA_OPERATION" != telegram-* && "$BOCA_OPERATION" != cutover-a-observe ]]; then test -z "$BOCA_BROWSER_IMAGE_REF"; fi',
        "beta-browser-install)",
        'test "$BOCA_DEPLOY_ENV_READY" = ready',
        'test "$BOCA_BETA_ENV_READY" = ready',
        'test "$BOCA_BROWSER_ENV_READY" = ready',
        "ghcr[.]io/mbalbo2023/boca-socios-assistant-browser@sha256:[0-9a-f]{64}",
        'test "$BOCA_BETA_PANEL_ORIGIN" = http://localhost:8443',
        'test -z "$BOCA_SITE_ENVELOPE"',
    ):
        assert proof in gate
    for legacy in (
        "owner-enroll)",
        "beta-install|beta-start|beta-acceptance)",
        "telegram-migrate|telegram-prepare|telegram-install|telegram-verify|telegram-test)",
        'if [[ "$BOCA_OPERATION" = owner-enroll ]]',
    ):
        assert legacy in gate
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "github.actor == 'mbalbo2023'" in workflow
    assert "environment: boca-first-deploy" in workflow
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in workflow
    assert "|| 'boca-first-deploy'" in workflow
    assert "  push:" not in workflow


def test_browser_requires_both_signed_off_digests_from_exact_same_release_before_ssh() -> None:
    workflow = _workflow()
    legacy = _step("Validate immutable inputs and successful matching release")
    companion = _step("Require same-run immutable browser companion release manifest")
    assert "startsWith(inputs.operation, 'beta-browser-')" in legacy
    assert "python scripts/check_release_run.py" in legacy
    assert "--name boca-release-manifest" in legacy
    assert "python -m boca_socios.release_manifest verify" in legacy
    assert 'python scripts/check_deploy_inputs.py --browser-ipc-v2 "$BOCA_IMAGE_REF"' in legacy
    assert 'python scripts/check_deploy_inputs.py "$BOCA_IMAGE_REF"' in legacy
    assert "startsWith(inputs.operation, 'beta-browser-')" in companion
    assert '[[ "$GITHUB_RUN_ID" =~ ^[1-9][0-9]*$ ]]' in companion
    assert 'gh run download "$BOCA_RELEASE_RUN_ID"' in companion
    assert "--name boca-browser-release-manifest" in companion
    assert "python -m boca_socios.browser_release_manifest verify" in companion
    for required in (
        '"$BOCA_IMAGE_REF"',
        '"$BOCA_BROWSER_IMAGE_REF"',
        '"$BOCA_SOURCE_SHA"',
        '"$BOCA_RELEASE_RUN_ID"',
    ):
        assert required in companion
    assert workflow.index("Require same-run immutable browser companion") < workflow.index(
        "Configure pinned SSH host key"
    )


def test_browser_runner_validates_three_reviewed_files_and_two_service_contract() -> None:
    workflow = _workflow()
    hashing = _step("Hash reviewed optional browser IPC overlay and seccomp")
    assert "sha256sum compose.beta.browser.yaml" in hashing
    assert "sha256sum docker/seccomp_profile.json" in hashing
    assert "sha256sum compose.beta.yaml" in _step("Hash reviewed served BETA Compose file")
    model = _step("Validate exact optional dual-service IPC Compose model before SSH")
    assert "startsWith(inputs.operation, 'beta-browser-')" in model
    assert "BOCA_BROWSER_IMAGE: ${{ inputs.browser_image_ref }}" in model
    assert "BOCA_BROWSER_SECCOMP_PATH: /srv/boca-socios/seccomp_profile.json" in model
    assert "BOCA_BROWSER_ATTEMPT_ID: ${{ github.run_id }}" in model
    assert (
        "docker compose -p boca-socios -f compose.beta.yaml -f compose.beta.browser.yaml config --format json"
        in model
    )
    assert "--topology=browser-ipc-v2" in model
    assert "python scripts/check_beta_deploy_contract.py" in model
    assert workflow.index("Validate exact optional dual-service") < workflow.index(
        "Configure pinned SSH host key"
    )


def test_browser_host_staging_is_marker_first_and_three_atomic_ssh_stdin_uploads() -> None:
    workflow = _workflow()
    preflight = _step("Read-only owner and new-only browser IPC host preflight")
    before_stage = _step("Recheck current main before new-only browser staging")
    attempt = _step("Mark browser IPC staging attempt for immediate selective cleanup")
    staging = _step("Record preexisting Boca images and atomically stage reviewed browser files")
    assert "browser-preflight" in preflight
    assert "python scripts/check_main_ref.py" in before_stage
    assert "id: boca_browser_stage_attempt" in attempt
    assert "started=true" in attempt
    assert "browser-stage" in staging
    # C2c host_first_deploy._browser_stage emits every one of these fields;
    # accepting only its old three-field prefix would reject a real install.
    pattern = staging.split('stage_pattern="', 1)[1].split('"', 1)[0]
    assert "namespace=new-only no_worker=yes" in pattern
    assert "mem_kib=[0-9]+ cpu_ceiling=[0-9]+[.][0-9]{2}" in pattern
    assert "stage_free_mib=[0-9]+ docker_free_mib=[0-9]+" in pattern
    concrete = pattern.replace("$GITHUB_RUN_ID", "123456789")
    receipt = (
        "BOCA_BROWSER_STAGE_PASS attempt=123456789 uid=10001 owner=existing"
        " namespace=new-only no_worker=yes mem_kib=1677722 cpu_ceiling=2.00"
        " pids_free=512 stage_free_mib=4096 docker_free_mib=8192"
    )
    assert re.fullmatch(concrete, receipt)
    for invalid in (
        receipt.replace("attempt=123456789", "attempt=987654321"),
        receipt.replace("no_worker=yes", "no_worker=no"),
        receipt.replace("namespace=new-only ", ""),
        receipt + " unreviewed=1",
    ):
        assert not re.fullmatch(concrete, invalid)
    assert 'stage_code="$(< src/boca_socios/host_browser_file_stage.py)"' in staging
    assert 'python3 -c "$stage_code" "$slot" "$reviewed_sha" "$GITHUB_RUN_ID"' in staging
    assert '"$BOCA_SOURCE_SHA" "$BOCA_IMAGE_REF" "$BOCA_BROWSER_IMAGE_REF"' in staging
    assert (
        'ssh -F "$RUNNER_TEMP/boca-ssh/config" '
        "-o ServerAliveInterval=10 -o ServerAliveCountMax=2 boca-target "
        '"$stage_command" < "$file"'
    ) in staging
    for upload in (
        "stage_one base compose.beta.yaml",
        "stage_one overlay compose.beta.browser.yaml",
        "stage_one seccomp docker/seccomp_profile.json",
    ):
        assert upload in staging
    assert "BOCA_BROWSER_FILE_STAGE_PASS" in staging
    assert "scp " not in staging
    assert (
        workflow.index("Read-only owner and new-only browser IPC")
        < workflow.index("Recheck current main before new-only browser staging")
        < workflow.index("Mark browser IPC staging attempt")
        < workflow.index("Record preexisting Boca images and atomically stage")
    )


def test_browser_post_stage_host_model_main_and_8443_checks_precede_single_apply() -> None:
    workflow = _workflow()
    host_model = _step("Verify exact staged browser host model and private seccomp proof")
    before_apply = _step("Recheck main and only Boca loopback 8443 before browser effects")
    apply = _step("Start worker then controller only after healthy private socket proof")
    assert "browser-config" in host_model
    assert "boca-browser-host-model.json" in host_model
    assert "--topology=browser-ipc-v2" in host_model
    assert "python scripts/check_main_ref.py" in before_apply
    assert "port-check" in before_apply
    assert "BOCA_PORT_CHECK state=FREE address=127.0.0.1 port=8443 reserved=no" in before_apply
    assert "browser-apply" in apply
    assert "no real provider" in apply
    assert "127.0.0.1:8443" in apply
    assert "https://" not in apply
    assert "Termux" not in apply
    assert (
        workflow.index("Verify exact staged browser host model")
        < workflow.index("Recheck main and only Boca loopback 8443")
        < workflow.index("Start worker then controller")
    )


def test_browser_failure_uses_only_same_job_immediate_positive_id_cleanup() -> None:
    workflow = _workflow()
    cleanup = _step("Immediately clean only positively identified failed browser IPC attempt")
    assert (
        "if: always() && (failure() || cancelled()) && inputs.operation == 'beta-browser-install' && "
        "steps.boca_browser_stage_attempt.outputs.started == 'true'"
    ) in cleanup
    assert "--browser-ipc-v2" in cleanup
    assert "< src/boca_socios/host_cleanup.py" in cleanup
    for arg in (
        '"$BOCA_IMAGE_REF"',
        '"$BOCA_SOURCE_SHA"',
        '"$BOCA_BROWSER_IMAGE_REF"',
        '"$GITHUB_RUN_ID"',
        '"$(cat "$RUNNER_TEMP/boca-beta-compose.sha")"',
        '"$(cat "$RUNNER_TEMP/boca-browser-overlay.sha")"',
        '"$(cat "$RUNNER_TEMP/boca-browser-seccomp.sha")"',
    ):
        assert arg in cleanup
    assert "BOCA_BROWSER_IPC_CLEANUP state=(CLEANED|ALREADY_CLEAN)" in cleanup
    assert "volumes=preserved seccomp_stage=" in cleanup
    assert "partials_removed=[0-9]+ marker=" in cleanup
    assert "browser_image_logical_mib=" in cleanup
    assert "NO_GO INDETERMINADO" in cleanup
    assert "original NO_GO" in cleanup
    assert "no retry" in cleanup.lower()
    for forbidden in ("docker prune", "--force", " -v ", " scp ", "docker compose down"):
        assert forbidden not in cleanup
    assert workflow.index("Start worker then controller") < workflow.index(
        "Immediately clean only positively identified failed browser IPC attempt"
    )
    assert (
        workflow.count(
            "if: always() && (failure() || cancelled()) && inputs.operation == 'beta-browser-install'"
        )
        == 1
    )


def test_browser_ssh_transport_has_per_phase_deadlines_with_cleanup_headroom() -> None:
    # Keepalive is browser-only: the legacy long owner-enrollment SSH wait
    # must retain its existing transport semantics.
    config = _step("Configure pinned SSH host key and dedicated identity")
    assert "ServerAliveInterval" not in config
    deadlines = (
        ("Read-only owner and new-only browser IPC host preflight", (60,)),
        (
            "Record preexisting Boca images and atomically stage reviewed browser files",
            (60, 30, 30, 30),
        ),
        ("Verify exact staged browser host model and private seccomp proof", (60,)),
        ("Recheck main and only Boca loopback 8443 before browser effects", (30,)),
        ("Start worker then controller only after healthy private socket proof", (600,)),
        ("Immediately clean only positively identified failed browser IPC attempt", (180,)),
    )
    assert sum(sum(phase) for _, phase in deadlines) <= 20 * 60
    assert deadlines[-1][1] == (180,)
    for name, phase_deadlines in deadlines:
        step = _step(name)
        for seconds in set(phase_deadlines):
            bounded = (
                f"timeout --signal=TERM --kill-after=5s {seconds}s "
                'ssh -F "$RUNNER_TEMP/boca-ssh/config" '
                "-o ServerAliveInterval=10 -o ServerAliveCountMax=2 boca-target "
            )
            assert step.count(bounded) == 1
    assert "# The original NO_GO is terminal. No retry" in _step(
        "Immediately clean only positively identified failed browser IPC attempt"
    )


@pytest.mark.parametrize(
    "failed_step",
    [
        "Record preexisting Boca images and atomically stage reviewed browser files",
        "Verify exact staged browser host model and private seccomp proof",
        "Recheck main and only Boca loopback 8443 before browser effects",
        "Start worker then controller only after healthy private socket proof",
    ],
)
def test_browser_early_or_late_failure_cannot_skip_same_job_cleanup(failed_step: str) -> None:
    workflow = _workflow()
    mark = "Mark browser IPC staging attempt for immediate selective cleanup"
    cleanup = "Immediately clean only positively identified failed browser IPC attempt"
    assert workflow.index(mark) < workflow.index(failed_step) < workflow.index(cleanup)
    assert "started=true" in _step(mark)
    assert (
        "if: always() && (failure() || cancelled()) && inputs.operation == 'beta-browser-install' && "
        "steps.boca_browser_stage_attempt.outputs.started == 'true'"
    ) in _step(cleanup)
    # No unrelated action after the final effect and before its recovery gate.
    after_apply = workflow.split(
        "      - name: Start worker then controller only after healthy private socket proof\n", 1
    )[1]
    assert after_apply.split("      - name:", 1)[1].startswith(
        " Immediately clean only positively identified failed browser IPC attempt\n"
    )


def test_failed_browser_cleanup_script_attempts_one_bounded_ssh_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Offline injection into real cleanup shell; ``ssh`` is a local stub."""
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    log = tmp_path / "ssh-calls"
    fake_ssh = fakebin / "ssh"
    fake_ssh.write_text(
        '#!/bin/sh\nprintf "one-attempt\\n" >> "$BOCA_MOCK_SSH_LOG"\nexit 42\n',
        encoding="utf-8",
    )
    fake_ssh.chmod(0o700)
    for name, value in (
        ("boca-beta-compose.sha", "d" * 64),
        ("boca-browser-overlay.sha", "e" * 64),
        ("boca-browser-seccomp.sha", "f" * 64),
    ):
        (tmp_path / name).write_text(value + "\n", encoding="ascii")
    summary = tmp_path / "summary"
    env = {
        **os.environ,
        "PATH": str(fakebin) + os.pathsep + os.environ["PATH"],
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_STEP_SUMMARY": str(summary),
        "GITHUB_RUN_ID": "123456789",
        "BOCA_MOCK_SSH_LOG": str(log),
        "BOCA_IMAGE_REF": "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64,
        "BOCA_BROWSER_IMAGE_REF": (
            "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "b" * 64
        ),
        "BOCA_SOURCE_SHA": "c" * 40,
    }
    run = _step("Immediately clean only positively identified failed browser IPC attempt")
    script = textwrap.dedent(run.split("        run: |\n", 1)[1])
    result = subprocess.run(  # noqa: S603 - fixed bash, offline local SSH stub only
        ["/bin/bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0  # The earlier workflow failure stays failed.
    assert log.read_text(encoding="utf-8") == "one-attempt\n"
    assert "original NO_GO" in summary.read_text(encoding="utf-8")
    assert "NO_GO INDETERMINADO" in summary.read_text(encoding="utf-8")
    assert "no retry" in summary.read_text(encoding="utf-8")


def test_browser_ci_covers_new_gate_and_legacy_contract_separately() -> None:
    workflow = _workflow()
    validation = workflow.split("  pr-validation:\n", 1)[1].split("  pr-runtime-smoke:\n", 1)[0]
    assert "tests/test_browser_ipc_workflow.py" in validation
    assert "tests/test_beta_browser_deploy_contract.py" in validation
    assert "tests/test_host_browser_ipc_file_stage.py" in validation
    assert "tests/test_host_browser_ipc_install.py" in validation
    assert "tests/test_host_browser_ipc_cleanup.py" in validation
    assert "tests/test_host_browser_ipc_cross_contract.py" in validation
    assert "tests/test_beta_deploy_contract.py" in validation
    assert "scripts/check_repo_policy.py" in validation
    assert "Validate optional served BETA Compose model" in validation
    assert "Validate opt-in dual-service browser IPC Compose model offline" in validation
    assert "--topology=browser-ipc-v2" in validation
    assert "-f compose.beta.yaml -f compose.beta.browser.yaml" in validation


def test_pr_runner_disposable_docker_probe_checks_real_inspect_defaults() -> None:
    workflow = _workflow()
    smoke = _step("Verify disposable browser IPC one-shot Docker inspect and auto-remove defaults")
    runner = workflow.split("  pr-runtime-smoke:\n", 1)[1].split("  deploy:\n", 1)[0]
    assert (
        "Verify disposable browser IPC one-shot Docker inspect and auto-remove defaults" in runner
    )
    assert runner.index("Build local simulation image only") < runner.index(
        "Verify disposable browser IPC one-shot Docker inspect"
    )
    for proof in (
        "docker run -d --rm --pull never --cidfile",
        '"$BOCA_IMAGE" python -c',
        "--network none --ipc=private --cgroupns=private",
        "--read-only --cap-drop ALL --security-opt no-new-privileges",
        '"AutoRemove"] is True',
        '"UsernsMode"] == host["UTSMode"] == ""',
        '"PidMode"] in ("", "private")',
        '"IpcMode"] == host["CgroupnsMode"] == "private"',
        "trap cleanup_probe EXIT",
        '"boca.ci.ipc-probe=$GITHUB_RUN_ID"',
        "docker stop -t 2",
        'test "$removed" = yes',
    ):
        assert proof in smoke
    assert "--publish" not in smoke and "--privileged" not in smoke
    assert "docker volume" not in smoke and "ssh " not in smoke
