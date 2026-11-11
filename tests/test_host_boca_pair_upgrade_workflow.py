"""R178 planning checks run in CI; no effectful host operation is registered."""

from __future__ import annotations

from pathlib import Path

FLOW = (Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml").read_text()


def test_pair_upgrade_plan_is_only_an_offline_gate_never_a_host_dispatch():
    options = FLOW.split("      operation:\n", 1)[1].split("      source_sha:", 1)[0]
    assert "boca-pair-upgrade" not in options
    heading = "      - name: Validate Boca installed pair observer offline only\n"
    assert FLOW.count(heading) == 1
    step = FLOW.split(heading, 1)[1].split("      - name:", 1)[0]
    assert "tests/test_host_boca_pair_upgrade_plan.py" in step
    assert "tests/test_host_boca_pair_upgrade_workflow.py" in step
    assert "mypy src/boca_socios/host_boca_pair_upgrade_plan.py" in step
    assert "if: inputs.operation" not in step
