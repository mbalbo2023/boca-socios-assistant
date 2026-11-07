"""Authenticate one V3 incident and one recovery dispatch; no host I/O."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from scripts.check_r96_stage_dispatch import load_paginated_history
from scripts.check_release_dispatch import RUN_ID, SOURCE_SHA, DispatchError, load_history
from scripts.check_worker_preflight_dispatch import validate_dispatch_history

REPO = "mbalbo2023/boca-socios-assistant"
WORKFLOW = ".github/workflows/boca-first-deploy.yml"


def validate(
    incident: object, history: object, prs: object, source: str, run: str, incident_id: str
) -> str:
    if not RUN_ID.fullmatch(incident_id) or incident_id == run or not isinstance(incident, dict):
        raise DispatchError("invalid incident")
    sha = incident.get("head_sha")
    if not (
        type(incident.get("id")) is int
        and incident["id"] == int(incident_id)
        and incident.get("run_attempt") == 1
        and type(incident.get("run_attempt")) is int
        and incident.get("event") == "workflow_dispatch"
        and incident.get("status") == "completed"
        and incident.get("conclusion") == "failure"
        and incident.get("head_branch") == "main"
        and isinstance(sha, str)
        and SOURCE_SHA.fullmatch(sha)
        and incident.get("path") == WORKFLOW
        and incident.get("display_title") == "BOCA-SIMULATION-DEPLOY-V3"
        and isinstance(incident.get("actor"), dict)
        and incident["actor"].get("login") == "mbalbo2023"
        and isinstance(incident.get("triggering_actor"), dict)
        and incident["triggering_actor"].get("login") == "mbalbo2023"
        and isinstance(incident.get("repository"), dict)
        and incident["repository"].get("full_name") == REPO
    ):
        raise DispatchError("V3 incident provenance unverified")
    if not isinstance(history, dict) or history.get("total_count") != history.get("fetched_count"):
        raise DispatchError("incomplete recovery history")
    runs = history.get("workflow_runs")
    if not isinstance(runs, list):
        raise DispatchError("recovery history malformed")
    marker = "BOCA-V3-STAGE-RECOVER-" + incident_id
    matching = [
        item for item in runs if isinstance(item, dict) and item.get("display_title") == marker
    ]
    if len(matching) != 1 or matching[0].get("triggering_actor") != {"login": "mbalbo2023"}:
        raise DispatchError("recovery triggering owner not established")
    validate_dispatch_history(
        {"total_count": len(matching), "workflow_runs": matching},
        prs,
        source,
        run,
        marker=marker,
        across_all_shas=True,
    )
    return sha


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 6:
        return 2
    try:
        incident: Any = load_history(Path(args[0]))
        history = load_paginated_history(Path(args[1]))
        prs = load_history(Path(args[2]))
        sha = validate(incident, history, prs, args[3], args[4], args[5])
        print(sha)
        return 0
    except (DispatchError, OSError, ValueError):
        print("BOCA_V3_STAGE_GATE state=NO_GO", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
