"""One-use first-owner passkey enrollment over a separately SSH-forwarded HTTP port.

This is a temporary, isolated Boca HTTP service, NOT the BETA panel. It must
never mount the owner/key/data volumes: the only filesystem output is one v2
encrypted envelope in its own disposable staging volume. A later protected,
offline `owner_bootstrap.install` installs that envelope and verifies custody.

The caller creates the 256-bit URL capability *outside* Actions and supplies
only its SHA-256 digest here. Never put the raw capability in Actions inputs,
Docker arguments, environment, access logs or persistent browser storage.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import hmac
import json
import math
import os
import re
import socket
import sys
from collections.abc import Callable, Iterable
from http import HTTPStatus
from pathlib import Path
from threading import Event, Lock
from time import monotonic
from typing import Any, BinaryIO, cast
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer

from boca_socios.owner_bootstrap import (
    MAX_ENVELOPE,
    UID,
    BootstrapError,
    RecipientReceipt,
    _directory,
    _read,
    _unb64,
    _write_new,
    seal_for_recipient,
)
from boca_socios.owner_enrollment_ui import _CSP, _PAGE, _SCRIPT
from boca_socios.owner_origin import SSH_LOOPBACK_ORIGIN
from boca_socios.panel.passkey import PasskeyAssertion
from boca_socios.panel.passkey_registration import CreationResponse, OwnerPasskeyRegistration

ORIGIN = SSH_LOOPBACK_ORIGIN
HOST = "localhost:8443"
STAGING = Path("/run/enrollment")
ENVELOPE_NAME = "owner-envelope.v2"
_CAP_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_SUBJECT_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_FINGERPRINT_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_ENROLLMENT_WINDOW_SECONDS = 900.0


class EnrollmentError(ValueError):
    """Only fixed, nonsecret error reasons may leave the service."""


def _capability(raw: object) -> bytes:
    if not isinstance(raw, str) or _CAP_PATTERN.fullmatch(raw) is None:
        raise EnrollmentError("invalid_capability")
    try:
        decoded = base64.b64decode(raw + "=", altchars=b"-_", validate=True)
    except (ValueError, binascii.Error):
        raise EnrollmentError("invalid_capability") from None
    if len(decoded) != 32 or base64.urlsafe_b64encode(decoded).rstrip(b"=").decode() != raw:
        raise EnrollmentError("invalid_capability")
    return decoded


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EnrollmentError("duplicate_json_key")
        result[key] = value
    return result


def _json_body(environ: dict[str, Any]) -> dict[str, Any]:
    length = environ.get("CONTENT_LENGTH")
    if (
        environ.get("CONTENT_TYPE") != "application/json"
        or not isinstance(length, str)
        or not length.isascii()
        or not length.isdecimal()
        or not 0 < int(length) <= 16384
    ):
        raise EnrollmentError("invalid_request")
    stream = cast(BinaryIO | None, environ.get("wsgi.input"))
    if stream is None:
        raise EnrollmentError("invalid_request")
    raw = stream.read(int(length))
    if len(raw) != int(length):
        raise EnrollmentError("invalid_request")
    try:
        data = json.loads(raw, object_pairs_hook=_unique_pairs)
    except (ValueError, UnicodeError):
        raise EnrollmentError("invalid_request") from None
    if not isinstance(data, dict):
        raise EnrollmentError("invalid_request")
    return data


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


class OneUseOwnerEnrollment:
    """Single in-memory grant, create→get proof, and encrypted staging output.

    Expects a preprepared public X25519 recipient receipt. Absolutely no owner
    volume is accessible to this class or to its temporary HTTP container.
    """

    def __init__(
        self,
        *,
        capability_digest: bytes,
        staging_dir: Path,
        recipient: RecipientReceipt,
        owner_subject: str,
        uid: int = UID,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if not isinstance(capability_digest, bytes) or len(capability_digest) != 32:
            raise EnrollmentError("invalid_capability_digest")
        if not isinstance(owner_subject, str) or _SUBJECT_PATTERN.fullmatch(owner_subject) is None:
            raise EnrollmentError("invalid_subject")
        if (
            not isinstance(recipient, RecipientReceipt)
            or recipient.state not in {"PREPARED", "ALREADY_PREPARED"}
            or not isinstance(recipient.fingerprint, str)
            or _FINGERPRINT_PATTERN.fullmatch(recipient.fingerprint) is None
        ):
            raise EnrollmentError("invalid_recipient")
        try:
            public = _unb64(recipient.public_key, maximum=32, length=32)
        except BootstrapError:
            raise EnrollmentError("invalid_recipient") from None
        if not hmac.compare_digest(hashlib.sha256(public).hexdigest(), recipient.fingerprint):
            raise EnrollmentError("invalid_recipient")
        if not isinstance(uid, int):
            raise EnrollmentError("invalid_identity")
        directory = _directory(staging_dir, uid)
        try:
            if os.listdir(directory):
                raise EnrollmentError("staging_not_empty")
        finally:
            os.close(directory)
        now = clock()
        if not math.isfinite(now):
            raise EnrollmentError("invalid_time")
        self._registration = OwnerPasskeyRegistration(
            origin=ORIGIN, rp_id="localhost", owner_subject=owner_subject, clock=clock
        )
        self._capability_digest = capability_digest
        self._staging = staging_dir
        self._recipient = recipient
        self._subject = owner_subject
        self._uid = uid
        self._clock = clock
        self._deadline = now + _ENROLLMENT_WINDOW_SECONDS
        self._session_digest: bytes | None = None
        self._phase = "capability"
        self._lock = Lock()
        self.stopped = Event()

    def expired(self) -> bool:
        now = self._clock()
        return not math.isfinite(now) or now >= self._deadline

    @property
    def completed(self) -> bool:
        """Only a validated WebAuthn proof plus verified ciphertext is success."""
        return self.stopped.is_set() and self._phase == "sealed"

    def __call__(
        self, environ: dict[str, Any], start: Callable[[str, list[tuple[str, str]]], object]
    ) -> Iterable[bytes]:
        with self._lock:
            if self.stopped.is_set() or self.expired():
                self.stopped.set()
                return _response(start, 410, b'{"error":"closed"}')
            if (
                environ.get("wsgi.url_scheme") != "http"
                or environ.get("HTTP_HOST") != HOST
                or environ.get("QUERY_STRING")
            ):
                if environ.get("REQUEST_METHOD") == "POST":
                    self.stopped.set()
                return _response(start, 403, b'{"error":"invalid_origin"}')
            path, method = environ.get("PATH_INFO"), environ.get("REQUEST_METHOD")
            if method == "GET" and path == "/activar":
                return _response(start, 200, _PAGE, content_type="text/html; charset=utf-8")
            if method == "GET" and path == "/activar.js":
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
                result = self._transition(path, body, environ.get("HTTP_X_BOCA_ENROLLMENT"))
            except (EnrollmentError, BootstrapError, OSError, ValueError, TypeError, KeyError):
                self.stopped.set()
                return _response(start, 403, b'{"error":"rejected"}')
            return _response(start, 200, json.dumps(result, separators=(",", ":")).encode())

    def _session(self, supplied: object) -> None:
        digest = hashlib.sha256(_capability(supplied)).digest()
        if self._session_digest is None or not hmac.compare_digest(digest, self._session_digest):
            raise EnrollmentError("invalid_session")

    def _transition(self, path: str, body: dict[str, Any], session: object) -> dict[str, Any]:
        if path == "/begin":
            if self._phase != "capability" or session is not None or set(body) != {"capability"}:
                raise EnrollmentError("invalid_begin")
            digest = hashlib.sha256(_capability(body["capability"])).digest()
            if not hmac.compare_digest(digest, self._capability_digest):
                raise EnrollmentError("invalid_capability")
            challenge = self._registration.begin()
            if challenge is None:
                raise EnrollmentError("registration_unavailable")
            next_session = _encode(os.urandom(32))
            self._session_digest = hashlib.sha256(_capability(next_session)).digest()
            self._phase = "creation"
            return {
                "session": next_session,
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
                raise EnrollmentError("invalid_creation")
            proof = self._registration.accept_creation(
                body["operation_id"], CreationResponse(**response)
            )
            if proof is None:
                raise EnrollmentError("invalid_creation")
            self._phase = "proof"
            return {"credential_id": proof.credential_id, "challenge": proof.challenge}
        if (
            self._phase == "proof"
            and path == "/proof"
            and set(body)
            == {
                "operation_id",
                "assertion",
            }
        ):
            assertion = body["assertion"]
            if not isinstance(assertion, dict) or set(assertion) != {
                "credential_id",
                "client_data_json",
                "authenticator_data",
                "signature",
            }:
                raise EnrollmentError("invalid_proof")
            credential = self._registration.finish(
                body["operation_id"], PasskeyAssertion(**assertion)
            )
            if credential is None:
                raise EnrollmentError("invalid_proof")
            envelope = seal_for_recipient(
                self._recipient,
                {
                    "credential_id": credential.credential_id,
                    "public_key.der": credential.public_key_der,
                },
                ORIGIN,
                self._subject,
            )
            directory = _directory(self._staging, self._uid)
            try:
                if os.listdir(directory):
                    raise EnrollmentError("staging_not_empty")
                _write_new(directory, ENVELOPE_NAME, envelope, self._uid)
                if not hmac.compare_digest(
                    _read(directory, ENVELOPE_NAME, self._uid, MAX_ENVELOPE), envelope
                ):
                    raise EnrollmentError("staging_unverified")
            finally:
                os.close(directory)
            self._phase = "sealed"
            self.stopped.set()
            return {"state": "verified_for_install"}
        raise EnrollmentError("invalid_transition")


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        # Never log a request URL or its headers, even for rejected attempts.
        return


class _TemporaryHTTPServer(WSGIServer):
    allow_reuse_address = False

    def __init__(self) -> None:
        # Container-internal bind. Host exposure MUST be 127.0.0.1:8443 only.
        # Only inside the disposable network namespace. The host MUST publish
        # exclusively 127.0.0.1:8443; never publish a host wildcard address.
        super().__init__(("0.0.0.0", 8443), _QuietHandler)  # noqa: S104
        self.timeout = 0.5

    def get_request(self) -> tuple[socket.socket, tuple[str, int]]:
        connection, address = super().get_request()
        connection.settimeout(5.0)
        return connection, address

    def handle_error(
        self,
        _request: socket.socket | tuple[bytes, socket.socket],
        _client_address: tuple[str, int],
    ) -> None:
        # No request or exception details leave the disposable container.
        return


def serve(
    staging_dir: Path,
    recipient: RecipientReceipt,
    subject: str,
    capability_digest: bytes,
    *,
    uid: int = UID,
) -> bool:
    """Block until one completed proof or the expiry; never operate the host."""
    app = OneUseOwnerEnrollment(
        capability_digest=capability_digest,
        staging_dir=staging_dir,
        recipient=recipient,
        owner_subject=subject,
        uid=uid,
    )
    with _TemporaryHTTPServer() as server:
        server.set_app(app)
        while not app.stopped.is_set() and not app.expired():
            server.handle_request()
    return app.completed and (staging_dir / ENVELOPE_NAME).is_file()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Boca disposable first-owner HTTP enrollment")
    parser.add_argument("subject")
    parser.add_argument("capability_sha256")
    parser.add_argument("recipient_public_key")
    parser.add_argument("recipient_fingerprint")
    args = parser.parse_args(argv)
    try:
        if _FINGERPRINT_PATTERN.fullmatch(args.capability_sha256) is None:
            raise EnrollmentError("invalid_capability_digest")
        recipient = RecipientReceipt(
            "PREPARED", args.recipient_public_key, args.recipient_fingerprint
        )
        completed = serve(STAGING, recipient, args.subject, bytes.fromhex(args.capability_sha256))
    except (EnrollmentError, BootstrapError, OSError, ValueError, TypeError):
        completed = False
    if not completed:
        print("BOCA_OWNER_ENROLL state=NO_GO", file=sys.stderr)
        return 1
    print("BOCA_OWNER_ENROLL state=VERIFIED_FOR_OFFLINE_INSTALL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
