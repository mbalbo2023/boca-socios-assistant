"""Local-only negative probes for the disposable Actions browser namespace."""

from __future__ import annotations

import ipaddress
import json
import select
import socket
import sys


def ipv4(value: str) -> str:
    address = ipaddress.IPv4Address(value)
    if not address.is_private or address.is_loopback or address.is_unspecified:
        raise ValueError("invalid runner address")
    return str(address)


def expect_blocked(address: str, port: int, *, ipv6: bool = False, udp: bool = False) -> None:
    family = socket.AF_INET6 if ipv6 else socket.AF_INET
    kind = socket.SOCK_DGRAM if udp else socket.SOCK_STREAM
    with socket.socket(family, kind) as connection:
        connection.settimeout(0.5)
        try:
            connection.connect((address, port))
            if udp:
                connection.send(b"BOCA-DENY-PROBE")
                connection.recv(32)
        except OSError:
            return
    raise ValueError("isolation bypass")


def request_proxy(address: str, request: bytes, status: bytes) -> None:
    with socket.create_connection((address, 18080), timeout=2) as connection:
        connection.sendall(request)
        response = connection.recv(128)
        if not response.startswith(status):
            raise ValueError("proxy gate mismatch")


def probe(proxy: str, exterior: str, gateway: str, *, post: bool = False) -> None:
    """Only own runner endpoints and Docker's local DNS address; no public host probes."""
    proxy, exterior, gateway = (ipv4(value) for value in (proxy, exterior, gateway))
    expect_blocked(gateway, 18081)
    expect_blocked(exterior, 18080)
    expect_blocked("127.0.0.11", 53)
    expect_blocked("127.0.0.11", 53, udp=True)
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as sentinel:
        sentinel.bind(("::1", 18082))
        sentinel.listen(1)
        expect_blocked("::1", 18082, ipv6=True)
    if not post:
        request_proxy(
            proxy,
            b"GET /health HTTP/1.1\r\nHost: proxy\r\n\r\n",
            b"HTTP/1.1 204 ",
        )
        for host in ("not-boca.invalid", "127.0.0.1"):
            request_proxy(
                proxy,
                f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n".encode(),
                b"HTTP/1.1 403 ",
            )
    print(json.dumps({"mode": "runner_egress_probe", "state": "PASS", "post": post}))


def sentinel(address: str) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((ipv4(address), 18081))
        listener.listen(4)
        while True:
            if select.select([listener], [], [], 1)[0]:
                connection, _ = listener.accept()
                connection.close()


def main() -> int:
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "sentinel":
            sentinel(sys.argv[2])
        elif len(sys.argv) == 6 and sys.argv[1] == "probe" and sys.argv[5] in {"pre", "post"}:
            probe(*sys.argv[2:5], post=sys.argv[5] == "post")
        else:
            raise ValueError("invalid probe arguments")
    except (OSError, ValueError):
        print("runner_egress_probe: STOPPED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
