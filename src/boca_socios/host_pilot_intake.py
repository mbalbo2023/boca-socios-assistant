"""Inert, single-use SSH-loopback credential intake for a future host pilot.

This module intentionally starts no listener or Chrome process. A separately
reviewed protected host adapter must establish the SSH-only boundary and pass
credentials directly to a browser driver, without printing or persisting them.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from threading import Lock
from time import monotonic
from typing import Protocol
from urllib.parse import parse_qsl


class LoginDriver(Protocol):
    def __call__(self, *, username: str, password: str) -> str: ...


StartResponse = Callable[[str, list[tuple[str, str]]], object]
_KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")
_STATES = frozenset(
    {"AUTHENTICATED", "QUEUE_PRELOBBY", "CHALLENGE", "LOGIN_FORM", "SITE_ERROR", "UNKNOWN"}
)
_ORIGIN = "http://localhost:8443"

_FORM = b"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ingreso privado Boca - piloto</title></head><body>
<main><h1>Ingreso privado de un socio</h1>
<p>Solo por el tunel SSH privado. Una cuenta, una sesion; no se reserva ni compra.</p>
<form id="login" autocomplete="off">
<label for="username">Correo del socio</label>
<input id="username" name="username" type="email" autocomplete="off" required>
<label for="password">Contrasena del socio</label>
<input id="password" name="password" type="password" autocomplete="off" required>
<button id="submit" type="submit" disabled>Comprobar ingreso</button></form>
<p id="result" role="status" aria-live="polite"></p></main>
<script src="/piloto.js" defer></script></body></html>"""

_SCRIPT = b"""'use strict';
const match = /^#key=([A-Za-z0-9_-]{43})$/.exec(location.hash);
history.replaceState(null, '', '/piloto');
let capability = location.origin === 'http://localhost:8443' && match ? match[1] : null;
const button = document.getElementById('submit');
const message = document.getElementById('result');
const form = document.getElementById('login');
button.disabled = !capability;
if (!capability) message.textContent = 'Enlace privado invalido o vencido.';
form.addEventListener('submit', async event => {
  event.preventDefault();
  if (!capability) return;
  button.disabled = true;
  const key = capability;
  capability = null;
  const payload = new URLSearchParams(new FormData(form));
  document.getElementById('password').value = '';
  try {
    const response = await fetch('/piloto/login', {method: 'POST', credentials: 'omit',
      cache: 'no-store', redirect: 'error', headers: {
      'Content-Type': 'application/x-www-form-urlencoded', 'X-Boca-Pilot-Key': key
    }, body: payload});
    const receipt = await response.json();
    message.textContent = receipt.message;
  } catch (_) {
    message.textContent = 'Estado desconocido: no reintentar automaticamente.';
  }
});"""


def _csp() -> str:
    return (
        "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
        "form-action 'none'; connect-src 'self'; "
        "script-src 'self'"
    )


def _respond(start: StartResponse, status: int, body: bytes, *, mime: str) -> list[bytes]:
    start(
        f"{status} {HTTPStatus(status).phrase}",
        [
            ("Content-Type", mime),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store, no-cache, must-revalidate"),
            ("Referrer-Policy", "no-referrer"),
            ("X-Content-Type-Options", "nosniff"),
            ("X-Frame-Options", "DENY"),
            ("Content-Security-Policy", _csp()),
        ],
    )
    return [body]


def _reply(start: StartResponse, status: int, state: str) -> list[bytes]:
    messages = {
        "AUTHENTICATED": "Ingreso acreditado por el navegador del piloto.",
        "QUEUE_PRELOBBY": "La pagina esta en prefila. No se acredito el ingreso.",
        "CHALLENGE": "El sitio solicita una comprobacion humana. Piloto detenido.",
        "LOGIN_FORM": "Sigue visible el formulario. Ingreso no acreditado.",
        "SITE_ERROR": "El sitio informo un error. Ingreso no acreditado.",
        "UNKNOWN": "No se pudo acreditar el ingreso. Estado desconocido.",
        "DENIED": "Solicitud privada rechazada o consumida.",
    }
    content = json.dumps({"state": state, "message": messages[state]}).encode("utf-8")
    return _respond(start, status, content, mime="application/json")


@dataclass(frozen=True, slots=True, repr=False)
class PilotGateConfig:
    capability_sha256: str
    lifetime_seconds: float = 900.0

    def __post_init__(self) -> None:
        if re.fullmatch(r"[0-9a-f]{64}", self.capability_sha256) is None:
            raise ValueError("one SHA-256 hex digest required, not the bearer")
        if not 0 < self.lifetime_seconds <= 900:
            raise ValueError("maximum 15-minute intake lifetime")


class HostPilotIntake:
    """One capability, at most one valid password submission, memory-only.

    An authenticated caller still requires an independently proven browser
    session; this WSGI adapter cannot verify a Boca account on its own.
    """

    def __init__(
        self,
        config: PilotGateConfig,
        driver: LoginDriver | None,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._expected_digest = bytes.fromhex(config.capability_sha256)
        self._expires = clock() + config.lifetime_seconds
        self._clock = clock
        self._driver = driver
        self._lock = Lock()
        self._consumed = False

    def __call__(self, env: Mapping[str, object], start: StartResponse) -> list[bytes]:
        if (
            env.get("wsgi.url_scheme") != "http"
            or env.get("HTTP_HOST") != "localhost:8443"
            or env.get("REMOTE_ADDR") != "127.0.0.1"
            or env.get("QUERY_STRING", "")
            or env.get("HTTP_TRANSFER_ENCODING", "")
            or env.get("HTTP_X_FORWARDED_FOR", "")
        ):
            return _reply(start, 403, "DENIED")
        path, method = env.get("PATH_INFO"), env.get("REQUEST_METHOD")
        if method == "GET" and path in ("/piloto", "/piloto.js"):
            if env.get("CONTENT_LENGTH", "") not in ("", "0"):
                return _reply(start, 403, "DENIED")
            body, mime = (
                (_FORM, "text/html; charset=utf-8")
                if path == "/piloto"
                else (_SCRIPT, "application/javascript; charset=utf-8")
            )
            return _respond(start, 200, body, mime=mime)
        if method != "POST" or path != "/piloto/login":
            return _reply(start, 404, "DENIED")
        if env.get("HTTP_ORIGIN") != _ORIGIN:
            return _reply(start, 403, "DENIED")
        if self._driver is None:
            return _reply(start, 503, "UNKNOWN")
        try:
            raw = env.get("HTTP_X_BOCA_PILOT_KEY")
            if not isinstance(raw, str) or _KEY_PATTERN.fullmatch(raw) is None:
                return _reply(start, 403, "DENIED")
            token = base64.urlsafe_b64decode(raw + "=")
            if len(token) != 32 or not hmac.compare_digest(
                hashlib.sha256(token).digest(), self._expected_digest
            ):
                return _reply(start, 403, "DENIED")
            length = env.get("CONTENT_LENGTH")
            if (
                not isinstance(length, str)
                or re.fullmatch(r"[0-9]{1,5}", length) is None
                or not 0 < int(length) <= 8192
                or env.get("CONTENT_TYPE") != "application/x-www-form-urlencoded"
            ):
                return _reply(start, 403, "DENIED")
            stream = env.get("wsgi.input")
            read = getattr(stream, "read", None)
            if not callable(read):
                return _reply(start, 403, "DENIED")
            body = read(int(length))
            if not isinstance(body, bytes) or len(body) != int(length):
                return _reply(start, 403, "DENIED")
            pairs = parse_qsl(
                body.decode("utf-8"),
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=2,
            )
            fields = dict(pairs)
            if len(pairs) != 2 or len(fields) != 2 or set(fields) != {"username", "password"}:
                return _reply(start, 403, "DENIED")
            username, password = fields["username"], fields["password"]
            if (
                not 3 <= len(username) <= 254
                or "@" not in username
                or any(ord(c) < 33 or ord(c) == 127 for c in username)
                or not 1 <= len(password.encode("utf-8")) <= 4096
            ):
                return _reply(start, 403, "DENIED")
        except (UnicodeError, ValueError, TypeError, AttributeError):
            return _reply(start, 403, "DENIED")
        with self._lock:
            if self._consumed or self._clock() >= self._expires:
                return _reply(start, 403, "DENIED")
            self._consumed = True
        try:
            state = self._driver(username=username, password=password)
        except Exception:
            state = "UNKNOWN"
        if state not in _STATES:
            state = "UNKNOWN"
        return _reply(start, 200 if state == "AUTHENTICATED" else 202, state)
