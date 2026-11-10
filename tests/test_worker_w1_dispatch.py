"""One owner workflow attempt may reach Boca SSH, never a second W1 dispatch."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import check_worker_w1_dispatch as gate  # noqa: E402

SHA = "e" * 40
RUN = "42900000001"


def _history():
    return [
        {
            "id": 42900000001,
            "name": "Boca first deploy",
            "workflow_id": 400115324,
            "path": ".github/workflows/boca-first-deploy.yml",
            "repository": {"full_name": "mbalbo2023/boca-socios-assistant"},
            "event": "workflow_dispatch",
            "head_sha": SHA,
            "head_branch": "main",
            "run_attempt": 1,
            "actor": {"login": "mbalbo2023"},
        },
        {
            "id": 42806447101,
            "name": "BOCA-SIMULATION-DEPLOY-V3",
            "workflow_id": 400115324,
            "path": ".github/workflows/boca-first-deploy.yml",
            "repository": {"full_name": "mbalbo2023/boca-socios-assistant"},
            "event": "workflow_dispatch",
            "head_sha": "03df9a14bdd78cf768386a865876fed9d5656911",
            "head_branch": "main",
            "run_attempt": 1,
            "actor": {"login": "mbalbo2023"},
        },
    ]


def _installed():
    return {
        "id": 42806447101,
        "name": "BOCA-SIMULATION-DEPLOY-V3",
        "workflow_id": 400115324,
        "path": ".github/workflows/boca-first-deploy.yml",
        "repository": {"full_name": "mbalbo2023/boca-socios-assistant"},
        "event": "workflow_dispatch",
        "head_sha": "03df9a14bdd78cf768386a865876fed9d5656911",
        "head_branch": "main",
        "run_attempt": 1,
        "status": "completed",
        "conclusion": "success",
        "actor": {"login": "mbalbo2023"},
    }


def test_one_proven_current_dispatch_with_exact_historical_install_is_admitted():
    """Historical #926 has a dynamic run name, not the workflow's UI label."""
    gate.validate(_history(), _installed(), RUN, SHA)


def test_current_run_name_is_not_an_authority_for_workflow_identity():
    history = _history()
    history[0]["name"] = "BOCA-WORKER-DIAGNOSE-ONCE"
    gate.validate(history, _installed(), RUN, SHA)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-run",
        "extra-dispatch-same-head",
        "retry",
        "other-actor",
        "other-branch",
        "installed-failed",
        "installed-source-drift",
        "wrong-workflow-path",
        "wrong-workflow-id",
        "wrong-repository",
    ],
)
def test_second_attempt_or_mismatched_provenance_fails_pre_ssh(mutation):
    history = copy.deepcopy(_history())
    installed = copy.deepcopy(_installed())
    if mutation == "missing-run":
        history = history[1:]
    elif mutation == "extra-dispatch-same-head":
        extra = copy.deepcopy(history[0])
        extra["id"] += 7
        history.append(extra)
    elif mutation == "retry":
        history[0]["run_attempt"] = 2
    elif mutation == "other-actor":
        history[0]["actor"] = {"login": "attacker"}
    elif mutation == "other-branch":
        history[0]["head_branch"] = "other"
    elif mutation == "installed-failed":
        installed["conclusion"] = "failure"
    elif mutation == "installed-source-drift":
        installed["head_sha"] = "a" * 40
    elif mutation == "wrong-workflow-path":
        history[0]["path"] = ".github/workflows/other.yml"
    elif mutation == "wrong-workflow-id":
        installed["workflow_id"] = 42
    elif mutation == "wrong-repository":
        history[0]["repository"] = {"full_name": "someone-else/unrelated"}
    with pytest.raises(gate.DispatchUnavailable):
        gate.validate(history, installed, RUN, SHA)


def test_jsonl_runner_projection_does_not_accept_partial_documents(tmp_path):
    history = tmp_path / "history.jsonl"
    installed = tmp_path / "installed.json"
    history.write_text("\n".join(json.dumps(item) for item in _history()) + "\n")
    installed.write_text(json.dumps(_installed()))
    assert gate.main([str(history), str(installed), RUN, SHA]) == 0
    history.write_text(history.read_text() + "{malformed\n")
    assert gate.main([str(history), str(installed), RUN, SHA]) == 3
