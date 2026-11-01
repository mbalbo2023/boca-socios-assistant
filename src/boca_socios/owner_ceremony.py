"""One-use HTTPS WebAuthn ceremony on the owner's device, never on the host.

This module has no Boca host operation or public endpoint. Real Android trust,
physical user verification and ciphertext handoff remain separate gates.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import getpass
import hashlib
import hmac
import json
import re
import secrets
import socket
import ssl
import sys
from collections.abc import Callable, Iterable
from http import HTTPStatus
from pathlib import Path
from threading import Event, Lock
from time import monotonic
from typing import Any, BinaryIO, cast
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer

from boca_socios.owner_bootstrap import (
    BootstrapError,
    RecipientReceipt,
    seal_for_recipient,
)
from boca_socios.owner_ceremony_tls import (
    RP_ID,
    TLS_FILES,
    CeremonyError,
    prepare_device_tls,
    read_device_tls,
)
from boca_socios.owner_ceremony_ui import _CSP, _PAGE, _SCRIPT
from boca_socios.panel.passkey import PasskeyAssertion
from boca_socios.panel.passkey_registration import CreationResponse, OwnerPasskeyRegistration

ORIGIN = "https://localhost:8443"
HOST = "localhost:8443"
_B64 = re.compile(r"[A-Za-z0-9_-]{43}\Z")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _capability(value: str) -> bytes:
    if not isinstance(value, str) or _B64.fullmatch(value) is None:
        raise CeremonyError("invalid_local_capability")
    try:
        decoded = base64.urlsafe_b64decode(value + "=")
    except (ValueError, binascii.Error):
        raise CeremonyError("invalid_local_capability") from None
    if len(decoded) != 32 or _encode(decoded) != value:
        raise CeremonyError("invalid_local_capability")
    return decoded


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _json_body(environ: dict[str, Any]) -> dict[str, Any]:
    length = environ.get("CONTENT_LENGTH", "")
    if (
        environ.get("CONTENT_TYPE") != "application/json"
        or not isinstance(length, str)
        or not length.isascii()
        or not length.isdecimal()
        or not 0 < int(length) <= 16384
    ):
        raise CeremonyError("invalid_request")
    stream = cast(BinaryIO | None, environ.get("wsgi.input"))
    if stream is None:
        raise CeremonyError("invalid_request")
    payload = stream.read(int(length))
    if len(payload) != int(length):
        raise CeremonyError("invalid_request")
    try:
        result = json.loads(payload, object_pairs_hook=_unique)
    except (ValueError, UnicodeError):
        raise CeremonyError("invalid_request") from None
    if not isinstance(result, dict):
        raise CeremonyError("invalid_request")
    return result


def _response(
    start: Callable[[str, list[tuple[str, str]]], object],
    status: int,
    body: bytes,
    *,
    content_type: str = "application/json",
) -> Iterable[bytes]:
    start(
        f"{status} {HTTPStatus(status).phrase}",
        [
            ("Content-Type", content_type),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("Content-Security-Policy", _CSP),
            (
                "Permissions-Policy",
                "publickey-credentials-create=(self), publickey-credentials-get=(self)",
            ),
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"),
            ("X-Frame-Options", "DENY"),
        ],
    )
    return [body]


class LocalOwnerCeremony:
    """One device-local capability and one create→get proof, then stop."""

    def __init__(
        self,
        *,
        capability_digest: bytes,
        recipient: RecipientReceipt,
        owner_subject: str,
        tls: dict[str, bytes],
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if (
            recipient.state not in {"PREPARED", "ALREADY_PREPARED"}
            or set(tls) != set(TLS_FILES)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", owner_subject) is None
            or re.fullmatch(r"[0-9a-f]{64}", recipient.fingerprint) is None
        ):
            raise CeremonyError("invalid_coordinates")
        try:
            public = _capability(recipient.public_key)
        except CeremonyError:
            raise CeremonyError("invalid_coordinates") from None
        if not hmac.compare_digest(hashlib.sha256(public).hexdigest(), recipient.fingerprint):
            raise CeremonyError("invalid_coordinates")
        self._registration = OwnerPasskeyRegistration(
            origin=ORIGIN, rp_id=RP_ID, owner_subject=owner_subject, clock=clock
        )
        if not isinstance(capability_digest, bytes) or len(capability_digest) != 32:
            raise CeremonyError("invalid_local_capability")
        self._cap_digest = capability_digest
        self._recipient = recipient
        self._subject = owner_subject
        self._tls = tls
        self._clock = clock
        self._cap_deadline = clock() + 120.0
        self._deadline = clock() + 360.0
        self._session_digest: bytes | None = None
        self._phase = "capability"
        self._lock = Lock()
        self.stopped = Event()

    def expired(self) -> bool:
        return self._clock() >= self._deadline or (
            self._phase == "capability" and self._clock() >= self._cap_deadline
        )

    def __call__(
        self, environ: dict[str, Any], start: Callable[[str, list[tuple[str, str]]], object]
    ) -> Iterable[bytes]:
        with self._lock:
            if self.stopped.is_set() or self.expired():
                self.stopped.set()
                return _response(start, 410, b'{"error":"closed"}')
            if (
                environ.get("wsgi.url_scheme") != "https"
                or environ.get("HTTPS") != "on"
                or environ.get("HTTP_HOST") != HOST
                or environ.get("QUERY_STRING")
            ):
                if environ.get("REQUEST_METHOD") == "POST":
                    self.stopped.set()
                return _response(start, 403, b'{"error":"invalid_origin"}')
            path, method = environ.get("PATH_INFO"), environ.get("REQUEST_METHOD")
            if method == "GET" and path == "/":
                return _response(start, 200, _PAGE, content_type="text/html; charset=utf-8")
            if method == "GET" and path == "/ceremony.js":
                return _response(start, 200, _SCRIPT, content_type="text/javascript; charset=utf-8")
            if method != "POST" or path not in {"/begin", "/creation", "/proof", "/abort"}:
                if method == "POST":
                    self.stopped.set()
                return _response(start, 404, b'{"error":"not_found"}')
            if environ.get("HTTP_ORIGIN") != ORIGIN:
                self.stopped.set()
                return _response(start, 403, b'{"error":"invalid_origin"}')
            try:
                body = _json_body(environ)
                result = self._transition(path, body, environ.get("HTTP_X_BOCA_CEREMONY"))
            except (CeremonyError, BootstrapError, OSError, ValueError, TypeError, KeyError):
                self.stopped.set()
                return _response(start, 403, b'{"error":"rejected"}')
            return _response(start, 200, json.dumps(result, separators=(",", ":")).encode())

    def _session(self, value: object) -> None:
        if not isinstance(value, str) or _B64.fullmatch(value) is None:
            raise CeremonyError("invalid_session")
        supplied = hashlib.sha256(_capability(value)).digest()
        if self._session_digest is None or not hmac.compare_digest(supplied, self._session_digest):
            raise CeremonyError("invalid_session")

    def _transition(self, path: str, body: dict[str, Any], session: object) -> dict[str, Any]:
        if path == "/begin":
            if self._phase != "capability" or session is not None or set(body) != {"capability"}:
                raise CeremonyError("invalid_begin")
            supplied = hashlib.sha256(_capability(body["capability"])).digest()
            if not hmac.compare_digest(supplied, self._cap_digest):
                raise CeremonyError("invalid_capability")
            challenge = self._registration.begin()
            if challenge is None:
                raise CeremonyError("unavailable")
            token = _encode(secrets.token_bytes(32))
            self._session_digest = hashlib.sha256(_capability(token)).digest()
            self._phase = "creation"
            return {
                "session": token,
                "operation_id": challenge.operation_id,
                "challenge": challenge.challenge,
                "user_id": challenge.user_id,
                "rp_id": challenge.rp_id,
                "timeout_ms": challenge.timeout_ms,
            }
        self._session(session)
        if path == "/abort" and body == {}:
            self.stopped.set()
            return {"state": "closed"}
        if (
            self._phase == "creation"
            and path == "/creation"
            and set(body) == {"operation_id", "response"}
        ):
            response = body["response"]
            if not isinstance(response, dict) or set(response) != {
                "credential_id",
                "client_data_json",
                "authenticator_data",
                "public_key_der",
                "public_key_algorithm",
            }:
                raise CeremonyError("invalid_creation")
            proof = self._registration.accept_creation(
                body["operation_id"], CreationResponse(**response)
            )
            if proof is None:
                raise CeremonyError("invalid_creation")
            self._phase = "proof"
            return {"credential_id": proof.credential_id, "challenge": proof.challenge}
        if (
            self._phase == "proof"
            and path == "/proof"
            and set(body) == {"operation_id", "assertion"}
        ):
            assertion = body["assertion"]
            if not isinstance(assertion, dict) or set(assertion) != {
                "credential_id",
                "client_data_json",
                "authenticator_data",
                "signature",
            }:
                raise CeremonyError("invalid_proof")
            credential = self._registration.finish(
                body["operation_id"], PasskeyAssertion(**assertion)
            )
            if credential is None:
                raise CeremonyError("invalid_proof")
            bundle = {
                "credential_id": credential.credential_id,
                "public_key.der": credential.public_key_der,
                **self._tls,
            }
            envelope = seal_for_recipient(self._recipient, bundle, ORIGIN, self._subject)
            self.stopped.set()
            return {"envelope": _encode(envelope)}
        raise CeremonyError("invalid_transition")


class _QuietHandler(WSGIRequestHandler):
    def get_environ(self) -> dict[str, str]:
        environ = super().get_environ()
        environ["HTTPS"] = "on"
        environ["wsgi.url_scheme"] = "https"
        return environ

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _LocalTLSServer(WSGIServer):
    allow_reuse_address = False

    def __init__(self, context: ssl.SSLContext) -> None:
        self._context = context
        super().__init__(("127.0.0.1", 8443), _QuietHandler)
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

    def handle_error(
        self,
        _request: socket.socket | tuple[bytes, socket.socket],
        _client_address: tuple[str, int],
    ) -> None:
        # No traceback or request material may reach a device log.
        return


def serve_device(
    path: Path, recipient: RecipientReceipt, owner_subject: str, capability_digest: bytes
) -> None:
    """Serve only this device's loopback; close after one result or timeout."""
    tls = read_device_tls(path)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(path / "tls.crt"), str(path / "tls.key"))
    app = LocalOwnerCeremony(
        capability_digest=capability_digest,
        recipient=recipient,
        owner_subject=owner_subject,
        tls=tls,
    )
    with _LocalTLSServer(context) as server:
        server.set_app(app)
        while not app.stopped.is_set() and not app.expired():
            server.handle_request()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Boca owner-device ceremony candidate")
    parser.add_argument("phase", choices=("prepare-tls", "serve"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--recipient-public-key")
    parser.add_argument("--recipient-fingerprint")
    parser.add_argument("--owner-subject")
    args = parser.parse_args(argv)
    try:
        if args.phase == "prepare-tls":
            if any((args.recipient_public_key, args.recipient_fingerprint, args.owner_subject)):
                raise CeremonyError("invalid_coordinates")
            fingerprint = prepare_device_tls(args.directory)
            print(f"BOCA_DEVICE_TLS state=PREPARED ca_sha256={fingerprint}")
        else:
            if not sys.stdin.isatty():
                raise CeremonyError("local_tty_required")
            if not all((args.recipient_public_key, args.recipient_fingerprint, args.owner_subject)):
                raise CeremonyError("invalid_coordinates")
            capability_digest = hashlib.sha256(
                _capability(getpass.getpass("Capacidad local de 256 bits (sin eco): "))
            ).digest()
            receipt = RecipientReceipt(
                "PREPARED", args.recipient_public_key, args.recipient_fingerprint
            )
            print("BOCA_DEVICE_CEREMONY state=LOCAL_ONLY origin=https://localhost:8443")
            serve_device(args.directory, receipt, args.owner_subject, capability_digest)
            print("BOCA_DEVICE_CEREMONY state=CLOSED")
    except (CeremonyError, BootstrapError, OSError, ValueError):
        print("BOCA_DEVICE_CEREMONY state=NO_GO", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
