"""Cutover A must expose private Telegram V2 staging only on the IPC controller.

No provider calls, browser navigation, Docker access or host side effects.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boca_socios.deploy_contract import ContractError, validate_beta_contract
from test_beta_browser_deploy_contract import browser_model, valid
from test_beta_deploy_contract import ORIGIN, OWNER, beta_model
from test_deploy_contract import IMAGE

ROOT = Path(__file__).resolve().parents[1]
STAGE_KEY = "BOCA_TELEGRAM_PAIRING_STAGE_MODE"


def test_reviewed_overlay_optin_is_only_on_ipc_controller() -> None:
    base = (ROOT / "compose.beta.yaml").read_text(encoding="utf-8")
    overlay = (ROOT / "compose.beta.browser.yaml").read_text(encoding="utf-8")
    controller, worker = overlay.split("  browser-worker:", maxsplit=1)

    assert STAGE_KEY not in base
    assert 'BOCA_TELEGRAM_PAIRING_STAGE_MODE: "encrypted-only"' in controller
    assert STAGE_KEY not in worker
    assert 'BOCA_BROWSER_BACKEND: ipc' in controller
    assert "BOCA_ENGINE_MODE: \"off\"" in base
    assert "telegram-sender:" not in overlay


def test_browser_contract_accepts_only_explicit_ciphertext_stage_on_controller() -> None:
    candidate = browser_model()
    candidate["services"]["controller"]["environment"][STAGE_KEY] = "encrypted-only"  # type: ignore[index]
    valid(candidate)


@pytest.mark.parametrize(
    "mode",
    [None, "", "off", "enabled", "encrypted", "encrypted-only ", "plaintext"],
)
def test_browser_contract_rejects_unapproved_staging_mode(mode: str | None) -> None:
    candidate = browser_model()
    environment = candidate["services"]["controller"]["environment"]  # type: ignore[index]
    if mode is None:
        environment.pop(STAGE_KEY, None)
    else:
        environment[STAGE_KEY] = mode
    with pytest.raises(ContractError):
        valid(candidate)


def test_browser_contract_rejects_staging_in_worker() -> None:
    candidate = browser_model()
    candidate["services"]["controller"]["environment"][STAGE_KEY] = "encrypted-only"  # type: ignore[index]
    candidate["services"]["browser-worker"]["environment"][STAGE_KEY] = "encrypted-only"  # type: ignore[index]
    with pytest.raises(ContractError):
        valid(candidate)


def test_legacy_controller_cannot_enable_staging() -> None:
    legacy = beta_model()
    validate_beta_contract(legacy, IMAGE, ORIGIN, OWNER)
    legacy["services"]["controller"]["environment"][STAGE_KEY] = "encrypted-only"  # type: ignore[index]
    with pytest.raises(ContractError):
        validate_beta_contract(legacy, IMAGE, ORIGIN, OWNER)


def test_browser_controller_requires_ipc_when_staging_enabled() -> None:
    candidate = browser_model()
    candidate["services"]["controller"]["environment"][STAGE_KEY] = "encrypted-only"  # type: ignore[index]
    candidate["services"]["controller"]["environment"]["BOCA_BROWSER_BACKEND"] = "off"  # type: ignore[index]
    with pytest.raises(ContractError):
        valid(candidate)
