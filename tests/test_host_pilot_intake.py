"""Offline, no-network tests for inert SSH-only pilot credential intake."""

import base64
import hashlib
import io
from urllib.parse import urlencode

import pytest

from boca_socios.host_pilot_intake import HostPilotIntake, PilotGateConfig

_TOKEN = base64.urlsafe_b64encode(b"f" * 32).decode().rstrip("=")
_DIGEST = hashlib.sha256(b"f" * 32).hexdigest()


def _request(
    app: HostPilotIntake,
    *,
    path: str = "/piloto/login",
    method: str = "POST",
    token: str = _TOKEN,
    origin: str = "http://localhost:8443",
    host: str = "localhost:8443",
    addr: str = "127.0.0.1",
    fields: list[tuple[str, str]] | None = None,
) -> tuple[str, dict[str, str], bytes]:
    body = urlencode(
        fields
        if fields is not None
        else [("username", "fernando@example.invalid"), ("password", "test-secret")]
    ).encode()
    status = ""
    headers: dict[str, str] = {}

    def start(new_status: str, new_headers: list[tuple[str, str]]) -> None:
        nonlocal status, headers
        status = new_status
        headers = dict(new_headers)

    env: dict[str, object] = {
        "wsgi.url_scheme": "http",
        "HTTP_HOST": host,
        "REMOTE_ADDR": addr,
        "PATH_INFO": path,
        "REQUEST_METHOD": method,
        "CONTENT_LENGTH": str(len(body)) if method == "POST" else "",
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
        "HTTP_ORIGIN": origin,
        "HTTP_X_BOCA_PILOT_KEY": token,
        "wsgi.input": io.BytesIO(body),
    }
    output = b"".join(app(env, start))
    return status, headers, output


def test_one_valid_request_invokes_driver_once_and_never_echoes_secrets() -> None:
    calls = []

    def fake_driver(*, username: str, password: str) -> str:
        calls.append((username, password))
        return "AUTHENTICATED"

    app = HostPilotIntake(PilotGateConfig(_DIGEST), fake_driver)
    status, headers, body = _request(app)
    assert status == "200 OK"
    assert b'"state": "AUTHENTICATED"' in body
    assert b"test-secret" not in body
    assert b"fernando@" not in body
    assert "no-store" in headers["Cache-Control"]
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert calls == [("fernando@example.invalid", "test-secret")]
    retry_status, _, _ = _request(app)
    assert retry_status == "403 Forbidden"
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"token": "x" * 43}, "403 Forbidden"),
        ({"origin": "https://localhost:8443"}, "403 Forbidden"),
        ({"host": "evil.test:8443"}, "403 Forbidden"),
        ({"addr": "10.0.0.8"}, "403 Forbidden"),
        ({"fields": [("username", "a"), ("password", "b")]}, "403 Forbidden"),
        (
            {
                "fields": [
                    ("username", "fernando@example.invalid"),
                    ("password", "test-secret"),
                    ("password", "duplicate"),
                ]
            },
            "403 Forbidden",
        ),
    ],
)
def test_untrusted_requests_never_call_driver(kwargs: dict[str, object], expected: str) -> None:
    calls = []

    def driver(*, username: str, password: str) -> str:
        calls.append((username, password))
        return "AUTHENTICATED"

    app = HostPilotIntake(PilotGateConfig(_DIGEST), driver)
    status, _, _ = _request(app, **kwargs)  # type: ignore[arg-type]
    assert status == expected
    assert not calls


def test_web_form_keeps_key_in_fragment_then_clears_and_never_echoes() -> None:
    app = HostPilotIntake(PilotGateConfig(_DIGEST), None)
    status, _, body = _request(app, path="/piloto", method="GET")
    assert status == "200 OK"
    assert b"Correo del socio" in body
    assert b"test-secret" not in body
    _, _, script = _request(app, path="/piloto.js", method="GET")
    assert b"history.replaceState" in script
    assert b"location.hash" in script
    assert b"credentials: 'omit'" in script
    assert b"localStorage" not in script


def test_expired_or_unwired_gate_never_accepts_credentials() -> None:
    calls = []

    def driver(*, username: str, password: str) -> str:
        calls.append((username, password))
        return "AUTHENTICATED"

    expired = HostPilotIntake(PilotGateConfig(_DIGEST, 1), driver, clock=lambda: 100)
    expired._clock = lambda: 101  # synthetic expiry clock, not a real wait
    status, _, _ = _request(expired)
    assert status == "403 Forbidden"
    assert not calls
    unconfigured = HostPilotIntake(PilotGateConfig(_DIGEST), None)
    status, _, body = _request(unconfigured)
    assert status == "503 Service Unavailable"
    assert b'"state": "UNKNOWN"' in body


def test_driver_failure_never_claims_authentication() -> None:
    def error(*, username: str, password: str) -> str:
        raise RuntimeError("do not leak provider diagnostics")

    app = HostPilotIntake(PilotGateConfig(_DIGEST), error)
    status, _, body = _request(app)
    assert status == "202 Accepted"
    assert b'"state": "UNKNOWN"' in body
    assert b"provider diagnostics" not in body


@pytest.mark.parametrize("digest", ["", "Z" * 64, _TOKEN])
def test_gate_rejects_capability_instead_of_sha256_digest(digest: str) -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        PilotGateConfig(digest)


def test_no_live_binding_side_effects_or_dynamic_sites() -> None:
    from boca_socios import host_pilot_intake

    source = host_pilot_intake.__file__
    assert source is not None
    text = open(source, encoding="utf-8").read()
    assert "requests." not in text
    assert "socket." not in text
    assert "subprocess." not in text
    assert "--no-sandbox" not in text
    assert "queue-it.net" not in text
