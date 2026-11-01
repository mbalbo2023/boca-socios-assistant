"""Strongly bounded runtime configuration."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from boca_socios.integration.bridge_client import SITE_ORIGIN


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str
    runtime_mode: str
    db_path: Path
    master_key_file: Path
    engine_mode: str = "off"
    panel_origin: str = ""
    owner_subject: str = ""
    passkey_credential_id_file: Path | None = None
    passkey_public_key_der_file: Path | None = None
    tls_cert_file: Path | None = None
    tls_key_file: Path | None = None
    bind_host: str = "127.0.0.1"
    bind_port: int = 8443
    site_bridge_mode: str = "off"
    site_origin: str = ""
    site_token_file: Path | None = None
    site_hmac_key_file: Path | None = None
    source_sha: str = ""

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
            panel_origin=os.environ.get("BOCA_PANEL_ORIGIN", ""),
            owner_subject=os.environ.get("BOCA_OWNER_SUBJECT", ""),
            passkey_credential_id_file=cls._optional_path("BOCA_PASSKEY_CREDENTIAL_ID_FILE"),
            passkey_public_key_der_file=cls._optional_path("BOCA_PASSKEY_PUBLIC_KEY_DER_FILE"),
            tls_cert_file=cls._optional_path("BOCA_TLS_CERT_FILE"),
            tls_key_file=cls._optional_path("BOCA_TLS_KEY_FILE"),
            bind_host=os.environ.get("BOCA_BIND_HOST", "127.0.0.1"),
            bind_port=int(os.environ.get("BOCA_BIND_PORT", "8443")),
            site_bridge_mode=os.environ.get("BOCA_SITE_BRIDGE_MODE", "off"),
            site_origin=os.environ.get("BOCA_SITE_ORIGIN", ""),
            site_token_file=cls._optional_path("BOCA_SITE_TOKEN_FILE"),
            site_hmac_key_file=cls._optional_path("BOCA_SITE_HMAC_KEY_FILE"),
            source_sha=os.environ.get("BOCA_SOURCE_SHA", ""),
        )

    @staticmethod
    def _optional_path(name: str) -> Path | None:
        value = os.environ.get(name)
        return Path(value) if value else None

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

    def validate_beta(self) -> None:
        self.validate()
        origin = urlsplit(self.panel_origin)
        if (
            origin.scheme != "https"
            or not origin.hostname
            or origin.username is not None
            or origin.password is not None
            or origin.path
            or origin.query
            or origin.fragment
            or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.owner_subject) is None
            # 0.0.0.0 is inside Boca's isolated container only; Compose must
            # publish to host loopback and verify the effective HostConfig.
            or self.bind_host not in {"127.0.0.1", "0.0.0.0"}  # noqa: S104
            or type(self.bind_port) is not int
            or not 1024 <= self.bind_port <= 65535
        ):
            raise ValueError("invalid private BETA serving configuration")
        paths = (
            self.passkey_credential_id_file,
            self.passkey_public_key_der_file,
            self.tls_cert_file,
            self.tls_key_file,
        )
        if any(path is None or not path.is_absolute() for path in paths):
            raise ValueError("private BETA credential and TLS paths are required")

    def validate_bridge(self) -> bool:
        """Return opt-in state; malformed partial activation fails closed."""
        if self.site_bridge_mode == "off":
            return False
        if (
            self.site_bridge_mode != "poll"
            or self.site_origin != SITE_ORIGIN
            or self.site_token_file is None
            or not self.site_token_file.is_absolute()
            or self.site_hmac_key_file is None
            or not self.site_hmac_key_file.is_absolute()
            or re.fullmatch(r"[0-9a-f]{40}", self.source_sha) is None
        ):
            raise ValueError("private Site bridge configuration is incomplete")
        return True
