"""Executable historical #843/#844/#845 REST attestation, including Python -O."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = "scripts.check_r96_stage_evidence"
SHA = "e3cbd38856a2aa75e9ec5e276335da0be6ed520b"
PREPARE = 42381545964
INCIDENT = 42388694186
READONLY = 42388994569


def _run(identifier: int, conclusion: str, **overrides) -> dict:
    return {
        "id": identifier,
        "status": "completed",
        "conclusion": conclusion,
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": SHA,
        "run_attempt": 1,
        "path": ".github/workflows/boca-first-deploy.yml",
        "actor": {"login": "mbalbo2023"},
        "repository": {"full_name": "mbalbo2023/boca-socios-assistant"},
        **overrides,
    }


def _cli(tmp_path: Path, *, replacement: dict | None = None) -> subprocess.CompletedProcess[str]:
    records = [
        _run(READONLY, "success"),
        _run(INCIDENT, "failure"),
        _run(PREPARE, "success"),
    ]
    if replacement is not None:
        records[1] = {**records[1], **replacement}
    paths = [tmp_path / f"run-{index}.json" for index in range(3)]
    for path, record in zip(paths, records, strict=True):
        path.write_text(json.dumps(record), encoding="utf-8")
    return subprocess.run(  # noqa: S603 - fixed local Python interpreter, no shell
        [
            sys.executable,
            "-O",  # Ensure the gate still enforces every condition with assertions stripped.
            "-m",
            SCRIPT,
            *(str(path) for path in paths),
            str(INCIDENT),
            str(PREPARE),
            str(READONLY),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": "src:."},
        capture_output=True,
        text=True,
        timeout=7,
        check=False,
    )


def test_r96_optimized_python_accepts_only_exact_historical_triplet(tmp_path: Path) -> None:
    result = _cli(tmp_path)
    assert result.returncode == 0
    assert "BOCA_REMEDIATION_GATE state=PASS" in result.stdout


@pytest.mark.parametrize(
    "replacement",
    [
        {"id": 42388694187},
        {"status": "in_progress"},
        {"conclusion": "success"},
        {"head_branch": "feature/fake"},
        {"head_sha": "f" * 40},
        {"run_attempt": 2},
        {"event": "push"},
        {"path": ".github/workflows/other.yml"},
        {"actor": {"login": "intruder"}},
        {"repository": {"full_name": "foreign/repo"}},
    ],
)
def test_r96_optimized_python_rejects_false_history(tmp_path: Path, replacement: dict) -> None:
    result = _cli(tmp_path, replacement=replacement)
    assert result.returncode != 0
    assert "BOCA_REMEDIATION_GATE state=PASS" not in result.stdout
