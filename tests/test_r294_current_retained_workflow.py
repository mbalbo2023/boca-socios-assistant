"""Current retained workflow gate/transport exercised with offline boundaries."""

from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

from test_r294_current_retained import RUN, fixture_snapshot, module

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/boca-first-deploy.yml"
OPERATION = "boca-current-retained-resource-observe"
STEP = "Observe current Boca retained resources READ_ONLY"


def step() -> str:
    raw = WORKFLOW.read_text()
    heading = f"      - name: {STEP}\n"
    assert raw.count(heading) == 1
    return raw.split(heading, 1)[1].split("      - name:", 1)[0]


def test_current_selector_is_distinct_and_reuses_one_upload_step() -> None:
    raw = WORKFLOW.read_text()
    operations = raw.split("      operation:\n", 1)[1].split("      source_sha:\n", 1)[0]
    assert operations.count(OPERATION) == 1
    env = raw.split("    env:\n", 1)[1].split("    steps:\n", 1)[0]
    assert f"inputs.operation == '{OPERATION}'" in env
    upload = "Upload authenticated candidate for retained Boca resources READ_ONLY"
    assert raw.count(f"      - name: {upload}\n") == 1
    body = raw.split(f"      - name: {upload}\n", 1)[1].split("      - name:", 1)[0]
    assert (
        f"if: inputs.operation == 'boca-retained-resource-observe' || inputs.operation == '{OPERATION}'"
        in body
    )
    assert "name: boca-retained-resources-observation" in body
    assert "boca-retained-observation.receipt" in body
    names = re.findall(r"^      - name: (.+)$", raw.split("  deploy:\n", 1)[1], re.M)
    assert len(names) == len(set(names))


@pytest.mark.parametrize(
    "field,value,code",
    (
        ("BOCA_SOURCE_SHA_SUBMITTED", "", 0),
        ("BOCA_SOURCE_SHA_SUBMITTED", "a" * 40, 1),
        ("BOCA_SOURCE_SHA", "b" * 40, 1),
        ("BOCA_IMAGE_REF", "unexpected", 1),
        ("BOCA_PROTECTED_ACTION_CONTEXT", "43534359504", 1),
        ("BOCA_OFFICIAL_NEWS_RUN_ID", "43504739633", 1),
        ("BOCA_HOST_READONLY_ENV_READY", "", 1),
        ("BOCA_DEPLOY_ENV_READY", "", 1),
        ("BOCA_BUDGET", "0.5cpu-256m-64pids", 1),
    ),
)
def test_current_gate_uses_runner_source_and_accepts_no_installed_coordinates(
    field: str, value: str, code: int
) -> None:
    raw = WORKFLOW.read_text()
    gate = raw.split(f"            {OPERATION})\n", 1)[1].split("              ;;", 1)[0]
    env = {
        **os.environ,
        "BOCA_HOST_READONLY_ENV_READY": "ready",
        "BOCA_DEPLOY_ENV_READY": "ready",
        "BOCA_SOURCE_SHA": "a" * 40,
        "GITHUB_SHA": "a" * 40,
        "BOCA_BUDGET": "1.5cpu-1024m-192pids",
    }
    for name in re.findall(r"\$([A-Z_][A-Z_0-9]*)", gate):
        env.setdefault(name, "")
    env[field] = value
    result = subprocess.run(  # noqa: S603 - exact local gate, no host commands
        ["/bin/bash", "-euc", gate],
        env=env,
        capture_output=True,
        check=False,
    )
    assert result.returncode == code


@pytest.mark.parametrize("remote_rc,valid", ((0, True), (255, True), (3, True), (0, False)))
def test_current_step_exports_only_verified_success_and_redacts_failures(
    tmp_path: Path, remote_rc: int, valid: bool
) -> None:
    raw = module().observe(RUN, snapshot_reader=lambda _run: fixture_snapshot()).decode()
    raw = raw if valid else "TOKEN=UNTRUSTED_RAW_HOST_OUTPUT\n"
    script = textwrap.dedent(step().split("        run: |\n", 1)[1])
    summary = tmp_path / "summary"
    summary.touch()
    setup = """
gh() { printf '%s\\n' '{"ref":"refs/heads/main","object":{"type":"commit","sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}'; }
ssh() { printf '%s' "$TEST_STDOUT"; printf '%s' 'TOKEN=UNTRUSTED_STDERR' >&2; return "$TEST_REMOTE_RC"; }
timeout() { shift 3; "$@"; }
"""
    result = subprocess.run(  # noqa: S603 - offline fakes for every network boundary
        ["/bin/bash", "-c", setup + script],
        cwd=ROOT,
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_RUN_ID": RUN,
            "GITHUB_REPOSITORY": "mbalbo2023/boca-socios-assistant",
            "BOCA_SOURCE_SHA": "a" * 40,
            "GITHUB_STEP_SUMMARY": str(summary),
            "TEST_STDOUT": raw,
            "TEST_REMOTE_RC": str(remote_rc),
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    accepted = valid and remote_rc == 0
    assert (result.returncode == 0) is accepted
    exported = tmp_path / "boca-retained-observation.receipt"
    assert exported.exists() is accepted
    if accepted:
        assert exported.read_text() == raw
    for output in (summary.read_text(), result.stdout, result.stderr):
        assert "TOKEN=" not in output
    assert ('"state":"READ_ONLY"' in summary.read_text()) is accepted
