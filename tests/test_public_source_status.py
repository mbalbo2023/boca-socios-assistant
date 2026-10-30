"""Offline contract for the single public source observation."""

from __future__ import annotations

import importlib.util
import json
import ssl
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE_PATH = Path(__file__).resolve().parents[1] / "scripts/check_public_source.py"
SOURCE_SPEC = importlib.util.spec_from_file_location("boca_public_source_status", SOURCE_PATH)
assert SOURCE_SPEC is not None and SOURCE_SPEC.loader is not None
source = importlib.util.module_from_spec(SOURCE_SPEC)
sys.modules[SOURCE_SPEC.name] = source
SOURCE_SPEC.loader.exec_module(source)


NOW = datetime(2026, 10, 30, 0, 0, tzinfo=UTC)


class FakeConnection:
    def __init__(self, status: int | None = 200, failure: OSError | None = None) -> None:
        self.status = status
        self.failure = failure
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self.closed = False

    def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
        self.calls.append((method, path, headers))
        if self.failure:
            raise self.failure

    def getresponse(self) -> SimpleNamespace:
        assert self.status is not None
        return SimpleNamespace(status=self.status)

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("http_status", "color", "reason"),
    [
        (200, "GREEN", "http_200_unverified"),
        (302, "YELLOW", "redirect_not_followed"),
        (403, "YELLOW", "public_access_limited"),
        (429, "YELLOW", "public_access_limited"),
        (503, "RED", "server_error"),
        (204, "YELLOW", "unexpected_status"),
    ],
)
def test_one_bounded_anonymous_https_get_with_no_redirect_or_body(
    monkeypatch: pytest.MonkeyPatch, http_status: int, color: str, reason: str
) -> None:
    connection = FakeConnection(http_status)
    construction: list[tuple[str, float, ssl.SSLContext]] = []

    def factory(host: str, *, timeout: float, context: ssl.SSLContext) -> FakeConnection:
        construction.append((host, timeout, context))
        return connection

    monkeypatch.setattr(source.http.client, "HTTPSConnection", factory)
    observation = source.observe(now=lambda: NOW)
    assert construction[0][0:2] == ("bocasocios.bocajuniors.com.ar", 8.0)
    assert isinstance(construction[0][2], ssl.SSLContext)
    assert construction[0][2].verify_mode == ssl.CERT_REQUIRED
    assert connection.calls == [
        ("GET", "/auth/login", {"Accept": "text/html", "User-Agent": "BocaSociosSourceStatus/1.0"})
    ]
    assert connection.closed
    assert observation.color == color
    assert observation.reason == reason
    assert observation.http_status == http_status
    assert observation.observed_at == "2026-10-30T00:00:00+00:00"


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (TimeoutError("url or cookie in error"), "timeout"),
        (ssl.SSLError("url or cookie in error"), "tls_error"),
        (OSError("url or cookie in error"), "transport_error"),
    ],
)
def test_transport_failures_are_redacted_alerts_not_code_failures(
    monkeypatch: pytest.MonkeyPatch, failure: OSError, reason: str
) -> None:
    connection = FakeConnection(failure=failure)
    monkeypatch.setattr(source.http.client, "HTTPSConnection", lambda *args, **kwargs: connection)
    observation = source.observe(now=lambda: NOW)
    assert connection.closed
    assert observation.color == "RED"
    assert observation.reason == reason
    assert observation.http_status is None
    assert "cookie" not in json.dumps(observation.__dict__)


def test_cli_source_failure_reports_semaphore_and_exits_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        source,
        "observe",
        lambda: source.Observation("2026-10-30T00:00:00+00:00", "RED", "timeout", None),
    )
    assert source.main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report == {
        "color": "RED",
        "http_status": None,
        "observed_at": "2026-10-30T00:00:00+00:00",
        "reason": "timeout",
        "target": "boca_public_login",
    }


def test_live_source_workflow_is_manual_main_only_and_has_no_host_or_secret_path() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/boca-source-status.yml"
    ).read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "github.actor == 'mbalbo2023'" in workflow
    for forbidden in (
        "pull_request:",
        "push:",
        "schedule:",
        "ssh ",
        "docker ",
        "secrets.",
        "continue-on-error:",
    ):
        assert forbidden not in workflow
