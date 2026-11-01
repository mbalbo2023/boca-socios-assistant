"""Synthetic device-local owner ceremony; no Android passkey or host operation."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import ssl
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from threading import Thread
from typing import Any
from wsgiref.simple_server import WSGIServer

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtensionOID

from boca_socios import owner_bootstrap as boot
from boca_socios import owner_ceremony as ceremony

CAP = base64.urlsafe_b64encode(b"synthetic-token-" + b"x" * 16).rstrip(b"=").decode()
SUBJECT = "synthetic-owner"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _request(
    app: ceremony.LocalOwnerCeremony,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    origin: str = ceremony.ORIGIN,
    host: str = ceremony.HOST,
    scheme: str = "https",
    session: str | None = None,
    query: str = "",
) -> tuple[int, dict[str, Any] | bytes, dict[str, str]]:
    raw = json.dumps(body, separators=(",", ":")).encode() if body is not None else b""
    metadata: dict[str, Any] = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "wsgi.url_scheme": scheme,
        "HTTPS": "on" if scheme == "https" else "off",
        "HTTP_HOST": host,
        "HTTP_ORIGIN": origin,
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": str(len(raw)),
        "wsgi.input": BytesIO(raw),
    }
    if session is not None:
        metadata["HTTP_X_BOCA_CEREMONY"] = session
    response: dict[str, Any] = {}

    def start(status: str, headers: list[tuple[str, str]]) -> None:
        response["status"] = int(status.split()[0])
        response["headers"] = dict(headers)

    content = b"".join(app(metadata, start))
    parsed: dict[str, Any] | bytes = (
        content
        if path in {"/", "/ceremony.js"} and response["status"] == 200
        else json.loads(content)
    )
    return response["status"], parsed, response["headers"]


def _cose(key: ec.EllipticCurvePrivateKey) -> bytes:
    numbers = key.public_key().public_numbers()
    return (
        b"\xa5\x01\x02\x03\x26\x20\x01\x21\x58\x20"
        + numbers.x.to_bytes(32, "big")
        + b"\x22\x58\x20"
        + numbers.y.to_bytes(32, "big")
    )


def _creation(
    challenge: str,
    key: ec.EllipticCurvePrivateKey,
    *,
    origin: str = ceremony.ORIGIN,
    flags: int = 0x45,
) -> dict[str, Any]:
    credential_id = b"synthetic-owner-credential-id"
    client = json.dumps(
        {"type": "webauthn.create", "challenge": challenge, "origin": origin},
        separators=(",", ":"),
    ).encode()
    auth = (
        hashlib.sha256(ceremony.RP_ID.encode()).digest()
        + bytes([flags])
        + bytes(4)
        + bytes(16)
        + len(credential_id).to_bytes(2, "big")
        + credential_id
        + _cose(key)
    )
    return {
        "credential_id": _b64(credential_id),
        "client_data_json": _b64(client),
        "authenticator_data": _b64(auth),
        "public_key_der": _b64(
            key.public_key().public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        ),
        "public_key_algorithm": -7,
    }


def _assertion(
    challenge: str,
    key: ec.EllipticCurvePrivateKey,
    *,
    origin: str = ceremony.ORIGIN,
    flags: int = 0x05,
) -> dict[str, str]:
    client = json.dumps(
        {"type": "webauthn.get", "challenge": challenge, "origin": origin},
        separators=(",", ":"),
    ).encode()
    auth = hashlib.sha256(ceremony.RP_ID.encode()).digest() + bytes([flags]) + bytes(4)
    signature = key.sign(auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
    return {
        "credential_id": _b64(b"synthetic-owner-credential-id"),
        "client_data_json": _b64(client),
        "authenticator_data": _b64(auth),
        "signature": _b64(signature),
    }


def _setup(
    tmp_path: Path, clock: list[float] | None = None
) -> tuple[ceremony.LocalOwnerCeremony, Path]:
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    device = tmp_path / "device"
    ceremony.prepare_device_tls(device)
    host = tmp_path / "synthetic-recipient"
    host.mkdir(mode=0o700)
    receipt = boot.prepare(host, uid=os.geteuid())
    app = ceremony.LocalOwnerCeremony(
        capability=CAP,
        recipient=receipt,
        owner_subject=SUBJECT,
        tls=ceremony.read_device_tls(device),
        clock=(lambda: clock[0]) if clock is not None else (lambda: 100.0),
    )
    return app, host


def test_tls_generated_only_in_new_private_device_directory(tmp_path: Path) -> None:
    device = tmp_path / "device"
    fingerprint = ceremony.prepare_device_tls(device, now=datetime.now(UTC))
    assert len(fingerprint) == 64
    assert set(path.name for path in device.iterdir()) == set(ceremony.TLS_FILES)
    assert all(path.stat().st_mode & 0o777 == 0o400 for path in device.iterdir())
    cert = x509.load_pem_x509_certificate((device / "tls.crt").read_bytes())
    sans = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
    assert sans.get_values_for_type(x509.DNSName) == ["localhost"]
    assert ceremony.read_device_tls(device)["health-ca.pem"]
    with pytest.raises(ceremony.CeremonyError):
        ceremony.prepare_device_tls(device)
    assert not (device / "ca.key").exists()


def test_no_anonymous_begin_and_one_use_capability(tmp_path: Path) -> None:
    app, _ = _setup(tmp_path)
    status, page, headers = _request(app, "GET", "/")
    assert status == 200 and isinstance(page, bytes)
    assert b"navigator.credentials" not in page
    assert headers["Cache-Control"] == "no-store"
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    status, script, _ = _request(app, "GET", "/ceremony.js")
    assert status == 200 and isinstance(script, bytes)
    assert b"navigator.credentials.create" in script and b"navigator.credentials.get" in script
    assert b"navigator.clipboard.writeText" in script
    assert b"input cifrado protegido" in script and b"issues, PRs ni chats" in script
    assert _request(app, "POST", "/begin", {})[0] == 403
    assert app.stopped.is_set()
    assert _request(app, "POST", "/begin", {"capability": CAP})[0] == 410


@pytest.mark.parametrize(
    "change",
    [
        {"origin": "https://localhost:9000"},
        {"host": "127.0.0.1:8443"},
        {"scheme": "http"},
        {"query": "capability=leak"},
    ],
)
def test_wrong_origin_host_tls_or_query_stops_without_challenge(
    tmp_path: Path, change: dict[str, str]
) -> None:
    app, _ = _setup(tmp_path)
    status, result, _ = _request(app, "POST", "/begin", {"capability": CAP}, **change)
    assert status == 403 and result == {"error": "invalid_origin"}
    assert app.stopped.is_set()


def test_expired_capability_and_wrong_value_close(tmp_path: Path) -> None:
    clock = [100.0]
    app, _ = _setup(tmp_path / "expired", clock)
    clock[0] = 220.0
    assert _request(app, "POST", "/begin", {"capability": CAP})[0] == 410
    app, _ = _setup(tmp_path / "wrong")
    wrong = _b64(b"x" * 32)
    assert _request(app, "POST", "/begin", {"capability": wrong})[0] == 403
    assert app.stopped.is_set()


def test_session_timeout_and_recipient_mismatch_fail_closed(tmp_path: Path) -> None:
    clock = [100.0]
    app, host = _setup(tmp_path, clock)
    assert _request(app, "POST", "/begin", {"capability": CAP})[0] == 200
    clock[0] = 460.0
    assert _request(app, "POST", "/creation", {})[0] == 410
    assert app.stopped.is_set()
    receipt = boot.prepare(host, uid=os.geteuid())
    wrong = boot.RecipientReceipt(receipt.state, receipt.public_key, "0" * 64)
    with pytest.raises(ceremony.CeremonyError, match="invalid_coordinates"):
        ceremony.LocalOwnerCeremony(
            capability=CAP,
            recipient=wrong,
            owner_subject=SUBJECT,
            tls=ceremony.read_device_tls(tmp_path / "device"),
        )


def test_success_seals_only_public_passkey_and_matching_device_tls_then_stops(
    tmp_path: Path,
) -> None:
    app, host = _setup(tmp_path)
    status, begin, _ = _request(app, "POST", "/begin", {"capability": CAP})
    assert status == 200 and isinstance(begin, dict)
    assert begin["rp_id"] == "localhost" and begin["timeout_ms"] == 120000
    assert _request(app, "POST", "/begin", {"capability": CAP})[0] == 403
    # A replayed begin kills this one-use process, so use a fresh process for success.
    app, host = _setup(tmp_path / "success")
    _, begin, _ = _request(app, "POST", "/begin", {"capability": CAP})
    assert isinstance(begin, dict)
    key = ec.generate_private_key(ec.SECP256R1())
    status, proof, _ = _request(
        app,
        "POST",
        "/creation",
        {"operation_id": begin["operation_id"], "response": _creation(begin["challenge"], key)},
        session=begin["session"],
    )
    assert status == 200 and isinstance(proof, dict)
    status, result, headers = _request(
        app,
        "POST",
        "/proof",
        {"operation_id": begin["operation_id"], "assertion": _assertion(proof["challenge"], key)},
        session=begin["session"],
    )
    assert status == 200 and isinstance(result, dict)
    assert set(result) == {"envelope"} and headers["Cache-Control"] == "no-store"
    assert app.stopped.is_set()
    envelope = base64.urlsafe_b64decode(result["envelope"] + "=" * (-len(result["envelope"]) % 4))
    assert len(envelope) <= boot.MAX_ENVELOPE and b"synthetic-owner-credential-id" not in envelope
    assert b"PRIVATE KEY" not in envelope
    assert boot.install(host, envelope, ceremony.ORIGIN, SUBJECT, uid=os.geteuid())
    assert (host / "credential_id").read_bytes() == b"synthetic-owner-credential-id"
    assert _request(app, "POST", "/proof", {}, session=begin["session"])[0] == 410


@pytest.mark.parametrize(
    "stage",
    ["creation-origin", "creation-uv", "proof-origin", "proof-uv", "proof-signature", "session"],
)
def test_wrong_origin_uv_signature_or_session_fails_closed(tmp_path: Path, stage: str) -> None:
    app, _ = _setup(tmp_path)
    _, begin, _ = _request(app, "POST", "/begin", {"capability": CAP})
    assert isinstance(begin, dict)
    key = ec.generate_private_key(ec.SECP256R1())
    creation = _creation(
        begin["challenge"],
        key,
        origin="https://localhost:9000" if stage == "creation-origin" else ceremony.ORIGIN,
        flags=0x41 if stage == "creation-uv" else 0x45,
    )
    status, proof, _ = _request(
        app,
        "POST",
        "/creation",
        {"operation_id": begin["operation_id"], "response": creation},
        session=_b64(b"x" * 32) if stage == "session" else begin["session"],
    )
    if stage.startswith("creation") or stage == "session":
        assert status == 403 and app.stopped.is_set()
        return
    assert status == 200 and isinstance(proof, dict)
    signing_key = ec.generate_private_key(ec.SECP256R1()) if stage == "proof-signature" else key
    assertion = _assertion(
        proof["challenge"],
        signing_key,
        origin="https://localhost:9000" if stage == "proof-origin" else ceremony.ORIGIN,
        flags=0x01 if stage == "proof-uv" else 0x05,
    )
    assert (
        _request(
            app,
            "POST",
            "/proof",
            {"operation_id": begin["operation_id"], "assertion": assertion},
            session=begin["session"],
        )[0]
        == 403
    )
    assert app.stopped.is_set()


def test_tls_tamper_and_symlink_fail_before_any_listener(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = tmp_path / "device"
    ceremony.prepare_device_tls(device)
    tls = device / "tls.key"
    tls.chmod(0o600)
    tls.write_text("broken")
    tls.chmod(0o400)
    monkeypatch.setattr(ceremony, "_LocalTLSServer", lambda *_args: pytest.fail("listener opened"))
    with pytest.raises(ceremony.CeremonyError):
        ceremony.serve_device(device, boot.RecipientReceipt("PREPARED", "", ""), SUBJECT, CAP)
    tls.unlink()
    tls.symlink_to(tmp_path / "outside")
    with pytest.raises(ceremony.CeremonyError):
        ceremony.read_device_tls(device)


def test_server_is_fixed_loopback_quiet_and_no_outbound_code() -> None:
    assert ceremony._LocalTLSServer.allow_reuse_address is False
    assert ceremony._QuietHandler.log_message is not None
    source = Path(ceremony.__file__).read_text()
    assert 'super().__init__(("127.0.0.1", 8443), _QuietHandler)' in source
    assert "urlopen(" not in source and "create_connection(" not in source


def test_serving_context_closes_after_invalid_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, host = _setup(tmp_path)
    receipt = boot.prepare(host, uid=os.geteuid())
    servers: list[Any] = []

    class FakeServer:
        def __init__(self, _context: object) -> None:
            self.app: ceremony.LocalOwnerCeremony | None = None
            self.closed = False
            servers.append(self)

        def __enter__(self) -> FakeServer:
            return self

        def __exit__(self, *_args: object) -> None:
            self.closed = True

        def set_app(self, app: ceremony.LocalOwnerCeremony) -> None:
            self.app = app

        def handle_request(self) -> None:
            assert self.app is not None
            assert _request(self.app, "POST", "/begin", {"capability": _b64(b"x" * 32)})[0] == 403

    monkeypatch.setattr(ceremony, "_LocalTLSServer", FakeServer)
    ceremony.serve_device(tmp_path / "device", receipt, SUBJECT, CAP)
    assert len(servers) == 1 and servers[0].closed


def test_real_local_tls_page_uses_device_ca_and_exact_origin(tmp_path: Path) -> None:
    app, _ = _setup(tmp_path)
    device = tmp_path / "device"
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(str(device / "tls.crt"), str(device / "tls.key"))

    class Ephemeral(ceremony._LocalTLSServer):
        def __init__(self, context: ssl.SSLContext) -> None:
            self._context = context
            WSGIServer.__init__(self, ("127.0.0.1", 0), ceremony._QuietHandler)

    with Ephemeral(server_context) as server:
        server.set_app(app)
        worker = Thread(target=server.handle_request)
        worker.start()
        client_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        client_context.load_verify_locations(cafile=str(device / "health-ca.pem"))
        with socket.create_connection(("127.0.0.1", server.server_port), timeout=2) as raw:
            with client_context.wrap_socket(raw, server_hostname="localhost") as client:
                client.sendall(
                    b"GET / HTTP/1.1\r\nHost: localhost:8443\r\nConnection: close\r\n\r\n"
                )
                chunks = []
                while chunk := client.recv(8192):
                    chunks.append(chunk)
        worker.join(timeout=2)
        assert not worker.is_alive()
    response = b"".join(chunks)
    assert b"200 OK" in response and b"Alta privada de la llave Boca" in response
    assert b"Cache-Control: no-store" in response
    assert not app.stopped.is_set()  # GET never calls begin
