"""No-input, protected, no-effect GitHub dispatch for installed Boca pair."""

from __future__ import annotations

from pathlib import Path

FLOW = (Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml").read_text()


def _step(name: str) -> str:
    heading = f"      - name: {name}\n"
    assert FLOW.count(heading) == 1
    return FLOW.split(heading, 1)[1].split("      - name:", 1)[0]


def test_pair_observe_runs_only_on_current_protected_main_with_no_caller_pins():
    assert (
        "boca-pair-observe"
        in FLOW.split("      operation:\n", 1)[1].split("      source_sha:", 1)[0]
    )
    assert "github.event_name == 'workflow_dispatch'" in FLOW
    assert "github.ref == 'refs/heads/main'" in FLOW
    assert "github.actor == 'mbalbo2023'" in FLOW
    assert "environment: boca-first-deploy" in FLOW
    assert (
        "inputs.operation == 'boca-pair-observe'"
        in FLOW.split("BOCA_SOURCE_SHA:", 1)[1].split("BOCA_SOURCE_SHA_SUBMITTED:", 1)[0]
    )
    admission = _step("Require verified protected environment and matching main commit")
    case = admission.split("            boca-pair-observe)\n", 1)[1].split("              ;;", 1)[0]
    for expected in (
        'test "$BOCA_HOST_READONLY_ENV_READY" = ready',
        'test "$BOCA_DEPLOY_ENV_READY" = ready',
        'test "$BOCA_SOURCE_SHA" = "$GITHUB_SHA"',
        'test "$BOCA_BUDGET" = 1.5cpu-1024m-192pids',
        '"$BOCA_SOURCE_SHA_SUBMITTED"',
        '"$BOCA_IMAGE_REF"',
        '"$BOCA_BROWSER_IMAGE_REF"',
        '"$BOCA_RELEASE_RUN_ID"',
        '"$BOCA_LEGACY_CONTROLLER_ID"',
        '"$BOCA_SITE_ENVELOPE"',
        '"$BOCA_TELEGRAM_ENVELOPE"',
        '"$BOCA_OWNER_ENVELOPE"',
        'test -z "$unexpected"',
    ):
        assert expected in case


def test_pair_observe_uses_standalone_readonly_memfd_and_strict_runner_verification():
    step = _step("Observe installed Boca controller and worker pair READ_ONLY")
    for expected in (
        "if: inputs.operation == 'boca-pair-observe'",
        "scripts/build_protected_boca_bundle.py --pair-observe",
        "sha256sum",
        "scripts/boca_protected_memfd_bootstrap.py",
        '"boca-pair-observe"',
        '"$GITHUB_RUN_ID"',
        'gh api "repos/$GITHUB_REPOSITORY/git/ref/heads/main"',
        "scripts/check_main_ref.py",
        '"$RUNNER_TEMP/boca-ssh/config"',
        "boca-target",
        "timeout --signal=TERM --kill-after=5s",
        "ulimit -f 8",
        "boca_socios.host_boca_pair_observe verify",
        '"$GITHUB_STEP_SUMMARY"',
        "state=NO_GO",
        "cutover=NO_GO",
    ):
        assert expected in step
    for forbidden in (
        "docker compose",
        "docker start",
        "docker stop",
        "docker rm",
        "docker exec",
        "protected_boca_job_lease",
        "sudo",
        "--worker-physical",
        "--worker-w1",
        "cutover-a-apply",
        "cleanup-allow",
    ):
        assert forbidden not in step
    assert "2>/dev/null" in step
    assert 'cat "$pair_dir/receipt" >> "$GITHUB_STEP_SUMMARY"' not in step


def test_pair_observe_has_local_regressions_without_host_dispatch():
    step = _step("Validate Boca installed pair observer offline only")
    for testcase in (
        "test_host_boca_pair_observe.py",
        "test_host_boca_pair_bundle.py",
        "test_host_boca_pair_workflow.py",
    ):
        assert testcase in step
