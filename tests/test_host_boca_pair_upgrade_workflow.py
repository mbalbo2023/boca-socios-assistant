"""R178 planning remains inert; R179 has its own gated host dispatcher."""

from __future__ import annotations

from pathlib import Path

from test_ci_parallel_pytest_contract import assert_required_ci_covers

FLOW = (Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml").read_text()


def test_pair_upgrade_plan_remains_offline_with_separate_r179_host_dispatch():
    options = FLOW.split("      operation:\n", 1)[1].split("      source_sha:", 1)[0]
    assert "boca-pair-upgrade-apply" in options
    assert "boca-pair-upgrade," not in options
    assert_required_ci_covers(
        "tests/test_host_boca_pair_upgrade_plan.py",
        "tests/test_host_boca_pair_upgrade_workflow.py",
    )
    ci = (Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text()
    assert "        run: uv run mypy src\n" in ci
    assert "      - name: Upgrade Boca-only rootless pair under one lease\n" in FLOW
    assert "if: inputs.operation == 'boca-pair-upgrade-apply'" in FLOW
