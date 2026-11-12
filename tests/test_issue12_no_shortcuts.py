"""Negative, offline-only tests: no TLS weakening or queue bypass in issue #12."""

from __future__ import annotations

import re
import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest

from boca_socios.queue.pass_observation import QueuePassObservation, QueuePassState
from boca_socios.security.credential_vault import CredentialVault
from boca_socios.security.member_auth_contract import BocaAuthUnavailable, BocaMemberAuthService
from boca_socios.storage.database import Database

ROOT = Path(__file__).resolve().parents[1]
ISSUE12_RUNTIME_FILES = (
    "src/boca_socios/queue/pass_observation.py",
    "src/boca_socios/queue/private_pass_monitor.py",
    "src/boca_socios/security/member_auth_contract.py",
    "src/boca_socios/panel/private_token_view.py",
    "src/boca_socios/panel/private_ui.py",
    "src/boca_socios/panel/private_http.py",
)
UNSAFE_TLS_OR_BYPASS = re.compile(
    r"verify\s*=\s*False\b|ssl\.CERT_NONE\b|_create_unverified_context\s*\("
    r"|NODE_TLS_REJECT_UNAUTHORIZED|--ignore-certificate-errors|--disable-web-security"
    r"|queue[_-]?bypass\s*=|skip[_-]?queue\s*=",
    re.IGNORECASE,
)


@pytest.mark.parametrize("relative_path", ISSUE12_RUNTIME_FILES)
def test_issue12_runtime_has_no_tls_relaxation_or_queue_bypass(relative_path: str) -> None:
    source = (ROOT / relative_path).read_text(encoding="utf-8")
    assert UNSAFE_TLS_OR_BYPASS.search(source) is None


def test_bypass_only_url_does_not_become_a_queue_pass_or_network_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def network_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("An issue #12 test attempted a live network connection")

    monkeypatch.setattr(socket.socket, "connect", network_forbidden)
    with pytest.raises(ValueError, match="queueittoken"):
        QueuePassObservation.from_observed_url(
            member_id="member-fixture",
            event_id="event-fixture",
            session_id="session-fixture",
            target_url="https://offline.invalid/?queueId=fixture&skipQueue=1",
            observed_at=datetime(2026, 11, 12, tzinfo=UTC),
        )

    observation = QueuePassObservation.from_observed_url(
        member_id="member-fixture",
        event_id="event-fixture",
        session_id="session-fixture",
        target_url="https://offline.invalid/?queueittoken=already-observed",
        observed_at=datetime(2026, 11, 12, tzinfo=UTC),
    )
    assert observation.summary(at=datetime(2026, 11, 12, tzinfo=UTC)).state == (
        QueuePassState.OBSERVED_UNVERIFIED
    )
    assert not hasattr(observation, "admit")
    assert not hasattr(observation, "navigate")


def test_absent_boca_transport_cannot_open_a_socket_or_create_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def network_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("An issue #12 test attempted a live network connection")

    monkeypatch.setattr(socket.socket, "connect", network_forbidden)
    path = tmp_path / "uninitialized.sqlite3"
    with pytest.raises(BocaAuthUnavailable, match="not configured"):
        BocaMemberAuthService(Database(path), CredentialVault(b"t" * 32)).authenticate(
            "00000000-0000-0000-0000-000000000001"
        )
    assert not path.exists()
