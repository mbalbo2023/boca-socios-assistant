"""Recovered login contract, exercised only with an injected offline session."""

from __future__ import annotations

import json
import ssl
import subprocess
import sys
import traceback
from importlib import import_module
from pathlib import Path

import pytest

from boca_socios.security.member_auth_contract import BocaAuthObservation, BocaAuthUnavailable

LOGIN_URL = "https://bocasocios-gw.bocajuniors.com.ar/auth/login/baas"
PAYLOAD = b'{"token":"offline-access","refreshToken":"offline-refresh"}'
SECRET = "private-offline-fixture"


def _api():
    return import_module("boca_socios.security.boca_login_transport")


def _transport(api, **kwargs):
    return api.BocaHttpLoginTransport(boundary_check=lambda: None, **kwargs)


def _transport_error():
    return _api().BocaLoginTransportUnavailable


class Session:
    def __init__(self, cookies=()):
        self.cookies = cookies
        self.calls = []

    def cookies_for_url(self, url):
        self.calls.append(url)
        return self.cookies


class Response:
    def __init__(self, payload=PAYLOAD, status=200, content_type="application/json"):
        self.payload = payload
        self.status = status
        self.content_type = content_type
        self.read_limits = []

    def getheader(self, name, default=None):
        assert name == "Content-Type"
        return self.content_type

    def read(self, limit):
        self.read_limits.append(limit)
        return self.payload[:limit]


class Connection:
    def __init__(self, response=None):
        self.response = response or Response()
        self.requests = []
        self.closed = 0

    def request(self, method, url, body, headers):
        self.requests.append((method, url, body, headers))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed += 1


class Factory:
    def __init__(self, connection=None):
        self.connection = connection or Connection()
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.connection


def test_exact_historical_contract_is_inert_until_one_explicit_exchange():
    api = _api()
    session, factory = Session(), Factory()
    transport = _transport(api, session=session, connection_factory=factory)
    assert session.calls == factory.calls == []

    assert transport.login(email="socio@example.invalid", password=SECRET) == PAYLOAD

    assert session.calls == [LOGIN_URL]
    assert len(factory.calls) == 1
    options = factory.calls[0]
    assert options["host"] == "bocasocios-gw.bocajuniors.com.ar"
    assert 0 < options["timeout"] <= 15
    context = options["context"]
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is True
    assert factory.connection.closed == 1
    assert len(factory.connection.requests) == 1
    method, path, body, headers = factory.connection.requests[0]
    assert (method, path) == ("POST", "/auth/login/baas")
    assert json.loads(body) == {"email": "socio@example.invalid", "password": SECRET}
    assert headers == {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://bocasocios.bocajuniors.com.ar",
        "Referer": "https://bocasocios.bocajuniors.com.ar/",
    }
    assert factory.connection.response.read_limits == [65_537]
    assert SECRET not in repr(transport)


def test_session_cookie_scope_is_exact_and_values_are_private():
    api = _api()
    cookie = api.BocaSessionCookie
    valid = cookie("session", SECRET, ".bocajuniors.com.ar", "/auth", True)
    session = Session(
        (
            valid,
            cookie("gateway", "fixture", "bocasocios-gw.bocajuniors.com.ar", "/", True),
            cookie("foreign", "never-send", ".queue-it.net", "/", True),
            cookie("portal", "never-send", "bocasocios.bocajuniors.com.ar", "/", True),
            cookie("hostonly_parent", "never-send", "bocajuniors.com.ar", "/", True),
            cookie("path", "never-send", ".bocajuniors.com.ar", "/authentication", True),
            cookie("insecure", "never-send", ".bocajuniors.com.ar", "/", False),
            cookie("expired", "never-send", ".bocajuniors.com.ar", "/", True, 9.0),
        )
    )
    factory = Factory()
    transport = _transport(api, session=session, connection_factory=factory, now=lambda: 10.0)
    transport.login(email="socio@example.invalid", password=SECRET)
    headers = factory.connection.requests[0][3]
    assert headers["Cookie"] == f"session={SECRET}; gateway=fixture"
    assert SECRET not in repr(valid)
    assert SECRET not in repr(transport)
    # Every explicit invocation reads the current existing session; no cookie cache.
    session.cookies = ()
    transport.login(email="socio@example.invalid", password=SECRET)
    assert "Cookie" not in factory.connection.requests[-1][3]


@pytest.mark.parametrize(
    "name,value",
    [("bad\r\nHeader", "x"), ("ok", "x; injected=y"), ("ok", "x\r\nHeader: y"), ("", "x")],
)
def test_invalid_cookie_never_reaches_network(name, value):
    api = _api()
    factory = Factory()
    session = Session((api.BocaSessionCookie(name, value, ".bocajuniors.com.ar", "/", True),))
    with pytest.raises(_transport_error()):
        _transport(api, session=session, connection_factory=factory).login(
            email="socio@example.invalid", password=SECRET
        )
    assert factory.calls == []


@pytest.mark.parametrize("status", [201, 301, 302, 307, 308, 401, 403, 429, 500])
def test_redirect_and_unsuccessful_reply_is_never_followed_or_retried(status):
    api = _api()
    factory = Factory(Connection(Response(status=status)))
    with pytest.raises(_transport_error()):
        _transport(api, session=Session(), connection_factory=factory).login(
            email="socio@example.invalid", password=SECRET
        )
    assert len(factory.calls) == len(factory.connection.requests) == 1
    assert factory.connection.closed == 1


@pytest.mark.parametrize(
    "payload,content_type",
    [
        (b"", "application/json"),
        (b"x" * 65_537, "application/json"),
        (PAYLOAD, "text/html"),
        (PAYLOAD, None),
    ],
)
def test_empty_oversized_or_wrong_media_reply_is_rejected(payload, content_type):
    api = _api()
    factory = Factory(Connection(Response(payload, content_type=content_type)))
    with pytest.raises(_transport_error()):
        _transport(api, session=Session(), connection_factory=factory).login(
            email="socio@example.invalid", password=SECRET
        )
    assert len(factory.calls) == 1
    assert factory.connection.closed == 1


def test_malformed_provider_payload_remains_rejected_by_existing_parser():
    from datetime import UTC, datetime

    api = _api()
    factory = Factory(Connection(Response(b'{"token":"only-one-field"}')))
    raw = _transport(api, session=Session(), connection_factory=factory).login(
        email="socio@example.invalid", password=SECRET
    )
    with pytest.raises(BocaAuthUnavailable):
        BocaAuthObservation.from_provider_response(
            member_id="fixture", provider_payload=raw, observed_at=datetime.now(UTC)
        )


@pytest.mark.parametrize("phase", ["session", "factory", "request", "response", "read", "close"])
def test_injected_failure_is_redacted_without_retry_or_cookie_leak(phase, caplog):
    api = _api()
    session, factory = Session(), Factory()

    def fail(*args, **kwargs):
        raise RuntimeError(SECRET)

    if phase == "session":
        session.cookies_for_url = fail
    elif phase == "factory":
        factory = fail
    elif phase == "request":
        factory.connection.request = fail
    elif phase == "response":
        factory.connection.getresponse = fail
    elif phase == "read":
        factory.connection.response.read = fail
    else:
        factory.connection.close = fail
    transport = _transport(api, session=session, connection_factory=factory)
    with pytest.raises(_transport_error()) as raised:
        transport.login(email="socio@example.invalid", password=SECRET)
    rendered = "".join(traceback.format_exception(raised.value))
    assert SECRET not in rendered + repr(transport) + caplog.text


@pytest.mark.parametrize("timeout", [0, -1, 16, float("nan"), float("inf"), True])
def test_timeout_must_be_finite_and_bounded(timeout):
    api = _api()
    with pytest.raises(ValueError):
        _transport(api, session=Session(), timeout_seconds=timeout)


def test_worker_guard_runs_before_session_or_network():
    api = _api()
    session, factory = Session(), Factory()

    def deny():
        raise RuntimeError(SECRET)

    transport = api.BocaHttpLoginTransport(
        session=session, connection_factory=factory, boundary_check=deny
    )
    assert session.calls == factory.calls == []
    with pytest.raises(_transport_error()):
        transport.login(email="socio@example.invalid", password=SECRET)
    assert session.calls == factory.calls == []


def test_default_guard_rejects_controller_profile_before_network(monkeypatch):
    api = _api()
    monkeypatch.delenv("BOCA_BROWSER_EXECUTOR", raising=False)
    session, factory = Session(), Factory()
    transport = api.BocaHttpLoginTransport(session=session, connection_factory=factory)
    with pytest.raises(_transport_error()):
        transport.login(email="socio@example.invalid", password=SECRET)
    assert session.calls == factory.calls == []


@pytest.mark.parametrize("cookies_kind", ["duplicate", "too_many", "header_limit", "bad_expiry"])
def test_ambiguous_or_unbounded_cookie_snapshot_is_rejected_before_network(cookies_kind):
    api = _api()
    cookie = api.BocaSessionCookie
    if cookies_kind == "duplicate":
        cookies = (
            cookie("same", "one", ".bocajuniors.com.ar", "/", True),
            cookie("same", "two", "bocasocios-gw.bocajuniors.com.ar", "/", True),
        )
    elif cookies_kind == "too_many":
        cookies = tuple(cookie(f"c{i}", "x", ".bocajuniors.com.ar", "/", True) for i in range(65))
    elif cookies_kind == "header_limit":
        cookies = tuple(
            cookie(f"c{i}", "x" * 8192, ".bocajuniors.com.ar", "/", True) for i in range(3)
        )
    else:
        cookies = (cookie("c", "x", ".bocajuniors.com.ar", "/", True, float("nan")),)
    session, factory = Session(cookies), Factory()
    with pytest.raises(_transport_error()):
        _transport(api, session=session, connection_factory=factory).login(
            email="socio@example.invalid", password=SECRET
        )
    assert factory.calls == []


def test_maximum_sized_response_and_json_media_parameters_are_accepted():
    api = _api()
    raw = PAYLOAD + b" " * (65_536 - len(PAYLOAD))
    factory = Factory(Connection(Response(raw, content_type="application/json; charset=utf-8")))
    assert (
        _transport(api, session=Session(), connection_factory=factory).login(
            email="socio@example.invalid", password=SECRET
        )
        == raw
    )


@pytest.mark.parametrize(
    "invalid_credentials",
    [
        ("", SECRET),
        ("x" * 321, SECRET),
        ("socio@example.invalid", ""),
        ("socio@example.invalid", "x" * 4097),
    ],
)
def test_invalid_credential_is_rejected_before_session_or_network(invalid_credentials):
    api = _api()
    session, factory = Session(), Factory()
    with pytest.raises(_transport_error()):
        _transport(api, session=session, connection_factory=factory).login(
            email=invalid_credentials[0], password=invalid_credentials[1]
        )
    assert session.calls == factory.calls == []


def test_default_worker_guard_checks_existing_limits_and_interface_set(monkeypatch):
    api = _api()
    checks = []
    monkeypatch.setenv("BOCA_BROWSER_EXECUTOR", "automatic-observation")
    monkeypatch.setattr(api, "validate_worker_boundary", lambda: checks.append("limits"))
    monkeypatch.setattr(api.socket, "if_nameindex", lambda: [(1, "lo"), (2, "foreign")])
    session, factory = Session(), Factory()
    transport = api.BocaHttpLoginTransport(session=session, connection_factory=factory)
    with pytest.raises(_transport_error()):
        transport.login(email="socio@example.invalid", password=SECRET)
    assert checks == ["limits"]
    assert session.calls == factory.calls == []
    monkeypatch.setattr(api.socket, "if_nameindex", lambda: [(1, "lo"), (2, "eth0")])
    assert transport.login(email="socio@example.invalid", password=SECRET) == PAYLOAD
    assert checks == ["limits", "limits"]


def test_worker_import_needs_only_stdlib_and_existing_browser_leafs(tmp_path):
    root = Path(__file__).resolve().parents[1] / "src"
    leafs = (
        "boca_socios/__init__.py",
        "boca_socios/security/__init__.py",
        "boca_socios/security/boca_login_transport.py",
        "boca_socios/browser/__init__.py",
        "boca_socios/browser/worker_health.py",
        "boca_socios/browser/ipc_protocol.py",
        "boca_socios/browser/queue_page_observation.py",
        "boca_socios/browser/site_url_runtime.py",
    )
    for relative in leafs:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / relative).read_bytes())
    program = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from boca_socios.security.boca_login_transport import BocaHttpLoginTransport; "
        "assert all(name not in sys.modules for name in "
        "('cryptography', 'sqlite3', 'boca_socios.security.credential_vault', "
        "'boca_socios.storage.database'))"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-S", "-c", program, str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
