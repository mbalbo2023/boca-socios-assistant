"""Boca-only, config-file transport between the dashboard and cold browser worker.

The controller owns the sole writable mount; the browser worker receives a
read-only mount containing this one URL, never the controller's database,
passkey, credential or Telegram volumes. No function here starts navigation.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import secrets
import stat
from pathlib import Path
from urllib.parse import unquote, urlsplit

RUNTIME_SITE_URL_PATH = Path("/run/boca-site-config/boca-site-url.runtime.json")
_BASENAME = RUNTIME_SITE_URL_PATH.name
_MAX_URL = 512
_MAX_FILE = 2048
_FILE_MODE = 0o644  # Worker UID 10002 needs read access to this URL-only file.
_DIRECTORY_MODE = 0o711  # Worker may traverse, never list the Boca config volume.


class SiteUrlInvalid(ValueError):
    """A URL is not credential-free, syntactically safe HTTP(S)."""


class RuntimeSiteUrlUnavailable(RuntimeError):
    """A runtime URL has no verified, exact Boca-only file representation."""


def require_site_url(value: str) -> str:
    """Validate syntax, not public/private class or DNS resolution.

    The owner intentionally allows public and private destinations. No network
    request is performed by this validator or any runtime-config operation.
    """
    if not isinstance(value, str):
        raise SiteUrlInvalid("SITE_URL debe ser una URL HTTP(S) válida.")
    try:
        byte_size = len(value.encode("utf-8"))
    except UnicodeError:
        raise SiteUrlInvalid("SITE_URL debe ser una URL HTTP(S) válida.") from None
    if (
        not 1 <= byte_size <= _MAX_URL
        or value != value.strip()
        or any(ord(character) <= 32 or ord(character) == 127 for character in value)
    ):
        raise SiteUrlInvalid("SITE_URL debe ser una URL HTTP(S) válida.")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise SiteUrlInvalid("SITE_URL debe ser una URL HTTP(S) válida.") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or not parsed.netloc
        or parsed.netloc.endswith(":")
        or parsed.username is not None
        or parsed.password is not None
        or "?" in value
        or "#" in value
        or parsed.query
        or parsed.fragment
        or (port is not None and port < 1)
    ):
        raise SiteUrlInvalid("SITE_URL debe ser una URL HTTP(S) sin credenciales.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        labels = hostname.split(".")
        if len(hostname) > 253 or any(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None for label in labels
        ):
            raise SiteUrlInvalid("El nombre del sitio no es válido.") from None
        # WHATWG/Chromium turns short, decimal, octal and hexadecimal IPv4
        # authorities into addresses, e.g. 2852039166 -> 169.254.169.254.
        # Accept only canonical dotted-quad IPs via ipaddress above; never
        # allow a numeric DNS-looking alias to bypass the metadata IP guard.
        final_label = labels[-1]
        if final_label.isdecimal() or re.fullmatch(r"0x[0-9a-f]+", final_label):
            raise SiteUrlInvalid("La dirección numérica no es canónica.") from None
    else:
        # This is not a public URL restriction: reject only addresses that can
        # reach metadata/link-local or unusable network destinations.
        if address.is_link_local or address.is_multicast or address.is_unspecified:
            raise SiteUrlInvalid("La dirección del sitio no es utilizable.")
    if hostname == "api.telegram.org":
        # Telegram Bot API token-bearing endpoints are not browser destinations.
        # Decode encoded route bytes so the common /%62ot... variant is denied.
        route = parsed.path
        for _ in range(2):
            route = unquote(route)
            if route.lower().startswith("/bot"):
                raise SiteUrlInvalid("No se permiten rutas con tokens de Telegram.")
    return value


def site_url_fingerprint(site_url: str) -> str:
    """Stable revision witness, not a signature or permission to navigate."""
    return hashlib.sha256(b"BOCA_SITE_URL_V1\0" + require_site_url(site_url).encode()).hexdigest()


def _path(path: Path) -> None:
    if not isinstance(path, Path) or not path.is_absolute() or path.name != _BASENAME:
        raise RuntimeSiteUrlUnavailable("Boca runtime SITE_URL path unverified")


def _directory(path: Path, *, owner_uid: int, owner_gid: int, readonly: bool) -> int:
    # O_PATH is crucial: UID 10002 only has execute/search, not read/list,
    # permission on this 0711 directory, yet may open the fixed child by name.
    flags = os.O_PATH if readonly else os.O_RDONLY
    try:
        descriptor = os.open(path.parent, flags | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(info.st_mode)
            or (info.st_uid, info.st_gid) != (owner_uid, owner_gid)
            or stat.S_IMODE(info.st_mode) != _DIRECTORY_MODE
        ):
            raise OSError("unverified Boca runtime directory")
        return descriptor
    except OSError:
        if "descriptor" in locals():
            os.close(descriptor)
        raise RuntimeSiteUrlUnavailable("Boca runtime SITE_URL directory unverified") from None


def _read_from(directory: int, *, owner_uid: int, owner_gid: int) -> str | None:
    try:
        descriptor = os.open(
            _BASENAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory
        )
    except FileNotFoundError:
        return None
    except OSError:
        raise RuntimeSiteUrlUnavailable("Boca runtime SITE_URL inode unverified") from None
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or (info.st_uid, info.st_gid) != (owner_uid, owner_gid)
            or stat.S_IMODE(info.st_mode) != _FILE_MODE
            or info.st_nlink != 1
            or not 0 < info.st_size <= _MAX_FILE
        ):
            raise RuntimeSiteUrlUnavailable("Boca runtime SITE_URL file unverified")
        data = os.read(descriptor, _MAX_FILE + 1)
        after = os.fstat(descriptor)
        if len(data) != info.st_size or (
            after.st_dev,
            after.st_ino,
            after.st_mtime_ns,
            after.st_size,
        ) != (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size):
            raise RuntimeSiteUrlUnavailable("Boca runtime SITE_URL read changed")
        document = json.loads(data)
        if (
            not isinstance(document, dict)
            or set(document) != {"version", "SITE_URL", "sha256"}
            or type(document["version"]) is not int
            or document["version"] != 1
            or type(document["SITE_URL"]) is not str
            or type(document["sha256"]) is not str
        ):
            raise RuntimeSiteUrlUnavailable("Boca runtime SITE_URL schema unverified")
        destination = require_site_url(document["SITE_URL"])
        if document["sha256"] != site_url_fingerprint(destination):
            raise RuntimeSiteUrlUnavailable("Boca runtime SITE_URL revision unverified")
        return destination
    except (OSError, ValueError, TypeError, UnicodeError):
        raise RuntimeSiteUrlUnavailable("Boca runtime SITE_URL invalid") from None
    finally:
        os.close(descriptor)


def read_site_url(
    path: Path = RUNTIME_SITE_URL_PATH,
    *,
    owner_uid: int = 10001,
    owner_gid: int = 10001,
) -> str:
    """Read only the newest inode on each worker START; no implicit fallback."""
    _path(path)
    directory = _directory(path, owner_uid=owner_uid, owner_gid=owner_gid, readonly=True)
    try:
        destination = _read_from(directory, owner_uid=owner_uid, owner_gid=owner_gid)
        if destination is None:
            raise RuntimeSiteUrlUnavailable("Boca runtime SITE_URL not configured")
        return destination
    finally:
        os.close(directory)


def publish_site_url(
    path: Path,
    site_url: str,
    *,
    owner_uid: int = 10001,
    owner_gid: int = 10001,
) -> str:
    """Atomically publish one URL into a preprovisioned Boca config-only mount.

    A missing directory, unexpected owner, malformed existing inode or write
    failure is NO_GO. In particular, this never repairs or mounts host paths.
    """
    destination = require_site_url(site_url)
    _path(path)
    if (os.geteuid(), os.getegid()) != (owner_uid, owner_gid):
        raise RuntimeSiteUrlUnavailable("Boca runtime SITE_URL writer identity unverified")
    directory = _directory(path, owner_uid=owner_uid, owner_gid=owner_gid, readonly=False)
    temp_name = ".boca-site-url-" + secrets.token_hex(8)
    fingerprint = site_url_fingerprint(destination)
    try:
        _read_from(directory, owner_uid=owner_uid, owner_gid=owner_gid)
        descriptor = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=directory,
        )
        try:
            content = json.dumps(
                {"version": 1, "SITE_URL": destination, "sha256": fingerprint},
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
            if len(content) > _MAX_FILE or os.write(descriptor, content) != len(content):
                raise OSError("Boca runtime SITE_URL short write")
            os.fchmod(descriptor, _FILE_MODE)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temp_name, _BASENAME, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
        return fingerprint
    except OSError:
        raise RuntimeSiteUrlUnavailable("Boca runtime SITE_URL publication failed") from None
    finally:
        try:
            os.unlink(temp_name, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.close(directory)
