"""Owner-dispatched V3 admission, not a second or independently minted GO.

Only the protected Actions workflow downloads this evidence. No networking or
host effects here. A successful dispatch authorizes one exact simulation
transaction; its derived digest binds bytes, it is not human approval proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO = "mbalbo2023/boca-socios-assistant"
WORKFLOW = ".github/workflows/boca-first-deploy.yml"
TITLE = "BOCA-SIMULATION-DEPLOY-V3"
FILES = ("run", "main", "pulls", "history", "checks", "ci", "event")


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("V3 exact owner/main/one-shot evidence unverified")


def _pages(raw: Any, field: str) -> list[dict[str, Any]]:
    _require(type(raw) is list and bool(raw))
    rows: list[dict[str, Any]] = []
    _require(type(raw[0]) is dict)
    total = raw[0].get("total_count")
    _require(type(total) is int and 0 <= total < 1000)
    for page in raw:
        _require(type(page) is dict and page.get("total_count") == total)
        _require(type(page.get(field)) is list)
        rows.extend(page[field])
    _require(len(rows) == total and all(type(row) is dict for row in rows))
    return rows


def verify_dispatch(env: Mapping[str, str], proof: dict[str, Any]) -> None:
    """Fail before SSH on missing pages, foreign context, rerun or second run."""
    for key, expected in {
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_ACTOR": "mbalbo2023",
        "GITHUB_TRIGGERING_ACTOR": "mbalbo2023",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKFLOW_REF": f"{REPO}/{WORKFLOW}@refs/heads/main",
        "BOCA_OPERATION": "cutover-a-apply",
    }.items():
        _require(env.get(key) == expected)
    sha, run_id = env.get("GITHUB_SHA", ""), env.get("GITHUB_RUN_ID", "")
    _require(re.fullmatch(r"[0-9a-f]{40}", sha) is not None)
    _require(re.fullmatch(r"[1-9][0-9]{0,19}", run_id) is not None)
    _require(set(proof) == set(FILES))
    run = proof["run"]
    for key, expected_run in {
        "id": int(run_id),
        "run_attempt": 1,
        "event": "workflow_dispatch",
        "head_sha": sha,
        "head_branch": "main",
        "path": WORKFLOW,
        "display_title": TITLE,
        "status": "in_progress",
        "conclusion": None,
    }.items():
        _require(run.get(key) == expected_run and type(run.get(key)) is type(expected_run))
    for key in ("actor", "triggering_actor"):
        _require(run.get(key, {}).get("login") == "mbalbo2023")
    for key in ("repository", "head_repository"):
        _require(run.get(key, {}).get("full_name") == REPO)
    _require(proof["main"].get("object", {}).get("sha") == sha)
    _require(proof["pulls"] == [])
    inputs = proof["event"].get("inputs")
    _require(type(inputs) is dict and inputs.get("operation") == "cutover-a-apply")
    for key, value in inputs.items():
        if key == "operation":
            continue
        if key == "service":
            _require(value == "controller")
        elif key == "resource_budget":
            # V3 derives its reviewed cap; old form's default is not a host pin.
            _require(value in ("0.5cpu-256m-64pids", "1.5cpu-1024m-192pids"))
        else:
            _require(value == "")
    history = _pages(proof["history"], "workflow_runs")
    ids = [item.get("id") for item in history]
    _require(all(type(value) is int for value in ids) and len(ids) == len(set(ids)))
    matching = [item for item in history if item.get("display_title") == TITLE]
    _require(len(matching) == 1)
    # Run detail and listing endpoints may add different metadata. Compare the
    # authenticated identity, not their incidental REST projection shapes.
    for key in (
        "id",
        "run_attempt",
        "event",
        "head_sha",
        "head_branch",
        "path",
        "display_title",
        "status",
        "conclusion",
        "actor",
        "triggering_actor",
        "repository",
        "head_repository",
    ):
        if key in ("actor", "triggering_actor"):
            _require(matching[0].get(key, {}).get("login") == "mbalbo2023")
        elif key in ("repository", "head_repository"):
            _require(matching[0].get(key, {}).get("full_name") == REPO)
        else:
            _require(matching[0].get(key) == run[key])
    ci_runs = _pages(proof["ci"], "workflow_runs")
    _require(len(ci_runs) == 1)
    ci = ci_runs[0]
    for key, expected_ci in {
        "event": "push",
        "head_sha": sha,
        "head_branch": "main",
        "path": ".github/workflows/ci.yml",
        "run_attempt": 1,
        "status": "completed",
        "conclusion": "success",
    }.items():
        _require(ci.get(key) == expected_ci and type(ci.get(key)) is type(expected_ci))
    _require(type(ci.get("id")) is int and ci["id"] > 0)
    suite = ci.get("check_suite_id")
    _require(type(suite) is int and suite > 0)
    for key in ("repository", "head_repository"):
        _require(ci.get(key, {}).get("full_name") == REPO)
    checks = _pages(proof["checks"], "check_runs")
    for name in ("quality-and-tests", "image-build"):
        relevant = [item for item in checks if item.get("name") == name]
        _require(len(relevant) == 1)
        check = relevant[0]
        _require(
            check.get("head_sha") == sha
            and check.get("status") == "completed"
            and check.get("conclusion") == "success"
            and check.get("app", {}).get("slug") == "github-actions"
            and check.get("check_suite", {}).get("id") == suite
        )


def write_invocation(env: Mapping[str, str], proof: dict[str, Any]) -> None:
    """Write a V3-only run/byte binding after authenticated dispatch admission."""
    verify_dispatch(env, proof)
    import check_cutover_a_go as go

    from boca_socios.host_boca_cutover_cli import encode_invocation

    request = go.actions_request(env)
    bundle_before = go._read_bounded(request.bundle_path, go.memfd.MAX_ZIP)
    reviewed = go.authorization_digest(request)
    bundle_after = go._read_bounded(request.bundle_path, go.memfd.MAX_ZIP)
    _require(bundle_before == bundle_after)
    binding = hashlib.sha256(("boca-dispatch-v3\0" + reviewed).encode("ascii")).hexdigest()
    token = encode_invocation(
        request.plan,
        bundle_sha256=hashlib.sha256(bundle_after).hexdigest(),
        go_binding_sha256=binding,
        dispatch_v3=True,
    )
    go._write_once(request.bundle_path.parent / go.HOST_INVOCATION_NAME, (token + "\n").encode())
    go._write_once(request.bundle_path.parent / go.HOST_APPROVAL_NAME, (binding + "\n").encode())


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in out)
        out[key] = value
    return out


def _paginated_json(raw: bytes) -> list[Any]:
    """Decode bounded adjacent gh --paginate pages without requiring --slurp."""
    document = raw.decode("utf-8")
    decoder = json.JSONDecoder(object_pairs_hook=_unique)
    pages: list[Any] = []
    offset = 0
    while offset < len(document):
        while offset < len(document) and document[offset].isspace():
            offset += 1
        if offset == len(document):
            break
        page, offset = decoder.raw_decode(document, offset)
        pages.append(page)
        _require(len(pages) <= 20)
    # Accept a single array envelope for offline fixtures; production uses
    # adjacent REST objects on both old and new versions of gh.
    if len(pages) == 1 and type(pages[0]) is list:
        return list(pages[0])
    return pages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--write-invocation", action="store_true")
    args = parser.parse_args(argv)
    try:
        proof = {}
        for name in FILES:
            with (args.evidence / (name + ".json")).open("rb") as stream:
                raw = stream.read(4_000_001)
            _require(0 < len(raw) <= 4_000_000)
            proof[name] = (
                _paginated_json(raw)
                if name in ("history", "checks", "ci")
                else json.loads(raw, object_pairs_hook=_unique)
            )
        if args.write_invocation:
            write_invocation(os.environ, proof)
        else:
            verify_dispatch(os.environ, proof)
    except (ValueError, TypeError, KeyError, OSError, AttributeError):
        print("BOCA_DISPATCH_V3 state=NO_GO host=untouched no_retry=true", file=sys.stderr)
        return 1
    print("BOCA_DISPATCH_V3 state=PASS authority=owner_dispatch host=untouched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
