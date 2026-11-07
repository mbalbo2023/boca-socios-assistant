"""R96: the physical stage cleanup can run ONCE only, across every source SHA."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
RUN = "42389000002"
MARKER = "BOCA-R96-STAGE-844-RECOVER-ONCE"


def _selected(**changes: object) -> dict:
    return {
        "id": int(RUN),
        "display_title": MARKER,
        "event": "workflow_dispatch",
        "head_sha": SHA,
        "head_branch": "main",
        "run_attempt": 1,
        "path": ".github/workflows/boca-first-deploy.yml",
        "actor": {"login": "mbalbo2023"},
        "repository": {"full_name": "mbalbo2023/boca-socios-assistant"},
        **changes,
    }


def _call(
    tmp_path: Path,
    *,
    record: dict | None = None,
    prs: list | None = None,
    summary: dict | list[dict] | None = None,
    sha: str = SHA,
    run: str = RUN,
) -> subprocess.CompletedProcess[str]:
    pages = (
        [
            *(
                {
                    "total_count": 850,
                    "fetched_count": 100,
                    "run_ids": list(range(10000 + index * 100, 10100 + index * 100)),
                    "workflow_runs": [],
                }
                for index in range(8)
            ),
            {
                "total_count": 850,
                "fetched_count": 50,
                "run_ids": [int(RUN), *range(10801, 10850)],
                "workflow_runs": [_selected() if record is None else record],
            },
        ]
        if summary is None
        else summary
        if isinstance(summary, list)
        else [summary]
    )
    history_path, pr_path = tmp_path / "history.json", tmp_path / "prs.json"
    history_path.write_text("\n".join(json.dumps(page) for page in pages) + "\n", encoding="utf-8")
    pr_path.write_text(json.dumps([] if prs is None else prs), encoding="utf-8")
    return subprocess.run(  # noqa: S603 - fixed local Python interpreter, no shell
        [
            sys.executable,
            "-O",
            "-m",
            "scripts.check_r96_stage_dispatch",
            str(history_path),
            str(pr_path),
            sha,
            run,
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": "src:."},
        text=True,
        capture_output=True,
        check=False,
        timeout=7,
    )


def test_r96_proven_850_run_global_history_and_pr0_accepts(tmp_path: Path) -> None:
    result = _call(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "BOCA_R96_STAGE_DISPATCH_PASS" in result.stdout


@pytest.mark.parametrize(
    "record_delta",
    [
        {"id": 42389000003},
        {"head_sha": "b" * 40},
        {"run_attempt": 2},
        {"event": "push"},
        {"head_branch": "branch"},
        {"display_title": "unrelated"},
        {"path": ".github/workflows/other.yml"},
        {"actor": {"login": "intruder"}},
        {"repository": {"full_name": "other/repo"}},
    ],
)
def test_r96_optimized_gate_rejects_spoofed_run(tmp_path: Path, record_delta: dict) -> None:
    result = _call(tmp_path, record=_selected(**record_delta))
    assert result.returncode != 0


@pytest.mark.parametrize(
    "change",
    [
        {"total_count": 850, "fetched_count": 849, "workflow_runs": [_selected()]},
        {"total_count": 850, "fetched_count": 851, "workflow_runs": [_selected()]},
        {
            "total_count": 850,
            "fetched_count": 850,
            "workflow_runs": [_selected(), _selected(id=99)],
        },
        {"total_count": 0, "fetched_count": 0, "workflow_runs": [_selected()]},
        {"total_count": 2001, "fetched_count": 2001, "workflow_runs": [_selected()]},
        {"total_count": 1000, "fetched_count": 1000, "workflow_runs": [_selected()]},
        {"total_count": "850", "fetched_count": 850, "workflow_runs": [_selected()]},
    ],
)
def test_r96_optimized_gate_rejects_truncated_or_replayed_history(
    tmp_path: Path, change: dict
) -> None:
    result = _call(tmp_path, summary=change)
    assert result.returncode != 0


def test_r96_optimized_gate_rejects_missing_page(tmp_path: Path) -> None:
    pages = [
        *(
            {
                "total_count": 850,
                "fetched_count": 100,
                "run_ids": list(range(10000 + index * 100, 10100 + index * 100)),
                "workflow_runs": [],
            }
            for index in range(7)
        ),
        {
            "total_count": 850,
            "fetched_count": 50,
            "run_ids": [int(RUN), *range(10801, 10850)],
            "workflow_runs": [_selected()],
        },
    ]
    assert _call(tmp_path, summary=pages).returncode != 0


def test_r96_optimized_gate_rejects_second_marker_on_another_source(tmp_path: Path) -> None:
    pages = [
        *(
            {
                "total_count": 850,
                "fetched_count": 100,
                "run_ids": list(range(10000 + index * 100, 10100 + index * 100)),
                "workflow_runs": [],
            }
            for index in range(8)
        ),
        {
            "total_count": 850,
            "fetched_count": 50,
            "run_ids": [int(RUN), 42389000009, *range(10802, 10850)],
            "workflow_runs": [_selected(), _selected(id=42389000009, head_sha="b" * 40)],
        },
    ]
    assert _call(tmp_path, summary=pages).returncode != 0


def test_r96_optimized_gate_rejects_inconsistent_page_total(tmp_path: Path) -> None:
    pages = [
        *(
            {
                "total_count": 850,
                "fetched_count": 100,
                "run_ids": list(range(10000 + index * 100, 10100 + index * 100)),
                "workflow_runs": [],
            }
            for index in range(8)
        ),
        {
            "total_count": 851,
            "fetched_count": 50,
            "run_ids": [int(RUN), *range(10801, 10850)],
            "workflow_runs": [_selected()],
        },
    ]
    assert _call(tmp_path, summary=pages).returncode != 0


def test_r96_optimized_gate_rejects_duplicate_run_id_across_pages(tmp_path: Path) -> None:
    pages = [
        *(
            {
                "total_count": 850,
                "fetched_count": 100,
                "run_ids": list(range(10000 + index * 100, 10100 + index * 100)),
                "workflow_runs": [],
            }
            for index in range(8)
        ),
        {
            "total_count": 850,
            "fetched_count": 50,
            "run_ids": [10000, int(RUN), *range(10802, 10850)],
            "workflow_runs": [_selected()],
        },
    ]
    assert _call(tmp_path, summary=pages).returncode != 0


def test_r96_optimized_gate_rejects_selected_marker_not_in_page_ids(tmp_path: Path) -> None:
    pages = [
        *(
            {
                "total_count": 850,
                "fetched_count": 100,
                "run_ids": list(range(10000 + index * 100, 10100 + index * 100)),
                "workflow_runs": [],
            }
            for index in range(8)
        ),
        {
            "total_count": 850,
            "fetched_count": 50,
            "run_ids": list(range(10800, 10850)),
            "workflow_runs": [_selected()],
        },
    ]
    assert _call(tmp_path, summary=pages).returncode != 0


def test_r96_optimized_gate_rejects_workflow_api_cap_even_with_complete_10_pages(
    tmp_path: Path,
) -> None:
    pages = [
        *(
            {
                "total_count": 1000,
                "fetched_count": 100,
                "run_ids": list(range(10000 + index * 100, 10100 + index * 100)),
                "workflow_runs": ([_selected()] if index == 9 else []),
            }
            for index in range(10)
        ),
    ]
    assert _call(tmp_path, summary=pages).returncode != 0


def test_r96_optimized_gate_rejects_open_pr(tmp_path: Path) -> None:
    result = _call(tmp_path, prs=[{"number": 999}])
    assert result.returncode != 0


def test_r96_optimized_gate_rejects_wrong_current_sha(tmp_path: Path) -> None:
    result = _call(tmp_path, sha="b" * 40)
    assert result.returncode != 0


def test_r96_optimized_gate_rejects_wrong_run_id(tmp_path: Path) -> None:
    result = _call(tmp_path, run="42389000003")
    assert result.returncode != 0
