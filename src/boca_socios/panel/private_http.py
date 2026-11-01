"""Same-origin private simulation UI and passkey session boundary.

This WSGI callable is inert until a reviewed private server wires it to a Boca-only
database, passkey public credential and synthetic command host. No real Boca
login, queue admission, reservation or purchase path exists here.
"""

from __future__ import annotations

import hmac
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

from boca_socios.notify.projection import list_local_notices
from boca_socios.owner_origin import owner_rp_host
from boca_socios.panel import private_ui
from boca_socios.panel.enrollment_http import EnrollmentApplication
from boca_socios.panel.local_status import read_local_status
from boca_socios.panel.members import MemberDirectory
from boca_socios.panel.owner_sessions import OwnerSession, OwnerSessions
from boca_socios.panel.passkey import PasskeyAssertion, PasskeyOwnerAuthentication
from boca_socios.security.enrollment import (
    CredentialUnavailable,
    MemberNotFound,
)
from boca_socios.storage.database import Database

StartResponse = Callable[[str, list[tuple[str, str]]], object]
_UUID_PATH = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


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
) -> list[bytes]:
    headers = [
        ("Content-Type", "text/html; charset=utf-8" if html else "application/json"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
        ("Content-Security-Policy", private_ui.CSP),
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
        self._members = members
        self._directory = MemberDirectory(database_path)
        self._commands = commands
        self._events = dict(events)
        self._passkey = passkey
        self._sessions = OwnerSessions(owner_subject=owner_subject, verify_owner=passkey.verify)
        self._enroll = EnrollmentApplication(members, self._sessions, origin=origin, now=now)
        self._now = now

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
        if path == "/socios/nuevo" or (path == "/socios" and method == "POST"):
            return self._enroll(environ, start)
        if path == "/socios" or (isinstance(path, str) and path.startswith("/socios/")):
            if "members:read" not in session.permissions:
                return _error(start, 403, "Permiso insuficiente.")
        if path == "/comandos" or (isinstance(path, str) and path.startswith("/comandos/")):
            if "simulation:write" not in session.permissions:
                return _error(start, 403, "Permiso insuficiente.")
        if path in ("/estado", "/avisos") and "local-status:read" not in session.permissions:
            return _error(start, 403, "Permiso insuficiente.")
        if method == "GET":
            if not self._empty_get(environ):
                return _error(start, 400, "Solicitud inválida.")
            if path == "/":
                return _response(start, 200, private_ui.home(session.csrf))
            if path == "/socios":
                return _response(start, 200, private_ui.members(self._directory.list_members()))
            if path == "/comandos":
                return self._command_list(start, session)
            if path == "/estado":
                snapshot = read_local_status(self._database_path, observed_at=self._now())
                data = asdict(snapshot)
                data["observed_at"] = snapshot.observed_at.isoformat()
                return _response(start, 200, private_ui.status(data))
            if path == "/avisos":
                return _response(
                    start, 200, private_ui.notices(list_local_notices(self._database, limit=20))
                )
            if isinstance(path, str) and path.startswith("/socios/"):
                return self._member_detail(path.removeprefix("/socios/"), session, start)
            if isinstance(path, str) and path.startswith("/comandos/"):
                return self._command_detail(path.removeprefix("/comandos/"), session, start)
            return _error(start, 404, "Ruta no disponible.")
        if method != "POST":
            return _error(start, 405, "Método no permitido.")
        if environ.get("HTTP_ORIGIN") != self._origin:
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
        if path == "/comandos":
            return self._begin(environ, session, start)
        if isinstance(path, str) and path.startswith("/comandos/") and path.endswith("/detener"):
            command_id = path.removeprefix("/comandos/").removesuffix("/detener")
            return self._stop(environ, command_id, session, start)
        if isinstance(path, str) and path.startswith("/socios/"):
            if "members:write" not in session.permissions:
                return _error(start, 403, "Permiso insuficiente.")
            return self._credential_action(environ, path, session, start)
        return _error(start, 404, "Ruta no disponible.")

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
        return _response(
            start, 200, private_ui.member_detail(item, session.csrf, rotate_id, revoke_id)
        )

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
        fingerprint = json.dumps(fields, sort_keys=True).encode()
        result, operation = self._sessions.reserve(
            session, fields["operation_id"], fields["csrf"], fingerprint
        )
        if result:
            if result == 303 and operation is not None and operation.member_id:
                return self._redirect(start, f"/comandos/{operation.member_id}")
            return _error(start, result, "Comando ya procesado o no autorizado. Consulte estado.")
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
