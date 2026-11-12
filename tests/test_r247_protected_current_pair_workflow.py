"""R247 one-existing-workflow protected V2 wiring (offline lexical contract)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/boca-first-deploy.yml"


def _upgrade_block() -> str:
    source = WORKFLOW.read_text(encoding="utf-8")
    return source.split("- name: Upgrade Boca-only rootless pair under one lease\n", 1)[1].split(
        "      - name:", 1
    )[0]


def test_existing_dispatch_keeps_exactly_25_fields_and_one_upgrade_operation() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    input_block = source.split("workflow_dispatch:\n    inputs:\n", 1)[1].split(
        "\npermissions:", 1
    )[0]
    inputs = re.findall(r"^      ([a-z][a-z0-9_]*):$", input_block, re.M)
    assert len(inputs) == len(set(inputs)) == 25
    assert inputs.count("legacy_release_run_id") == 1
    assert inputs.count("official_news_run_id") == 1
    assert source.count("- name: Upgrade Boca-only rootless pair under one lease") == 1
    assert source.count("- name: Authenticate historical Boca pair") == 0


def test_one_upgrade_reuses_existing_obs_and_release_and_runner_only_v2() -> None:
    block = _upgrade_block()
    assert "python3 -m boca_socios.host_boca_upgrade_observation_bridge" in block
    assert "python3 -m boca_socios.host_boca_upgrade_release_bridge" in block
    assert "python3 scripts/attest_current_pair_v2.py" in block
    assert "python3 -m boca_socios.host_boca_upgrade_retained_bridge" not in block
    assert "BOCA_RETAINED_OBSERVATION_RUN_ID" in block
    assert "BOCA_PROTECTED_ACTION_CONTEXT" in block
    assert "BOCA_RELEASE_RUN_ID" in block
    assert "BOCA_CURRENT_PAIR_V2_AUTH state=VERIFIED host_authorized=false" in block
    assert "current-pair-v2.receipt" in block
    assert "--pair-upgrade-release-dir" in block
    assert block.count("timeout --signal=TERM --kill-after=10s 540s ssh") == 1
    assert block.count("boca-pair-upgrade.pyz") >= 2
    assert "gh workflow run" not in block
    assert "docker " not in block
    assert 'GITHUB_RUN_ATTEMPT" = 1' in block


def test_pr_validation_includes_new_provenance_contract_tests() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "tests/test_r247_runner_current_pair_v2.py" in text
    assert "tests/test_r247_protected_current_pair_bundle.py" in text
    assert "tests/test_r247_protected_current_pair_workflow.py" in text
