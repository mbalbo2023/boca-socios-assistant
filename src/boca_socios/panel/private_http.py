"""Same-origin private simulation UI and passkey session boundary.

This WSGI callable is inert until a reviewed private server wires it to a Boca-only
database, passkey public credential and synthetic command host. No real Boca
login, queue admission, reservation or purchase path exists here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from threading import Lock
from typing import Protocol
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID, uuid4

from boca_socios import telegram_bootstrap
from boca_socios.browser.site_url_runtime import (
    RUNTIME_SITE_URL_PATH,
    RuntimeSiteUrlUnavailable,
    SiteUrlInvalid,
    publish_site_url,
    read_site_url,
    require_site_url,
)
from boca_socios.domain.sector_preferences import SectorMode
from boca_socios.events.official_catalog import (
    OfficialCatalogError,
    OfficialNotice,
    build_observed_catalog,
)
from boca_socios.events.official_presentation import export_observed_catalog_json
from boca_socios.notify.projection import list_local_notices
from boca_socios.owner_origin import owner_rp_host
from boca_socios.panel import private_ui, telegram_setup_ui
from boca_socios.panel.enrollment_http import EnrollmentApplication
from boca_socios.panel.lifecycle_intents import (
    LifecycleConflict,
    LifecycleIntentStore,
    LifecycleStorageUnavailable,
)
from boca_socios.panel.local_status import read_local_status
from boca_socios.panel.member_sector_store import (
    MemberSectorStorageUnavailable,
    MemberSectorStore,
)
from boca_socios.panel.members import MemberDirectory
from boca_socios.panel.owner_session_store import (
    OwnerBrowserSessionStore,
    OwnerSessionStorageUnavailable,
)
from boca_socios.panel.owner_sessions import OwnerSession, OwnerSessions
from boca_socios.panel.passkey import PasskeyAssertion, PasskeyOwnerAuthentication
from boca_socios.panel.site_url_settings import (
    SiteUrlSettingsStore,
    SiteUrlSettingsUnavailable,
)
from boca_socios.panel.telegram_pairing_staging import (
    PairingStageConflict,
    PairingStageReceipt,
    PairingStageRequest,
    PairingStageUnavailable,
)
from boca_socios.panel.worker_activity import WorkerActivityUnavailable, read_worker_activity
from boca_socios.queue.private_pass_monitor import PrivateQueuePassMonitor
from boca_socios.security.enrollment import (
    CredentialUnavailable,
    MemberNotFound,
)
from boca_socios.security.member_auth_contract import PrivateBocaAuthMonitor
from boca_socios.storage.database import Database
from boca_socios.telegram_owner_webauthn import (
    TelegramOwnerWitnessError,
    TelegramStageOwnerWitness,
    stage_owner_challenge,
    verify_stage_owner_witness,
)

StartResponse = Callable[[str, list[tuple[str, str]]], object]
_UUID_PATH = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_INTAKE_PAUSED = "owner_simulation_intake_paused"
_INTAKE_RESUMED = "owner_simulation_intake_resumed"
_TOKEN_REVEAL_SCOPE = b"issue12-owner-token-reveal-v1"
_WAKE_LOST = (
    "Solicitud guardada. Abra Control y vuelva a pulsar el mismo botón para reenviar el aviso."
)


class OwnerMemberService(Protocol):
    def enroll(
        self, *, email: str, password: str, consent_recorded_at: datetime, display_name: str = ""
    ) -> str: ...

    def rotate_password(self, member_id: str, new_password: str) -> None: ...

    def revoke_credential(self, member_id: str) -> bool: ...


class LocalCommandHost(Protocol):
    @property
    def failed(self) -> bool: ...

    def begin(self, command_id: str, *, member_id: str, event_id: str) -> object: ...

    def status(self, command_id: str, *, member_id: str) -> object | None: ...

    def stop(self, command_id: str, *, member_id: str) -> object | None: ...


def _response(
    start: StartResponse,
    status: int,
    body: bytes,
    *,
    extra: tuple[str, str] | None = None,
    html: bool = True,
    csp: str = private_ui.CSP,
) -> list[bytes]:
    headers = [
        ("Content-Type", "text/html; charset=utf-8" if html else "application/json"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
        ("Content-Security-Policy", csp),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "no-referrer"),
        ("X-Frame-Options", "DENY"),
    ]
    if extra is not None:
        headers.append(extra)
    start(f"{status} {HTTPStatus(status).phrase}", headers)
    return [body]


def _error(start: StartResponse, status: int, detail: str) -> list[bytes]:
    return _response(start, status, private_ui.message("Panel privado", detail))


def _canonical_uuid(value: object) -> str | None:
    if not isinstance(value, str) or _UUID_PATH.fullmatch(value) is None:
        return None
    try:
        return value if str(UUID(value)) == value and UUID(value).int != 0 else None
    except ValueError:
        return None


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _origin_rejection_category(received: object, expected: str) -> str:
    """Classify one rejected Origin without retaining or reflecting its value.

    This is diagnostic only; the exact same-origin check remains authoritative.
    An adversary controls the supplied header and thus the resulting label.
    """
    if received is None or received == "":
        return "MISSING"
    if (
        not isinstance(received, str)
        or len(received) > 512
        or any(ord(char) < 33 or ord(char) > 126 for char in received)
    ):
        return "MALFORMED"
    try:
        supplied = urlsplit(received)
        configured = urlsplit(expected)
        # Access .port to reject nonnumeric/out-of-range ports, which urlsplit
        # otherwise leaves as an apparently valid authority.
        valid_port = supplied.port is not None or not supplied.netloc.endswith(":")
        if (
            not supplied.scheme
            or not supplied.netloc
            or supplied.path
            or supplied.query
            or supplied.fragment
            or supplied.username is not None
            or supplied.password is not None
            or not valid_port
        ):
            return "MALFORMED"
    except ValueError:
        return "MALFORMED"
    if supplied.scheme != configured.scheme and supplied.netloc == configured.netloc:
        return "SCHEME"
    if supplied.scheme == configured.scheme and supplied.netloc != configured.netloc:
        return "HOST"
    return "UNTRUSTED"


class PrivatePanelApplication:
    """Bounded owner UI, with no listener or implicit storage initialization."""

    def __init__(
        self,
        *,
        origin: str,
        database_path: Path,
        owner_subject: str,
        passkey: PasskeyOwnerAuthentication,
        members: OwnerMemberService,
        commands: LocalCommandHost | None,
        events: Mapping[str, str],
        observed_official_notices: Iterable[OfficialNotice] = (),
        official_notices_loader: Callable[[], Iterable[OfficialNotice]] | None = None,
        telegram_pairing_stager: Callable[[PairingStageRequest], PairingStageReceipt] | None = None,
        bot_control: Callable[[str], None] | None = None,
        queue_monitor: PrivateQueuePassMonitor | None = None,
        auth_monitor: PrivateBocaAuthMonitor | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        parsed = urlsplit(origin)
        if (
            not parsed.netloc
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("an exact private origin is required")
        owner_rp_host(origin)
        if not database_path.is_absolute() or not owner_subject:
            raise ValueError("Boca database and owner must be configured")
        if len(events) > 20 or any(
            _canonical_uuid(key) is None or not 1 <= len(label) <= 100
            for key, label in events.items()
        ):
            raise ValueError("only bounded synthetic event identifiers are allowed")
        self._origin = origin
        self._host = parsed.netloc
        self._database_path = database_path
        self._database = Database(database_path)
        self._site_url_settings = SiteUrlSettingsStore.for_database(database_path)
        self._sector_store = MemberSectorStore.for_database(database_path)
        self._members = members
        self._directory = MemberDirectory(database_path)
        self._commands = commands
        # Within one controller process, order admission vs owner pause. SQLite
        # audit_events is the durable authority: re-read it for each action.
        # A pause never stops HTTP or claims to cancel already admitted work.
        self._intake_lock = Lock()
        self._events = dict(events)
        # Informational-only observations supplied by a trusted caller. Never
        # perform live fetches or turn them into synthetic admission choices.
        self._official_notices = build_observed_catalog(observed_official_notices)
        if official_notices_loader is not None and self._official_notices:
            raise ValueError("only one official-observation source is allowed")
        self._official_notices_loader = official_notices_loader
        if telegram_pairing_stager is not None and not callable(telegram_pairing_stager):
            raise ValueError("Telegram pairing stager must be an explicit local callback")
        self._telegram_pairing_stager = telegram_pairing_stager
        if bot_control is not None and not callable(bot_control):
            raise ValueError("bot control requires a local wake callback")
        self._bot_control = bot_control
        self._queue_monitor = queue_monitor
        self._auth_monitor = auth_monitor
        self._passkey = passkey
        self._owner_browser_store = OwnerBrowserSessionStore(
            self._database, owner_subject=owner_subject
        )
        # The controller must not serve a healthy panel whose passkey login
        # cannot persist: migration 0008 is an explicit installation gate.
        self._owner_browser_store.verify_schema()
        # Only the protected host executor may claim and confirm an intent.
        # The panel can wake it after the durable request transaction commits.
        self._lifecycle = LifecycleIntentStore(self._database)
        self._sessions = OwnerSessions(
            owner_subject=owner_subject,
            verify_owner=passkey.verify,
            persistent_store=self._owner_browser_store,
            authorization_binding=passkey.authorization_binding,
            restore_permissions=passkey.authorized_permissions,
        )
        self._enroll = EnrollmentApplication(members, self._sessions, origin=origin, now=now)
        self._now = now

    def owner_session_ready(self) -> bool:
        """Read-only liveness of the installed independent owner-session ledger.

        This deliberately rechecks on health probes: readiness at controller
        startup alone would miss subsequent filesystem or SQLite corruption.
        It cannot migrate or repair either SQLite file.
        """
        try:
            self._owner_browser_store.verify_schema()
        except OwnerSessionStorageUnavailable:
            return False
        return True

    def __call__(self, environ: Mapping[str, object], start: StartResponse) -> list[bytes]:
        try:
            return self._handle(environ, start)
        except Exception:
            # Never expose provider, credential, SQLite or request diagnostics.
            return _error(
                start, 503, "Servicio local no disponible. Revise antes de repetir una acción."
            )

    def _handle(self, environ: Mapping[str, object], start: StartResponse) -> list[bytes]:
        if (
            environ.get("wsgi.url_scheme") != urlsplit(self._origin).scheme
            or environ.get("HTTP_HOST") != self._host
        ):
            return _error(start, 400, "Se requiere el origen privado seguro.")
        if environ.get("QUERY_STRING", "") or environ.get("HTTP_TRANSFER_ENCODING", ""):
            return _error(start, 400, "Solicitud inválida.")
        path, method = environ.get("PATH_INFO"), environ.get("REQUEST_METHOD")
        if path == "/ingresar" and method == "GET":
            if not self._empty_get(environ):
                return _error(start, 400, "Solicitud inválida.")
            challenge = self._passkey.challenge()
            if challenge is None:
                return _error(start, 429, "Espere antes de solicitar otro ingreso.")
            return _response(start, 200, private_ui.login(challenge, self._passkey.credential_id))
        if path == "/sesion" and method == "POST":
            return self._login(environ, start)
        session = self._sessions.lookup(environ.get("HTTP_COOKIE", ""))
        if session is None:
            return _error(start, 401, "Ingrese con la llave de acceso del dueño.")
        renewed = self._sessions.renew_cookie(environ.get("HTTP_COOKIE", ""), session)
        if renewed is None:
            return _error(start, 401, "La sesión del dueño fue revocada.")
        original_start = start

        def start_with_renewal(status: str, headers: list[tuple[str, str]]) -> object:
            # Logout already clears the same cookie; never override it.
            if not any(name.lower() == "set-cookie" for name, _ in headers):
                headers.append(("Set-Cookie", renewed))
            return original_start(status, headers)

        start = start_with_renewal
        if path == "/socios/nuevo" or (path == "/socios" and method == "POST"):
            return self._enroll(environ, start)
        if path == "/socios" or (isinstance(path, str) and path.startswith("/socios/")):
            if "members:read" not in session.permissions:
                return _error(start, 403, "Permiso insuficiente.")
        if path == "/comandos" or (isinstance(path, str) and path.startswith("/comandos/")):
            if "simulation:write" not in session.permissions:
                return _error(start, 403, "Permiso insuficiente.")
        if path == "/control" or (isinstance(path, str) and path.startswith("/control/")):
            if "simulation:write" not in session.permissions:
                return _error(start, 403, "Permiso insuficiente.")
        if path == "/configuracion" and "simulation:write" not in session.permissions:
            return _error(start, 403, "Permiso insuficiente.")
        if path in ("/monitor/tokens", "/monitor/tokens/revelar") and (
            "local-status:read" not in session.permissions
        ):
            return _error(start, 403, "Permiso insuficiente.")
        if path in ("/estado", "/avisos", "/avisos-oficiales", "/avisos-oficiales.json") and (
            "local-status:read" not in session.permissions
        ):
            return _error(start, 403, "Permiso insuficiente.")
        if method == "GET":
            if not self._empty_get(environ):
                return _error(start, 400, "Solicitud inválida.")
            if path == "/":
                if self._bot_control is not None and "simulation:write" in session.permissions:
                    return self._bot_page(start, session, home=True)
                return _response(start, 200, private_ui.home(session.csrf))
            if path == "/telegram/configurar":
                return _response(start, 200, telegram_setup_ui.page(), csp=telegram_setup_ui.CSP)
            if path == "/configuracion":
                return self._site_url_page(start, session)
            if path == "/monitor/tokens":
                return self._token_monitor_page(start, session)
            if path == "/telegram/emparejar":
                if self._telegram_pairing_stager is not None:
                    operation_id = self._sessions.new_operation(session)
                    if operation_id is None:
                        return _error(start, 429, "Espere antes de abrir otro emparejamiento.")
                    return _response(
                        start,
                        200,
                        telegram_setup_ui.pairing_page(
                            csrf=session.csrf, operation_id=operation_id
                        ),
                        csp=telegram_setup_ui.PAIRING_STAGING_CSP,
                    )
                return _response(
                    start,
                    200,
                    telegram_setup_ui.pairing_page(),
                    csp=telegram_setup_ui.PAIRING_CSP,
                )
            if path == "/socios":
                return _response(start, 200, private_ui.members(self._directory.list_members()))
            if path == "/comandos":
                return self._command_list(start, session)
            if path == "/control":
                if self._bot_control is not None:
                    return self._bot_page(start, session, home=False)
                return self._control_page(start, session)
            if path in ("/control/actividad", "/control/actividad.json"):
                try:
                    activity_snapshot = read_worker_activity(
                        self._database_path, observed_at=self._now()
                    )
                except WorkerActivityUnavailable:
                    if path.endswith(".json"):
                        return _response(
                            start,
                            503,
                            b'{"message":"Actividad local temporalmente no disponible."}',
                            html=False,
                        )
                    return _error(start, 503, "Actividad local temporalmente no disponible.")
                if path.endswith(".json"):
                    return _response(
                        start,
                        200,
                        json.dumps(asdict(activity_snapshot), separators=(",", ":")).encode(
                            "utf-8"
                        ),
                        html=False,
                    )
                return _response(start, 200, private_ui.worker_activity(activity_snapshot))
            if path == "/estado":
                snapshot = read_local_status(self._database_path, observed_at=self._now())
                data = asdict(snapshot)
                data["observed_at"] = snapshot.observed_at.isoformat()
                return _response(start, 200, private_ui.status(data))
            if path == "/avisos":
                return _response(
                    start, 200, private_ui.notices(list_local_notices(self._database, limit=20))
                )
            if path == "/avisos-oficiales":
                try:
                    notices = self._current_official_notices()
                except OfficialCatalogError:
                    return _error(
                        start,
                        503,
                        "Avisos oficiales no disponibles. La simulación local sigue operativa.",
                    )
                return _response(
                    start,
                    200,
                    private_ui.official_events(notices, at=self._now()),
                )
            if path == "/avisos-oficiales.json":
                try:
                    notices = self._current_official_notices()
                except OfficialCatalogError:
                    return _response(
                        start,
                        503,
                        b'{"source_mode":"OFFLINE_PREOBSERVED_ONLY","source_health":"UNAVAILABLE",'
                        b'"events":[],"actionable":false,"availability_verified":false,'
                        b'"live_feed":false}',
                        html=False,
                    )
                document = export_observed_catalog_json(notices, at=self._now())
                return _response(start, 200, document.encode("utf-8"), html=False)
            if isinstance(path, str) and path.startswith("/socios/"):
                return self._member_detail(path.removeprefix("/socios/"), session, start)
            if isinstance(path, str) and path.startswith("/comandos/"):
                return self._command_detail(path.removeprefix("/comandos/"), session, start)
            return _error(start, 404, "Ruta no disponible.")
        if method != "POST":
            return _error(start, 405, "Método no permitido.")
        if environ.get("HTTP_ORIGIN") != self._origin:
            if path == "/control/bot/iniciar":
                category = _origin_rejection_category(environ.get("HTTP_ORIGIN"), self._origin)
                return _error(
                    start,
                    403,
                    "Origen no autorizado. Código: BOCA_ORIGIN_DIAG_"
                    + category
                    + ". No se ejecutó la orden.",
                )
            return _error(start, 403, "Origen no autorizado.")
        if path == "/salir":
            fields = self._form(environ, expected={"csrf"})
            if fields is None or not hmac.compare_digest(fields["csrf"], session.csrf):
                return _error(start, 403, "Solicitud no autorizada.")
            self._sessions.revoke(environ.get("HTTP_COOKIE", ""))
            return _response(
                start,
                200,
                private_ui.message("Sesión cerrada", "La sesión fue cerrada."),
                extra=(
                    "Set-Cookie",
                    "__Host-boca_session=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0",
                ),
            )
        if self._telegram_pairing_stager is not None:
            if path == "/telegram/emparejar/desafio":
                return self._challenge_private_telegram_pairing(environ, session, start)
            if path == "/telegram/emparejar":
                return self._stage_private_telegram_pairing(environ, session, start)
        if path == "/comandos":
            return self._begin(environ, session, start)
        if path == "/configuracion":
            return self._save_site_url(environ, session, start)
        if path == "/monitor/tokens/revelar":
            if "simulation:write" not in session.permissions:
                return _error(start, 403, "Permiso insuficiente.")
            return self._reveal_observed_token(environ, session, start)
        if path in ("/control/reanudar", "/control/pausar"):
            if self._bot_control is not None:
                return _error(start, 404, "Ruta no disponible.")
            return self._set_intake(environ, path.rsplit("/", 1)[-1], session, start)
        if isinstance(path, str) and re.fullmatch(
            r"/control/(bot|chromium)/(iniciar|detener)", path
        ):
            _prefix, _control, component, label = path.split("/")
            return self._request_lifecycle(
                environ, component, "start" if label == "iniciar" else "stop", session, start
            )
        if isinstance(path, str) and path.startswith("/comandos/") and path.endswith("/detener"):
            command_id = path.removeprefix("/comandos/").removesuffix("/detener")
            return self._stop(environ, command_id, session, start)
        if isinstance(path, str) and path.startswith("/socios/"):
            if "members:write" not in session.permissions:
                return _error(start, 403, "Permiso insuficiente.")
            if re.fullmatch(r"/socios/[0-9a-f-]{36}/sectores", path):
                return self._save_member_sectors(environ, path, session, start)
            return self._credential_action(environ, path, session, start)
        return _error(start, 404, "Ruta no disponible.")

    def _token_monitor_page(self, start: StartResponse, session: OwnerSession) -> list[bytes]:
        queue = (
            self._queue_monitor.list_summaries(at=self._now())
            if self._queue_monitor is not None
            else ()
        )
        auth = self._auth_monitor.list_summaries() if self._auth_monitor is not None else ()
        can_reveal = "simulation:write" in session.permissions
        operation_id = (
            self._sessions.new_operation(session, form_scope=_TOKEN_REVEAL_SCOPE)
            if can_reveal and (queue or auth)
            else None
        )
        if can_reveal and (queue or auth) and operation_id is None:
            return _error(start, 429, "Espere antes de revelar otra observación privada.")
        return _response(
            start,
            200,
            private_ui.token_monitor(
                queue,
                auth,
                csrf=session.csrf,
                operation_id=operation_id,
                can_reveal=can_reveal,
            ),
        )

    def _reveal_observed_token(
        self, environ: Mapping[str, object], session: OwnerSession, start: StartResponse
    ) -> list[bytes]:
        fields = self._form(
            environ,
            expected={"csrf", "operation_id", "kind", "member_id", "event_id", "session_id"},
        )
        if (
            fields is None
            or _canonical_uuid(fields["operation_id"]) is None
            or _canonical_uuid(fields["member_id"]) is None
            or fields["kind"] not in ("queue", "boca")
            or (
                fields["kind"] == "queue"
                and (
                    _canonical_uuid(fields["event_id"]) is None
                    or _canonical_uuid(fields["session_id"]) is None
                )
            )
            or (fields["kind"] == "boca" and (fields["event_id"] or fields["session_id"]))
        ):
            return _error(start, 400, "Solicitud de revelación inválida.")
        # The page intentionally offers either observed flow with one shared
        # owner-initiated reveal. A fixed form scope lets repeated GETs reuse
        # their unused nonce instead of exhausting the 16-operation budget;
        # reserve() still enforces the session, CSRF, Origin, one-use state and
        # the existing 1-second protected-action throttle.
        replay, operation = self._sessions.reserve(
            session, fields["operation_id"], fields["csrf"], _TOKEN_REVEAL_SCOPE
        )
        if replay:
            # Unlike an idempotent durable write, re-revealing a bearer secret
            # by replay never returns the old successful response.
            return _error(
                start, 409 if replay == 200 else replay, "Revelación ya usada o denegada."
            )
        assert operation is not None
        body: bytes | None = None
        if fields["kind"] == "queue" and self._queue_monitor is not None:
            details = self._queue_monitor.owner_details(
                fields["member_id"],
                fields["event_id"],
                fields["session_id"],
                at=self._now(),
                owner_authenticated=True,
            )
            if details is not None:
                try:
                    token = details.copy_full_token()
                except ValueError:
                    body = None
                else:
                    try:
                        target_url = details.copy_full_target_url()
                    except ValueError:
                        target_url = None
                    body = private_ui.queue_token_reveal(token, target_url)
        if fields["kind"] == "boca" and self._auth_monitor is not None:
            received = self._auth_monitor.owner_details(
                fields["member_id"], owner_authenticated=True
            )
            if received is not None:
                body = private_ui.boca_token_reveal(
                    received.copy_full_token(), received.copy_full_refresh_token()
                )
        self._sessions.finish(operation, 200 if body is not None else 404)
        if body is None:
            return _error(start, 404, "Observación privada no disponible.")
        return _response(start, 200, body)

    def _site_url_page(self, start: StartResponse, session: OwnerSession) -> list[bytes]:
        operation_id = self._sessions.new_operation(session)
        if operation_id is None:
            return _error(start, 429, "Espere antes de cambiar la configuración.")
        try:
            configured = self._site_url_settings.read()
        except SiteUrlSettingsUnavailable:
            return _error(start, 503, "Configuración privada no verificable.")
        return _response(
            start,
            200,
            private_ui.site_url_configuration(session.csrf, operation_id, configured),
        )

    def _save_site_url(
        self, environ: Mapping[str, object], session: OwnerSession, start: StartResponse
    ) -> list[bytes]:
        fields = self._form(environ, expected={"csrf", "operation_id", "SITE_URL"})
        if fields is None or _canonical_uuid(fields["operation_id"]) is None:
            return _error(start, 400, "Configuración inválida.")
        try:
            destination = require_site_url(fields["SITE_URL"])
        except SiteUrlInvalid:
            return _error(
                start, 400, "SITE_URL debe ser una URL HTTP(S) válida y sin credenciales."
            )
        result, operation = self._sessions.reserve(
            session,
            fields["operation_id"],
            fields["csrf"],
            b"site-url-update-v1:" + destination.encode("utf-8"),
        )
        if result:
            if result == 303:
                return self._redirect(start, "/configuracion")
            return _error(start, result, "Configuración ya procesada o no autorizada.")
        assert operation is not None
        try:
            self._site_url_settings.save(destination)
            # Keep the private source of truth, then atomically publish the
            # URL-only read boundary for the cold, unprivileged browser worker.
            # No worker process is started by configuration changes.
            publish_site_url(RUNTIME_SITE_URL_PATH, destination)
        except (SiteUrlSettingsUnavailable, RuntimeSiteUrlUnavailable):
            self._sessions.finish(operation, 503)
            return _error(start, 503, "Configuración privada del bot no verificable.")
        self._sessions.finish(operation, 303)
        return self._redirect(start, "/configuracion")

    def _challenge_private_telegram_pairing(
        self, environ: Mapping[str, object], session: OwnerSession, start: StartResponse
    ) -> list[bytes]:
        """Server-issued one-use, ciphertext-bound WebAuthn UV challenge."""
        fields = self._form(environ, expected={"csrf", "operation_id", "envelope_sha256"})
        if (
            fields is None
            or _canonical_uuid(fields["operation_id"]) is None
            or not hmac.compare_digest(fields["csrf"], session.csrf)
            or fields["operation_id"] not in session.operations
            or session.operations[fields["operation_id"]].fingerprint is not None
        ):
            return _error(start, 403, "Emparejamiento privado no autorizado.")
        request_nonce = secrets.token_hex(32)
        challenged_at = int(self._now().timestamp())
        try:
            challenge = stage_owner_challenge(
                envelope_sha256=fields["envelope_sha256"],
                operation_id=fields["operation_id"],
                request_nonce=request_nonce,
                challenged_at=challenged_at,
                verifier_binding=self._passkey.authorization_binding.hex(),
            )
        except TelegramOwnerWitnessError:
            return _error(start, 422, "Sobre cifrado V2 inválido.")
        if not self._passkey.issue_telegram_stage_challenge(challenge):
            return _error(start, 429, "Espere antes de solicitar otra firma.")
        result = {
            "version": 1,
            "challenge": telegram_bootstrap._b64(challenge),
            "request_nonce": request_nonce,
            "challenged_at": challenged_at,
            "credential_id": self._passkey.credential_id,
            "rp_id": owner_rp_host(self._origin),
        }
        return _response(
            start, 200, json.dumps(result, separators=(",", ":")).encode("ascii"), html=False
        )

    def _stage_private_telegram_pairing(
        self, environ: Mapping[str, object], session: OwnerSession, start: StartResponse
    ) -> list[bytes]:
        """Persist ciphertext + REAL fresh owner UV proof, never activate a bot."""
        fields = self._form(
            environ,
            expected={
                "csrf",
                "operation_id",
                "envelope",
                "request_nonce",
                "challenged_at",
                "credential_id",
                "client_data_json",
                "authenticator_data",
                "signature",
            },
        )
        if fields is None or _canonical_uuid(fields["operation_id"]) is None:
            return _error(start, 400, "Solicitud privada inválida.")
        try:
            envelope = telegram_bootstrap._unb64(
                fields["envelope"], maximum=telegram_bootstrap.MAX_ENVELOPE
            )
        except telegram_bootstrap.BootstrapError:
            return _error(start, 422, "Sobre cifrado V2 inválido.")
        if not envelope:
            return _error(start, 422, "Sobre cifrado V2 inválido.")
        status, operation = self._sessions.reserve(
            session,
            fields["operation_id"],
            fields["csrf"],
            b"telegram-v2-stage-webAuthn:\0" + envelope,
        )
        if status:
            return _error(
                start, 409 if status == 202 else status, "Solicitud ya procesada o inválida."
            )
        assert operation is not None and self._telegram_pairing_stager is not None
        try:
            witness = TelegramStageOwnerWitness(
                operation_id=fields["operation_id"],
                request_nonce=fields["request_nonce"],
                challenged_at=int(fields["challenged_at"]),
                verifier_binding=self._passkey.authorization_binding.hex(),
                assertion=PasskeyAssertion(
                    fields["credential_id"],
                    fields["client_data_json"],
                    fields["authenticator_data"],
                    fields["signature"],
                ),
            )
            challenge = stage_owner_challenge(
                envelope_sha256=hashlib.sha256(envelope).hexdigest(),
                operation_id=witness.operation_id,
                request_nonce=witness.request_nonce,
                challenged_at=witness.challenged_at,
                verifier_binding=witness.verifier_binding,
            )
            now = int(self._now().timestamp())
            if (
                not 0 <= now - witness.challenged_at <= 120
                or self._passkey.verify_telegram_stage_assertion(witness.assertion, challenge)
                is None
                or not verify_stage_owner_witness(witness, envelope, self._passkey, staged_at=now)
            ):
                raise TelegramOwnerWitnessError("telegram_owner_webauthn_unverified")
        except (TelegramOwnerWitnessError, ValueError, TypeError):
            self._sessions.finish(operation, 403)
            return _error(start, 403, "La firma reciente de la llave no se verificó.")
        try:
            receipt = self._telegram_pairing_stager(
                PairingStageRequest(sealed_envelope=envelope, owner_witness=witness)
            )
            if type(receipt) is not PairingStageReceipt or (
                receipt.state != "STAGED_PENDING_PROTECTED_CUTOVER"
            ):
                raise PairingStageUnavailable("pairing_stage_unavailable")
        except PairingStageConflict:
            self._sessions.finish(operation, 409)
            return _error(start, 409, "Ya existe un emparejamiento pendiente de verificar.")
        except Exception:
            # Callback errors may embed token, host path or ciphertext.
            self._sessions.finish(operation, 503)
            return _error(start, 503, "No se confirmó el resguardo cifrado. Consulte el estado.")
        self._sessions.finish(operation, 202)
        return _response(
            start,
            202,
            b'{"state":"STAGED_PENDING_PROTECTED_CUTOVER","telegram_connected":false,'
            b'"sender":"OFF","notification_receipt":"UNVERIFIED",'
            b'"owner_passkey":"UV_VERIFIED_ONLY"}',
            html=False,
        )

    def _current_official_notices(self) -> tuple[OfficialNotice, ...]:
        if self._official_notices_loader is None:
            return self._official_notices
        # Refresh on each authenticated GET so an offline Boca-only snapshot
        # can be replaced without restarting the owner session or controller.
        return build_observed_catalog(self._official_notices_loader())

    def _empty_get(self, environ: Mapping[str, object]) -> bool:
        return environ.get("CONTENT_LENGTH", "") in ("", "0") and environ.get(
            "HTTP_ORIGIN", ""
        ) in ("", self._origin)

    def _form(self, environ: Mapping[str, object], *, expected: set[str]) -> dict[str, str] | None:
        length = environ.get("CONTENT_LENGTH")
        if (
            not isinstance(length, str)
            or re.fullmatch(r"[0-9]{1,5}", length) is None
            or not 0 < int(length) <= 8192
            or environ.get("CONTENT_TYPE") != "application/x-www-form-urlencoded"
        ):
            return None
        stream = environ.get("wsgi.input")
        read = getattr(stream, "read", None)
        if not callable(read):
            return None
        body = read(int(length))
        if not isinstance(body, bytes) or len(body) != int(length):
            return None
        try:
            pairs = parse_qsl(
                body.decode("utf-8"),
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=len(expected),
                errors="strict",
            )
        except (ValueError, UnicodeError):
            return None
        fields = dict(pairs)
        return fields if len(fields) == len(pairs) and set(fields) == expected else None

    def _login(self, environ: Mapping[str, object], start: StartResponse) -> list[bytes]:
        if (
            environ.get("HTTP_ORIGIN") != self._origin
            or environ.get("CONTENT_TYPE") != "application/json"
        ):
            return _error(start, 403, "Ingreso no autorizado.")
        length = environ.get("CONTENT_LENGTH")
        if not isinstance(length, str) or not length.isdigit() or not 0 < int(length) <= 12000:
            return _error(start, 400, "Ingreso inválido.")
        read = getattr(environ.get("wsgi.input"), "read", None)
        if not callable(read):
            return _error(start, 400, "Ingreso inválido.")
        body = read(int(length))
        try:
            if not isinstance(body, bytes) or len(body) != int(length):
                raise ValueError("invalid assertion length")
            data = json.loads(body, object_pairs_hook=_unique_pairs)
            if (
                not isinstance(data, dict)
                or set(data)
                != {"credential_id", "client_data_json", "authenticator_data", "signature"}
                or any(not isinstance(value, str) for value in data.values())
            ):
                raise ValueError("invalid assertion")
            proof = PasskeyAssertion(**data)
        except (ValueError, TypeError, UnicodeError):
            return _error(start, 400, "Ingreso inválido.")
        cookie = self._sessions.authenticate(proof)
        if cookie is None:
            return _error(start, 401, "La llave de acceso no se verificó.")
        return _response(start, 204, b"", extra=("Set-Cookie", cookie))

    def _member_detail(
        self, member_id: str, session: OwnerSession, start: StartResponse
    ) -> list[bytes]:
        if _canonical_uuid(member_id) is None:
            return _error(start, 404, "Socio no encontrado.")
        item = next(
            (item for item in self._directory.list_members() if item.member_id == member_id), None
        )
        if item is None:
            return _error(start, 404, "Socio no encontrado.")
        rotate_id = self._sessions.new_operation(session)
        revoke_id = self._sessions.new_operation(session)
        if rotate_id is None or revoke_id is None:
            return _error(start, 429, "Demasiados formularios abiertos. Vuelva a ingresar.")
        try:
            defaults = self._sector_store.load(member_id)
        except MemberSectorStorageUnavailable:
            return _error(start, 503, "Las preferencias locales del socio no son verificables.")
        return _response(
            start,
            200,
            private_ui.member_detail(
                item,
                session.csrf,
                rotate_id,
                revoke_id,
                revoke_id,  # Reuse the existing one-time nonce; owner refreshes after POST.
                defaults,
                sector_storage_ready=self._sector_store.path.exists(),
            ),
        )

    def _save_member_sectors(
        self, environ: Mapping[str, object], path: str, session: OwnerSession, start: StartResponse
    ) -> list[bytes]:
        match = re.fullmatch(r"/socios/([0-9a-f-]{36})/sectores", path)
        if match is None or _canonical_uuid(match.group(1)) is None:
            return _error(start, 404, "Socio no encontrado.")
        member_id = match.group(1)
        fields = self._form(environ, expected={"csrf", "operation_id", "mode", "sector_ids"})
        if fields is None or _canonical_uuid(fields["operation_id"]) is None:
            return _error(start, 400, "Formulario de sectores inválido.")
        try:
            mode = SectorMode(fields["mode"])
            raw = fields["sector_ids"]
            if len(raw) > 2000:
                raise ValueError("too many characters")
            sectors = (
                () if mode is SectorMode.ALL else tuple(item.strip() for item in raw.split(","))
            )
        except ValueError:
            return _error(start, 422, "Selección de sectores inválida.")
        fingerprint = (path + "\0" + json.dumps(fields, sort_keys=True)).encode()
        replay, operation = self._sessions.reserve(
            session, fields["operation_id"], fields["csrf"], fingerprint
        )
        if replay:
            if replay == 200 and operation is not None:
                return self._redirect(start, f"/socios/{member_id}")
            return _error(start, replay, "Operación ya utilizada o no autorizada.")
        assert operation is not None
        try:
            self._sector_store.save(member_id, mode, sectors, self._now())
        except ValueError:
            self._sessions.finish(operation, 422)
            return _error(start, 422, "Prioridades inválidas o duplicadas.")
        except LookupError:
            self._sessions.finish(operation, 404)
            return _error(start, 404, "Socio no encontrado.")
        except MemberSectorStorageUnavailable:
            self._sessions.finish(operation, 503)
            return _error(start, 503, "Preferencias locales no disponibles.")
        self._sessions.finish(operation, 200)
        return self._redirect(start, f"/socios/{member_id}")

    def _credential_action(
        self, environ: Mapping[str, object], path: str, session: OwnerSession, start: StartResponse
    ) -> list[bytes]:
        match = re.fullmatch(r"/socios/([0-9a-f-]{36})/(credencial|revocar)", path)
        if match is None or _canonical_uuid(match.group(1)) is None:
            return _error(start, 404, "Acción no disponible.")
        member_id, action = match.groups()
        expected = (
            {"csrf", "operation_id", "password"}
            if action == "credencial"
            else {"csrf", "operation_id"}
        )
        fields = self._form(environ, expected=expected)
        if fields is None or _canonical_uuid(fields["operation_id"]) is None:
            return _error(start, 400, "Formulario inválido.")
        if action == "credencial" and not 0 < len(fields["password"].encode()) <= 4096:
            return _error(start, 422, "Contraseña inválida.")
        fingerprint = (path + "\0" + json.dumps(fields, sort_keys=True)).encode()
        result, operation = self._sessions.reserve(
            session, fields["operation_id"], fields["csrf"], fingerprint
        )
        if result:
            if result == 200 and operation is not None:
                return self._redirect(start, f"/socios/{member_id}")
            return _error(start, result, "Acción ya procesada o no autorizada. Consulte el socio.")
        assert operation is not None
        try:
            if action == "credencial":
                self._members.rotate_password(member_id, fields["password"])
            else:
                self._members.revoke_credential(member_id)
        except (MemberNotFound, CredentialUnavailable):
            self._sessions.finish(operation, 409)
            return _error(start, 409, "El socio o su credencial ya no está disponible.")
        except Exception:
            self._sessions.finish(operation, 503)
            return _error(
                start, 503, "No se confirmó la acción. Consulte el estado antes de repetir."
            )
        self._sessions.finish(operation, 200)
        return self._redirect(start, f"/socios/{member_id}")

    def _command_list(self, start: StartResponse, session: OwnerSession) -> list[bytes]:
        operation_id = self._sessions.new_operation(session)
        if operation_id is None:
            return _error(start, 429, "Demasiados formularios abiertos. Vuelva a ingresar.")
        return _response(
            start,
            200,
            private_ui.commands(
                self._directory.list_commands(),
                self._directory.list_members(),
                self._events,
                session.csrf,
                operation_id,
            ),
        )

    def _bot_page(self, start: StartResponse, session: OwnerSession, *, home: bool) -> list[bytes]:
        try:
            lifecycle = self._lifecycle.current()
        except LifecycleStorageUnavailable:
            status, reason = 503, "Estado de solicitudes al host no disponible."
        else:
            start_id = self._sessions.new_operation(
                session, form_scope=b"owner-lifecycle-v1:bot:start"
            )
            stop_id = self._sessions.new_operation(
                session, form_scope=b"owner-lifecycle-v1:bot:stop"
            )
            if start_id is not None and stop_id is not None:
                site_url_ready = self._site_url_ready()
                if home:
                    body = private_ui.home(
                        session.csrf,
                        bot=(lifecycle, start_id, stop_id),
                        site_url_ready=site_url_ready,
                    )
                else:
                    body = private_ui.bot_control(
                        lifecycle,
                        session.csrf,
                        start_id,
                        stop_id,
                        site_url_ready=site_url_ready,
                    )
                return _response(start, 200, body)
            status, reason = 429, "Demasiados formularios abiertos. Vuelva a ingresar."
        if home:
            return _response(start, 200, private_ui.home(session.csrf, bot_unavailable=True))
        return _error(start, status, reason)

    def _site_url_ready(self) -> bool:
        """Use the exact START precondition for an advisory panel state.

        A matching controller file and URL-only worker mirror permit a request;
        they never certify that a worker is running or using this destination.
        """
        try:
            configured = self._site_url_settings.read()
            return configured is not None and read_site_url(RUNTIME_SITE_URL_PATH) == configured
        except (SiteUrlSettingsUnavailable, RuntimeSiteUrlUnavailable):
            return False

    def _control_page(self, start: StartResponse, session: OwnerSession) -> list[bytes]:
        operation_id = self._sessions.new_operation(session)
        if operation_id is None:
            return _error(start, 429, "Demasiados formularios abiertos. Vuelva a ingresar.")
        with self._intake_lock:
            accepting = self._read_intake()
            ready = self._commands is not None and not self._commands.failed
        if accepting is None:
            return _error(start, 503, "Estado de admisión no disponible. No inicie simulaciones.")
        try:
            lifecycle = self._lifecycle.current()
        except LifecycleStorageUnavailable:
            return _error(start, 503, "Estado de solicitudes al host no disponible.")
        return _response(
            start,
            200,
            private_ui.global_simulation_control(
                accepting, ready, session.csrf, operation_id, lifecycle=lifecycle
            ),
        )

    def _request_lifecycle(
        self,
        environ: Mapping[str, object],
        component: str,
        target: str,
        session: OwnerSession,
        start: StartResponse,
    ) -> list[bytes]:
        """Authenticate the form, commit the intent, then optionally wake its executor."""
        if self._bot_control is not None and component != "bot":
            return _error(start, 404, "Ruta no disponible.")
        fields = self._form(environ, expected={"csrf", "operation_id"})
        if fields is None or _canonical_uuid(fields["operation_id"]) is None:
            return _error(start, 400, "Solicitud de ciclo inválida.")
        fingerprint = f"owner-lifecycle-v1:{component}:{target}".encode("ascii")
        result, operation = self._sessions.reserve(
            session,
            fields["operation_id"],
            fields["csrf"],
            fingerprint,
            pending_start=self._start_pending
            if self._bot_control is not None and target == "stop"
            else None,
        )
        if result:
            if result == 303:
                return self._redirect(start, "/control")
            if result == 503 and operation is not None and operation.lifecycle_id is not None:
                return _error(start, 503, _WAKE_LOST)
            return _error(start, result, "Solicitud ya procesada o no autorizada.")
        assert operation is not None
        if self._bot_control is not None and component == "bot" and target == "start":
            # Two separate volumes cannot be committed in one filesystem
            # transaction. If a prior save succeeded but the URL-only mirror
            # publication failed, do not request a START using the old URL.
            # Also refuse an unconfigured first START before waking the host.
            if not self._site_url_ready():
                self._sessions.finish(operation, 503)
                return _error(start, 503, "URL del worker no verificable. Revise Configuración.")
        try:
            if operation.lifecycle_id is not None:
                intent = self._lifecycle.current()
                if intent is None or intent.operation_id != operation.lifecycle_id:
                    self._sessions.finish(operation, 303)
                    return self._redirect(start, "/control")
            else:
                intent = self._lifecycle.request(
                    component,
                    target,
                    fields["operation_id"],
                    on_demand=self._bot_control is not None,
                )
        except LifecycleConflict:
            self._sessions.finish(operation, 409)
            return _error(
                start,
                409,
                "Ya existe una solicitud al host sin cierre confirmado. Consulte Control.",
            )
        except LifecycleStorageUnavailable:
            self._sessions.finish(operation, 503, lifecycle_id=operation.lifecycle_id)
            return _error(start, 503, "Resultado incierto. Consulte Control antes de repetir.")
        if self._bot_control is not None and intent.status == "REQUESTED":
            try:
                self._bot_control(intent.operation_id)
            except Exception:
                self._sessions.finish(operation, 503, lifecycle_id=intent.operation_id)
                return _error(start, 503, _WAKE_LOST)
        self._sessions.finish(operation, 303)
        return self._redirect(start, "/control")

    def _start_pending(self) -> bool:
        intent = self._lifecycle.current()
        return (
            intent is not None
            and intent.on_demand
            and intent.component == "bot"
            and intent.target == "start"
            and intent.status in ("REQUESTED", "CLAIMED")
        )

    def _set_intake(
        self,
        environ: Mapping[str, object],
        action: str,
        session: OwnerSession,
        start: StartResponse,
    ) -> list[bytes]:
        fields = self._form(environ, expected={"csrf", "operation_id"})
        if fields is None or _canonical_uuid(fields["operation_id"]) is None:
            return _error(start, 400, "Control inválido.")
        fingerprint = f"global-simulation-intake:{action}".encode("ascii")
        result, operation = self._sessions.reserve(
            session, fields["operation_id"], fields["csrf"], fingerprint
        )
        if result:
            if result == 303:
                return self._redirect(start, "/control")
            return _error(start, result, "Control ya procesado o no autorizado. Consulte estado.")
        assert operation is not None
        try:
            with self._intake_lock:
                if action == "reanudar":
                    if self._commands is None or self._commands.failed:
                        raise RuntimeError("local command host unavailable")
                self._write_intake(accepting=action == "reanudar")
        except Exception:
            self._sessions.finish(operation, 503)
            return _error(start, 503, "Control incierto. Consulte el estado antes de repetir.")
        self._sessions.finish(operation, 303)
        return self._redirect(start, "/control")

    def _read_intake(self) -> bool | None:
        """Read the latest owner admission decision; missing ledger fails closed."""
        if self._bot_control is not None:
            try:
                intent = self._lifecycle.current()
            except LifecycleStorageUnavailable:
                return None
            return (
                intent is not None
                and intent.on_demand
                and intent.component == "bot"
                and intent.target == "start"
                and intent.status == "APPLIED"
            )
        try:
            with self._database.connection() as connection:
                row = connection.execute(
                    "SELECT action FROM audit_events WHERE action IN (?, ?) "
                    "ORDER BY rowid DESC LIMIT 1",
                    (_INTAKE_PAUSED, _INTAKE_RESUMED),
                ).fetchone()
        except Exception:
            return None
        return row is not None and row[0] == _INTAKE_RESUMED

    def _write_intake(self, *, accepting: bool) -> None:
        """Idempotent durable control, without schema migration or side effects."""
        desired = _INTAKE_RESUMED if accepting else _INTAKE_PAUSED
        with self._database.connection() as connection, connection:
            # A writer transaction orders successive controls in SQLite, even
            # when their HTTP requests arrive in separate processes.
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT action FROM audit_events WHERE action IN (?, ?) "
                "ORDER BY rowid DESC LIMIT 1",
                (_INTAKE_PAUSED, _INTAKE_RESUMED),
            ).fetchone()
            if row is None or row[0] != desired:
                connection.execute(
                    "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
                    (str(uuid4()), desired),
                )

    def _begin(
        self, environ: Mapping[str, object], session: OwnerSession, start: StartResponse
    ) -> list[bytes]:
        fields = self._form(environ, expected={"csrf", "operation_id", "member_id", "event_id"})
        if fields is None or _canonical_uuid(fields["operation_id"]) is None:
            return _error(start, 400, "Comando inválido.")
        member_id = _canonical_uuid(fields["member_id"])
        if member_id is None or fields["event_id"] not in self._events:
            return _error(start, 422, "Seleccione un socio y evento de simulación válidos.")
        if not self._directory.active_member(member_id):
            return _error(start, 409, "El socio no tiene credencial local activa.")
        with self._intake_lock:
            accepting = self._read_intake()
            if accepting is None:
                return _error(
                    start, 503, "Estado de admisión no disponible. No inicie simulaciones."
                )
            if not accepting:
                if self._bot_control is not None:
                    return _error(
                        start,
                        409,
                        "Inicie el bot desde Control y espere la confirmación de arranque.",
                    )
                return _error(start, 409, "Nuevas simulaciones pausadas. Reanude desde Control.")
            fingerprint = json.dumps(fields, sort_keys=True).encode()
            result, operation = self._sessions.reserve(
                session, fields["operation_id"], fields["csrf"], fingerprint
            )
            if result:
                if result == 303 and operation is not None and operation.member_id:
                    return self._redirect(start, f"/comandos/{operation.member_id}")
                return _error(
                    start, result, "Comando ya procesado o no autorizado. Consulte estado."
                )
            assert operation is not None
            try:
                if self._commands is None or self._commands.failed:
                    raise RuntimeError("command host unavailable")
                snapshot = self._commands.begin(
                    fields["operation_id"], member_id=member_id, event_id=fields["event_id"]
                )
                canonical = _canonical_uuid(getattr(snapshot, "command_id", None))
                if canonical is None:
                    raise RuntimeError("canonical command result is unavailable")
            except Exception:
                self._sessions.finish(operation, 503)
                return _error(
                    start, 503, "Resultado incierto. Consulte el historial; no repita con otro ID."
                )
            self._sessions.finish(operation, 303, canonical)
            return self._redirect(start, f"/comandos/{canonical}")

    def _command_detail(
        self, command_id: str, session: OwnerSession, start: StartResponse
    ) -> list[bytes]:
        if _canonical_uuid(command_id) is None:
            return _error(start, 404, "Comando no encontrado.")
        member_id = self._directory.command_member(command_id)
        if member_id is None:
            return _error(start, 404, "Comando no encontrado.")
        if self._commands is None or self._commands.failed:
            return _error(start, 503, "Servicio de simulación no disponible.")
        snapshot = self._commands.status(command_id, member_id=member_id)
        if snapshot is None:
            return _error(start, 404, "Comando no encontrado.")
        state, updated_at = getattr(snapshot, "state", None), getattr(snapshot, "updated_at", None)
        if state is None or not isinstance(updated_at, (int, float)):
            return _error(start, 503, "Estado local no disponible.")
        return _response(
            start,
            200,
            private_ui.command_detail(command_id, str(state), float(updated_at), session.csrf),
        )

    def _stop(
        self,
        environ: Mapping[str, object],
        command_id: str,
        session: OwnerSession,
        start: StartResponse,
    ) -> list[bytes]:
        if _canonical_uuid(command_id) is None:
            return _error(start, 404, "Comando no encontrado.")
        fields = self._form(environ, expected={"csrf"})
        if fields is None or not hmac.compare_digest(fields["csrf"], session.csrf):
            return _error(start, 403, "Solicitud no autorizada.")
        member_id = self._directory.command_member(command_id)
        if member_id is None:
            return _error(start, 404, "Comando no encontrado.")
        try:
            if self._commands is None or self._commands.failed:
                raise RuntimeError("command host unavailable")
            self._commands.stop(command_id, member_id=member_id)
        except Exception:
            return _error(start, 503, "Parada incierta. Consulte el estado antes de repetir.")
        return self._redirect(start, f"/comandos/{command_id}")

    @staticmethod
    def _redirect(start: StartResponse, path: str) -> list[bytes]:
        return _response(start, 303, b"", extra=("Location", path))
