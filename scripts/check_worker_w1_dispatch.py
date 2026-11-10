"""One W1 protected Actions dispatch, exact successful #926, no host access here."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TypeGuard

_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_OWNER = "mbalbo2023"
_WORKFLOW_ID = 400115324
_WORKFLOW_PATH = ".github/workflows/boca-first-deploy.yml"
_REPOSITORY = "mbalbo2023/boca-socios-assistant"
_INSTALL = 42806447101
_INSTALL_SHA = "03df9a14bdd78cf768386a865876fed9d5656911"


class DispatchUnavailable(ValueError):
    """Immutable GitHub REST evidence cannot authorize W1 host access."""


def _identity(document: object) -> TypeGuard[dict[str, object]]:
    return (
        type(document) is dict
        # The `name` field can be overridden by the workflow's dynamic `run-name`.
        # GitHub #926 is really named BOCA-SIMULATION-DEPLOY-V3; authenticate
        # its immutable workflow ID, source path and repository instead.
        and document.get("workflow_id") == _WORKFLOW_ID
        and document.get("path") == _WORKFLOW_PATH
        and type(document.get("repository")) is dict
        and document["repository"].get("full_name") == _REPOSITORY
        and document.get("event") == "workflow_dispatch"
        and document.get("head_branch") == "main"
        and type(document.get("run_attempt")) is int
        and document["run_attempt"] == 1
        and type(document.get("actor")) is dict
        and document["actor"].get("login") == _OWNER
    )


def validate(history: object, installed: object, run_id: str, main_sha: str) -> None:
    if (
        type(run_id) is not str
        or not _RUN.fullmatch(run_id)
        or type(main_sha) is not str
        or not _SHA.fullmatch(main_sha)
        or main_sha == _INSTALL_SHA
        or type(history) is not list
        or not 1 <= len(history) <= 20000
        or not all(type(record) is dict for record in history)
        or not _identity(installed)
        or installed.get("id") != _INSTALL
        or installed.get("head_sha") != _INSTALL_SHA
        or installed.get("status") != "completed"
        or installed.get("conclusion") != "success"
    ):
        raise DispatchUnavailable
    # Main SHA is new because the W1 dispatcher must be reviewed and merged;
    # every manual operation on that SHA counts. This is stricter than just
    # counting calls labelled W1: unrelated on-demand dispatch also blocks it.
    current = [record for record in history if record.get("head_sha") == main_sha]
    if len(current) != 1 or not _identity(current[0]) or current[0].get("id") != int(run_id):
        raise DispatchUnavailable


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(args) != 4:
            raise DispatchUnavailable
        history_path, install_path, run_id, sha = map(str, args)
        raw_history = Path(history_path).read_bytes()
        raw_install = Path(install_path).read_bytes()
        if not raw_history or len(raw_history) > 5_000_000 or not 0 < len(raw_install) < 100_000:
            raise DispatchUnavailable
        history = [json.loads(line) for line in raw_history.splitlines()]
        installed = json.loads(raw_install)
        validate(history, installed, run_id, sha)
    except (ValueError, OSError, UnicodeError, TypeError, KeyError):
        print("BOCA_WORKER_W1_GATE state=NO_GO")
        return 3
    print("BOCA_WORKER_W1_GATE state=PASS historic_install=926 one_manual_run=YES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
