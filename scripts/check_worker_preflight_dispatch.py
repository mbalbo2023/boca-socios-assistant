"""R84: prohibit a second fresh Cutover worker preflight dispatch for one SHA.

GitHub REST evidence only. Called on the protected runner BEFORE SSH; no host I/O.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.check_release_dispatch import RUN_ID, SOURCE_SHA, DispatchError, load_history

TITLE = "BOCA-R84-WORKER-PREFLIGHT-ONCE"
REPO = "mbalbo2023/boca-socios-assistant"
WORKFLOW = ".github/workflows/boca-first-deploy.yml"
WORKFLOW_PATHS = {WORKFLOW, f"{WORKFLOW}@main", f"{WORKFLOW}@refs/heads/main"}


def validate_dispatch_history(
    history: object,
    open_prs: object,
    source_sha: str,
    run_id: str,
    *,
    marker: str = TITLE,
    across_all_shas: bool = False,
) -> None:
    """Accept one unique protected dispatch for a fixed marker and provenance.

    The original R84 path stays filtered by exact source SHA. Incident-bound
    recoveries use a complete bounded workflow history across source SHAs:
    a new commit must never make the same physical recovery replayable.
    """
    if not SOURCE_SHA.fullmatch(source_sha) or not RUN_ID.fullmatch(run_id):
        raise DispatchError("unreviewed worker preflight coordinates")
    if not isinstance(marker, str) or not marker or type(across_all_shas) is not bool:
        raise DispatchError("invalid unique dispatch marker policy")
    if open_prs != [] or not isinstance(history, dict):
        raise DispatchError("open pull requests or unverified worker history")
    count = history.get("total_count")
    runs = history.get("workflow_runs")
    if (
        type(count) is not int
        or not 1 <= count <= (2000 if across_all_shas else 100)
        or not isinstance(runs, list)
        or len(runs) != count
        or any(not isinstance(item, dict) for item in runs)
    ):
        raise DispatchError("worker preflight history incomplete or unbounded")
    seen: set[int] = set()
    matched: list[dict[str, object]] = []
    for record in runs:
        identifier = record.get("id")
        if (
            type(identifier) is not int
            or identifier <= 0
            or identifier in seen
            or (
                not isinstance(record.get("head_sha"), str)
                or not SOURCE_SHA.fullmatch(record["head_sha"])
                if across_all_shas
                else record.get("head_sha") != source_sha
            )
            or record.get("event") != "workflow_dispatch"
        ):
            raise DispatchError("worker history origin or identity unverified")
        seen.add(identifier)
        if record.get("display_title") == marker:
            matched.append(record)
    if len(matched) != 1:
        raise DispatchError("worker preflight absent or repeated for exact SHA")
    current = matched[0]
    actor = current.get("actor")
    repository = current.get("repository")
    if not (
        current["id"] == int(run_id)
        and current.get("head_sha") == source_sha
        and current.get("head_branch") == "main"
        and current.get("path") in WORKFLOW_PATHS
        and type(current.get("run_attempt")) is int
        and current["run_attempt"] == 1
        and isinstance(actor, dict)
        and actor.get("login") == "mbalbo2023"
        and isinstance(repository, dict)
        and repository.get("full_name") == REPO
    ):
        raise DispatchError("worker preflight run, actor or workflow unverified")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 4:
        print(
            "usage: check_worker_preflight_dispatch.py HISTORY_JSON PRS_JSON SHA RUN_ID",
            file=sys.stderr,
        )
        return 2
    try:
        history, prs = load_history(Path(args[0])), load_history(Path(args[1]))
        validate_dispatch_history(history, prs, args[2], args[3])
    except DispatchError as exc:
        print(f"BOCA_WORKER_PREFLIGHT_NO_GO: {exc}", file=sys.stderr)
        return 1
    print("BOCA_WORKER_PREFLIGHT_DISPATCH_PASS same_sha_dispatches=1 open_prs=0 no_retry=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
