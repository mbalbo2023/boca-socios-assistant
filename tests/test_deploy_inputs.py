"""A deployment dispatch must carry exact immutable, Boca-only coordinates."""

import runpy
import sys
from pathlib import Path

import pytest

from boca_socios.deploy_inputs import DeployInputError, validate_deploy_inputs

SHA = "a" * 40
IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64
BUDGET = "0.5cpu-256m-64pids"
BROWSER_BUDGET = "1.5cpu-1024m-192pids"
TELEGRAM_BUDGET = "1.75cpu-1152m-224pids"
SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_deploy_inputs.py"


def test_exact_deploy_coordinates_pass() -> None:
    validate_deploy_inputs(IMAGE, SHA, "controller", BUDGET, "123456")


def test_browser_ipc_v2_budget_requires_explicit_opt_in() -> None:
    validate_deploy_inputs(IMAGE, SHA, "controller", BROWSER_BUDGET, "123456", browser_ipc_v2=True)
    with pytest.raises(DeployInputError):
        validate_deploy_inputs(IMAGE, SHA, "controller", BROWSER_BUDGET, "123456")
    with pytest.raises(DeployInputError):
        validate_deploy_inputs(IMAGE, SHA, "controller", BUDGET, "123456", browser_ipc_v2=True)


def test_full3_budget_requires_both_browser_and_sender_opt_in() -> None:
    validate_deploy_inputs(
        IMAGE,
        SHA,
        "controller",
        TELEGRAM_BUDGET,
        "123456",
        browser_ipc_v2=True,
        telegram_runtime=True,
    )
    for browser, sender, budget in (
        (False, True, TELEGRAM_BUDGET),
        (True, False, TELEGRAM_BUDGET),
        (True, True, BROWSER_BUDGET),
        (False, False, TELEGRAM_BUDGET),
    ):
        with pytest.raises(DeployInputError):
            validate_deploy_inputs(
                IMAGE,
                SHA,
                "controller",
                budget,
                "123456",
                browser_ipc_v2=browser,
                telegram_runtime=sender,
            )


@pytest.mark.parametrize(
    ("argv", "expected_rc"),
    [
        ([IMAGE, SHA, "controller", BUDGET, "123456"], 0),
        (["--browser-ipc-v2", IMAGE, SHA, "controller", BROWSER_BUDGET, "123456"], 0),
        (
            [
                "--browser-ipc-v2",
                "--telegram-runtime",
                IMAGE,
                SHA,
                "controller",
                TELEGRAM_BUDGET,
                "123456",
            ],
            0,
        ),
        (
            [
                "--browser-ipc-v2",
                "--telegram-runtime",
                IMAGE,
                SHA,
                "controller",
                BROWSER_BUDGET,
                "123456",
            ],
            1,
        ),
        (["--telegram-runtime", IMAGE, SHA, "controller", TELEGRAM_BUDGET, "123456"], 2),
        (["--browser-ipc-v2", IMAGE, SHA, "controller", BUDGET, "123456"], 1),
        ([IMAGE, SHA, "controller", BROWSER_BUDGET, "123456"], 1),
        (["--browser-ipc-v2", IMAGE, SHA, "worker", BROWSER_BUDGET, "123456"], 1),
        (["--browser-ipc-v2", IMAGE, "bad", "controller", BROWSER_BUDGET, "123456"], 1),
        (["--unknown", IMAGE, SHA, "controller", BROWSER_BUDGET, "123456"], 2),
    ],
)
def test_budget_dispatch_cli_is_phase_explicit_and_rejects_cross_mode(
    argv: list[str], expected_rc: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *argv])
    assert runpy.run_path(str(SCRIPT))["main"]() == expected_rc


@pytest.mark.parametrize(
    ("image", "sha", "service", "budget", "run_id"),
    [
        ("ghcr.io/mbalbo2023/boca-socios-assistant:latest", SHA, "controller", BUDGET, "1"),
        (IMAGE, "bad", "controller", BUDGET, "1"),
        (IMAGE, SHA, "worker", BUDGET, "1"),
        (IMAGE, SHA, "controller", "2cpu-4g", "1"),
        (IMAGE, SHA, "controller", BUDGET, "0"),
        (IMAGE, SHA, "controller", BUDGET, "1; id"),
    ],
)
def test_mutable_or_unsafe_dispatch_fails(
    image: str, sha: str, service: str, budget: str, run_id: str
) -> None:
    with pytest.raises(DeployInputError):
        validate_deploy_inputs(image, sha, service, budget, run_id)
