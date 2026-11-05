"""Regression for GO_B runner Compose interpolation without host/Docker I/O."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

_YAML = (Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml").read_text(
    encoding="utf-8"
)
_STEP = "      - name: Validate exact optional dual-service IPC Compose model before SSH\n"
_CONTROLLER = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64
_BROWSER = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "b" * 64


def _runner_prefix() -> str:
    assert _YAML.count(_STEP) == 1
    stage = _YAML.split(_STEP, 1)[1].split("      - name: ", 1)[0]
    assert "docker compose -p boca-socios" in stage
    assert "check_beta_deploy_contract.py" in stage
    run = stage.split("        run: |\n", 1)[1]
    prefix = textwrap.dedent(run).split("docker compose -p boca-socios", 1)[0]
    assert "BOCA_IMAGE_REF" in prefix and "BOCA_BROWSER_IMAGE_REF" in prefix
    assert "ssh " not in prefix
    return prefix + 'printf "image=%s\\nbrowser=%s\\n" "$BOCA_IMAGE" "$BOCA_BROWSER_IMAGE"\n'


def _offline_probe(operation: str, image: str, browser: str) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.defpath,
        "BOCA_OPERATION": operation,
        "BOCA_IMAGE_REF": _CONTROLLER,
        "BOCA_BROWSER_IMAGE_REF": _BROWSER,
        "BOCA_IMAGE": image,
        "BOCA_BROWSER_IMAGE": browser,
    }
    return subprocess.run(
        ["/usr/bin/bash", "-c", _runner_prefix()],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
        env=env,
    )


@pytest.mark.parametrize(
    "operation",
    ["cutover-a-apply", "official-notice-import", "protected-go-prepare", "lifecycle-apply"],
)
def test_blank_go_b_inputs_use_immutable_derived_release_refs(operation: str) -> None:
    result = _offline_probe(operation, "", "")
    assert result.returncode == 0
    assert result.stdout == f"image={_CONTROLLER}\nbrowser={_BROWSER}\n"
    assert result.stderr == ""


@pytest.mark.parametrize("field", ["controller", "browser"])
def test_go_b_explicit_conflicting_input_fails_before_compose(field: str) -> None:
    image = "other" if field == "controller" else ""
    browser = "other" if field == "browser" else ""
    result = _offline_probe("cutover-a-apply", image, browser)
    assert result.returncode != 0
    assert "image=" not in result.stdout and "browser=" not in result.stdout


def test_browser_install_without_required_ref_is_not_silently_upgraded() -> None:
    result = _offline_probe("beta-browser-install", "", "")
    assert result.returncode == 0
    assert result.stdout == "image=\nbrowser=\n"


def test_runner_still_validates_reviewed_compose_model_before_ssh() -> None:
    stage = _YAML.split(_STEP, 1)[1].split("      - name: ", 1)[0]
    assert "docker compose -p boca-socios -f compose.beta.yaml -f compose.beta.browser.yaml config" in stage
    assert 'check_beta_deploy_contract.py "$RUNNER_TEMP/boca-browser-runner-model.json" "$BOCA_IMAGE_REF" --topology=browser-ipc-v2' in stage
