"""Offline provenance and replay checks for V3 stage recovery."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.check_release_dispatch import DispatchError
from scripts.check_v3_stage_github import validate

SHA = "a" * 40
INCIDENT = "42405706503"
RUN = "42410321232"
TITLE = "BOCA-V3-STAGE-RECOVER-" + INCIDENT


def incident():
    return {
        "id": int(INCIDENT),
        "run_attempt": 1,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "failure",
        "head_branch": "main",
        "head_sha": SHA,
        "path": ".github/workflows/boca-first-deploy.yml",
        "display_title": "BOCA-SIMULATION-DEPLOY-V3",
        "actor": {"login": "mbalbo2023"},
        "triggering_actor": {"login": "mbalbo2023"},
        "repository": {"full_name": "mbalbo2023/boca-socios-assistant"},
    }


def current():
    value = incident() | {"id": int(RUN), "display_title": TITLE}
    return value


def test_accepts_one_authenticated_v3_incident_and_one_dispatch():
    assert (
        validate(
            incident(),
            {"total_count": 1, "fetched_count": 1, "workflow_runs": [current()]},
            [],
            SHA,
            RUN,
            INCIDENT,
        )
        == SHA
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_attempt", 2),
        ("conclusion", "success"),
        ("display_title", "Boca first deploy"),
        ("head_branch", "feature"),
        ("actor", {"login": "other"}),
        ("triggering_actor", {"login": "other"}),
    ],
)
def test_rejects_forged_incident(field, value):
    with pytest.raises(DispatchError):
        validate(
            incident() | {field: value},
            {"total_count": 1, "fetched_count": 1, "workflow_runs": [current()]},
            [],
            SHA,
            RUN,
            INCIDENT,
        )


def test_rejects_prior_dispatch_even_on_another_sha():
    with pytest.raises(DispatchError):
        validate(
            incident(),
            {
                "total_count": 2,
                "fetched_count": 2,
                "workflow_runs": [current(), current() | {"id": 3, "head_sha": "b" * 40}],
            },
            [],
            SHA,
            RUN,
            INCIDENT,
        )


def test_rejects_current_run_triggered_by_another_actor():
    with pytest.raises(DispatchError):
        validate(
            incident(),
            {
                "total_count": 1,
                "fetched_count": 1,
                "workflow_runs": [current() | {"triggering_actor": {"login": "other"}}],
            },
            [],
            SHA,
            RUN,
            INCIDENT,
        )


def test_workflow_exposes_incident_bound_marker_and_v3_gate():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
    ).read_text()
    assert "BOCA-V3-STAGE-RECOVER-{0}" in workflow
    assert "scripts.check_v3_stage_github" in workflow
    assert "cutover-stage-recover-v3" in workflow


def test_reviewed_bundle_dispatches_v3_host_mode():
    from scripts.build_protected_boca_bundle import MAIN

    assert b"cutover-stage-recover-v3" in MAIN
    assert b"host-v3" in MAIN
