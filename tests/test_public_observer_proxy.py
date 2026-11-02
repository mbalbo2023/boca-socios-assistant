"""Offline transport boundary tests; no DNS, public sockets or Boca content."""

from __future__ import annotations

import json
import socket
import ssl

import pytest
from scripts import public_observer_proxy as proxy


def hello(host: str = proxy.HOST, *, extra: bytes = b"") -> bytes:
    name = host.encode("ascii")
    sni = b"\x00" + len(name).to_bytes(2, "big") + name
    extension = len(sni).to_bytes(2, "big") + sni
    extensions = b"\x00\x00" + len(extension).to_bytes(2, "big") + extension + extra
    body = b"\x03\x03" + b"x" * 32 + b"\x00\x00\x02\x13\x01\x01\x00"
    body += len(extensions).to_bytes(2, "big") + extensions
    return b"\x01" + len(body).to_bytes(3, "big") + body


def test_connect_permits_only_exact_authority() -> None:
    header = f"CONNECT {proxy.HOST}:443 HTTP/1.1\r\nHost: {proxy.HOST}:443\r\n\r\n"
    assert proxy.exact_connect(header.encode())
    for forbidden in (
        header.replace(proxy.HOST, "127.0.0.1"),
        header.replace(proxy.HOST, proxy.HOST + ".evil.invalid"),
        header.replace(":443", ":80"),
        header.replace("CONNECT", "GET", 1),
        header.replace("\r\n\r\n", "\r\nProxy-Authorization: private\r\n\r\n"),
        header.replace("\r\n\r\n", "\r\nCookie: private\r\n\r\n"),
        header.replace("\r\n\r\n", f"\r\nHost: {proxy.HOST}:443\r\n\r\n"),
        header + "GET /another HTTP/1.1\r\n\r\n",
    ):
        assert not proxy.exact_connect(forbidden.encode())


def test_tls_clienthello_requires_exact_visible_sni() -> None:
    assert proxy.client_hello_hostname(hello()) == proxy.HOST
    for data in (
        hello("other.invalid"),
        hello(proxy.HOST + "."),
        hello(extra=b"\xfe\x0d\x00\x00"),
        hello(extra=b"\x00\x00\x00\x00"),
        hello()[:-1],
        hello() + b"second handshake",
        b"\x01\xff\xff\xff" + b"x" * 40,
    ):
        with pytest.raises(ValueError):
            proxy.client_hello_hostname(data)


def test_tls_parser_accepts_fragmentation_without_forwarding_unchecked_bytes() -> None:
    data = hello()
    records = b"".join(
        b"\x16\x03\x01" + len(part).to_bytes(2, "big") + part for part in (data[:9], data[9:])
    )
    left, right = socket.socketpair()
    try:
        left.sendall(records)
        right.settimeout(1)
        assert proxy.read_client_hello(right) == records
    finally:
        left.close()
        right.close()


def test_tls_parser_handles_real_openssl_clienthello_without_network() -> None:
    outgoing = ssl.MemoryBIO()
    client = ssl.create_default_context().wrap_bio(
        ssl.MemoryBIO(), outgoing, server_hostname=proxy.HOST
    )
    with pytest.raises(ssl.SSLWantReadError):
        client.do_handshake()
    wire = outgoing.read()
    left, right = socket.socketpair()
    try:
        left.sendall(wire)
        right.settimeout(1)
        assert proxy.read_client_hello(right) == wire
    finally:
        left.close()
        right.close()


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.1", "169.254.169.254", "0.0.0.0", "224.0.0.1", "192.0.2.1"],  # noqa: S104 - refused fixture, no bind
)
def test_dns_never_allows_private_reserved_or_mixed_answers(address: str) -> None:
    def resolve(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        assert args == (proxy.HOST, 443)
        assert kwargs == {"family": socket.AF_INET, "type": socket.SOCK_STREAM}
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (value, 443))
            for value in ("8.8.8.8", address)
        ]

    with pytest.raises(ValueError):
        proxy.public_address(resolve)


def test_dns_is_resolved_once_and_returns_one_pinned_address() -> None:
    calls = 0

    def resolve(*_args: object, **_kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (value, 443))
            for value in ("8.8.8.8", "1.1.1.1")
        ]

    assert proxy.public_address(resolve) == "1.1.1.1"
    assert calls == 1


@pytest.mark.parametrize("valid_sni", [False, True])
def test_serve_uses_at_most_one_pinned_connection_and_reports_honest_counters(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], valid_sni: bool
) -> None:
    data = hello() if valid_sni else hello("wrong.invalid")
    payload = (
        f"CONNECT {proxy.HOST}:443 HTTP/1.1\r\nHost: {proxy.HOST}:443\r\n\r\n".encode()
        + b"\x16\x03\x01"
        + len(data).to_bytes(2, "big")
        + data
    )
    accepted = 0
    connected: list[object] = []
    resolved: list[bool] = []

    class Connection:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def settimeout(self, _value: float) -> None:
            pass

        def sendall(self, _value: bytes) -> None:
            pass

        def recv(self, count: int) -> bytes:
            nonlocal payload
            result, payload = payload[:count], payload[count:]
            return result

        def connect(self, address: object) -> None:
            connected.append(address)

    client = Connection()
    upstream = Connection()

    class Listener(Connection):
        def setsockopt(self, *_args: object) -> None:
            pass

        def bind(self, _address: object) -> None:
            pass

        def listen(self, _count: int) -> None:
            pass

        def accept(self) -> tuple[Connection, None]:
            nonlocal accepted
            accepted += 1
            assert accepted == 1, "a second accepted tunnel is forbidden"
            return client, None

    sockets = iter([Listener(), upstream])
    monkeypatch.setattr(proxy.socket, "socket", lambda *_args, **_kwargs: next(sockets))

    def resolve() -> str:
        resolved.append(True)
        return "8.8.8.8"

    monkeypatch.setattr(proxy, "public_address", resolve)
    monkeypatch.setattr(proxy, "relay", lambda *_args: None)
    assert proxy.serve() == (0 if valid_sni else 1)
    assert connected == ([("8.8.8.8", 443)] if valid_sni else [])
    assert resolved == ([True] if valid_sni else [])
    receipt = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert receipt == {
        "mode": "exact_fqdn_proxy",
        "accepted_tunnels": 1,
        "upstream_connections": int(valid_sni),
        "state": "complete" if valid_sni else "stopped",
    }
