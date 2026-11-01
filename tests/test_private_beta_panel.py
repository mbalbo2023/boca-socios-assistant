"""Synthetic private HTTP journey and passkey security regression."""

import base64
import hashlib
import io
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep
from urllib.parse import urlencode

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from boca_socios.integration.command_store import CommandStore
from boca_socios.panel.passkey import PasskeyAssertion, PasskeyOwnerAuthentication
from boca_socios.panel.private_http import PrivatePanelApplication
from boca_socios.security.credential_vault import CredentialVault
from boca_socios.security.enrollment import MemberEnrollmentService
from boca_socios.storage.database import Database

ORIGIN = "https://boca.example.test"
EVENT_ID = "5387eb20-c962-42f5-933e-d5f681ab0877"
PERMISSIONS = frozenset(
    {"members:enroll", "members:read", "members:write", "simulation:write", "local-status:read"}
)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _assertion(
    key: ec.EllipticCurvePrivateKey,
    credential_id: bytes,
    challenge: str,
    *,
    origin: str = ORIGIN,
    flags: int = 0x05,
) -> PasskeyAssertion:
    client = json.dumps(
        {"type": "webauthn.get", "challenge": challenge, "origin": origin},
        separators=(",", ":"),
    ).encode()
    auth = hashlib.sha256(b"boca.example.test").digest() + bytes([flags]) + (1).to_bytes(4, "big")
    signature = key.sign(auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
    return PasskeyAssertion(_b64(credential_id), _b64(client), _b64(auth), _b64(signature))


def _passkey(
    clock: list[float],
) -> tuple[PasskeyOwnerAuthentication, ec.EllipticCurvePrivateKey, bytes]:
    key = ec.generate_private_key(ec.SECP256R1())
    credential_id = os.urandom(32)
    provider = PasskeyOwnerAuthentication(
        credential_id=credential_id,
        public_key_der=key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
        rp_id="boca.example.test",
        origin=ORIGIN,
        owner_subject="owner",
        permissions=PERMISSIONS,
        clock=lambda: clock[0],
    )
    return provider, key, credential_id


def _request(
    app: PrivatePanelApplication,
    path: str,
    *,
    method: str = "GET",
    cookie: str = "",
    payload: dict[str, str] | bytes | None = None,
    content_type: str = "application/x-www-form-urlencoded",
    origin: str = ORIGIN,
    extra: dict[str, object] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    body = payload if isinstance(payload, bytes) else urlencode(payload or {}).encode()
    environ: dict[str, object] = {
        "wsgi.url_scheme": "https",
        "HTTP_HOST": "boca.example.test",
        "PATH_INFO": path,
        "REQUEST_METHOD": method,
        "QUERY_STRING": "",
        "HTTP_COOKIE": cookie,
        "HTTP_ORIGIN": origin if method == "POST" else "",
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": content_type,
        "wsgi.input": io.BytesIO(body),
    }
    environ.update(extra or {})
    captured: list[tuple[str, list[tuple[str, str]]]] = []
    response = b"".join(app(environ, lambda status, headers: captured.append((status, headers))))
    status, headers = captured[0]
    return int(status.split()[0]), dict(headers), response


@dataclass
class FakeCommand:
    state: str = "accepted"
    updated_at: float = 1.0


class FakeHost:
    failed = False
    calls: list[tuple[str, str, str]]

    def __init__(self) -> None:
        self.calls = []

    def begin(self, command_id: str, *, member_id: str, event_id: str) -> FakeCommand:
        self.calls.append((command_id, member_id, event_id))
        return FakeCommand()

    def status(self, command_id: str, *, member_id: str) -> FakeCommand | None:
        return FakeCommand()

    def stop(self, command_id: str, *, member_id: str) -> FakeCommand | None:
        return FakeCommand("stopped")


def _app(
    path: Path,
    provider: PasskeyOwnerAuthentication,
    host: FakeHost | None = None,
) -> tuple[PrivatePanelApplication, Database]:
    db = Database(path)
    db.migrate()
    CommandStore(db).migrate()
    db.create_event(EVENT_ID, "Partido sintético")
    app = PrivatePanelApplication(
        origin=ORIGIN,
        database_path=path,
        owner_subject="owner",
        passkey=provider,
        members=MemberEnrollmentService(db, CredentialVault(os.urandom(32))),
        commands=host,
        events={EVENT_ID: "Partido sintético"},
    )
    return app, db


def _login(
    app: PrivatePanelApplication, key: ec.EllipticCurvePrivateKey, credential_id: bytes
) -> str:
    status, _, page = _request(app, "/ingresar")
    assert status == 200 and b"navigator.credentials.get" in page
    challenge = re.search(rb'data-challenge="([A-Za-z0-9_-]+)"', page).group(1).decode()
    assertion = _assertion(key, credential_id, challenge)
    status, headers, body = _request(
        app,
        "/sesion",
        method="POST",
        content_type="application/json",
        payload=json.dumps(asdict(assertion)).encode(),
    )
    assert status == 204 and body == b""
    assert "Secure" in headers["Set-Cookie"] and "HttpOnly" in headers["Set-Cookie"]
    return headers["Set-Cookie"].split(";", 1)[0]


def test_passkey_requires_exact_origin_uv_signature_and_one_use_challenge() -> None:
    clock = [0.0]
    provider, key, credential_id = _passkey(clock)
    first = provider.challenge()
    assert first is not None
    assert provider.challenge() is None
    invalid_origin = _assertion(key, credential_id, first, origin="https://evil.example.test")
    assert provider.verify(invalid_origin) is None
    # Failed origin does not authenticate; a new challenge requires the next budget window.
    clock[0] = 2.0
    second = provider.challenge()
    assert second is not None
    assert provider.verify(_assertion(key, credential_id, second, flags=0x01)) is None
    clock[0] = 4.0
    third = provider.challenge()
    assert third is not None
    proof = _assertion(key, credential_id, third)
    assert provider.verify(proof) is not None
    assert provider.verify(proof) is None


def test_private_login_enrollment_listing_and_local_command_are_connected() -> None:
    clock = [0.0]
    provider, key, credential_id = _passkey(clock)
    host = FakeHost()
    with TemporaryDirectory() as directory:
        app, db = _app(Path(directory) / "boca.sqlite3", provider, host)
        assert _request(app, "/socios")[0] == 401
        assert _request(app, "/comandos")[0] == 401
        cookie = _login(app, key, credential_id)
        status, headers, page = _request(app, "/socios/nuevo", cookie=cookie)
        assert status == 200 and headers["Cache-Control"] == "no-store"
        csrf = re.search(rb'name="csrf" value="([^"]+)"', page).group(1).decode()
        operation = re.search(rb'name="operation_id" value="([^"]+)"', page).group(1).decode()
        fields = {
            "csrf": csrf,
            "operation_id": operation,
            "alias": "Persona de prueba",
            "email": "persona@example.test",
            "password": "test-only-password",
            "consent": "yes",
        }
        assert _request(app, "/socios", cookie=cookie, method="POST", payload=fields)[0] == 201
        status, _, listing = _request(app, "/socios", cookie=cookie)
        assert status == 200 and b"Persona de prueba" in listing
        assert b"test-only-password" not in listing and b"persona@example.test" not in listing
        with db.connection() as connection:
            member_id = connection.execute("SELECT member_id FROM members").fetchone()[0]
            assert connection.execute("SELECT count(*) FROM credentials").fetchone() == (1,)
        status, _, command_page = _request(app, "/comandos", cookie=cookie)
        assert status == 200 and b"Iniciar simulaci" in command_page
        command_id = (
            re.search(rb'name="operation_id" value="([^"]+)"', command_page).group(1).decode()
        )
        csrf = re.search(rb'name="csrf" value="([^"]+)"', command_page).group(1).decode()
        command_fields = {
            "csrf": csrf,
            "operation_id": command_id,
            "member_id": member_id,
            "event_id": EVENT_ID,
        }
        assert (
            _request(app, "/comandos", cookie=cookie, method="POST", payload=command_fields)[0]
            == 429
        )
        sleep(1.05)
        started = _request(app, "/comandos", cookie=cookie, method="POST", payload=command_fields)
        assert started[0] == 303 and started[1]["Location"] == f"/comandos/{command_id}"
        assert host.calls == [(command_id, member_id, EVENT_ID)]
        replay = _request(app, "/comandos", cookie=cookie, method="POST", payload=command_fields)
        assert replay[0] == 303 and len(host.calls) == 1
        assert _request(app, "/estado", cookie=cookie)[0] == 200


def test_cross_origin_csrf_and_spoofed_tls_never_start_simulation() -> None:
    clock = [0.0]
    provider, key, credential_id = _passkey(clock)
    host = FakeHost()
    with TemporaryDirectory() as directory:
        app, db = _app(Path(directory) / "boca.sqlite3", provider, host)
        member_id = MemberEnrollmentService(db, CredentialVault(os.urandom(32))).enroll(
            email="member@example.test",
            password="test-password",
            consent_recorded_at=datetime.now(UTC),
        )
        cookie = _login(app, key, credential_id)
        _, _, page = _request(app, "/comandos", cookie=cookie)
        fields = {
            "csrf": re.search(rb'name="csrf" value="([^"]+)"', page).group(1).decode(),
            "operation_id": re.search(rb'name="operation_id" value="([^"]+)"', page)
            .group(1)
            .decode(),
            "member_id": member_id,
            "event_id": EVENT_ID,
        }
        for extra, origin in (
            ({}, "https://evil.example.test"),
            ({"wsgi.url_scheme": "http", "HTTP_X_FORWARDED_PROTO": "https"}, ORIGIN),
            ({"QUERY_STRING": "member=test"}, ORIGIN),
        ):
            assert (
                _request(
                    app,
                    "/comandos",
                    cookie=cookie,
                    method="POST",
                    payload=fields,
                    origin=origin,
                    extra=extra,
                )[0]
                >= 400
            )
        assert (
            _request(
                app, "/comandos", cookie=cookie, method="POST", payload=dict(fields, csrf="invalid")
            )[0]
            == 403
        )
        assert host.calls == []


def test_credential_rotation_and_revocation_are_local_idempotent_and_redacted() -> None:
    clock = [0.0]
    provider, key, credential_id = _passkey(clock)
    with TemporaryDirectory() as directory:
        path = Path(directory) / "boca.sqlite3"
        db = Database(path)
        db.migrate()
        CommandStore(db).migrate()
        vault = CredentialVault(os.urandom(32))
        service = MemberEnrollmentService(db, vault)
        member_id = service.enroll(
            email="member@example.test",
            password="initial-test-only",
            consent_recorded_at=datetime.now(UTC),
            display_name="<Persona>",
        )
        app = PrivatePanelApplication(
            origin=ORIGIN,
            database_path=path,
            owner_subject="owner",
            passkey=provider,
            members=service,
            commands=None,
            events={},
        )
        cookie = _login(app, key, credential_id)
        status, _, detail = _request(app, f"/socios/{member_id}", cookie=cookie)
        assert status == 200 and b"&lt;Persona&gt;" in detail and b"<Persona>" not in detail
        identifiers = re.findall(rb'name="operation_id" value="([^"]+)"', detail)
        csrf = re.search(rb'name="csrf" value="([^"]+)"', detail).group(1).decode()
        rotation = {
            "csrf": csrf,
            "operation_id": identifiers[0].decode(),
            "password": "rotated-test-only",
        }
        rotated = _request(
            app, f"/socios/{member_id}/credencial", cookie=cookie, method="POST", payload=rotation
        )
        assert rotated[0] == 303
        assert (
            _request(
                app,
                f"/socios/{member_id}/credencial",
                cookie=cookie,
                method="POST",
                payload=rotation,
            )[0]
            == 303
        )
        sealed = db.get_credential(member_id)
        assert sealed is not None and vault.open(sealed, member_id=member_id) == "rotated-test-only"
        assert b"rotated-test-only" not in rotated[2]
        sleep(1.05)
        revocation = {"csrf": csrf, "operation_id": identifiers[1].decode()}
        assert (
            _request(
                app,
                f"/socios/{member_id}/revocar",
                cookie=cookie,
                method="POST",
                payload=revocation,
            )[0]
            == 303
        )
        assert db.get_credential(member_id) is None
        assert (
            _request(
                app,
                f"/socios/{member_id}/revocar",
                cookie=cookie,
                method="POST",
                payload=revocation,
            )[0]
            == 303
        )
        status, _, page = _request(app, "/socios", cookie=cookie)
        assert status == 200 and b"Credencial revocada" in page
        assert b"member@example.test" not in page and b"initial-test-only" not in page
