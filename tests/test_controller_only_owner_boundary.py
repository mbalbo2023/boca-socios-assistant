"""Offline proof that controller-only mode does not load owner-controlled code.

The two reserved browser modules are never imported, opened or executed here.
"""

from __future__ import annotations

import subprocess
import sys
from textwrap import dedent


def test_inert_controller_selects_local_adapter_without_owner_modules() -> None:
    # Use a fresh interpreter to keep a previous test import from masking a
    # prohibited import. A finder rejects the two names before source loading.
    # No listener, browser process, Docker or website request is started.
    source = dedent(
        """
        import importlib.abc
        import sys
        from pathlib import Path

        reserved = {
            "boca_socios.browser.synthetic",
            "boca_socios.browser.ipc_worker",
        }

        class OwnerBoundary(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname in reserved:
                    raise AssertionError("owner-controlled browser module import attempted")
                return None

        sys.meta_path.insert(0, OwnerBoundary())
        from boca_socios.config import Settings
        from boca_socios.runtime import _browser_for_beta

        settings = Settings(
            environment="staging",
            runtime_mode="simulation",
            db_path=Path("/data/boca.sqlite3"),
            master_key_file=Path("/run/secrets/boca_master_key"),
            engine_mode="off",
            browser_backend="off",
        )
        settings.validate()
        selected, timeout = _browser_for_beta(settings)
        assert type(selected).__name__ == "_LocalSyntheticBrowser"
        assert timeout == 5.0
        assert not (reserved & sys.modules.keys())
        """
    )
    result = subprocess.run(  # noqa: S603 - isolated local interpreter, constant argv
        [sys.executable, "-c", source],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
