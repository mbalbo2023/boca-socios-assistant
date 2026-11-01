"""Signed Site protocol tests; no connection to the real Site is opened."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path
from uuid import UUID

import pytest

from boca_socios.integration import bridge_client

OP_ID = "5387eb20-c962-42f5-933e-d5f681ab0877"
COMMAND_ID = "ba1e7e37-5e4a-4be9-b31b-3379027e4b0c"
MEMBER_ID = "ec6d7503-f92b-4094-9f24-b7483e9b82e1"
LEASE_ID = "c0ae377c-d477-4a46-8e69-266c4ea7eac0"
NONCE = UUID("92e4c8df-2372-4eca-9fed-fca1bc765ac2")
KEY = b"k" * 32
TOKEN = b"synthetic-bypass-token-never-live"


class Response:
    def __init__(self, status: int, payload: bytes) -> None:
        self.status = status
        self.payload = payload

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]

    def getheader(self, name: str, default: str = "") -> str:
        return "application/json" if name == "Content-Type" else default


class Connection:
    def __init__(self, response: Response) -> None:
        self.response = response
        self.sent: tuple[str, str, bytes, dict[str, str]] | None = None
        self.closed = False

    def request(self, method: str, path: str, *, body: bytes, headers: dict[str, str]) -> None:
        self.sent = method, path, body, headers

    def getresponse(self) -> Response:
        return self.response

    def close(self) -> None:
        self.closed = True


def _file(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    path.chmod(0o400)
    return path


def _transport(tmp_path: Path) -> bridge_client.SiteBridgeTransport:
    return bridge_client.SiteBridgeTransport(
        origin=bridge_client.SITE_ORIGIN,
        token_file=_file(tmp_path / "bypass", TOKEN + b"\n"),
        hmac_key_file=_file(tmp_path / "hmac", KEY),
        clock=lambda: 1793502000.0,
        nonce=lambda: NONCE,
    )


def _leased() -> bytes:
    return json.dumps(
        {
            "status": "leased",
            "operation": {
                "operation_id": OP_ID,
                "command_id": COMMAND_ID,
                "operation": "synthetic_begin",
                "member_id": MEMBER_ID,
                "event_id": "00000000-0000-4000-8000-000000000001",
                "lease_id": LEASE_ID,
                "lease_until": "2026-11-01T03:00:30.000Z",
                "attempts": 1,
            },
        }
    ).encode()


def test_signed_nonredirecting_lease_ack_and_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = _transport(tmp_path)
    responses = [
        Response(200, _leased()),
        Response(200, b'{"status":"acknowledged"}'),
        Response(200, b'{"status":"recorded","received_at":"2026-11-01T03:00:00Z"}'),
    ]
    connections: list[Connection] = []

    def connect(host: str, port: int, **kwargs: object) -> Connection:
        assert host == "boca-socios-consola-demo-20261031.mbalbo14901.chatgpt.site"
        assert port == 443 and kwargs["timeout"] == 3.0
        result = Connection(responses.pop(0))
        connections.append(result)
        return result

    monkeypatch.setattr(bridge_client.http.client, "HTTPSConnection", connect)
    lease = transport.lease()
    assert lease is not None and lease.command_id == COMMAND_ID
    transport.ack(lease, "accepted")
    transport.heartbeat("a" * 40, "ready", {"source": "local_sqlite_intents"})
    assert all(connection.closed for connection in connections)
    paths = [connection.sent[1] for connection in connections if connection.sent]
    assert paths == ["/api/bridge/lease", "/api/bridge/ack", "/api/bridge/heartbeat"]
    for connection in connections:
        assert connection.sent is not None
        method, path, body, headers = connection.sent
        assert method == "POST" and len(body) <= 2048
        assert headers["OAI-Sites-Authorization"] == f"Bearer {TOKEN.decode()}"
        assert headers["x-boca-bridge-ts"] == "1793502000"
        assert headers["x-boca-bridge-nonce"] == str(NONCE)
        signed = (
            f"boca-site-bridge-v1\n1793502000\n{NONCE}\nPOST\n{path}\n"
            f"{hashlib.sha256(body).hexdigest()}\n"
        ).encode()
        expected = base64.urlsafe_b64encode(hmac.new(KEY, signed, hashlib.sha256).digest())
        assert headers["x-boca-bridge-signature"] == expected.rstrip(b"=").decode()
    assert b'"mode":"simulation"' in connections[1].sent[2]
    assert b'"external_confirmation":"not_observed"' in connections[1].sent[2]


@pytest.mark.parametrize(
    ("status", "payload"),
    [
        (302, b'{"status":"empty"}'),
        (200, b'{"status":"empty","status":"leased"}'),
        (200, b"x" * 4097),
        (200, b'{"status":"leased","operation":{}}'),
    ],
)
def test_untrusted_response_never_dispatches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int, payload: bytes
) -> None:
    connection = Connection(Response(status, payload))
    monkeypatch.setattr(
        bridge_client.http.client, "HTTPSConnection", lambda *_args, **_kwargs: connection
    )
    with pytest.raises(bridge_client.BridgeUnavailable):
        _transport(tmp_path).lease()
    assert connection.closed


def test_private_files_and_pinned_origin_fail_closed(tmp_path: Path) -> None:
    transport = _transport(tmp_path)
    with pytest.raises(ValueError, match="unapproved"):
        bridge_client.SiteBridgeTransport(
            origin="https://other.chatgpt.site",
            token_file=tmp_path / "bypass",
            hmac_key_file=tmp_path / "hmac",
        )
    (tmp_path / "hmac").chmod(0o644)
    with pytest.raises(ValueError, match="unsafe"):
        bridge_client.SiteBridgeTransport(
            origin=bridge_client.SITE_ORIGIN,
            token_file=tmp_path / "bypass",
            hmac_key_file=tmp_path / "hmac",
        )
    (tmp_path / "hmac").chmod(0o400)
    (tmp_path / "bypass").unlink()
    (tmp_path / "bypass").symlink_to(tmp_path / "hmac")
    with pytest.raises(ValueError, match="unavailable"):
        bridge_client.SiteBridgeTransport(
            origin=bridge_client.SITE_ORIGIN,
            token_file=tmp_path / "bypass",
            hmac_key_file=tmp_path / "hmac",
        )
    assert "synthetic-bypass" not in repr(transport)
