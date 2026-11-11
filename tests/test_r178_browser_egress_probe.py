"""R178: DNS/TLS/HTTPS egress diagnostic is neutral, bounded and categoric."""

from __future__ import annotations

import http.client
import io
import socket
import ssl
from typing import Any

import pytest

from boca_socios.browser import egress_probe


class FakeHTTPS:
    def __init__(self, *, status: int = 200, error: Exception | None = None) -> None:
        self.status = status
        self.error = error
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self.closed = False
        self.sock: Any = None

    def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
        self.requests.append((method, path, headers))
        if self.error is not None:
            raise self.error

    def getresponse(self) -> Any:
        return type("Response", (), {"status": self.status})()

    def close(self) -> None:
        self.closed = True
        if self.sock is not None:
            self.sock.close()


class FakeSocket:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeVerifiedContext:
    check_hostname = True
    verify_mode = ssl.CERT_REQUIRED

    def wrap_socket(self, _raw: FakeSocket, *, server_hostname: str) -> FakeSocket:
        assert server_hostname == "example.com"
        return FakeSocket()


def _offline_transports(fake: FakeHTTPS) -> dict[str, Any]:
    return {
        "dial": lambda *_a, **_kw: FakeSocket(),
        "tls_context": FakeVerifiedContext,
        "connect": lambda *_a, **_kw: fake,
    }


def _public_ipv4(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
    assert args == ("example.com", 443)
    assert kwargs == {"family": socket.AF_INET, "type": socket.SOCK_STREAM}
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.215.14", 443))]


def test_verified_a_record_is_only_tcp_target_and_tls_uses_fixed_sni() -> None:
    resolutions: list[tuple[object, ...]] = []
    dials: list[tuple[object, ...]] = []
    tls_sni: list[tuple[object, ...]] = []
    raw_closed: list[bool] = []
    tls_closed: list[bool] = []
    fake = FakeHTTPS()

    class RawSocket:
        def close(self) -> None:
            raw_closed.append(True)

    class TLSSocket:
        def close(self) -> None:
            tls_closed.append(True)

    class VerifiedContext:
        check_hostname = True
        verify_mode = ssl.CERT_REQUIRED

        def wrap_socket(self, raw: RawSocket, *, server_hostname: str) -> TLSSocket:
            assert isinstance(raw, RawSocket)
            tls_sni.append((raw, server_hostname))
            return TLSSocket()

    def resolve(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        resolutions.append((args, kwargs))
        assert len(resolutions) == 1, "second DNS resolution is forbidden"
        return _public_ipv4(*args, **kwargs)

    def dial(*args: object, **kwargs: object) -> RawSocket:
        dials.append((args, kwargs))
        return RawSocket()

    assert (
        egress_probe.probe(
            resolve=resolve,
            dial=dial,
            tls_context=VerifiedContext,
            connect=lambda *_args, **_kwargs: fake,
        )
        == "BOCA_WORKER_EGRESS state=PASS dns=PASS https=PASS"
    )
    assert len(resolutions) == 1
    assert dials == [((("93.184.215.14", 443),), {"timeout": 5.0})]
    assert len(tls_sni) == 1 and tls_sni[0][1] == "example.com"
    assert fake.requests == [("HEAD", "/", {"Host": "example.com", "Connection": "close"})]
    assert fake.closed and tls_closed
    # Ownership moves to TLS after wrap; raw socket is closed by TLS in vivo.
    assert raw_closed == []


def test_standard_http_client_cannot_redial_dns_after_tls_socket_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[bytes] = []
    closed: list[bool] = []

    class TLSSocket:
        def sendall(self, data: bytes) -> None:
            sent.append(data)

        def makefile(self, mode: str) -> io.BytesIO:
            assert mode == "rb"
            return io.BytesIO(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")

        def close(self) -> None:
            closed.append(True)

    class VerifiedContext:
        check_hostname = True
        verify_mode = ssl.CERT_REQUIRED

        def wrap_socket(self, _socket: FakeSocket, *, server_hostname: str) -> TLSSocket:
            assert server_hostname == "example.com"
            return TLSSocket()

    def forbidden_redial(_connection: http.client.HTTPConnection) -> None:
        raise AssertionError("HTTPConnection may not re-resolve the hostname")

    monkeypatch.setattr(http.client.HTTPConnection, "connect", forbidden_redial)
    assert (
        egress_probe.probe(
            resolve=_public_ipv4,
            dial=lambda *_a, **_kw: FakeSocket(),
            tls_context=VerifiedContext,
            connect=http.client.HTTPConnection,
        )
        == "BOCA_WORKER_EGRESS state=PASS dns=PASS https=PASS"
    )
    assert sent
    assert sent[0].startswith(b"HEAD / HTTP/1.1\r\n")
    assert sent[0].count(b"Host: example.com") == 1
    assert closed


def test_probe_uses_fixed_neutral_head_with_verified_tls_and_no_secrets() -> None:
    fake = FakeHTTPS()
    values: list[tuple[object, ...]] = []

    def factory(*args: object, **kwargs: object) -> FakeHTTPS:
        values.append((*args, kwargs))
        return fake

    assert egress_probe.probe(
        resolve=_public_ipv4,
        dial=lambda *_a, **_kw: FakeSocket(),
        tls_context=FakeVerifiedContext,
        connect=factory,
    ) == ("BOCA_WORKER_EGRESS state=PASS dns=PASS https=PASS")
    assert values[0][0:2] == ("example.com", 443)
    assert values[0][2]["timeout"] <= 6
    assert fake.requests == [("HEAD", "/", {"Host": "example.com", "Connection": "close"})]
    assert fake.closed


@pytest.mark.parametrize(
    ("resolved", "expected"),
    [
        ([], "dns"),
        ([(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))], "dns"),
        ([(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))], "dns"),
    ],
)
def test_rejects_empty_or_private_dns_without_opening_https(
    resolved: list[tuple[object, ...]], expected: str
) -> None:
    opened: list[bool] = []
    assert (
        egress_probe.probe(
            resolve=lambda *_a, **_kw: resolved,
            connect=lambda *_a, **_kw: opened.append(True),
        )
        == f"BOCA_WORKER_EGRESS state=NO_GO stage={expected}"
    )
    assert opened == []


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ssl.SSLError("secret URL /token=..."), "tls"),
        (TimeoutError("potential private path"), "https"),
        (OSError("sensitive host"), "https"),
    ],
)
def test_protocol_and_connection_failure_redacts_private_exception(
    error: Exception, expected: str
) -> None:
    fake = FakeHTTPS(error=error)
    receipt = egress_probe.probe(resolve=_public_ipv4, **_offline_transports(fake))
    assert receipt == f"BOCA_WORKER_EGRESS state=NO_GO stage={expected}"
    assert fake.closed


def test_https_server_failure_is_no_go_not_fake_connectivity() -> None:
    fake = FakeHTTPS(status=503)
    assert egress_probe.probe(resolve=_public_ipv4, **_offline_transports(fake)) == (
        "BOCA_WORKER_EGRESS state=NO_GO stage=https"
    )


def test_cli_does_not_accept_url_secret_or_any_runtime_argument(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert egress_probe.main(["--once", "https://socios.example"]) == 2
    assert capsys.readouterr().out == "BOCA_WORKER_EGRESS state=NO_GO stage=arguments\n"
