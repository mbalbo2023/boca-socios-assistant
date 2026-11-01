"""Dormant SQLite liveness or explicit local HTTPS BETA readiness."""

from __future__ import annotations

import os
import socket
import sqlite3
import ssl
from pathlib import Path
from urllib.parse import urlsplit

from boca_socios.config import Settings

_BETA_READY = b"BOCA_BETA_READY"


def _beta_health() -> int:
    try:
        settings = Settings.from_environment()
        settings.validate_beta()
        origin = urlsplit(settings.panel_origin)
        ca_file = os.environ.get("BOCA_HEALTH_CA_FILE")
        if ca_file and not Path(ca_file).is_absolute():
            return 1
        context = ssl.create_default_context(cafile=ca_file or None)
        with socket.create_connection(("127.0.0.1", settings.bind_port), timeout=2.0) as raw:
            with context.wrap_socket(raw, server_hostname=origin.hostname) as tls:
                tls.settimeout(2.0)
                tls.sendall(
                    f"GET /healthz HTTP/1.1\r\nHost: {origin.netloc}\r\nConnection: close\r\n\r\n".encode(
                        "ascii"
                    )
                )
                response = bytearray()
                while len(response) <= 2048:
                    chunk = tls.recv(2049 - len(response))
                    if not chunk:
                        break
                    response.extend(chunk)
        header, separator, body = bytes(response).partition(b"\r\n\r\n")
        if (
            separator != b"\r\n\r\n"
            or not header.startswith(b"HTTP/1.0 200 OK\r\n")
            and not header.startswith(b"HTTP/1.1 200 OK\r\n")
            or body != _BETA_READY
        ):
            return 1
        return 0
    except (OSError, ValueError, ssl.SSLError, UnicodeError):
        return 1


def main() -> int:
    health_mode = os.environ.get("BOCA_HEALTH_MODE", "dormant")
    if health_mode == "beta":
        return _beta_health()
    if health_mode != "dormant":
        return 1
    db_path = Path(os.environ.get("BOCA_DB_PATH", "/data/boca.sqlite3"))
    if not db_path.is_file():
        return 1
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0) as conn:
            row = conn.execute("SELECT count(*) FROM schema_migrations").fetchone()
    except sqlite3.Error:
        return 1
    return 0 if row and row[0] >= 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
