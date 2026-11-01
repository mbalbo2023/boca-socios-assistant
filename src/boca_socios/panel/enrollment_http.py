"""Private enrollment WSGI adapter; no listener or real authenticator is enabled."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Protocol
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

from boca_socios.panel.enrollment_form import CSP, render_form, render_members
from boca_socios.panel.owner_sessions import OwnerSession, OwnerSessions
from boca_socios.security.enrollment import EnrollmentConflict

StartResponse = Callable[[str, list[tuple[str, str]]], object]


class EnrollmentService(Protocol):
    def enroll(
        self, *, email: str, password: str, consent_recorded_at: datetime, display_name: str = ""
    ) -> str: ...


_MESSAGES = {
    201: "Socio agregado. La credencial quedó cifrada; no se inició ninguna reserva.",
    400: "Solicitud inválida. Revise los campos e intente desde el formulario.",
    401: "La sesión venció o no está autorizada. Conservamos alias y correo; vuelva a ingresar.",
    403: "No se autorizó el envío. Abra el formulario desde el panel privado.",
    404: "Página no disponible.",
    405: "Método no permitido.",
    409: "El alta ya está en curso o entra en conflicto. Revise antes de volver a enviarla.",
    413: "El formulario supera el tamaño permitido.",
    422: "Revise correo, alias, contraseña y consentimiento antes de guardar.",
    429: "Espere un momento antes de volver a guardar.",
    503: "No se pudo confirmar el alta. Revise el estado antes de volver a enviarla.",
}


def _response(start: StartResponse, status: int, body: bytes, *, html: bool = False) -> list[bytes]:
    start(
        f"{status} {HTTPStatus(status).phrase}",
        [
            ("Content-Type", "text/html; charset=utf-8" if html else "application/json"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("Content-Security-Policy", CSP),
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"),
        ],
    )
    return [body]


def _result(start: StartResponse, status: int, member_id: str | None = None) -> list[bytes]:
    value = {"message": _MESSAGES[status]}
    if member_id is not None:
        value["member_id"] = member_id
    return _response(start, status, json.dumps(value, ensure_ascii=False).encode())


class EnrollmentApplication:
    """Same-origin session and mutation checks around the existing service.

    The hosting server must enforce header/time/connection limits. Requests do
    not select a database, key, owner, session lifetime or identity verifier.
    """

    def __init__(
        self,
        service: EnrollmentService | None,
        sessions: OwnerSessions,
        *,
        origin: str,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or any(char.isspace() for char in origin)
        ):
            raise ValueError("one HTTPS origin must be configured")
        self._origin = origin
        self._host = parsed.netloc
        self._sessions = sessions
        self._service = service
        self._now = now

    def __call__(self, environ: Mapping[str, object], start: StartResponse) -> list[bytes]:
        if environ.get("wsgi.url_scheme") != "https" or environ.get("HTTP_HOST") != self._host:
            return _result(start, 400)
        try:
            session = self._sessions.lookup(environ.get("HTTP_COOKIE", ""))
        except Exception:
            return _result(start, 503)
        if session is None:
            return _result(start, 401)
        if environ.get("QUERY_STRING", "") or environ.get("HTTP_TRANSFER_ENCODING", ""):
            return _result(start, 400)
        path, method = environ.get("PATH_INFO"), environ.get("REQUEST_METHOD")
        if path not in ("/socios", "/socios/nuevo"):
            return _result(start, 404)
        if method == "GET":
            if environ.get("CONTENT_LENGTH", "") not in ("", "0"):
                return _result(start, 400)
            if environ.get("HTTP_ORIGIN", "") not in ("", self._origin):
                return _result(start, 403)
            if path == "/socios":
                return _response(start, 200, render_members(), html=True)
            operation_id = self._sessions.new_operation(session)
            if operation_id is None:
                return _result(start, 429)
            return _response(start, 200, render_form(session.csrf, operation_id), html=True)
        if method != "POST" or path != "/socios":
            return _result(start, 405)
        if environ.get("HTTP_ORIGIN") != self._origin:
            return _result(start, 403)
        return self._enroll(environ, start, session)

    def _enroll(
        self, environ: Mapping[str, object], start: StartResponse, session: OwnerSession
    ) -> list[bytes]:
        length = environ.get("CONTENT_LENGTH")
        if not isinstance(length, str) or re.fullmatch(r"[0-9]{1,5}", length) is None:
            return _result(start, 400)
        size = int(length)
        if not 0 < size <= 16384:
            return _result(start, 413)
        if environ.get("CONTENT_TYPE") not in (
            "application/x-www-form-urlencoded",
            "application/x-www-form-urlencoded;charset=UTF-8",
            "application/x-www-form-urlencoded; charset=UTF-8",
        ):
            return _result(start, 400)
        try:
            stream = environ.get("wsgi.input")
            read = getattr(stream, "read", None)
            if not callable(read):
                return _result(start, 400)
            body = read(size)
            if not isinstance(body, bytes) or len(body) != size:
                return _result(start, 400)
            pairs = parse_qsl(
                body.decode("utf-8"),
                keep_blank_values=True,
                strict_parsing=True,
                encoding="utf-8",
                errors="strict",
                max_num_fields=6,
            )
            fields = dict(pairs)
            if len(fields) != len(pairs) or set(fields) != {
                "csrf",
                "operation_id",
                "alias",
                "email",
                "password",
                "consent",
            }:
                return _result(start, 400)
            if (
                fields["consent"] != "yes"
                or len(fields["alias"]) > 200
                or any(ord(char) < 32 for char in fields["alias"])
                or len(fields["email"]) > 254
                or not 0 < len(fields["password"].encode("utf-8")) <= 4096
                or len(fields["csrf"]) > 100
                or len(fields["operation_id"]) != 36
            ):
                return _result(start, 422)
            status, operation = self._sessions.reserve(
                session, fields["operation_id"], fields["csrf"], body
            )
        except Exception:
            return _result(start, 400)
        if status:
            return _result(start, status, operation.member_id if operation else None)
        assert operation is not None
        try:
            if self._service is None:
                raise ValueError("enrollment not configured")
            now = self._now()
            if now.tzinfo is None or now.utcoffset() is None:
                raise ValueError("invalid clock")
            member_id = self._service.enroll(
                email=fields["email"],
                password=fields["password"],
                display_name=fields["alias"],
                consent_recorded_at=now,
            )
            if not isinstance(member_id, str) or str(UUID(member_id)) != member_id:
                raise ValueError("invalid enrollment result")
        except EnrollmentConflict:
            self._sessions.finish(operation, 409)
            return _result(start, 409)
        except Exception:
            self._sessions.finish(operation, 503)
            return _result(start, 503)
        self._sessions.finish(operation, 201, member_id)
        return _result(start, 201, member_id)
