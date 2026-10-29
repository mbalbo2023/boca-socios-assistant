from pathlib import Path

import pytest

from boca_socios import runtime
from boca_socios.config import Settings


def test_live_runtime_is_fail_closed() -> None:
    unsafe = Settings("production", "live", Path("/data/boca.db"), Path("/run/secrets/key"))
    with pytest.raises(ValueError, match="not implemented"):
        unsafe.validate()


def test_simulation_is_valid() -> None:
    Settings(
        "development", "simulation", Path("/data/boca.db"), Path("/run/secrets/key")
    ).validate()


def test_engine_defaults_to_off_and_on_fails_before_key_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BOCA_ENGINE_MODE", raising=False)
    assert Settings.from_environment().engine_mode == "off"
    monkeypatch.setenv("BOCA_ENGINE_MODE", "on")
    monkeypatch.setattr(
        runtime.CredentialVault,
        "from_secret_file",
        lambda _path: pytest.fail("key must not be accessed with engine=on"),
    )
    with pytest.raises(ValueError, match="engine"):
        runtime.main()


def test_unknown_engine_mode_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOCA_ENGINE_MODE", "paused")
    with pytest.raises(ValueError, match="engine"):
        Settings.from_environment().validate()
