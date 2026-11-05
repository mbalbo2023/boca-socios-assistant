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
from functools import partial
from pathlib import Path
from threading import Event
from urllib.parse import quote, urlsplit
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer

from boca_socios.browser.contracts import SimulationOutcome, SyntheticBrowserPort
from boca_socios.config import Settings
from boca_socios.events.official_snapshot import OFFICIAL_SNAPSHOT_NAME, load_official_snapshot
from boca_socios.integration.bridge_client import SiteBridgeTransport, SiteBridgeWorker
from boca_socios.integration.engine_socket import LocalEngineSocket
from boca_socios.integration.operational import (
    LocalBetaRuntime,
    LocalRuntimeUnavailable,
    validate_existing_beta_storage,
)
from boca_socios.owner_origin import SSH_LOOPBACK_ORIGIN
from boca_socios.panel.lifecycle_intents import (
    LifecycleIntentStore,
    LifecycleStorageUnavailable,
)
from boca_socios.panel.owner_session_store import OwnerBrowserSessionStore
from boca_socios.panel.passkey import PasskeyOwnerAuthentication
from boca_socios.panel.private_http import PrivatePanelApplication
from boca_socios.panel.telegram_pairing_staging import (
    STAGING_FILENAME,
    PairingStageReceipt,
    PairingStageRequest,
    stage_private_telegram_pairing,
)
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


def _engine_stopped_after_reboot(database_path: Path, *, browser_backend: str) -> bool:
    """Reconcile the durable owner host receipt before synthetic recovery.

    This applies only to the future opt-in IPC BETA, not the installed
    legacy controller-only backend. An unresolved host operation is NO_GO;
    a confirmed STOP (or non-bot latest receipt whose prior bot state is
    ambiguous) starts an *inert* engine, never a transient replaying thread.
    """
    if browser_backend != "ipc":
        return False
    try:
        state = LifecycleIntentStore(Database(database_path)).current()
    except LifecycleStorageUnavailable:
        raise LocalRuntimeUnavailable("owner lifecycle reconciliation unavailable") from None
    if state is None:
        return False
    if state.status in {"REQUESTED", "CLAIMED", "UNCERTAIN"}:
        raise LocalRuntimeUnavailable("pending owner host operation requires reconciliation")
    # Only the latest unambiguous BOT START authorizes automatic worker
    # recovery. Chromium receipts and REFUSED do not prove bot RUNNING;
    # default to stopped without modifying the SQLite audit log.
    return not (state.component == "bot" and state.target == "start" and state.status == "APPLIED")


def _configured_telegram_pairing_stager(
    settings: Settings, *, boca_volume_root: Path = Path("/data")
) -> Callable[[PairingStageRequest], PairingStageReceipt] | None:
    """Opt in encrypted-only owner handoff inside an *existing* Boca volume.

    The passkey session, origin, CSRF and one-use operation are checked by the
    private panel before calling this pure, single-slot staging callback.
    It cannot authorize a protected host cutover, start a bot or call Telegram.
    """
    settings.validate_beta()
    if settings.telegram_pairing_stage_mode == "off":
        return None
    if (
        settings.telegram_pairing_stage_mode != "encrypted-only"
        or settings.db_path.parent != boca_volume_root
        or not boca_volume_root.is_absolute()
    ):
        raise ValueError("private Telegram staging unavailable")
    directory_fd: int | None = None
    try:
        directory_fd = os.open(
            boca_volume_root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        metadata = os.fstat(directory_fd)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o022
            or not os.access(boca_volume_root, os.W_OK | os.X_OK, effective_ids=True)
        ):
            raise ValueError("private Telegram staging unavailable")
    except OSError:
        raise ValueError("private Telegram staging unavailable") from None
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
    return partial(stage_private_telegram_pairing, boca_volume_root / STAGING_FILENAME)


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


class _LoopbackHTTPWSGIServer(WSGIServer):
    """Plain HTTP only inside Boca; the droplet publishes solely to loopback."""

    def __init__(self, address: tuple[str, int], handler: type[WSGIRequestHandler]) -> None:
        super().__init__(address, handler)
        self.timeout = 0.5

    def get_request(self) -> tuple[socket.socket, tuple[str, int]]:
        connection, address = super().get_request()
        connection.settimeout(5.0)
        return connection, address


class _QuietHTTPHandler(WSGIRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


class ServedBeta:
    """One private WSGI server and one local command host, closed together."""

    def __init__(
        self,
        server: _TLSWSGIServer | _LoopbackHTTPWSGIServer,
        runtime: LocalBetaRuntime,
        bridge: SiteBridgeWorker | None = None,
        engine_socket: LocalEngineSocket | None = None,
        enable_engine_socket: bool = False,
    ) -> None:
        self.server = server
        self.runtime = runtime
        self.bridge = bridge
        self.engine_socket = engine_socket
        self._enable_engine_socket = enable_engine_socket
        self._closed = False

    def serve_until(self, stopping: Event) -> None:
        try:
            # The control socket is strictly in-container and available only
            # for the opt-in IPC BETA. It cannot launch Docker or expose TCP.
            if self._enable_engine_socket and self.engine_socket is None:
                self.engine_socket = LocalEngineSocket(self.runtime.commands)
            if self.engine_socket is not None:
                self.engine_socket.start()
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
            if self.engine_socket is not None:
                self.engine_socket.close()
        finally:
            try:
                if self.bridge is not None:
                    self.bridge.close()
            finally:
                self.runtime.close()


def _browser_for_beta(
    settings: Settings, supplied: SyntheticBrowserPort | None = None
) -> tuple[SyntheticBrowserPort, float]:
    """Select an inert default or explicitly isolated single-flight IPC.

    A requested worker must have the expected UID and positively identified
    AF_UNIX socket *before* the application touches member storage or opens
    an HTTP listener. This metadata gate is not evidence of worker liveness,
    cgroup enforcement or Docker no-egress; protected host acceptance owns
    those independent checks.
    """
    if supplied is not None:
        if settings.browser_backend != "off":
            raise ValueError("ambiguous browser injection")
        return supplied, 5.0
    if settings.browser_backend == "off":
        return _LocalSyntheticBrowser(), 5.0
    if settings.browser_backend != "ipc":
        raise ValueError("invalid synthetic browser backend")

    from boca_socios.browser.ipc_client import UnixSyntheticBrowser
    from boca_socios.browser.ipc_protocol import (
        SOCKET_PATH,
        WORKER_UID,
        SyntheticIPCError,
        socket_identity,
    )

    if os.geteuid() != 10001 or os.getegid() != 10001:
        raise ValueError("synthetic browser worker boundary unavailable")
    try:
        socket_identity(SOCKET_PATH, uid=WORKER_UID)
    except SyntheticIPCError:
        raise ValueError("synthetic browser worker boundary unavailable") from None
    # Allow the existing durable coordinator a finite 30 seconds for the
    # 25-second IPC client budget; never change its five-second default.
    return UnixSyntheticBrowser(), 30.0


def build_beta_server(
    settings: Settings, *, browser: SyntheticBrowserPort | None = None
) -> ServedBeta:
    """Serve only a trusted synthetic browser port, defaulting to inert local work.

    Injection allows an independently confined, one-shot worker to be tested
    against the existing command/DB lifecycle. It is never a public HTTP
    parameter or an implicit host-side Chromium activation.
    """
    settings.validate_beta()
    # Defer the owner receipt until IPC UID/socket and storage preflight,
    # but still before any command thread or recovery can start.
    initial_engine_stopped = partial(
        _engine_stopped_after_reboot,
        settings.db_path,
        browser_backend=settings.browser_backend,
    )
    telegram_pairing_stager = _configured_telegram_pairing_stager(settings)
    selected_browser, command_timeout = _browser_for_beta(settings, browser)
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
    origin = urlsplit(settings.panel_origin)
    passkey = PasskeyOwnerAuthentication(
        credential_id=credential_id,
        public_key_der=public_key,
        rp_id=origin.hostname or "",
        origin=settings.panel_origin,
        owner_subject=settings.owner_subject,
        permissions=_OWNER_PERMISSIONS,
    )
    context: ssl.SSLContext | None = None
    if settings.panel_origin != SSH_LOOPBACK_ORIGIN:
        _read_config_file(settings.tls_key_file, limit=8192, private=True)
        _read_config_file(settings.tls_cert_file, limit=16384)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        assert settings.tls_cert_file is not None and settings.tls_key_file is not None
        context.load_cert_chain(str(settings.tls_cert_file), str(settings.tls_key_file))
    events = _configured_event(settings.db_path)
    runtime = LocalBetaRuntime.start(
        database_path=settings.db_path,
        key_file=settings.master_key_file,
        browser=selected_browser,
        initial_engine_stopped=initial_engine_stopped,
        command_timeout_seconds=command_timeout,
    )
    bridge: SiteBridgeWorker | None = None
    server: _TLSWSGIServer | _LoopbackHTTPWSGIServer | None = None
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
            # The volume-local observation file is optional. On each private
            # GET, only the notices routes read and validate it; a broken
            # external-source snapshot cannot stop the simulation controller.
            official_notices_loader=lambda: load_official_snapshot(
                settings.db_path.with_name(OFFICIAL_SNAPSHOT_NAME)
            ),
            telegram_pairing_stager=telegram_pairing_stager,
        )

        def app(environ: dict[str, object], start: Callable[..., object]) -> list[bytes]:
            if environ.get("PATH_INFO") == "/healthz":
                healthy = (
                    environ.get("REQUEST_METHOD") == "GET"
                    and environ.get("wsgi.url_scheme") == origin.scheme
                    and environ.get("HTTP_HOST") == origin.netloc
                    and not environ.get("QUERY_STRING")
                    and runtime.ready
                    and (bridge is None or not bridge.failed)
                )
                if healthy:
                    try:
                        healthy = (
                            _configured_event(settings.db_path) == events
                            and panel.owner_session_ready()
                        )
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

        if context is None:
            server = _LoopbackHTTPWSGIServer(
                (settings.bind_host, settings.bind_port), _QuietHTTPHandler
            )
        else:
            server = _TLSWSGIServer(
                (settings.bind_host, settings.bind_port), _QuietTLSHandler, context
            )
        server.set_app(app)
        if bridge is not None:
            bridge.start()
        # Keep the existing controller-only deployment and its tests unchanged.
        # The new UDS is installed solely with the separately reviewed IPC
        # cutover candidate, using its private container /tmp namespace.
        return ServedBeta(
            server, runtime, bridge, enable_engine_socket=settings.browser_backend == "ipc"
        )
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
    if settings.browser_backend != "off":
        raise ValueError("synthetic browser must be off during BETA initialization")
    runtime = LocalBetaRuntime.start(
        database_path=settings.db_path,
        key_file=settings.master_key_file,
        browser=_LocalSyntheticBrowser(),
        initialize_new=True,
    )
    try:
        # Initial install may opt into the owner session schema only here.
        # Existing controllers require a separate, protected migration before
        # the new panel version can start; build_beta_server never migrates.
        if settings.owner_subject:
            # A configured, private owner panel requires persistent auth. An
            # ownerless offline storage initializer remains scoped to its
            # synthetic ledgers and cannot fabricate an owner authorization.
            OwnerBrowserSessionStore.migrate_schema(runtime.database)
        runtime.database.create_event(SIMULATION_EVENT_ID, SIMULATION_EVENT_LABEL)
    finally:
        runtime.close()


def _dormant() -> int:
    os.umask(0o077)
    settings = Settings.from_environment()
    settings.validate()
    if settings.browser_backend != "off":
        raise ValueError("synthetic browser requires the served BETA entrypoint")
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
            ca_env = os.environ.get("BOCA_HEALTH_CA_FILE", "")
            ca_file = Path(ca_env) if ca_env else None
            if full:
                beta_config_preflight.check_beta_config(
                    settings, ca_file=ca_file, owner_root=beta_config_preflight.OWNER_ROOT
                )
                # This CLI gate must not claim a complete IPC-enabled BETA
                # configuration when the fixed worker socket is absent.
                if settings.browser_backend == "ipc":
                    _browser_for_beta(settings)
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
