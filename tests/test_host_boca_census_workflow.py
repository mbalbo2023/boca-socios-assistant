"""Independent, fixed-input Boca rootless current census workflow safety."""

from __future__ import annotations

from pathlib import Path

from test_ci_parallel_pytest_contract import assert_required_ci_covers

FLOW = (Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml").read_text()


def _step(name: str) -> str:
    heading = f"      - name: {name}\n"
    assert FLOW.count(heading) == 1
    return FLOW.split(heading, 1)[1].split("      - name:", 1)[0]


def test_current_census_manual_only_main_owner_and_existing_environment():
    assert (
        "cutover-a-census"
        in FLOW.split("      operation:\n", 1)[1].split("      source_sha:", 1)[0]
    )
    assert "github.event_name == 'workflow_dispatch'" in FLOW
    assert "github.ref == 'refs/heads/main'" in FLOW
    assert "github.repository == 'mbalbo2023/boca-socios-assistant'" in FLOW
    assert "github.actor == 'mbalbo2023'" in FLOW
    assert "environment: boca-first-deploy" in FLOW
    assert "'boca-first-deploy'" in FLOW.split("concurrency:", 1)[1].split("jobs:", 1)[0]
    assert (
        "inputs.operation == 'cutover-a-census'"
        in FLOW.split("BOCA_SOURCE_SHA:", 1)[1].split("BOCA_SOURCE_SHA_SUBMITTED:", 1)[0]
    )


def test_current_census_gate_rejects_every_image_secret_and_legacy_coordinate():
    step = _step("Require verified protected environment and matching main commit")
    case = step.split("            cutover-a-census)\n", 1)[1].split("              ;;", 1)[0]
    for expected in (
        'test "$BOCA_HOST_READONLY_ENV_READY" = ready',
        'test "$BOCA_DEPLOY_ENV_READY" = ready',
        'test "$BOCA_SOURCE_SHA" = "$GITHUB_SHA"',
        'test "$BOCA_BUDGET" = 1.5cpu-1024m-192pids',
        '"$BOCA_SOURCE_SHA_SUBMITTED"',
        '"$BOCA_PROTECTED_ACTION_CONTEXT"',
        '"$BOCA_IMAGE_REF"',
        '"$BOCA_BROWSER_IMAGE_REF"',
        '"$BOCA_RELEASE_RUN_ID"',
        '"$BOCA_LEGACY_SOURCE_SHA"',
        '"$BOCA_LEGACY_IMAGE_REF"',
        '"$BOCA_LEGACY_RELEASE_RUN_ID"',
        '"$BOCA_LEGACY_CONTROLLER_ID"',
        '"$BOCA_SITE_ENVELOPE"',
        '"$BOCA_TELEGRAM_ENVELOPE"',
        '"$BOCA_OWNER_ENVELOPE"',
        '"$BOCA_OWNER_CAPABILITY_SHA256"',
        '"$BOCA_FAILED_TELEGRAM_RUN_ID"',
        '"$BOCA_OFFICIAL_CONTROLLER_ID"',
        '"$BOCA_OFFICIAL_NEWS_RUN_ID"',
        '"$BOCA_OFFICIAL_NEWS_SOURCE_SHA"',
        '"$BOCA_OFFICIAL_NEWS_ARTIFACT_ID"',
        '"$BOCA_OFFICIAL_NEWS_ZIP_SHA256"',
        '"$BOCA_OFFICIAL_NEWS_JSONL_SHA256"',
        '"$BOCA_OFFICIAL_NEWS_HTML_SHA256"',
        '"$BOCA_OFFICIAL_NEWS_OBSERVED_AT_UTC"',
        'test -z "$unexpected"',
    ):
        assert expected in case


def test_current_census_uses_reviewed_minimal_memfd_no_host_effects_or_leases():
    step = _step("Observe Boca rootless current inventory READ_ONLY without leases")
    for expected in (
        "if: inputs.operation == 'cutover-a-census'",
        "scripts/build_protected_boca_bundle.py --census",
        "sha256sum",
        "scripts/boca_protected_memfd_bootstrap.py",
        '"cutover-a-census"',
        '"$GITHUB_RUN_ID"',
        '"$RUNNER_TEMP/boca-ssh/config"',
        "boca-target",
        "timeout --signal=TERM --kill-after=5s",
        "ulimit -f 2",
        "boca_socios.host_boca_census verify",
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
    assert '< "$RUNNER_TEMP/boca-current-census.pyz"' in step
    assert "2>/dev/null" in step
    # Never append the unverified remote stream to a public Actions summary.
    assert 'cat "$census_dir/receipt" >> "$GITHUB_STEP_SUMMARY"' not in step


def test_current_census_pr_workflow_runs_local_regressions_without_host_access():
    assert_required_ci_covers(
        "tests/test_host_boca_census.py",
        "tests/test_host_boca_census_bundle.py",
        "tests/test_host_boca_census_workflow.py",
    )


def test_current_census_rechecks_main_immediately_before_host_access():
    step = _step("Observe Boca rootless current inventory READ_ONLY without leases")
    assert "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in step
    exact_ref = 'gh api "repos/$GITHUB_REPOSITORY/git/ref/heads/main"'
    recheck = (
        "python3 scripts/check_main_ref.py "
        '"$RUNNER_TEMP/boca-current-census-main.json" "$BOCA_SOURCE_SHA"'
    )
    assert exact_ref in step and recheck in step
    assert step.index("--census") < step.index(exact_ref) < step.index(recheck)
    assert step.index(recheck) < step.index("timeout --signal=TERM --kill-after=5s")
    assert "GITHUB_RUN_ATTEMPT" in _step(
        "Require verified protected environment and matching main commit"
    )
