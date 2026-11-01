"""No-listener owner/TLS gate for the isolated simulation BETA image.

This checks only local configuration and performs an in-memory TLS handshake.
It neither opens a network socket nor reads, creates or migrates the database.
"""

from __future__ import annotations

import os
import ssl
import stat
from contextlib import ExitStack
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from boca_socios.config import Settings
from boca_socios.integration.bridge_client import SiteBridgeTransport
from boca_socios.owner_origin import owner_rp_host
from boca_socios.panel.passkey import PasskeyOwnerAuthentication
from boca_socios.security.credential_vault import CredentialVault

OWNER_ROOT = Path("/run/owner")


def _owner_files(root: Path, names: tuple[str, ...]) -> dict[str, bytes]:
    """Read fixed files by owner-directory descriptor, rejecting links and modes."""
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY
    try:
        directory = os.open(root, flags)
        with ExitStack() as stack:
            stack.callback(os.close, directory)
            metadata = os.fstat(directory)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or metadata.st_gid != os.getegid()
                or stat.S_IMODE(metadata.st_mode) != 0o700
            ):
                raise ValueError("owner BETA configuration is unsafe")
            limits = {
                "credential_id": 1024,
                "public_key.der": 512,
                "tls.crt": 16384,
                "tls.key": 8192,
                "health-ca.pem": 16384,
            }
            result: dict[str, bytes] = {}
            for name in names:
                descriptor = os.open(
                    name,
                    os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=directory,
                )
                with os.fdopen(descriptor, "rb") as item:
                    info = os.fstat(item.fileno())
                    if (
                        not stat.S_ISREG(info.st_mode)
                        or info.st_uid != metadata.st_uid
                        or info.st_gid != metadata.st_gid
                        or info.st_dev != metadata.st_dev
                        or info.st_nlink != 1
                        or stat.S_IMODE(info.st_mode) != 0o400
                    ):
                        raise ValueError("owner BETA configuration is unsafe")
                    payload = item.read(limits[name] + 1)
                    if not payload or len(payload) > limits[name]:
                        raise ValueError("owner BETA configuration is invalid")
                    result[name] = payload
            return result
    except OSError:
        raise ValueError("owner BETA configuration is unavailable") from None


def _tls_handshake(cert_file: Path, key_file: Path, ca_file: Path, hostname: str) -> None:
    """Verify key pairing, issuer, SAN and time without a listener or network."""
    try:
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.minimum_version = ssl.TLSVersion.TLSv1_2
        # An encrypted key is an invalid bundle; never ask for a passphrase.
        server_context.load_cert_chain(str(cert_file), str(key_file), password=lambda: b"")
        client_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        client_context.minimum_version = ssl.TLSVersion.TLSv1_2
        client_context.verify_mode = ssl.CERT_REQUIRED
        client_context.check_hostname = True
        # Deliberately trust only this Boca owner-volume CA, not system roots.
        client_context.load_verify_locations(cafile=str(ca_file))
        client_in, client_out = ssl.MemoryBIO(), ssl.MemoryBIO()
        server_in, server_out = ssl.MemoryBIO(), ssl.MemoryBIO()
        client = client_context.wrap_bio(
            client_in, client_out, server_side=False, server_hostname=hostname
        )
        server = server_context.wrap_bio(server_in, server_out, server_side=True)
        client_done = server_done = False
        for _ in range(16):
            if not client_done:
                try:
                    client.do_handshake()
                    client_done = True
                except ssl.SSLWantReadError:
                    pass
            to_server = client_out.read()
            if to_server:
                server_in.write(to_server)
            if not server_done:
                try:
                    server.do_handshake()
                    server_done = True
                except ssl.SSLWantReadError:
                    pass
            to_client = server_out.read()
            if to_client:
                client_in.write(to_client)
            if client_done and server_done:
                return
        raise ValueError("owner BETA configuration TLS proof incomplete")
    except (OSError, ssl.SSLError):
        raise ValueError("owner BETA configuration TLS proof failed") from None


def check_beta_owner(settings: Settings, *, ca_file: Path, owner_root: Path = OWNER_ROOT) -> None:
    """Validate public passkey and TLS owner bundle before creating a key volume."""
    settings.validate_beta()
    try:
        host = owner_rp_host(settings.panel_origin)
    except ValueError:
        raise ValueError("owner BETA configuration is invalid") from None
    if (
        settings.bind_host != "0.0.0.0"  # noqa: S104 - only inside isolated container
        or settings.bind_port != 8443
        or not owner_root.is_absolute()
        or settings.passkey_credential_id_file != owner_root / "credential_id"
        or settings.passkey_public_key_der_file != owner_root / "public_key.der"
        or settings.tls_cert_file != owner_root / "tls.crt"
        or settings.tls_key_file != owner_root / "tls.key"
        or ca_file != owner_root / "health-ca.pem"
    ):
        raise ValueError("owner BETA configuration is invalid")
    bundle = _owner_files(
        owner_root,
        ("credential_id", "public_key.der", "tls.crt", "tls.key", "health-ca.pem"),
    )
    public_der = bundle["public_key.der"]
    try:
        public_key = serialization.load_der_public_key(public_der)
        if (
            not isinstance(public_key, ec.EllipticCurvePublicKey)
            or not isinstance(public_key.curve, ec.SECP256R1)
            or public_key.public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            != public_der
        ):
            raise ValueError("owner BETA configuration public key invalid")
        PasskeyOwnerAuthentication(
            credential_id=bundle["credential_id"],
            public_key_der=public_der,
            rp_id=host,
            origin=settings.panel_origin,
            owner_subject=settings.owner_subject,
            permissions=frozenset({"members:enroll"}),
        )
    except (TypeError, ValueError):
        raise ValueError("owner BETA configuration public credential invalid") from None
    assert settings.tls_cert_file is not None and settings.tls_key_file is not None
    _tls_handshake(settings.tls_cert_file, settings.tls_key_file, ca_file, host)


def check_beta_config(settings: Settings, *, ca_file: Path, owner_root: Path = OWNER_ROOT) -> None:
    """Validate the full local serving configuration before creating data."""
    check_beta_owner(settings, ca_file=ca_file, owner_root=owner_root)
    CredentialVault.from_secret_file(settings.master_key_file)
    if settings.validate_bridge():
        assert settings.site_token_file is not None and settings.site_hmac_key_file is not None
        SiteBridgeTransport(
            origin=settings.site_origin,
            token_file=settings.site_token_file,
            hmac_key_file=settings.site_hmac_key_file,
        )
