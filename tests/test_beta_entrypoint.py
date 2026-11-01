"""Only disposable local TLS, public test passkey, and synthetic Boca storage."""

from __future__ import annotations

import base64
import http.client
import socket
import sqlite3
import ssl
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from boca_socios import healthcheck
from boca_socios import runtime as runtime_module
from boca_socios.config import Settings
from boca_socios.integration.bridge_client import SITE_ORIGIN
from boca_socios.integration.operational import LocalRuntimeUnavailable
from boca_socios.runtime import SIMULATION_EVENT_ID, build_beta_server, initialize_beta

ORIGIN = "https://boca.example.test"


def _private(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    path.chmod(0o400)
    return path


def _port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _settings(tmp_path: Path) -> Settings:
    owner = ec.generate_private_key(ec.SECP256R1())
    credential = _private(tmp_path / "credential_id", b"synthetic-owner-credential-id")
    public = _private(
        tmp_path / "public_key.der",
        owner.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
    )
    tls = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(UTC)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "boca.example.test")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(tls.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("boca.example.test")]), critical=False
        )
        .sign(tls, hashes.SHA256())
    )
    cert_pem = certificate.public_bytes(serialization.Encoding.PEM)
    cert = _private(tmp_path / "tls.crt", cert_pem)
    _private(tmp_path / "health-ca.pem", cert_pem)
    key = _private(
        tmp_path / "tls.key",
        tls.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    master = _private(tmp_path / "boca.key", base64.b64encode(b"k" * 32) + b"\n")
    return Settings(
        environment="development",
        runtime_mode="simulation",
        db_path=tmp_path / "boca.sqlite3",
        master_key_file=master,
        panel_origin=ORIGIN,
        owner_subject="synthetic-owner",
        passkey_credential_id_file=credential,
        passkey_public_key_der_file=public,
        tls_cert_file=cert,
        tls_key_file=key,
        bind_host="127.0.0.1",
        bind_port=_port(),
    )


def _request(port: int, path: str, *, host: str = "boca.example.test") -> tuple[int, bytes]:
    context = ssl._create_unverified_context()  # noqa: S323, SLF001 - disposable local test cert
    connection = http.client.HTTPSConnection("127.0.0.1", port, timeout=3, context=context)
    try:
        connection.request("GET", path, headers={"Host": host})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def test_new_only_initialization_and_existing_only_restart(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(LocalRuntimeUnavailable):
        build_beta_server(settings)
    assert not settings.db_path.exists()
    initialize_beta(settings)
    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute(
            "SELECT label FROM events WHERE event_id=?", (SIMULATION_EVENT_ID,)
        ).fetchone() == ("Evento de prueba local",)
        versions = connection.execute("SELECT version FROM schema_migrations").fetchall()
    with pytest.raises(LocalRuntimeUnavailable):
        initialize_beta(settings)
    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute("SELECT version FROM schema_migrations").fetchall() == versions


def test_served_tls_health_requires_ready_loop_and_owner_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    initialize_beta(settings)
    for key, value in {
        "BOCA_DB_PATH": str(settings.db_path),
        "BOCA_MASTER_KEY_FILE": str(settings.master_key_file),
        "BOCA_PANEL_ORIGIN": ORIGIN,
        "BOCA_OWNER_SUBJECT": settings.owner_subject,
        "BOCA_PASSKEY_CREDENTIAL_ID_FILE": str(settings.passkey_credential_id_file),
        "BOCA_PASSKEY_PUBLIC_KEY_DER_FILE": str(settings.passkey_public_key_der_file),
        "BOCA_TLS_CERT_FILE": str(settings.tls_cert_file),
        "BOCA_TLS_KEY_FILE": str(settings.tls_key_file),
        "BOCA_BIND_PORT": str(settings.bind_port),
        "BOCA_BIND_HOST": "127.0.0.1",
        "BOCA_HEALTH_CA_FILE": str(tmp_path / "health-ca.pem"),
        "BOCA_HEALTH_MODE": "beta",
    }.items():
        monkeypatch.setenv(key, value)
    assert healthcheck.main() == 1
    served = build_beta_server(settings)
    assert served.runtime.ready
    stopping = Event()
    thread = Thread(target=served.serve_until, args=(stopping,), daemon=True)
    thread.start()
    try:
        assert _request(settings.bind_port, "/healthz") == (200, b"BOCA_BETA_READY")
        assert healthcheck.main() == 0
        assert _request(settings.bind_port, "/ingresar")[0] == 200
        assert _request(settings.bind_port, "/socios")[0] == 401
        assert _request(settings.bind_port, "/healthz", host="evil.example")[0] == 503
        monkeypatch.setenv("BOCA_HEALTH_CA_FILE", str(tmp_path / "missing-ca.pem"))
        assert healthcheck.main() == 1
        monkeypatch.setenv("BOCA_HEALTH_CA_FILE", str(tmp_path / "health-ca.pem"))
        with socket.create_connection(("127.0.0.1", settings.bind_port), timeout=2) as plain:
            plain.sendall(b"GET /healthz HTTP/1.0\r\n\r\n")
        assert healthcheck.main() == 0
        with sqlite3.connect(settings.db_path) as connection, connection:
            connection.execute("DELETE FROM events WHERE event_id=?", (SIMULATION_EVENT_ID,))
        assert healthcheck.main() == 1
    finally:
        stopping.set()
        thread.join(timeout=3)
        served.close()
    assert not thread.is_alive()
    assert not served.runtime.ready
    assert healthcheck.main() == 1


def test_refuses_unsafe_identity_and_tls_files_before_listener(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    initialize_beta(settings)
    assert settings.tls_key_file is not None
    settings.tls_key_file.chmod(0o644)
    with pytest.raises(ValueError, match="unsafe"):
        build_beta_server(settings)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", settings.bind_port))
    settings.tls_key_file.chmod(0o400)
    assert settings.passkey_credential_id_file is not None
    settings.passkey_credential_id_file.unlink()
    settings.passkey_credential_id_file.symlink_to(tmp_path / "tls.crt")
    with pytest.raises(ValueError, match="unavailable"):
        build_beta_server(settings)


def test_site_bridge_is_explicit_and_secret_gated_before_listener(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    initialize_beta(settings)
    assert settings.validate_bridge() is False
    bridge_settings = replace(
        settings,
        site_bridge_mode="poll",
        site_origin=SITE_ORIGIN,
        site_token_file=tmp_path / "missing-token",
        site_hmac_key_file=tmp_path / "missing-hmac",
        source_sha="a" * 40,
    )
    with pytest.raises(ValueError, match="unavailable"):
        build_beta_server(bridge_settings)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", settings.bind_port))
    with pytest.raises(ValueError, match="configuration"):
        replace(bridge_settings, site_origin="https://other.chatgpt.site").validate_bridge()
    with pytest.raises(ValueError, match="configuration"):
        replace(bridge_settings, source_sha="unverified").validate_bridge()

    _private(tmp_path / "missing-token", b"synthetic-bypass-token-no-live")
    _private(tmp_path / "missing-hmac", b"h" * 32)

    class LocalOnlyTransport:
        states: list[str] = []

        def lease(self) -> None:
            return None

        def heartbeat(self, _sha: str, state: str, _snapshot: object) -> None:
            self.states.append(state)

        def ack(self, _lease: object, _state: str) -> None:
            raise AssertionError("no synthetic Site operation was leased")

    local = LocalOnlyTransport()
    monkeypatch.setattr(runtime_module, "SiteBridgeTransport", lambda **_kwargs: local)
    served = build_beta_server(bridge_settings)
    try:
        assert served.bridge is not None and not served.bridge.failed
        assert served.runtime.ready
    finally:
        served.close()
    assert not served.runtime.ready and local.states[-1] == "stopping"
