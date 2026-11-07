"""R96: one global GitHub stage-recovery dispatch, complete history and PR=0.

The protected runner projects *every* workflow_dispatch page to a total count
and only the exact unique recovery marker to its provenance record. That keeps
the runner evidence bounded without allowing a second action on another SHA.
This module has no host, Docker or network access.
"""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

from scripts.check_release_dispatch import (
    MAX_RESPONSE_BYTES,
    DispatchError,
    _unique_fields,
    load_history,
)
from scripts.check_worker_preflight_dispatch import validate_dispatch_history

MARKER = "BOCA-R96-STAGE-844-RECOVER-ONCE"
PER_PAGE = 100
MAX_PAGES = 20


def load_paginated_history(path: Path) -> object:
    """Parse gh api --paginate --jq output: adjacent JSON pages, not one array.

    GitHub CLI does not support `--slurp`. `--jq` may pretty-print each page,
    so splitting on newline is unsafe: decode bounded consecutive JSON values.
    A missing/truncated page, duplicate field, inconsistent total or blank
    middle page fails BEFORE SSH.
    """
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= MAX_RESPONSE_BYTES:
            raise DispatchError("R96 unsafe or missing paginated history")
        raw = path.read_bytes()
        if not 0 < len(raw) <= MAX_RESPONSE_BYTES:
            raise DispatchError("R96 history unbounded or empty")
        document = raw.decode("utf-8")
        decoder = json.JSONDecoder(object_pairs_hook=_unique_fields)
        pages: list[object] = []
        offset = 0
        while offset < len(document):
            while offset < len(document) and document[offset].isspace():
                offset += 1
            if offset == len(document):
                break
            page, offset = decoder.raw_decode(document, offset)
            pages.append(page)
            if len(pages) > MAX_PAGES:
                raise DispatchError("R96 too many pages")
        if not pages or not isinstance(pages[0], dict):
            raise DispatchError("R96 GitHub history has no first page")
        total = pages[0].get("total_count")
        # This REST endpoint caps filtered workflow runs at 1,000, so at the
        # cap the API no longer proves a complete global anti-replay history.
        if type(total) is not int or not 1 <= total < 1000:
            raise DispatchError("R96 unbounded GitHub history count")
        expected_pages = (total + PER_PAGE - 1) // PER_PAGE
        if len(pages) != expected_pages:
            raise DispatchError("R96 GitHub history missing a page")
        matched: list[object] = []
        fetched = 0
        seen_ids: set[int] = set()
        for index, page in enumerate(pages):
            expected_page_count = min(PER_PAGE, total - index * PER_PAGE)
            if (
                not isinstance(page, dict)
                or page.get("total_count") != total
                or type(page.get("fetched_count")) is not int
                or page["fetched_count"] != expected_page_count
                or not isinstance(page.get("run_ids"), list)
                or len(page["run_ids"]) != expected_page_count
                or not isinstance(page.get("workflow_runs"), list)
            ):
                raise DispatchError("R96 GitHub page is missing or inconsistent")
            fetched += page["fetched_count"]
            for item_id in page["run_ids"]:
                if type(item_id) is not int or item_id <= 0 or item_id in seen_ids:
                    raise DispatchError("R96 GitHub pages duplicated a run ID")
                seen_ids.add(item_id)
            for match in page["workflow_runs"]:
                if (
                    not isinstance(match, dict)
                    or type(match.get("id")) is not int
                    or match["id"] not in page["run_ids"]
                ):
                    raise DispatchError("R96 marker missing from its authenticated page")
            matched.extend(page["workflow_runs"])
        return {"total_count": total, "fetched_count": fetched, "workflow_runs": matched}
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise DispatchError("R96 paginated history could not be authenticated") from exc


def validate_stage_summary(summary: object, open_prs: object, source_sha: str, run_id: str) -> None:
    if not isinstance(summary, dict):
        raise DispatchError("R96 full history summary unavailable")
    count = summary.get("total_count")
    fetched = summary.get("fetched_count")
    matching_runs = summary.get("workflow_runs")
    if (
        type(count) is not int
        or type(fetched) is not int
        or not 1 <= count < 1000
        or fetched != count
        or not isinstance(matching_runs, list)
        or len(matching_runs) != 1
    ):
        raise DispatchError("R96 global history truncated, duplicated or unbounded")
    # Existing R84 verifier enforces first attempt, source, owner, repo, main,
    # workflow, actor, zero PRs and exactly one matching recovery marker.
    # The independent fetched==REST total assertion above proves the filter
    # was applied to the complete paginated workflow history.
    validate_dispatch_history(
        {"total_count": 1, "workflow_runs": matching_runs},
        open_prs,
        source_sha,
        run_id,
        marker=MARKER,
        across_all_shas=True,
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 4:
        print("usage: check_r96_stage_dispatch HISTORY_JSON PRS_JSON SHA RUN_ID", file=sys.stderr)
        return 2
    try:
        summary, prs = load_paginated_history(Path(args[0])), load_history(Path(args[1]))
        validate_stage_summary(summary, prs, args[2], args[3])
    except DispatchError as exc:
        print(f"BOCA_R96_STAGE_DISPATCH_NO_GO: {exc}", file=sys.stderr)
        return 1
    print("BOCA_R96_STAGE_DISPATCH_PASS one_action=1 all_shas=1 open_prs=0 first_attempt=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
