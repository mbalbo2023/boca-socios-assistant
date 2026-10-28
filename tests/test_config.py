from pathlib import Path

import pytest

from boca_socios.config import Settings


def test_live_runtime_is_fail_closed() -> None:
    unsafe = Settings("production", "live", Path("/data/boca.db"), Path("/run/secrets/key"))
    with pytest.raises(ValueError, match="not implemented"):
        unsafe.validate()


def test_simulation_is_valid() -> None:
    Settings(
        "development", "simulation", Path("/data/boca.db"), Path("/run/secrets/key")
    ).validate()
