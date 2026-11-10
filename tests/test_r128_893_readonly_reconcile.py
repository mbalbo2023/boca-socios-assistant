"""R128 #893: narrow READ_ONLY V3 reconciliation; no host or BLACKBOX calls."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text(encoding="utf-8")
OBSERVER = (ROOT / "scripts/host_cutover_postapply_reconcile.py").read_text(encoding="utf-8")
INCIDENT = "42658939650"
SOURCE_SHA = "759a1dbadd6e50ab8c331daefc4e39608025a66f"
V3_RUNS = "42405706503|42426260583|42658939650|42742150879"


def test_r128_all_v3_without_prepare_paths_accept_only_exact_incidents() -> None:
    # Input guard + required empty PREPARE + host-v3 + verify-v3 share a
    # literal, closed, four-incident whitelist. They must not diverge.
    assert WORKFLOW.count(f"^({V3_RUNS})$") == 4
    assert "inputs.protected_action_context == '42658939650'" in WORKFLOW
    assert '"$BOCA_PROTECTED_ACTION_CONTEXT" != "$GITHUB_RUN_ID"' in WORKFLOW
    assert 'test -z "$BOCA_INCIDENT_PREPARE_RUN_ID"' in WORKFLOW


def test_r128_exact_failed_run_source_is_authenticated_before_ssh() -> None:
    match = re.search(r"expected_sources = (\{[^}]+\})", WORKFLOW)
    assert match is not None
    sources = ast.literal_eval(match.group(1))
    assert sources == {
        "42405706503": "1273338005abf7203d26e618648fe55216030cf3",
        "42426260583": "f57173862df3143062a136452f2ffc7e3cc51d35",
        INCIDENT: SOURCE_SHA,
        "42742150879": "b6a53c3348ce39c4d8536487e2baed559c2ca42f",
    }
    assert 'incident["id"] != 42742150879 or incident.get("run_number") == 904' in WORKFLOW
    assert 'incident.get("run_attempt") == 1' in WORKFLOW
    assert 'incident.get("event") == "workflow_dispatch"' in WORKFLOW
    assert 'incident.get("conclusion") == "failure"' in WORKFLOW
    assert 'incident.get("head_branch") == "main"' in WORKFLOW
    assert 'incident.get("display_title") == "BOCA-SIMULATION-DEPLOY-V3"' in WORKFLOW
    assert 'incident.get("actor", {}).get("login") == "mbalbo2023"' in WORKFLOW
    assert 'incident.get("triggering_actor", {}).get("login") == "mbalbo2023"' in WORKFLOW
    assert 'incident.get("path") == ".github/workflows/boca-first-deploy.yml"' in WORKFLOW


def test_r128_does_not_run_historical_cleanup_planner_for_893() -> None:
    assert (
        "if: inputs.operation == 'cutover-a-reconcile' "
        "&& inputs.protected_action_context != '42658939650' "
        "&& inputs.protected_action_context != '42742150879'"
    ) in WORKFLOW
    assert "< scripts/host_cutover_postapply_reconcile.py" in WORKFLOW
    assert "scope=OBSERVER_ONLY observer_writes=0" in OBSERVER
    assert "prior_apply_effects=UNKNOWN retry=NO_GO" in OBSERVER
    assert '"runtime_attested": False' in OBSERVER
    assert '"go_for_retry": False' in OBSERVER
    # Existing fixed postmortem #878 planner stays unchanged, no new GO path.
    assert 'RECOVERED_INVENTORY_RUN = "42426260583"' in OBSERVER
    assert INCIDENT not in OBSERVER


def test_r128_preserves_v4_closed_schema_and_no_payload_leaks() -> None:
    assert 'TERMINAL_V4 = "boca-cutover-a-terminal-v4"' in OBSERVER
    assert '"worker_exit_signature"' in OBSERVER
    assert "WORKER_EVIDENCE_FIELDS_V4" in OBSERVER
    assert "source_sha is not None and intent is not None" in OBSERVER
    # No log/exec hook added to the observer: it only compares bounded metadata.
    assert "docker logs" not in OBSERVER
    assert "docker exec" not in OBSERVER
