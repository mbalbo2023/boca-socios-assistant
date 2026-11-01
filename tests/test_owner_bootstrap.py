"""Synthetic owner custody proof; no real device, host, DNS or credentials."""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from boca_socios import owner_bootstrap as boot

ORIGIN = "https://owner.boca.example.test"
SUBJECT = "synthetic-owner"
HOST = "owner.boca.example.test"


def _bundle(host: str = HOST) -> dict[str, bytes]:
    key = ec.generate_private_key(ec.SECP256R1())
    tls_key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(UTC)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(tls_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(tls_key, hashes.SHA256())
        .public_bytes(serialization.Encoding.PEM)
    )
    return {
        "credential_id": b"synthetic-passkey-id-32-bytes-only",
        "public_key.der": key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
        "tls.crt": certificate,
        "tls.key": tls_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        "health-ca.pem": certificate,
    }


def _owner(tmp_path: Path) -> Path:
    directory = tmp_path / "owner"
    directory.mkdir(mode=0o700, parents=True)
    return directory


def test_sealed_real_shape_installs_only_owner_files_once(tmp_path: Path) -> None:
    directory = _owner(tmp_path)
    receipt = boot.prepare(directory, uid=os.geteuid())
    assert receipt.state == "PREPARED"
    assert boot.prepare(directory, uid=os.geteuid()).state == "ALREADY_PREPARED"
    bundle = _bundle()
    envelope = boot.seal_for_recipient(receipt, bundle, ORIGIN, SUBJECT)
    assert all(content not in envelope for content in bundle.values())
    assert (
        boot.install(directory, envelope, ORIGIN, SUBJECT, uid=os.geteuid()) == receipt.fingerprint
    )
    for name, content in bundle.items():
        path = directory / name
        assert path.read_bytes() == content
        assert stat.S_IMODE(path.stat().st_mode) == 0o400
        assert path.stat().st_nlink == 1
    assert boot.verify(directory, ORIGIN, SUBJECT, uid=os.geteuid()) == receipt.fingerprint
    with pytest.raises(boot.BootstrapError, match="already_configured"):
        boot.install(directory, envelope, ORIGIN, SUBJECT, uid=os.geteuid())
    assert not (directory / "boca.sqlite3").exists()


def test_exact_tunnel_origin_seals_installs_and_verifies(tmp_path: Path) -> None:
    origin = "https://localhost:8443"
    directory = _owner(tmp_path)
    receipt = boot.prepare(directory, uid=os.geteuid())
    envelope = boot.seal_for_recipient(receipt, _bundle("localhost"), origin, SUBJECT)
    assert (
        boot.install(directory, envelope, origin, SUBJECT, uid=os.geteuid()) == receipt.fingerprint
    )
    assert boot.verify(directory, origin, SUBJECT, uid=os.geteuid()) == receipt.fingerprint
    with pytest.raises(boot.BootstrapError):
        boot.verify(directory, ORIGIN, SUBJECT, uid=os.geteuid())


def test_ssh_only_http_custody_seals_no_certificate_or_ca(tmp_path: Path) -> None:
    origin = "http://localhost:8443"
    owner = _owner(tmp_path)
    receipt = boot.prepare(owner, uid=os.geteuid())
    bundle = {name: value for name, value in _bundle().items() if name in boot.HTTP_LIMITS}
    envelope = boot.seal_for_recipient(receipt, bundle, origin, SUBJECT)
    header = json.loads(envelope)
    assert header["purpose"] == boot.HTTP_PURPOSE
    assert all(private not in envelope for private in bundle.values())
    with pytest.raises(boot.BootstrapError):
        boot.install(owner, envelope, ORIGIN, SUBJECT, uid=os.geteuid())
    assert boot.install(owner, envelope, origin, SUBJECT, uid=os.geteuid()) == receipt.fingerprint
    assert boot.verify(owner, origin, SUBJECT, uid=os.geteuid()) == receipt.fingerprint
    assert {path.name for path in owner.iterdir()} == set(boot.HTTP_LIMITS) | {boot.PRIVATE_KEY}
    (owner / "health-ca.pem").symlink_to(tmp_path / "missing-ca")
    with pytest.raises(boot.BootstrapError, match="unexpected_tls_artifact"):
        boot.verify(owner, origin, SUBJECT, uid=os.geteuid())


def test_wrong_recipient_origin_tamper_and_invalid_tls_have_no_owner_effect(tmp_path: Path) -> None:
    a, b = _owner(tmp_path / "a"), _owner(tmp_path / "b")
    receipt = boot.prepare(a, uid=os.geteuid())
    boot.prepare(b, uid=os.geteuid())
    bundle = _bundle()
    envelope = boot.seal_for_recipient(receipt, bundle, ORIGIN, SUBJECT)
    for directory, payload, origin, subject in (
        (b, envelope, ORIGIN, SUBJECT),
        (a, envelope, "https://wrong.example.test", SUBJECT),
        (a, envelope, ORIGIN, "another-owner"),
        (a, envelope[:-1] + b"x", ORIGIN, SUBJECT),
    ):
        with pytest.raises(boot.BootstrapError):
            boot.install(directory, payload, origin, subject, uid=os.geteuid())
        assert not any((directory / name).exists() for name in boot.LIMITS)
    bad = {**bundle, "tls.crt": _bundle("wrong.example.test")["tls.crt"]}
    with pytest.raises(boot.BootstrapError, match="invalid_owner_material"):
        boot.seal_for_recipient(receipt, bad, ORIGIN, SUBJECT)
    tampered = json.loads(envelope)
    tampered["purpose"] = "other"
    with pytest.raises(boot.BootstrapError):
        boot.install(a, json.dumps(tampered).encode(), ORIGIN, SUBJECT, uid=os.geteuid())
    assert not any((a / name).exists() for name in boot.LIMITS)


def test_symlink_and_partial_state_preserved_without_retry(tmp_path: Path) -> None:
    directory = _owner(tmp_path)
    receipt = boot.prepare(directory, uid=os.geteuid())
    envelope = boot.seal_for_recipient(receipt, _bundle(), ORIGIN, SUBJECT)
    (directory / "credential_id").symlink_to(tmp_path / "outside")
    with pytest.raises(boot.BootstrapError, match="already_configured"):
        boot.install(directory, envelope, ORIGIN, SUBJECT, uid=os.geteuid())
    assert not (tmp_path / "outside").exists()
    (directory / "credential_id").unlink()
    original = boot._write_new

    def fail_second(parent: int, name: str, content: bytes, uid: int) -> None:
        if name == "public_key.der":
            raise boot.BootstrapError("synthetic_write_interrupted")
        original(parent, name, content, uid)

    with patch.object(boot, "_write_new", side_effect=fail_second):
        with pytest.raises(boot.BootstrapError, match="synthetic_write_interrupted"):
            boot.install(directory, envelope, ORIGIN, SUBJECT, uid=os.geteuid())
    assert (directory / "credential_id").exists()
    assert not (directory / "public_key.der").exists()
    with pytest.raises(boot.BootstrapError, match="already_configured"):
        boot.install(directory, envelope, ORIGIN, SUBJECT, uid=os.geteuid())
    with pytest.raises(boot.BootstrapError):
        boot.verify(directory, ORIGIN, SUBJECT, uid=os.geteuid())


@pytest.mark.parametrize(
    "origin",
    [
        "http://owner.boca.example.test",
        "https://owner.boca.example.test/",
        "https://owner.boca.example.test:443",
        "https://localhost",
        "https://localhost:9000",
        "https://boca.localhost:8443",
        "https://127.0.0.1:8443",
        "https://LOCALHOST:8443",
        "https://localhost:8443/",
        "https://owner.boca.example.test/path",
    ],
)
def test_origin_must_be_stable_https_rp(origin: str) -> None:
    with pytest.raises(boot.BootstrapError, match="invalid_coordinates"):
        boot._coordinates(origin, SUBJECT)
