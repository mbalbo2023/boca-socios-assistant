"""One reviewed physical worker test under the original protected Boca operation."""

from __future__ import annotations

from pathlib import Path

FLOW = (Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml").read_text()


def _step(name: str) -> str:
    heading = f"      - name: {name}\n"
    assert FLOW.count(heading) == 1
    return FLOW.split(heading, 1)[1].split("      - name:", 1)[0]


def test_owner_only_dispatch_no_cutover_and_unchanged_main_release_pins() -> None:
    assert "worker-physical-once" in FLOW
    assert "environment: boca-first-deploy" in FLOW
    assert "github.actor == 'mbalbo2023'" in FLOW
    assert "github.ref == 'refs/heads/main'" in FLOW
    gate = _step("Authenticate one Boca worker physical test and reviewed dual release")
    for expected in (
        "if: inputs.operation == 'worker-physical-once'",
        "scripts/check_worker_physical_dispatch.py",
        "42847341532",
        "boca-release-manifest",
        "boca-browser-release-manifest",
        "pulls?state=open",
        "actions/workflows/ci.yml/runs?head_sha=$GITHUB_SHA&event=push",
        "commits/$GITHUB_SHA/check-runs?filter=latest&per_page=100",
        '"$GITHUB_RUN_ID" "$GITHUB_SHA" | tee -a "$GITHUB_STEP_SUMMARY"',
    ):
        assert expected in gate


def test_physical_step_uses_exact_ssh_and_sanitized_receipt() -> None:
    step = _step("Boca physical corrected worker one-start and exact-CID compensation")
    assert "if: inputs.operation == 'worker-physical-once'" in step
    assert "--worker-physical" in step
    assert '"worker-physical-once"' in step
    assert "boca-target" in step
    assert "boca_socios.host_worker_physical verify" in step
    assert "sudo" not in step
    assert "docker compose" not in step
    assert "cutover-a-apply" not in step


def test_physical_tests_participate_in_pr_gate() -> None:
    step = _step("Validate physical worker isolated ZIP and one-start guards offline only")
    for test in (
        "test_host_worker_physical.py",
        "test_worker_physical_bundle.py",
        "test_worker_physical_workflow.py",
        "test_worker_physical_dispatch.py",
    ):
        assert test in step
    assert "host_worker_physical.py" in step
