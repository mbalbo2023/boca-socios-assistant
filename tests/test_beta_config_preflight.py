"""Offline owner/TLS preflight; all credentials and certificates are synthetic."""

from __future__ import annotations

import base64
import socket
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from boca_socios import beta_config_preflight, runtime
from boca_socios.config import Settings

HOST = "boca.example.test"
ORIGIN = f"https://{HOST}"


def _private(path: Path, value: bytes) -> Path:
    path.unlink(missing_ok=True)
    path.write_bytes(value)
    path.chmod(0o400)
    return path


def _certificates(
    host: str = HOST, *, expired: bool = False, encrypted: bool = False
) -> tuple[bytes, bytes, bytes]:
    now = datetime.now(UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic Boca CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=2))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    tls_key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)]))
        .issuer_name(ca_name)
        .public_key(tls_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=2) if expired else now - timedelta(minutes=1))
        .not_valid_after(now - timedelta(days=1) if expired else now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    return (
        leaf.public_bytes(serialization.Encoding.PEM),
        tls_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(b"synthetic-only")
            if encrypted
            else serialization.NoEncryption(),
        ),
        ca.public_bytes(serialization.Encoding.PEM),
    )


def _fixture(tmp_path: Path) -> tuple[Settings, Path, Path]:
    owner = tmp_path / "owner"
    owner.mkdir(mode=0o700)
    key_root = tmp_path / "secrets"
    key_root.mkdir(mode=0o700)
    credential = _private(owner / "credential_id", b"synthetic-credential-id-32-bytes!")
    passkey = ec.generate_private_key(ec.SECP256R1())
    public = _private(
        owner / "public_key.der",
        passkey.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
    )
    cert, key, ca = _certificates()
    certificate = _private(owner / "tls.crt", cert)
    tls_key = _private(owner / "tls.key", key)
    ca_file = _private(owner / "health-ca.pem", ca)
    master = _private(key_root / "boca_master_key", base64.b64encode(b"k" * 32) + b"\n")
    settings = Settings(
        environment="staging",
        runtime_mode="simulation",
        db_path=tmp_path / "no-database.sqlite3",
        master_key_file=master,
        panel_origin=ORIGIN,
        owner_subject="synthetic-owner",
        passkey_credential_id_file=credential,
        passkey_public_key_der_file=public,
        tls_cert_file=certificate,
        tls_key_file=tls_key,
        bind_host="0.0.0.0",  # noqa: S104 - isolated container configuration
        bind_port=8443,
    )
    return settings, owner, ca_file


def test_owner_then_full_check_use_no_socket_or_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, owner, ca = _fixture(tmp_path)

    def no_socket(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("preflight must never open a socket")

    monkeypatch.setattr(socket, "socket", no_socket)
    beta_config_preflight.check_beta_owner(settings, owner_root=owner, ca_file=ca)
    beta_config_preflight.check_beta_config(settings, owner_root=owner, ca_file=ca)
    assert not settings.db_path.exists()


@pytest.mark.parametrize("bad", ["san", "ca", "expired", "key", "encrypted"])
def test_owner_check_rejects_untrusted_tls(tmp_path: Path, bad: str) -> None:
    settings, owner, ca = _fixture(tmp_path)
    if bad == "san":
        cert, key, _ = _certificates("other.example.test")
        _private(owner / "tls.crt", cert)
        _private(owner / "tls.key", key)
    elif bad == "ca":
        _, _, wrong_ca = _certificates()
        _private(ca, wrong_ca)
    elif bad == "expired":
        cert, key, matching_ca = _certificates(expired=True)
        _private(owner / "tls.crt", cert)
        _private(owner / "tls.key", key)
        _private(ca, matching_ca)
    elif bad == "encrypted":
        cert, key, matching_ca = _certificates(encrypted=True)
        _private(owner / "tls.crt", cert)
        _private(owner / "tls.key", key)
        _private(ca, matching_ca)
    else:
        _, wrong_key, _ = _certificates()
        _private(owner / "tls.key", wrong_key)
    with pytest.raises(ValueError, match="owner BETA configuration"):
        beta_config_preflight.check_beta_owner(settings, owner_root=owner, ca_file=ca)
    assert not settings.db_path.exists()


def test_owner_check_rejects_symlink_modes_bad_passkey_and_wrong_origin(tmp_path: Path) -> None:
    settings, owner, ca = _fixture(tmp_path)
    assert settings.passkey_credential_id_file is not None
    credential = settings.passkey_credential_id_file
    credential.chmod(0o644)
    with pytest.raises(ValueError):
        beta_config_preflight.check_beta_owner(settings, owner_root=owner, ca_file=ca)
    credential.chmod(0o400)
    credential.unlink()
    credential.symlink_to(owner / "tls.crt")
    with pytest.raises(ValueError):
        beta_config_preflight.check_beta_owner(settings, owner_root=owner, ca_file=ca)
    credential.unlink()
    _private(credential, b"short")
    with pytest.raises(ValueError):
        beta_config_preflight.check_beta_owner(settings, owner_root=owner, ca_file=ca)
    _private(credential, b"synthetic-credential-id-32-bytes!")
    assert settings.passkey_public_key_der_file is not None
    _private(settings.passkey_public_key_der_file, b"not-a-public-key")
    with pytest.raises(ValueError):
        beta_config_preflight.check_beta_owner(settings, owner_root=owner, ca_file=ca)
    passkey = ec.generate_private_key(ec.SECP256R1())
    _private(
        settings.passkey_public_key_der_file,
        passkey.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
    )
    with pytest.raises(ValueError):
        beta_config_preflight.check_beta_owner(
            replace(settings, panel_origin="https://other.example.test"),
            owner_root=owner,
            ca_file=ca,
        )
    with pytest.raises(ValueError):
        beta_config_preflight.check_beta_owner(
            replace(settings, panel_origin="https://127.0.0.1"),
            owner_root=owner,
            ca_file=ca,
        )
    with pytest.raises(ValueError):
        beta_config_preflight.check_beta_owner(
            replace(settings, panel_origin=f"{ORIGIN}:443"),
            owner_root=owner,
            ca_file=ca,
        )
    owner.chmod(0o755)
    with pytest.raises(ValueError):
        beta_config_preflight.check_beta_owner(settings, owner_root=owner, ca_file=ca)


def test_full_check_requires_master_key_after_owner_only(tmp_path: Path) -> None:
    settings, owner, ca = _fixture(tmp_path)
    settings.master_key_file.unlink()
    beta_config_preflight.check_beta_owner(settings, owner_root=owner, ca_file=ca)
    with pytest.raises(ValueError):
        beta_config_preflight.check_beta_config(settings, owner_root=owner, ca_file=ca)


def test_cli_emits_only_fixed_receipts_on_success_or_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings, owner, ca = _fixture(tmp_path)
    monkeypatch.setattr(Settings, "from_environment", lambda: settings)
    monkeypatch.setattr(beta_config_preflight, "OWNER_ROOT", owner)
    monkeypatch.setenv("BOCA_HEALTH_CA_FILE", str(ca))
    assert runtime.main(("check-beta-owner",)) == 0
    assert capsys.readouterr().out == (
        '{"event":"beta_owner_ready","mode":"simulation","engine":"off"}\n'
    )
    assert runtime.main(("check-beta-config",)) == 0
    assert capsys.readouterr().out == (
        '{"event":"beta_config_ready","mode":"simulation","engine":"off"}\n'
    )
    assert settings.tls_key_file is not None
    settings.tls_key_file.unlink()
    assert runtime.main(("check-beta-owner",)) == 1
    output = capsys.readouterr()
    assert output.out == '{"event":"beta_owner_unavailable"}\n'
    assert output.err == ""
    assert not settings.db_path.exists()
