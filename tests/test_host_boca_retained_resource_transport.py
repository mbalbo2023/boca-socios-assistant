"""Execute the read-only transport and input gate without host access."""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from test_ci_parallel_pytest_contract import assert_required_ci_covers
from test_host_boca_retained_resources import RUN, module, snapshot

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import boca_protected_memfd_bootstrap as bootstrap  # noqa: E402
import build_protected_boca_bundle as builder  # noqa: E402


def test_retained_resource_bundle_is_small_inert_and_imports_in_isolated_python(tmp_path):
    first, second = tmp_path / "first.pyz", tmp_path / "second.pyz"
    digest = builder.build(ROOT, first, retained_observe=True)
    assert builder.build(ROOT, second, retained_observe=True) == digest
    bootstrap.verify(first.read_bytes(), digest, retained_observe=True)
    with pytest.raises(ValueError):
        bootstrap.verify(first.read_bytes(), digest, pair_upgrade=True)
    with zipfile.ZipFile(first) as bundle:
        names = set(bundle.namelist())
    assert not any(
        "host_first_deploy" in name or "upgrade_backend" in name or "compose" in name
        for name in names
    )
    raw = module().observe(RUN, snapshot_reader=lambda _: snapshot())
    program = "import sys; sys.path.insert(0,sys.argv[1]); from boca_socios.host_boca_retained_resources import verify; sys.stdout.buffer.write(verify(sys.stdin.buffer.read(),sys.argv[2]))"
    result = subprocess.run(  # noqa: S603 - fixed interpreter and test-owned ZIP
        [sys.executable, "-I", "-B", "-c", program, str(first), RUN],
        input=raw,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()[:300]
    assert result.stdout == raw


def test_protected_validation_collects_retained_failure_regressions():
    modules = (
        "tests/test_host_boca_pair_upgrade_plan.py",
        "tests/test_host_boca_pair_upgrade_workflow.py",
        "tests/test_host_boca_retained_resources.py",
        "tests/test_host_boca_retained_resource_transport.py",
        "tests/test_host_boca_retained_resource_failures.py",
    )
    assert_required_ci_covers(*modules)
    result = subprocess.run(  # noqa: S603 - collect the protected CI regression modules only
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *modules],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert (
        "tests/test_host_boca_retained_resource_failures.py::test_docker_root_json_with_real_cli_newline_allows_exact_metadata"
        in result.stdout
    )
    assert (
        "tests/test_host_boca_retained_resource_failures.py::test_workflow_preserves_typed_host_failure_in_summary"
        in result.stdout
    )


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("BOCA_SOURCE_SHA_SUBMITTED", "", 0),
        *[
            (name, "unexpected", 1)
            for name in (
                "BOCA_SOURCE_SHA_SUBMITTED",
                "BOCA_PROTECTED_ACTION_CONTEXT",
                "BOCA_IMAGE_REF",
                "BOCA_BROWSER_IMAGE_REF",
                "BOCA_RELEASE_RUN_ID",
                "BOCA_LEGACY_SOURCE_SHA",
                "BOCA_LEGACY_IMAGE_REF",
                "BOCA_LEGACY_RELEASE_RUN_ID",
                "BOCA_LEGACY_CONTROLLER_ID",
                "BOCA_SITE_ENVELOPE",
                "BOCA_TELEGRAM_ENVELOPE",
                "BOCA_OWNER_ENVELOPE",
                "BOCA_OWNER_CAPABILITY_SHA256",
                "BOCA_FAILED_TELEGRAM_RUN_ID",
                "BOCA_OFFICIAL_CONTROLLER_ID",
                "BOCA_OFFICIAL_NEWS_RUN_ID",
                "BOCA_OFFICIAL_NEWS_SOURCE_SHA",
                "BOCA_OFFICIAL_NEWS_ARTIFACT_ID",
                "BOCA_OFFICIAL_NEWS_ZIP_SHA256",
                "BOCA_OFFICIAL_NEWS_JSONL_SHA256",
                "BOCA_OFFICIAL_NEWS_HTML_SHA256",
                "BOCA_OFFICIAL_NEWS_OBSERVED_AT_UTC",
            )
        ],
        ("BOCA_SOURCE_SHA", "b" * 40, 1),
        ("BOCA_HOST_READONLY_ENV_READY", "", 1),
        ("BOCA_DEPLOY_ENV_READY", "", 1),
        ("BOCA_BUDGET", "0.5cpu-256m-64pids", 1),
    ],
)
def test_workflow_dispatch_keeps_default_and_executes_readonly_empty_input_gate(
    field, value, expected
):
    raw = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    dispatch = raw.split("      operation:\n", 1)[1].split("      source_sha:", 1)[0]
    assert "default:" not in dispatch
    assert dispatch.split("options: [", 1)[1].startswith("inspect-prerequisites,")
    assert (
        dispatch.split("options: [", 1)[1].split("]", 1)[0].count("boca-retained-resource-observe")
        == 1
    )
    gate = raw.split("            boca-retained-resource-observe)", 1)[1].split(
        "              ;;", 1
    )[0]
    env = {
        **os.environ,
        "BOCA_HOST_READONLY_ENV_READY": "ready",
        "BOCA_DEPLOY_ENV_READY": "ready",
        "BOCA_SOURCE_SHA": "a" * 40,
        "GITHUB_SHA": "a" * 40,
        "BOCA_BUDGET": "1.5cpu-1024m-192pids",
    }
    import re

    for name in re.findall(r"\$([A-Z_][A-Z_0-9]*)", gate):
        env.setdefault(name, "")
    env[field] = value
    result = subprocess.run(["bash", "-euc", gate], env=env, capture_output=True, check=False)  # noqa: S603 S607
    assert result.returncode == expected
    step = raw.split("if: inputs.operation == 'boca-retained-resource-observe'", 1)[1].split(
        "      - name:", 1
    )[0]
    assert "--retained-observe" in step
    assert "host_boca_retained_resources report" in step
    assert "check_main_ref.py" in step
    assert "boca-target" in step and "docker " not in step
