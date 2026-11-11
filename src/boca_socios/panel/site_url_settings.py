"""Owner-managed HTTP destination for an isolated Boca simulation.

This module only stores a URL; it does not navigate, alter Docker, or claim
that a stopped worker inherited a changed environment. The host must explicitly
transport the reviewed setting to the isolated worker at its next activation.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import secrets
import stat
from pathlib import Path
from urllib.parse import urlsplit

_BASENAME = "boca-site-url.json"
_MAX_URL = 512
_MAX_FILE = 2048


class SiteUrlInvalid(ValueError):
    """The destination is not a well-formed credential-free HTTP URL."""


class SiteUrlSettingsUnavailable(RuntimeError):
    """The Boca-owned configuration file is absent in an unsafe form."""


def require_site_url(value: str) -> str:
    """Validate syntax, not public/private host class or DNS resolution."""
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= _MAX_URL
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
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (port is not None and port < 1)
    ):
        raise SiteUrlInvalid("SITE_URL debe ser una URL HTTP(S) sin credenciales.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", hostname):
            raise SiteUrlInvalid("El nombre del sitio no es válido.") from None
    else:
        # The user removed the public-address filter. Preserve only the
        # unrelated dangerous-address guard (e.g. host metadata endpoints).
        if address.is_link_local or address.is_multicast or address.is_unspecified:
            raise SiteUrlInvalid("La dirección del sitio no es utilizable.")
    return value


class SiteUrlSettingsStore:
    """Small atomic, no-symlink file in the existing *Boca-only* data volume."""

    def __init__(self, path: Path) -> None:
        if not path.is_absolute() or path.name != _BASENAME:
            raise ValueError("an exact Boca SITE_URL configuration path is required")
        self.path = path

    @classmethod
    def for_database(cls, database_path: Path) -> SiteUrlSettingsStore:
        if not database_path.is_absolute():
            raise ValueError("Boca database path must be absolute")
        return cls(database_path.with_name(_BASENAME))

    def _directory(self) -> int:
        try:
            fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            info = os.fstat(fd)
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_mode & 0o022
            ):
                raise OSError("untrusted directory")
            return fd
        except OSError:
            if "fd" in locals():
                os.close(fd)
            raise SiteUrlSettingsUnavailable("Boca SITE_URL storage is not isolated") from None

    def _read_from(self, directory: int) -> str | None:
        try:
            fd = os.open(self.path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        except FileNotFoundError:
            return None
        except OSError:
            raise SiteUrlSettingsUnavailable("Boca SITE_URL cannot be read safely") from None
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_mode & 0o777 != 0o600
                or info.st_size > _MAX_FILE
            ):
                raise SiteUrlSettingsUnavailable("Boca SITE_URL file integrity failed")
            body = os.read(fd, _MAX_FILE + 1)
            parsed = json.loads(body)
            if (
                not isinstance(parsed, dict)
                or set(parsed) != {"version", "SITE_URL"}
                or parsed["version"] != 1
                or type(parsed["SITE_URL"]) is not str
            ):
                raise ValueError("unexpected schema")
            return require_site_url(parsed["SITE_URL"])
        except (ValueError, UnicodeError, json.JSONDecodeError, SiteUrlInvalid):
            raise SiteUrlSettingsUnavailable("Boca SITE_URL file integrity failed") from None
        finally:
            os.close(fd)

    def read(self) -> str | None:
        directory = self._directory()
        try:
            return self._read_from(directory)
        finally:
            os.close(directory)

    def save(self, site_url: str) -> None:
        destination = require_site_url(site_url)
        directory = self._directory()
        temp_name = ".boca-site-url-" + secrets.token_hex(8)
        try:
            # Do not overwrite, follow, or silently repair a corrupt target.
            self._read_from(directory)
            try:
                temp_fd = os.open(
                    temp_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory,
                )
                try:
                    document = json.dumps(
                        {"version": 1, "SITE_URL": destination}, separators=(",", ":")
                    ).encode("utf-8")
                    if os.write(temp_fd, document) != len(document):
                        raise OSError("incomplete settings write")
                    os.fsync(temp_fd)
                finally:
                    os.close(temp_fd)
                os.replace(temp_name, self.path.name, src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                try:
                    os.unlink(temp_name, dir_fd=directory)
                except FileNotFoundError:
                    pass
        except (OSError, ValueError):
            raise SiteUrlSettingsUnavailable("Boca SITE_URL cannot be saved safely") from None
        finally:
            os.close(directory)
