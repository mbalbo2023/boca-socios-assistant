"""The SSH-only tablet route needs no device CA or public HTTPS listener."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, x25519

from boca_socios.config import Settings
from boca_socios.host_first_deploy import _validate_owner_context
from boca_socios.owner_bootstrap import (
    BootstrapError,
    RecipientReceipt,
    _decrypt,
    seal_for_recipient,
)
from boca_socios.owner_origin import owner_rp_host
from boca_socios.panel.enrollment_http import EnrollmentApplication
from boca_socios.panel.owner_session_store import OwnerBrowserSessionStore
from boca_socios.panel.owner_sessions import OwnerSessions
from boca_socios.panel.passkey import PasskeyOwnerAuthentication
from boca_socios.panel.passkey_registration import OwnerPasskeyRegistration
from boca_socios.panel.private_http import PrivatePanelApplication
from boca_socios.storage.database import Database

ORIGIN = "http://localhost:8443"


def _public() -> bytes:
    return (
        ec.generate_private_key(ec.SECP256R1())
        .public_key()
        .public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    )


def _recipient() -> tuple[x25519.X25519PrivateKey, RecipientReceipt]:
    private = x25519.X25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return private, RecipientReceipt(
        "PREPARED",
        base64.urlsafe_b64encode(public).rstrip(b"=").decode(),
        hashlib.sha256(public).hexdigest(),
    )


def test_exact_http_loopback_origin_is_a_valid_owner_rp() -> None:
    assert owner_rp_host(ORIGIN) == "localhost"
    _validate_owner_context(ORIGIN, "owner")
    assert owner_rp_host("https://owner.example.test") == "owner.example.test"


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost",
        "http://localhost:9000",
        "http://127.0.0.1:8443",
        "http://[::1]:8443",
        "http://other.localhost:8443",
        "http://owner.example.test:8443",
        "http://localhost:8443/",
        "http://localhost:8443?code=secret",
        "http://LOCALHOST:8443",
        "http://localhost:8443@evil.example.test",
    ],
)
def test_http_rp_rejects_aliases_public_hosts_and_other_ports(origin: str) -> None:
    with pytest.raises(ValueError):
        owner_rp_host(origin)


def test_ssh_http_beta_has_no_certificate_configuration_requirement(tmp_path: Path) -> None:
    settings = Settings(
        environment="staging",
        runtime_mode="simulation",
        db_path=tmp_path / "boca.sqlite3",
        master_key_file=tmp_path / "master.key",
        panel_origin=ORIGIN,
        owner_subject="owner",
        passkey_credential_id_file=tmp_path / "credential_id",
        passkey_public_key_der_file=tmp_path / "public_key.der",
        tls_cert_file=None,
        tls_key_file=None,
    )
    settings.validate_beta()


def test_http_localhost_allows_passkey_creation_and_assertion() -> None:
    public = _public()
    registration = OwnerPasskeyRegistration(origin=ORIGIN, rp_id="localhost", owner_subject="owner")
    challenge = registration.begin()
    assert challenge is not None and challenge.rp_id == "localhost"
    assertion = PasskeyOwnerAuthentication(
        credential_id=os.urandom(32),
        public_key_der=public,
        rp_id="localhost",
        origin=ORIGIN,
        owner_subject="owner",
        permissions=frozenset({"members:enroll"}),
    )
    assert assertion.challenge()


def test_http_localhost_panel_and_enrollment_require_exact_origin(tmp_path: Path) -> None:
    passkey = PasskeyOwnerAuthentication(
        credential_id=os.urandom(32),
        public_key_der=_public(),
        rp_id="localhost",
        origin=ORIGIN,
        owner_subject="owner",
        permissions=frozenset({"members:enroll"}),
    )
    database = Database(tmp_path / "boca.sqlite3")
    database.migrate()
    OwnerBrowserSessionStore(database, owner_subject="owner").migrate()
    application = PrivatePanelApplication(
        origin=ORIGIN,
        database_path=tmp_path / "boca.sqlite3",
        owner_subject="owner",
        passkey=passkey,
        members=None,  # type: ignore[arg-type]  # no mutations occur in this gate test
        commands=None,
        events={},
    )
    EnrollmentApplication(None, OwnerSessions(owner_subject="owner"), origin=ORIGIN)
    for scheme, host, expected in [
        ("http", "localhost:8443", 200),
        ("https", "localhost:8443", 400),
        ("http", "127.0.0.1:8443", 400),
        ("http", "localhost:9000", 400),
    ]:
        statuses: list[str] = []
        application(
            {
                "wsgi.url_scheme": scheme,
                "HTTP_HOST": host,
                "PATH_INFO": "/ingresar",
                "REQUEST_METHOD": "GET",
                "QUERY_STRING": "",
                "CONTENT_LENGTH": "",
                "HTTP_ORIGIN": "",
            },
            lambda status, _headers, captured=statuses: captured.append(status),
        )
        assert int(statuses[0].split()[0]) == expected


@pytest.mark.parametrize("encoded_tls_salt", [False, True], ids=["random-salt", "encoded-tls-salt"])
def test_http_localhost_owner_envelope_only_contains_public_passkey_material(
    monkeypatch: pytest.MonkeyPatch, encoded_tls_salt: bool
) -> None:
    if encoded_tls_salt:
        original_urandom = os.urandom
        # Valid synthetic salt whose base64url starts with "tls". Other entropy
        # and all production cryptography remain unchanged.
        salt = bytes.fromhex("b65b00") + bytes(13)
        monkeypatch.setattr(
            "boca_socios.owner_bootstrap.os.urandom",
            lambda size: salt if size == 16 else original_urandom(size),
        )
    private, recipient = _recipient()
    bundle = {"credential_id": os.urandom(32), "public_key.der": _public()}
    sealed = seal_for_recipient(recipient, bundle, ORIGIN, "owner")
    envelope = json.loads(sealed)
    assert set(envelope) == {
        "version",
        "repository",
        "purpose",
        "uid",
        "panel_origin",
        "owner_subject",
        "recipient_public_key",
        "recipient_fingerprint",
        "ephemeral_public_key",
        "salt",
        "nonce",
        "ciphertext",
    }
    assert envelope["purpose"] == "boca-owner-passkey-v2"
    assert envelope["panel_origin"] == ORIGIN
    if encoded_tls_salt:
        assert envelope["salt"] == "tlsAAAAAAAAAAAAAAAAAAA"
    restored = _decrypt(
        sealed,
        private.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        ),
        recipient,
        ORIGIN,
        "owner",
    )
    assert set(restored) == {"credential_id", "public_key.der"}
    assert restored == bundle


@pytest.mark.parametrize(
    "artifact",
    ["tls.crt", "tls.key", "health-ca.pem", "private_key.der", "owner_recipient_x25519.key"],
)
def test_http_owner_envelope_rejects_tls_and_private_artifact_fields(artifact: str) -> None:
    _, recipient = _recipient()
    bundle = {
        "credential_id": os.urandom(32),
        "public_key.der": _public(),
        artifact: b"synthetic-disallowed-material",
    }
    with pytest.raises(BootstrapError, match="invalid_owner_material"):
        seal_for_recipient(recipient, bundle, ORIGIN, "owner")


def test_http_owner_envelope_rejects_private_der_in_public_key_slot() -> None:
    _, recipient = _recipient()
    private_der = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    with pytest.raises(BootstrapError, match="invalid_owner_material"):
        seal_for_recipient(
            recipient,
            {"credential_id": os.urandom(32), "public_key.der": private_der},
            ORIGIN,
            "owner",
        )
