"""Offline, synthetic HTTP-first-owner enrollment; no droplet or real Android key."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from boca_socios import owner_bootstrap as custody
from boca_socios import owner_enrollment as enrollment


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


TOKEN = _b64(b"synthetic-key-32-bytes-long!!!!!!!")
SUBJECT = "synthetic-owner"


def _request(
    app: enrollment.OneUseOwnerEnrollment,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    origin: str = enrollment.ORIGIN,
    host: str = enrollment.HOST,
    scheme: str = "http",
    query: str = "",
    session: str | None = None,
) -> tuple[int, dict[str, Any] | bytes, dict[str, str]]:
    raw = json.dumps(body, separators=(",", ":")).encode() if body is not None else b""
    environ: dict[str, Any] = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "wsgi.url_scheme": scheme,
        "HTTP_HOST": host,
        "HTTP_ORIGIN": origin,
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": str(len(raw)),
        "wsgi.input": BytesIO(raw),
    }
    if session is not None:
        environ["HTTP_X_BOCA_ENROLLMENT"] = session
    result: dict[str, Any] = {}

    def start(status: str, headers: list[tuple[str, str]]) -> None:
        result["status"] = int(status.split()[0])
        result["headers"] = dict(headers)

    payload = b"".join(app(environ, start))
    content: dict[str, Any] | bytes = (
        payload
        if method == "GET" and result["status"] == 200
        else json.loads(payload)
    )
    return result["status"], content, result["headers"]


def _new(
    tmp_path: Path, *, clock: list[float] | None = None
) -> tuple[enrollment.OneUseOwnerEnrollment, Path, Path]:
    owner = tmp_path / "owner"
    owner.mkdir(mode=0o700, parents=True)
    receipt = custody.prepare(owner, uid=os.geteuid())
    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)
    app = enrollment.OneUseOwnerEnrollment(
        capability_digest=hashlib.sha256(base64.urlsafe_b64decode(TOKEN + "=")).digest(),
        staging_dir=staging,
        recipient=receipt,
        owner_subject=SUBJECT,
        uid=os.geteuid(),
        clock=(lambda: clock[0]) if clock is not None else (lambda: 100.0),
    )
    return app, staging, owner


def _cose(key: ec.EllipticCurvePrivateKey) -> bytes:
    point = key.public_key().public_numbers()
    return (
        b"\xa5\x01\x02\x03\x26\x20\x01\x21\x58\x20"
        + point.x.to_bytes(32, "big")
        + b"\x22\x58\x20"
        + point.y.to_bytes(32, "big")
    )


def _creation(challenge: str, key: ec.EllipticCurvePrivateKey) -> dict[str, Any]:
    identifier = b"synthetic-owner-credential-id"
    client = json.dumps(
        {"type": "webauthn.create", "challenge": challenge, "origin": enrollment.ORIGIN}
    ).encode()
    authenticator = (
        hashlib.sha256(b"localhost").digest()
        + b"\x45"
        + bytes(4)
        + bytes(16)
        + len(identifier).to_bytes(2, "big")
        + identifier
        + _cose(key)
    )
    return {
        "credential_id": _b64(identifier),
        "client_data_json": _b64(client),
        "authenticator_data": _b64(authenticator),
        "public_key_der": _b64(
            key.public_key().public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        ),
        "public_key_algorithm": -7,
    }


def _proof(challenge: str, key: ec.EllipticCurvePrivateKey) -> dict[str, str]:
    client = json.dumps(
        {"type": "webauthn.get", "challenge": challenge, "origin": enrollment.ORIGIN}
    ).encode()
    authenticator = hashlib.sha256(b"localhost").digest() + b"\x05" + bytes(4)
    signature = key.sign(authenticator + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
    return {
        "credential_id": _b64(b"synthetic-owner-credential-id"),
        "client_data_json": _b64(client),
        "authenticator_data": _b64(authenticator),
        "signature": _b64(signature),
    }


def test_url_fragment_not_sent_to_server_or_manual_input(tmp_path: Path) -> None:
    app, staging, owner = _new(tmp_path)
    status, page, headers = _request(app, "GET", "/activar")
    assert status == 200 and isinstance(page, bytes)
    assert b"http://localhost:8443" in page
    assert b"certificado" not in page.lower()
    assert b"type=\"password\"" not in page
    assert headers["Cache-Control"] == "no-store"
    assert headers["Referrer-Policy"] == "no-referrer"
    status, script, _ = _request(app, "GET", "/activar.js")
    assert status == 200 and isinstance(script, bytes)
    assert b"location.hash" in script and b"history.replaceState" in script
    assert b"navigator.credentials.create" in script
    assert b"navigator.credentials.get" in script
    assert b"residentKey: 'required'" in script
    assert b"userVerification: 'required'" in script
    assert not (owner / "credential_id").exists()
    assert not (staging / "owner-envelope.v2").exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"origin": "http://localhost:9000"},
        {"host": "127.0.0.1:8443"},
        {"scheme": "https"},
        {"query": "key=public-leak"},
    ],
)
def test_wrong_http_boundary_never_begins(tmp_path: Path, changes: dict[str, str]) -> None:
    app, staging, owner = _new(tmp_path)
    assert _request(app, "POST", "/begin", {"capability": TOKEN}, **changes)[0] == 403
    assert app.stopped.is_set()
    assert not (owner / "credential_id").exists()
    assert not (staging / "owner-envelope.v2").exists()


def test_capability_one_attempt_fail_closed(tmp_path: Path) -> None:
    app, staging, owner = _new(tmp_path)
    assert _request(app, "POST", "/begin", {})[0] == 403
    assert _request(app, "POST", "/begin", {"capability": TOKEN})[0] == 410
    assert not (owner / "credential_id").exists()
    assert not (staging / "owner-envelope.v2").exists()


def test_expiry_closes_without_side_effects(tmp_path: Path) -> None:
    clock = [100.0]
    app, staging, owner = _new(tmp_path, clock=clock)
    clock[0] = 1000.0
    assert _request(app, "POST", "/begin", {"capability": TOKEN})[0] == 410
    assert not (owner / "credential_id").exists()
    assert not (staging / "owner-envelope.v2").exists()


def test_full_synthetic_chrome_enrollment_writes_only_public_owner_key(tmp_path: Path) -> None:
    app, staging, owner = _new(tmp_path)
    key = ec.generate_private_key(ec.SECP256R1())
    status, begin, _ = _request(app, "POST", "/begin", {"capability": TOKEN})
    assert status == 200 and isinstance(begin, dict)
    assert begin["rp_id"] == "localhost"
    assert _request(app, "POST", "/begin", {"capability": TOKEN})[0] == 403
    # The preceding replay deliberately fails closed; a fresh one-use session
    # proves successful creation and persistence instead.
    app, staging, owner = _new(tmp_path / "successful")
    _, begin, _ = _request(app, "POST", "/begin", {"capability": TOKEN})
    assert isinstance(begin, dict)
    status, proof, _ = _request(
        app,
        "POST",
        "/creation",
        {"operation_id": begin["operation_id"], "response": _creation(begin["challenge"], key)},
        session=begin["session"],
    )
    assert status == 200 and isinstance(proof, dict)
    status, finish, _ = _request(
        app,
        "POST",
        "/proof",
        {"operation_id": begin["operation_id"], "assertion": _proof(proof["challenge"], key)},
        session=begin["session"],
    )
    assert status == 200 and finish == {"state": "configured"}
    assert app.stopped.is_set()
    assert not (owner / "credential_id").exists()
    envelope = (staging / "owner-envelope.v2").read_bytes()
    assert b"credential_id" not in envelope
    assert b"public_key.der" not in envelope
    assert set(staging.iterdir()) == {staging / "owner-envelope.v2"}
    assert (staging / "owner-envelope.v2").stat().st_mode & 0o777 == 0o400
    # This is a *different, offline* operation; the HTTP service never sees
    # the private owner X25519 recipient key or the owner volume itself.
    custody.install(owner, envelope, enrollment.ORIGIN, SUBJECT, uid=os.geteuid())
    assert (owner / "credential_id").read_bytes() == b"synthetic-owner-credential-id"
    assert all((owner / name).stat().st_mode & 0o777 == 0o400 for name in ("credential_id", "public_key.der"))
    assert not any(name.endswith((".key", ".crt", ".pem")) for name in os.listdir(owner) if name != custody.PRIVATE_KEY)
    assert custody.verify(owner, enrollment.ORIGIN, SUBJECT, uid=os.geteuid())
    assert _request(app, "POST", "/proof", {})[0] == 410


def test_existing_owner_material_rejected_before_listening(tmp_path: Path) -> None:
    app, staging, _ = _new(tmp_path)
    (staging / "owner-envelope.v2").write_bytes(b"existing")
    owner = tmp_path / "owner"
    receipt = custody.prepare(owner, uid=os.geteuid())
    with pytest.raises(custody.BootstrapError):
        enrollment.OneUseOwnerEnrollment(
            capability_digest=hashlib.sha256(base64.urlsafe_b64decode(TOKEN + "=")).digest(),
            staging_dir=staging,
            recipient=receipt,
            owner_subject=SUBJECT,
            uid=os.geteuid(),
        )
    assert not app.stopped.is_set()  # independent, earlier app state is unaffected
