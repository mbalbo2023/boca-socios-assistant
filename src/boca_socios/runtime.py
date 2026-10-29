"""Minimal safe container entrypoint; live-site actions explicitly disabled."""

from __future__ import annotations

import json
import os
import signal
from threading import Event

from boca_socios.config import Settings
from boca_socios.security.credential_vault import CredentialVault
from boca_socios.storage.database import Database


def main() -> int:
    os.umask(0o077)
    settings = Settings.from_environment()
    settings.validate()
    # Fail closed if decryption key is absent or malformed.
    CredentialVault.from_secret_file(settings.master_key_file)
    Database(settings.db_path).migrate()
    stopping = Event()
    signal.signal(signal.SIGINT, lambda _sig, _frame: stopping.set())
    signal.signal(signal.SIGTERM, lambda _sig, _frame: stopping.set())
    print(
        json.dumps({"event": "started", "mode": "simulation", "engine": "off", "site_calls": 0}),
        flush=True,
    )
    while not stopping.wait(timeout=30):
        pass
    print(json.dumps({"event": "stopped", "mode": "simulation", "engine": "off"}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
