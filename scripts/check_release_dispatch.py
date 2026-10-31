"""Refuse a manual image release when another dispatch targets its source SHA."""

from __future__ import annotations

import json
import re
import stat
import sys
from pathlib import Path
from typing import Any

MAX_RESPONSE_BYTES = 131_072
SOURCE_SHA = re.compile(r"[0-9a-f]{40}\Z")
RUN_ID = re.compile(r"[1-9][0-9]{0,18}\Z")


class DispatchError(ValueError):
    """The exact release dispatch cannot be established from GitHub metadata."""


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for name, value in pairs:
        if name in fields:
            raise DispatchError("duplicate release metadata field")
        fields[name] = value
    return fields


def load_history(path: Path) -> object:
    """Read only a bounded regular response produced by the GitHub API step."""
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_RESPONSE_BYTES:
            raise DispatchError("release history file is unsafe or oversized")
        with path.open("rb") as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise DispatchError("release history response is oversized")
        return json.loads(raw, object_pairs_hook=_unique_fields)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DispatchError("release history response is unavailable or malformed") from exc


def validate_dispatch_history(document: object, source_sha: str, run_id: str) -> None:
    """Accept only this run's first attempt among all dispatches for one SHA."""
    if not SOURCE_SHA.fullmatch(source_sha) or not RUN_ID.fullmatch(run_id):
        raise DispatchError("invalid release coordinates")
    if not isinstance(document, dict):
        raise DispatchError("release history metadata is invalid")
    count = document.get("total_count")
    runs = document.get("workflow_runs")
    if type(count) is not int or count != 1 or not isinstance(runs, list) or len(runs) != 1:
        raise DispatchError("release dispatch is absent or duplicated")
    run = runs[0]
    if not isinstance(run, dict) or (
        type(run.get("id")) is not int
        or run["id"] != int(run_id)
        or run.get("head_sha") != source_sha
        or run.get("head_branch") != "main"
        or run.get("event") != "workflow_dispatch"
        or type(run.get("run_attempt")) is not int
        or run["run_attempt"] != 1
    ):
        raise DispatchError("current release dispatch is unverified")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3:
        print("usage: check_release_dispatch.py RESPONSE_JSON SOURCE_SHA RUN_ID", file=sys.stderr)
        return 2
    try:
        validate_dispatch_history(load_history(Path(args[0])), args[1], args[2])
    except DispatchError as exc:
        print(f"BOCA_NO_GO: {exc}", file=sys.stderr)
        return 1
    print("BOCA_RELEASE_DISPATCH_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
