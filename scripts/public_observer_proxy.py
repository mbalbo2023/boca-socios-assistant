"""Disposable runner-only CONNECT gate; exact host, public pinned IP, one TLS tunnel.

This is not a generic proxy and is never installed on the droplet. It does not
decrypt TLS, log payloads, follow redirects, or claim to count encrypted HTTP.
"""

from __future__ import annotations

import ipaddress
import json
import select
import socket
import time
from collections.abc import Callable

HOST = "bocasocios.bocajuniors.com.ar"
PORT = 18080
MAX_HELLO = 32768
MAX_SERVER_BYTES = 2 * 1024 * 1024
MAX_CLIENT_BYTES = 65536


def exact_connect(header: bytes) -> bool:
    """Reject IP literals, alternate hosts, extra bytes and credential-bearing requests."""
    if len(header) > 4096 or not header.endswith(b"\r\n\r\n"):
        return False
    try:
        lines = header.decode("ascii").split("\r\n")
    except UnicodeDecodeError:
        return False
    if lines[0] != f"CONNECT {HOST}:443 HTTP/1.1":
        return False
    seen: set[str] = set()
    for line in lines[1:-2]:
        name, separator, value = line.partition(":")
        lowered = name.casefold()
        if (
            not separator
            or lowered in seen
            or lowered not in {"host", "connection", "proxy-connection", "user-agent"}
            or any(ord(char) < 32 for char in value)
        ):
            return False
        seen.add(lowered)
        if lowered == "host" and value.strip() != f"{HOST}:443":
            return False
    return "host" in seen


def public_address(
    resolve: Callable[
        ..., list[tuple[int, int, int, str, tuple[object, ...]]]
    ] = socket.getaddrinfo,
) -> str:
    """Resolve once, reject nonpublic answers, pin one IPv4; never retry another IP."""
    answers = resolve(HOST, 443, family=socket.AF_INET, type=socket.SOCK_STREAM)
    addresses = {str(item[4][0]) for item in answers}
    if not addresses or len(addresses) > 16:
        raise ValueError("public address unavailable")
    for value in addresses:
        address = ipaddress.IPv4Address(value)
        if not address.is_global or address.is_multicast or address.is_reserved:
            raise ValueError("nonpublic destination")
    return sorted(addresses)[0]


def client_hello_hostname(handshake: bytes) -> str:
    """Strict bounded TLS ClientHello parser; ECH/duplicate SNI are not accepted."""
    if len(handshake) < 42 or handshake[0] != 1:
        raise ValueError("invalid ClientHello")
    length = int.from_bytes(handshake[1:4], "big")
    if length != len(handshake) - 4 or length > MAX_HELLO:
        raise ValueError("invalid ClientHello length")
    offset = 38  # handshake header, legacy_version, random

    def take(length: int) -> bytes:
        nonlocal offset
        if length < 0 or offset + length > len(handshake):
            raise ValueError("truncated ClientHello")
        result = handshake[offset : offset + length]
        offset += length
        return result

    take(int.from_bytes(take(1), "big"))  # session id
    ciphers = int.from_bytes(take(2), "big")
    if not ciphers or ciphers % 2:
        raise ValueError("invalid cipher list")
    take(ciphers)
    take(int.from_bytes(take(1), "big"))  # compression methods
    extensions_length = int.from_bytes(take(2), "big")
    if offset + extensions_length != len(handshake):
        raise ValueError("invalid extensions")
    hostname = None
    seen_extensions: set[int] = set()
    while offset < len(handshake):
        kind = int.from_bytes(take(2), "big")
        extension = take(int.from_bytes(take(2), "big"))
        if kind in seen_extensions or kind == 0xFE0D:
            raise ValueError("duplicate or encrypted extension")
        seen_extensions.add(kind)
        if kind == 0:
            if (
                len(extension) < 5
                or int.from_bytes(extension[:2], "big") != len(extension) - 2
                or extension[2] != 0
                or int.from_bytes(extension[3:5], "big") != len(extension) - 5
            ):
                raise ValueError("invalid SNI")
            hostname = extension[5:].decode("ascii")
    if hostname != HOST:
        raise ValueError("SNI mismatch")
    return hostname


def read_exact(connection: socket.socket, count: int) -> bytes:
    result = bytearray()
    while len(result) < count:
        part = connection.recv(count - len(result))
        if not part:
            raise ValueError("unexpected EOF")
        result.extend(part)
    return bytes(result)


def read_client_hello(connection: socket.socket) -> bytes:
    wire = bytearray()
    handshake = bytearray()
    for _ in range(8):
        header = read_exact(connection, 5)
        length = int.from_bytes(header[3:5], "big")
        if header[0] != 22 or header[1] != 3 or not 1 <= length <= 16384:
            raise ValueError("invalid TLS record")
        payload = read_exact(connection, length)
        wire.extend(header + payload)
        handshake.extend(payload)
        if len(handshake) > MAX_HELLO:
            raise ValueError("large ClientHello")
        if len(handshake) >= 4 and len(handshake) >= 4 + int.from_bytes(handshake[1:4], "big"):
            client_hello_hostname(bytes(handshake))
            return bytes(wire)
    raise ValueError("fragmented ClientHello limit")


def relay(client: socket.socket, upstream: socket.socket) -> None:
    """Bound the tunnel without interpreting or retaining encrypted page content."""
    deadline = time.monotonic() + 30
    totals = {client: 0, upstream: 0}
    while time.monotonic() < deadline:
        readable, _, _ = select.select([client, upstream], [], [], 1)
        for source in readable:
            chunk = source.recv(16384)
            if not chunk:
                return
            totals[source] += len(chunk)
            limit = MAX_CLIENT_BYTES if source is client else MAX_SERVER_BYTES
            if totals[source] > limit:
                raise ValueError("tunnel byte limit")
            (upstream if source is client else client).sendall(chunk)
    raise TimeoutError("tunnel deadline")


def serve() -> int:
    receipt = {"mode": "exact_fqdn_proxy", "accepted_tunnels": 0, "upstream_connections": 0}
    result = 1
    deadline = time.monotonic() + 150
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Both disposable container interfaces; never published on the runner host.
            listener.bind(("0.0.0.0", PORT))  # noqa: S104
            listener.listen(4)
            listener.settimeout(2)
            print(json.dumps({"mode": "exact_fqdn_proxy", "state": "ready"}), flush=True)
            while time.monotonic() < deadline:
                try:
                    client, _ = listener.accept()
                except TimeoutError:
                    continue
                with client:
                    client.settimeout(5)
                    header = bytearray()
                    header_deadline = time.monotonic() + 5
                    while not header.endswith(b"\r\n\r\n") and len(header) <= 4096:
                        remaining = header_deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError("header deadline")
                        client.settimeout(remaining)
                        header.extend(read_exact(client, 1))
                    client.settimeout(5)
                    if bytes(header) == b"GET /health HTTP/1.1\r\nHost: proxy\r\n\r\n":
                        client.sendall(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
                        continue
                    if not exact_connect(bytes(header)):
                        client.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                        continue
                    receipt["accepted_tunnels"] = 1
                    client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    hello = read_client_hello(client)
                    address = public_address()
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as upstream:
                        upstream.settimeout(5)
                        upstream.connect((address, 443))
                        receipt["upstream_connections"] = 1
                        upstream.sendall(hello)
                        relay(client, upstream)
                    result = 0
                    break  # Never accept a second permitted tunnel, even after disconnect.
    except (OSError, ValueError, UnicodeError):
        result = 1
    finally:
        print(
            json.dumps({**receipt, "state": "complete" if result == 0 else "stopped"}), flush=True
        )
    return result


if __name__ == "__main__":
    raise SystemExit(serve())
