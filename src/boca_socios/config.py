"""Strongly bounded runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str
    runtime_mode: str
    db_path: Path
    master_key_file: Path
    engine_mode: str = "off"

    @classmethod
    def from_environment(cls) -> Settings:
        return cls(
            environment=os.environ.get("BOCA_ENVIRONMENT", "development"),
            runtime_mode=os.environ.get("BOCA_RUNTIME_MODE", "simulation"),
            db_path=Path(os.environ.get("BOCA_DB_PATH", "/data/boca.sqlite3")),
            master_key_file=Path(
                os.environ.get("BOCA_MASTER_KEY_FILE", "/run/secrets/boca_master_key")
            ),
            engine_mode=os.environ.get("BOCA_ENGINE_MODE", "off"),
        )

    def validate(self) -> None:
        if self.environment not in {"development", "staging", "production"}:
            raise ValueError("invalid environment")
        # The foundation intentionally has no connected live runtime.
        if self.runtime_mode != "simulation":
            raise ValueError("live mode is not implemented or authorized")
        if self.engine_mode != "off":
            raise ValueError("engine must remain off; activation is not implemented")
        if not self.db_path.is_absolute() or not self.master_key_file.is_absolute():
            raise ValueError("database and secret paths must be absolute")
