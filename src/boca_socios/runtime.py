"""Dormant default and explicit, isolated simulation BETA entrypoints."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import sqlite3
import ssl
import stat
import sys
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from threading import Event
from urllib.parse import quote, urlsplit
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer

from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.config import Settings
from boca_socios.integration.bridge_client import SiteBridgeTransport, SiteBridgeWorker
from boca_socios.integration.operational import (
    LocalBetaRuntime,
    LocalRuntimeUnavailable,
    validate_existing_beta_storage,
)
from boca_socios.panel.passkey import PasskeyOwnerAuthentication
from boca_socios.panel.private_http import PrivatePanelApplication
from boca_socios.security.credential_vault import CredentialVault
from boca_socios.storage.database import Database

SIMULATION_EVENT_ID = "00000000-0000-4000-8000-000000000001"
SIMULATION_EVENT_LABEL = "Evento de prueba local"
_OWNER_PERMISSIONS = frozenset(
    {"members:enroll", "members:read", "members:write", "simulation:write", "local-status:read"}
)


class _LocalSyntheticBrowser:
    """A deterministic local result, with no URL, session or credential port."""

    async def simulate_general_reservation(self) -> SimulationOutcome:
        await asyncio.sleep(0)
        return SimulationOutcome.RESERVED_IN_SIMULATOR


def _read_config_file(path: Path | None, *, limit: int, private: bool = False) -> bytes:
    if path is None or not path.is_absolute():
        raise ValueError("private BETA configuration is incomplete")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as source:
            metadata = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid not in {0, os.geteuid()}
                or stat.S_IMODE(metadata.st_mode) & (0o077 if private else 0o022)
            ):
                raise ValueError("private BETA configuration file is unsafe")
            content = source.read(limit + 1)
    except OSError:
        raise ValueError("private BETA configuration file is unavailable") from None
    if not content or len(content) > limit:
        raise ValueError("private BETA configuration file is invalid")
    return content


def _configured_event(path: Path) -> dict[str, str]:
    validate_existing_beta_storage(path)
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as connection:
            connection.execute("PRAGMA query_only = ON")
            row = connection.execute(
                "SELECT label FROM events WHERE event_id=?", (SIMULATION_EVENT_ID,)
            ).fetchone()
    except sqlite3.Error:
        raise ValueError("synthetic event is unavailable") from None
    if row is None or not isinstance(row[0], str) or row[0] != SIMULATION_EVENT_LABEL:
        raise ValueError("synthetic event is unavailable")
    return {SIMULATION_EVENT_ID: SIMULATION_EVENT_LABEL}


class _TLSWSGIServer(WSGIServer):
    def __init__(
        self,
        address: tuple[str, int],
        handler: type[WSGIRequestHandler],
        context: ssl.SSLContext,
    ) -> None:
        self._context = context
        super().__init__(address, handler)
        self.timeout = 0.5

    def get_request(self) -> tuple[socket.socket, tuple[str, int]]:
        connection, address = super().get_request()
        connection.settimeout(5.0)
        try:
            wrapped = self._context.wrap_socket(connection, server_side=True)
        except OSError:
            connection.close()
            raise
        wrapped.settimeout(5.0)
        return wrapped, address


class _QuietTLSHandler(WSGIRequestHandler):
    def get_environ(self) -> dict[str, str]:
        environ = super().get_environ()
        # This is set only for the SSL-wrapped accepted socket, never from a
        # caller-supplied forwarding header.
        environ["HTTPS"] = "on"
        environ["wsgi.url_scheme"] = "https"
        return environ

    def log_message(self, _format: str, *_args: object) -> None:
        # Default BaseHTTPRequestHandler logging includes request URLs.
        return


class ServedBeta:
    """One TLS WSGI server and one local command host, closed together."""

    def __init__(
        self,
        server: _TLSWSGIServer,
        runtime: LocalBetaRuntime,
        bridge: SiteBridgeWorker | None = None,
    ) -> None:
        self.server = server
        self.runtime = runtime
        self.bridge = bridge
        self._closed = False

    def serve_until(self, stopping: Event) -> None:
        try:
            while not stopping.is_set():
                self.server.handle_request()
        finally:
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.server.server_close()
        try:
            if self.bridge is not None:
                self.bridge.close()
        finally:
            self.runtime.close()


def build_beta_server(settings: Settings) -> ServedBeta:
    """Fail closed before opening a listener when identity/TLS is missing."""
    settings.validate_beta()
    bridge_enabled = settings.validate_bridge()
    transport = None
    if bridge_enabled:
        assert settings.site_token_file is not None and settings.site_hmac_key_file is not None
        transport = SiteBridgeTransport(
            origin=settings.site_origin,
            token_file=settings.site_token_file,
            hmac_key_file=settings.site_hmac_key_file,
        )
    credential_id = _read_config_file(settings.passkey_credential_id_file, limit=1024)
    public_key = _read_config_file(settings.passkey_public_key_der_file, limit=4096)
    _read_config_file(settings.tls_key_file, limit=8192, private=True)
    _read_config_file(settings.tls_cert_file, limit=16384)
    origin = urlsplit(settings.panel_origin)
    passkey = PasskeyOwnerAuthentication(
        credential_id=credential_id,
        public_key_der=public_key,
        rp_id=origin.hostname or "",
        origin=settings.panel_origin,
        owner_subject=settings.owner_subject,
        permissions=_OWNER_PERMISSIONS,
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    assert settings.tls_cert_file is not None and settings.tls_key_file is not None
    context.load_cert_chain(str(settings.tls_cert_file), str(settings.tls_key_file))
    events = _configured_event(settings.db_path)
    runtime = LocalBetaRuntime.start(
        database_path=settings.db_path,
        key_file=settings.master_key_file,
        browser=_LocalSyntheticBrowser(),
    )
    bridge: SiteBridgeWorker | None = None
    server: _TLSWSGIServer | None = None
    try:
        if transport is not None:
            bridge = SiteBridgeWorker(
                transport=transport,
                commands=runtime.commands,
                database_path=settings.db_path,
                source_sha=settings.source_sha,
            )
        panel = PrivatePanelApplication(
            origin=settings.panel_origin,
            database_path=settings.db_path,
            owner_subject=settings.owner_subject,
            passkey=passkey,
            members=runtime.members,
            commands=runtime.commands,
            events=events,
        )

        def app(environ: dict[str, object], start: Callable[..., object]) -> list[bytes]:
            if environ.get("PATH_INFO") == "/healthz":
                healthy = (
                    environ.get("REQUEST_METHOD") == "GET"
                    and environ.get("wsgi.url_scheme") == "https"
                    and environ.get("HTTP_HOST") == origin.netloc
                    and not environ.get("QUERY_STRING")
                    and runtime.ready
                    and (bridge is None or not bridge.failed)
                )
                if healthy:
                    try:
                        healthy = _configured_event(settings.db_path) == events
                    except (LocalRuntimeUnavailable, ValueError):
                        healthy = False
                body = b"BOCA_BETA_READY" if healthy else b"BOCA_BETA_UNAVAILABLE"
                start(
                    "200 OK" if healthy else "503 Service Unavailable",
                    [
                        ("Content-Type", "text/plain; charset=utf-8"),
                        ("Content-Length", str(len(body))),
                        ("Cache-Control", "no-store"),
                    ],
                )
                return [body]
            return panel(environ, start)

        server = _TLSWSGIServer((settings.bind_host, settings.bind_port), _QuietTLSHandler, context)
        server.set_app(app)
        if bridge is not None:
            bridge.start()
        return ServedBeta(server, runtime, bridge)
    except Exception:
        if server is not None:
            server.server_close()
        try:
            if bridge is not None:
                bridge.close()
        finally:
            runtime.close()
        raise


def initialize_beta(settings: Settings) -> None:
    settings.validate()
    runtime = LocalBetaRuntime.start(
        database_path=settings.db_path,
        key_file=settings.master_key_file,
        browser=_LocalSyntheticBrowser(),
        initialize_new=True,
    )
    try:
        runtime.database.create_event(SIMULATION_EVENT_ID, SIMULATION_EVENT_LABEL)
    finally:
        runtime.close()


def _dormant() -> int:
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


def main(argv: tuple[str, ...] = ()) -> int:
    if argv in {("check-beta-owner",), ("check-beta-config",)}:
        from boca_socios import beta_config_preflight

        full = argv == ("check-beta-config",)
        label = "beta_config" if full else "beta_owner"
        try:
            settings = Settings.from_environment()
            ca_file = Path(os.environ.get("BOCA_HEALTH_CA_FILE", ""))
            if full:
                beta_config_preflight.check_beta_config(
                    settings, ca_file=ca_file, owner_root=beta_config_preflight.OWNER_ROOT
                )
            else:
                beta_config_preflight.check_beta_owner(
                    settings, ca_file=ca_file, owner_root=beta_config_preflight.OWNER_ROOT
                )
        except Exception:
            # Public workflow receipts never include paths or credential content.
            print(json.dumps({"event": f"{label}_unavailable"}, separators=(",", ":")))
            return 1
        print(
            json.dumps(
                {"event": f"{label}_ready", "mode": "simulation", "engine": "off"},
                separators=(",", ":"),
            )
        )
        return 0
    if argv == ("init-beta",):
        os.umask(0o077)
        initialize_beta(Settings.from_environment())
        return 0
    if argv == ("serve-beta",):
        os.umask(0o077)
        served = build_beta_server(Settings.from_environment())
        stopping = Event()
        signal.signal(signal.SIGINT, lambda _sig, _frame: stopping.set())
        signal.signal(signal.SIGTERM, lambda _sig, _frame: stopping.set())
        print(
            json.dumps({"event": "beta_started", "mode": "simulation", "engine": "off"}), flush=True
        )
        try:
            served.serve_until(stopping)
        finally:
            served.close()
        print(
            json.dumps({"event": "beta_stopped", "mode": "simulation", "engine": "off"}), flush=True
        )
        return 0
    if argv:
        raise ValueError("unsupported Boca entrypoint")
    return _dormant()


if __name__ == "__main__":
    raise SystemExit(main(tuple(sys.argv[1:])))
