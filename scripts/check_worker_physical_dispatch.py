"""Offline proof of one owner Boca probe and corrected dual image #810 ancestry."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from boca_socios.host_worker_physical import RELEASE_RUN_ID, RELEASE_SOURCE_SHA
from boca_socios.release_run import ReleaseRunError, validate_release_run
from scripts.check_boca_deploy_dispatch import (
    load_evidence,
    verify_completed_ci,
)
from scripts.check_worker_w1_dispatch import DispatchUnavailable as W1Unavailable
from scripts.check_worker_w1_dispatch import validate as validate_owner_dispatch

_ALLOWED_CODE = frozenset(
    {
        ".github/workflows/boca-first-deploy.yml",
        "scripts/build_protected_boca_bundle.py",
        "scripts/boca_protected_memfd_bootstrap.py",
        "scripts/check_worker_physical_dispatch.py",
        "src/boca_socios/host_worker_physical.py",
        "tests/test_host_worker_physical.py",
        "tests/test_r158_volume_proof.py",
        "tests/test_worker_physical_bundle.py",
        "tests/test_worker_physical_workflow.py",
        "tests/test_worker_physical_dispatch.py",
    }
)


class DispatchUnavailable(ValueError):
    """Source ancestry, owner attempt or dual release cannot be authenticated."""


def validate(
    history: object,
    installed: object,
    release: object,
    comparison: object,
    open_prs: object,
    ci_runs: object,
    checks: object,
    run_id: str,
    main_sha: str,
) -> None:
    try:
        validate_owner_dispatch(history, installed, run_id, main_sha)
        validate_release_run(release, RELEASE_SOURCE_SHA, RELEASE_RUN_ID)
        verify_completed_ci(main_sha, ci_runs, checks)
    except (W1Unavailable, ReleaseRunError, ValueError, TypeError):
        raise DispatchUnavailable from None
    if (
        type(open_prs) is not list
        or open_prs
        or type(comparison) is not dict
        or comparison.get("status") != "ahead"
        or type(comparison.get("ahead_by")) is not int
        or not 1 <= comparison["ahead_by"] <= 15
        or comparison.get("behind_by") != 0
        or type(comparison.get("base_commit")) is not dict
        or comparison["base_commit"].get("sha") != RELEASE_SOURCE_SHA
        or type(comparison.get("merge_base_commit")) is not dict
        or comparison["merge_base_commit"].get("sha") != RELEASE_SOURCE_SHA
        or type(comparison.get("files")) is not list
        or not 1 <= len(comparison["files"]) < 100
    ):
        raise DispatchUnavailable
    for file in comparison["files"]:
        if (
            type(file) is not dict
            or type(file.get("filename")) is not str
            or file.get("status") not in ("added", "modified")
            or file["filename"] not in _ALLOWED_CODE
            and not file["filename"].startswith("docs/superpowers/")
            and not file["filename"].startswith("docs/ADR/0224-")
        ):
            raise DispatchUnavailable


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(args) != 9:
            raise DispatchUnavailable
        paths = [Path(name) for name in args[:7]]
        if any(not 0 < p.stat().st_size < 5_000_000 for p in paths):
            raise DispatchUnavailable
        history = [json.loads(line) for line in paths[0].read_text().splitlines()]
        data = [json.loads(path.read_text()) for path in paths[1:5]]
        ci_runs, checks = (load_evidence(path, paginated=True) for path in paths[5:7])
        validate(history, data[0], data[1], data[2], data[3], ci_runs, checks, args[7], args[8])
    except (ValueError, OSError, UnicodeError, TypeError, KeyError):
        print("BOCA_WORKER_PHYSICAL_GATE state=NO_GO")
        return 3
    print(
        "BOCA_WORKER_PHYSICAL_GATE state=PASS owner=VERIFIED release=810 pr0=YES action_ancestry=VERIFIED current_ci=GREEN"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
