"""New-only private TLS material generated and retained on the owner device."""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from boca_socios.beta_config_preflight import _tls_handshake

RP_ID = "localhost"
TLS_FILES = {"tls.crt": 8192, "tls.key": 4096, "health-ca.pem": 8192}


class CeremonyError(ValueError):
    """The caller must not expose a private input or exception detail."""


def _device_dir(path: Path) -> int:
    if not path.is_absolute() or ".." in path.parts:
        raise CeremonyError("unsafe_device_directory")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        raise CeremonyError("unsafe_device_directory") from None
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise CeremonyError("unsafe_device_directory")
    except (OSError, CeremonyError):
        os.close(descriptor)
        raise CeremonyError("unsafe_device_directory") from None
    return descriptor


def _write_new(directory: int, name: str, content: bytes) -> None:
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=directory,
    )
    with os.fdopen(descriptor, "wb") as item:
        item.write(content)
        item.flush()
        os.fchmod(item.fileno(), 0o400)
        os.fsync(item.fileno())
    os.fsync(directory)


def prepare_device_tls(path: Path, *, now: datetime | None = None) -> str:
    """Create a new private device directory, never overwrite or export a CA key."""
    if not path.is_absolute() or ".." in path.parts:
        raise CeremonyError("unsafe_device_directory")
    try:
        parent = path.parent
        parent_info = parent.stat()
        if (
            parent.resolve(strict=True) != parent
            or parent_info.st_uid != os.geteuid()
            or stat.S_IMODE(parent_info.st_mode) & 0o077
        ):
            raise CeremonyError("unsafe_device_directory")
        os.mkdir(path, 0o700)
        directory = _device_dir(path)
    except (OSError, CeremonyError):
        raise CeremonyError("unsafe_device_directory") from None
    try:
        instant = now or datetime.now(UTC)
        ca_key = ec.generate_private_key(ec.SECP256R1())
        leaf_key = ec.generate_private_key(ec.SECP256R1())
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Boca owner local CA")])
        leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, RP_ID)])
        ca = (
            x509.CertificateBuilder()
            .subject_name(ca_name)
            .issuer_name(ca_name)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(instant - timedelta(minutes=1))
            .not_valid_after(instant + timedelta(days=90))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(
                x509.KeyUsage(False, False, False, False, False, True, True, False, False),
                critical=True,
            )
            .sign(ca_key, hashes.SHA256())
        )
        leaf = (
            x509.CertificateBuilder()
            .subject_name(leaf_name)
            .issuer_name(ca_name)
            .public_key(leaf_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(instant - timedelta(minutes=1))
            .not_valid_after(instant + timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(RP_ID)]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(True, False, False, False, False, False, False, False, False),
                critical=True,
            )
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        files = {
            "tls.crt": leaf.public_bytes(serialization.Encoding.PEM),
            "tls.key": leaf_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
            "health-ca.pem": ca.public_bytes(serialization.Encoding.PEM),
        }
        for name, value in files.items():
            if len(value) > TLS_FILES[name]:
                raise CeremonyError("invalid_device_tls")
            _write_new(directory, name, value)
        _tls_handshake(path / "tls.crt", path / "tls.key", path / "health-ca.pem", RP_ID)
        return ca.fingerprint(hashes.SHA256()).hex()
    except (OSError, ValueError):
        # Preserve partial files for owner-side review; never overwrite on retry.
        raise CeremonyError("invalid_device_tls") from None
    finally:
        os.close(directory)


def read_device_tls(path: Path) -> dict[str, bytes]:
    directory = _device_dir(path)
    result: dict[str, bytes] = {}
    try:
        for name, limit in TLS_FILES.items():
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=directory,
            )
            with os.fdopen(descriptor, "rb") as item:
                metadata = os.fstat(item.fileno())
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_uid != os.geteuid()
                    or metadata.st_dev != os.fstat(directory).st_dev
                    or metadata.st_nlink != 1
                    or stat.S_IMODE(metadata.st_mode) != 0o400
                    or not 0 < metadata.st_size <= limit
                ):
                    raise CeremonyError("invalid_device_tls")
                result[name] = item.read(limit + 1)
                if len(result[name]) != metadata.st_size:
                    raise CeremonyError("invalid_device_tls")
    except OSError:
        raise CeremonyError("invalid_device_tls") from None
    finally:
        os.close(directory)
    try:
        _tls_handshake(path / "tls.crt", path / "tls.key", path / "health-ca.pem", RP_ID)
    except ValueError:
        raise CeremonyError("invalid_device_tls") from None
    return result
