"""Opt-in, read-only DNS/HTTPS egress receipt from a *running* Boca worker.

No URL, token, account, SITE_URL or arbitrary hostname crosses this API.
One fixed neutral HTTPS HEAD is intentionally separate from Chromium, IPC,
site navigation, and any ticket/reservation action. Nothing is persisted.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import sys
from collections.abc import Callable, Sequence
from typing import Protocol

_HOST = "example.com"  # Neutral Internet reachability target; NEVER the socios site.
_PORT = 443
_TIMEOUT_SECONDS = 5.0
_PREFIX = "BOCA_WORKER_EGRESS "


class _HTTPSResponse(Protocol):
    status: int


class _HTTPSConnection(Protocol):
    sock: socket.socket | None

    def request(self, method: str, path: str, *, headers: dict[str, str]) -> None: ...

    def getresponse(self) -> _HTTPSResponse: ...

    def close(self) -> None: ...


def _public_ipv4_records(records: object) -> str | None:
    if not isinstance(records, list) or not records:
        return None
    selected: str | None = None
    for record in records:
        if (
            not isinstance(record, tuple)
            or len(record) != 5
            or record[0] != socket.AF_INET
            or not isinstance(record[4], tuple)
            or len(record[4]) != 2
            or type(record[4][0]) is not str
            or record[4][1] != _PORT
        ):
            return None
        try:
            public = ipaddress.IPv4Address(record[4][0])
            if not public.is_global:
                return None
            if selected is None:
                selected = str(public)
        except ipaddress.AddressValueError:
            return None
    return selected


def probe(
    *,
    resolve: Callable[..., object] = socket.getaddrinfo,
    dial: Callable[..., socket.socket] = socket.create_connection,
    tls_context: Callable[[], ssl.SSLContext] = ssl.create_default_context,
    connect: Callable[..., _HTTPSConnection] = http.client.HTTPConnection,
) -> str:
    """One verified A record, one pinned IPv4 TCP dial and SNI-verified HEAD.

    The fixed returned line excludes IPs, hostnames, status codes and errors.
    The Docker/rootless namespace and exact image identity are verified by the
    caller. Site navigation and browser activity are intentionally untouched.
    """
    try:
        records = resolve(_HOST, _PORT, family=socket.AF_INET, type=socket.SOCK_STREAM)
        public_ipv4 = _public_ipv4_records(records)
        if public_ipv4 is None:
            return _PREFIX + "state=NO_GO stage=dns"
    except (OSError, ValueError, TypeError):
        return _PREFIX + "state=NO_GO stage=dns"

    raw_socket: socket.socket | None = None
    tls_socket: ssl.SSLSocket | None = None
    connection: _HTTPSConnection | None = None
    try:
        context = tls_context()
        if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
            return _PREFIX + "state=NO_GO stage=tls"
        # No hostname reaches the TCP dial, and HTTPConnection must never call
        # connect(): its socket is explicitly set to the verified TLS socket.
        raw_socket = dial((public_ipv4, _PORT), timeout=_TIMEOUT_SECONDS)
        tls_socket = context.wrap_socket(raw_socket, server_hostname=_HOST)
        raw_socket = None  # TLS wrapper now owns the underlying descriptor.
        connection = connect(_HOST, _PORT, timeout=_TIMEOUT_SECONDS)
        connection.sock = tls_socket
        connection.request("HEAD", "/", headers={"Host": _HOST, "Connection": "close"})
        response = connection.getresponse()
        if type(response.status) is not int or not 200 <= response.status < 500:
            return _PREFIX + "state=NO_GO stage=https"
        return _PREFIX + "state=PASS dns=PASS https=PASS"
    except ssl.SSLError:
        return _PREFIX + "state=NO_GO stage=tls"
    except (OSError, http.client.HTTPException, ValueError, TypeError):
        return _PREFIX + "state=NO_GO stage=https"
    finally:
        if connection is not None:
            try:
                connection.close()
            except OSError:
                # Never export the underlying remote exception or connection.
                pass
        elif tls_socket is not None:
            try:
                tls_socket.close()
            except OSError:
                pass
        if raw_socket is not None:
            try:
                raw_socket.close()
            except OSError:
                pass


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["--once"]:
        print(_PREFIX + "state=NO_GO stage=arguments")
        return 2
    # The host attestor consumes this fixed receipt, so a connectivity NO_GO
    # is a *valid diagnostic result* rather than lost Docker-exec stdout.
    print(probe())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
