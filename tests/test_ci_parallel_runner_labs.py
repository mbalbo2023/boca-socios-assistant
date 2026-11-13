"""Execute the real CI parallel-lab shell with disposable command stand-ins.

The external Docker-running programs are represented by two fixed local
executables; the *real workflow Bash* handles concurrency and failure status.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github/workflows/ci.yml"
STEP = "      - name: Prove independent capture and panel restart labs in parallel\n"


def _body() -> str:
    source = CI.read_text(encoding="utf-8")
    assert STEP in source, "Missing the fail-closed parallel-lab barrier"
    content = source.split(STEP, 1)[1].split("      - name:", 1)[0]
    return textwrap.dedent(content.split("        run: |\n", 1)[1])


def _fake_tool(path: Path, role: str) -> None:
    # This executable intentionally accepts only the exact intended lab.
    expected = (
        '[[ "$#" -eq 2 && "$1" == "-m" && "$2" == "scripts.check_worker_start_capture" ]]'
        if role == "capture"
        else '[[ "$#" -eq 5 && "$1" == "run" && "$2" == "--no-sync" '
        '&& "$3" == "python" && "$4" == "-m" '
        '&& "$5" == "scripts.lab_panel_restart_921" ]]'
    )
    other = "panel" if role == "capture" else "capture"
    script = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"{expected}\n"
        f'touch "$FAKE_LAB_MARKERS/{role}.started"\n'
        "for _ in $(seq 1 200); do\n"
        f'  [[ -f "$FAKE_LAB_MARKERS/{other}.started" ]] && break\n'
        "  sleep 0.01\n"
        "done\n"
        f'[[ -f "$FAKE_LAB_MARKERS/{other}.started" ]] || exit 90\n'
        f"printf 'BOCA_FAKE_{role.upper()} finished=yes\\n'\n"
        f'exit "${{FAKE_LAB_{role.upper()}_EXIT:-0}}"\n'
    )
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


@pytest.mark.parametrize(
    ("capture_exit", "panel_exit", "expected_success"),
    [(0, 0, True), (13, 0, False), (0, 23, False), (13, 23, False), (124, 0, False)],
)
def test_parallel_labs_wait_for_both_and_propagate_every_failure(
    tmp_path: Path, capture_exit: int, panel_exit: int, expected_success: bool
) -> None:
    """A sequential run or ignored exit code must break the real Bash test."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    markers = tmp_path / "markers"
    markers.mkdir()
    _fake_tool(bindir / "python3", "capture")
    _fake_tool(bindir / "uv", "panel")

    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_RUN_ID": "123456789",
        "GITHUB_SHA": "a" * 40,
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
        "FAKE_LAB_MARKERS": str(markers),
        "FAKE_LAB_CAPTURE_EXIT": str(capture_exit),
        "FAKE_LAB_PANEL_EXIT": str(panel_exit),
    }
    run = subprocess.run(  # noqa: S603 - execute the reviewed Bash with disposable fake tools
        ("/usr/bin/bash", "-euo", "pipefail", "-c", _body()),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    combined = run.stdout + run.stderr
    assert (run.returncode == 0) is expected_success, combined
    assert "BOCA_FAKE_CAPTURE finished=yes" in combined
    assert "BOCA_FAKE_PANEL finished=yes" in combined
    receipt = (
        f"BOCA_CI_PARALLEL_LABS result={'PASS' if expected_success else 'FAIL'} "
        f"capture_rc={capture_exit} panel_rc={panel_exit} "
    )
    assert receipt in combined
    assert receipt in (tmp_path / "summary.md").read_text(encoding="utf-8")
    for role in ("capture", "panel"):
        log_files = list(tmp_path.glob(f"boca-ci-{role}.*"))
        assert len(log_files) == 1
        assert log_files[0].stat().st_mode & 0o777 == 0o600
        assert f"BOCA_FAKE_{role.upper()} finished=yes" in log_files[0].read_text(encoding="utf-8")


def test_parallel_labs_preserve_builds_scans_and_aggregate_before_consumers() -> None:
    source = CI.read_text(encoding="utf-8")
    image = source.split("  image:\n", 1)[1]
    assert image.count("uses: docker/build-push-action@") == 2
    assert image.count('run: bash scripts/trivy_scan_image.sh "') == 2
    assert image.index("Install locked runtime dependencies for the Docker labs") < image.index(
        STEP
    )
    assert image.index(STEP) < image.index("Require scan aliases to identify the exact built pair")
    assert image.count("scripts.check_worker_start_capture") == 1
    assert image.count("scripts.lab_panel_restart_921") == 1
