"""Administration/status transport: real shell, fake SSH; no physical effects."""

import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

from test_r294_current_retained import RUN
from test_r294_installed_admin import WORKFLOW, canonical, document

ROOT = Path(__file__).resolve().parents[1]
FLOW = ROOT / ".github/workflows/boca-first-deploy.yml"
STATUS = "Observe installed Boca status from its current binding"
ADMIN = "Provision installed Boca sidecars and publish redacted Telegram status"


def step(name):
    raw = FLOW.read_text()
    marker = f"      - name: {name}\n"
    assert raw.count(marker) == 1
    return raw.split(marker)[1].split("      - name:")[0]


def test_post_apply_is_explicit_separate_and_uses_only_authenticated_binding():
    raw = FLOW.read_text()
    block = step(ADMIN)
    assert "if: inputs.operation == 'boca-installed-admin-provision'" in block
    assert "boca-pair-upgrade-apply" not in block and "continue-on-error" not in block
    assert raw.index(f"      - name: {ADMIN}") > raw.index('"state":"ACCEPTED"')
    assert "--installed-admin" in block
    assert "python3 -I -S -B" in block
    assert "current" in block
    assert "READ_ONLY" not in block
    assert "SECRET" not in block and "BOCA_IMAGE_REF" not in block
    assert "EXPLICIT_ADMIN_REFRESH_NO_DEPLOY" in block
    assert "BOCA_INSTALLED_ADMIN" in block
    assert "BOCA_INSTALLED_ADMIN state=PENDING action=EXPLICIT_PROVISION_REQUIRED" in raw
    status = step(STATUS)
    assert "verify-current" in status
    assert "python3 -I -S -B" in status
    assert "BOCA_IMAGE_REF" not in status and "BOCA_BROWSER_IMAGE_REF" not in status


@pytest.mark.parametrize(
    "operation", ("boca-installed-status-observe", "boca-installed-admin-provision")
)
@pytest.mark.parametrize(
    "field,value,ok",
    (
        ("BOCA_IMAGE_REF", "", True),
        ("BOCA_IMAGE_REF", "private", False),
        ("BOCA_SOURCE_SHA_SUBMITTED", "e" * 40, False),
    ),
)
def test_no_caller_installed_coordinates_accepted(operation, field, value, ok):
    raw = FLOW.read_text()
    gate = raw.split(f"            {operation})\n", 1)[1].split("              ;;", 1)[0]
    env = {
        **os.environ,
        "BOCA_SOURCE_SHA": WORKFLOW,
        "GITHUB_SHA": WORKFLOW,
        "BOCA_BUDGET": "1.5cpu-1024m-192pids",
    }
    for name in re.findall(r"\$([A-Z_][A-Z_0-9]*)", gate):
        env.setdefault(name, "ready" if name.endswith("ENV_READY") else "")
    env[field] = value
    result = subprocess.run(["/bin/bash", "-euc", gate], env=env, capture_output=True, check=False)  # noqa: S603
    assert (result.returncode == 0) is ok


@pytest.mark.parametrize("remote_rc,valid", ((0, True), (255, True), (3, True), (0, False)))
def test_admin_transport_classifies_failure_without_raw_output(tmp_path, remote_rc, valid):
    from boca_socios import host_boca_installed_admin as admin

    raw = admin.PREFIX + canonical(
        {
            "schema": 1,
            "state": "PROVISIONED",
            "workflow_source_sha": WORKFLOW,
            "sector_schema": 2,
            "legacy_writes": 0,
            "telegram": document(),
        }
    )
    script = textwrap.dedent(step(ADMIN).split("        run: |\n", 1)[1])
    summary = tmp_path / "summary"
    summary.touch()
    setup = """
gh() { printf '%s\\n' '{"ref":"refs/heads/main","object":{"type":"commit","sha":"ffffffffffffffffffffffffffffffffffffffff"}}'; }
ssh() { printf '%s' "$TEST_STDOUT"; printf '%s' 'PRIVATE_STDERR' >&2; return "$TEST_REMOTE_RC"; }
timeout() { shift 3; "$@"; }
"""
    result = subprocess.run(  # noqa: S603 - fixed script; every network boundary is an offline fake
        ["/bin/bash", "-c", setup + script],
        cwd=ROOT,
        env={  # noqa: S603
            **os.environ,
            "RUNNER_TEMP": str(tmp_path),
            "PYTHONPATH": str(ROOT / "src"),
            "GITHUB_RUN_ID": RUN,
            "GITHUB_SHA": WORKFLOW,
            "BOCA_SOURCE_SHA": WORKFLOW,
            "BOCA_OPERATION": "boca-installed-admin-provision",
            "GITHUB_REPOSITORY": "mbalbo2023/boca-socios-assistant",
            "GITHUB_STEP_SUMMARY": str(summary),
            "TEST_STDOUT": raw.decode() if valid else "PRIVATE_RAW_HOST_OUTPUT",
            "TEST_REMOTE_RC": str(remote_rc),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is (remote_rc == 0 and valid)
    output = summary.read_text() + result.stdout + result.stderr
    assert "PRIVATE_" not in output
    if remote_rc == 0 and valid:
        assert raw.decode().strip() in output
    else:
        assert "EXPLICIT_ADMIN_REFRESH_NO_DEPLOY" in output
