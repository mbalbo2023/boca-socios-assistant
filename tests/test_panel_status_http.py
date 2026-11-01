"""Synthetic request-boundary tests; no listener or real identity provider."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from boca_socios.panel.status_http import StatusApplication, VerifiedIdentity
from boca_socios.storage.database import Database

NOW = datetime(2026, 10, 31, 21, 0, tzinfo=UTC)
OWNER = "opaque-owner"
TOKEN = "synthetic-test-token"


def _identity(token: str, now: datetime) -> VerifiedIdentity | None:
    assert now == NOW
    if token != TOKEN:
        return None
    return VerifiedIdentity(OWNER, frozenset({"local-status:read"}), NOW + timedelta(minutes=1))


def _app(tmp_path: Path) -> StatusApplication:
    db = Database(tmp_path / "private" / "boca.sqlite3")
    db.migrate()
    return StatusApplication(
        db.path, owner_subject=OWNER, verify_identity=_identity, now=lambda: NOW
    )


def _request(
    app: StatusApplication, **changes: object
) -> tuple[int, dict[str, str], dict[str, object]]:
    environ: dict[str, object] = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": "/api/v1/local-status",
        "QUERY_STRING": "",
        "wsgi.url_scheme": "https",
        "HTTP_AUTHORIZATION": f"Bearer {TOKEN}",
        "CONTENT_LENGTH": "0",
    }
    environ.update(changes)
    recorded: list[tuple[str, list[tuple[str, str]]]] = []

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        recorded.append((status, headers))

    chunks = app(environ, start_response)
    assert len(recorded) == 1
    status, headers = recorded[0]
    payload = b"".join(chunks)
    assert len(payload) <= 2048
    assert dict(headers)["Content-Length"] == str(len(payload))
    assert dict(headers)["Cache-Control"] == "no-store"
    return int(status.split()[0]), dict(headers), json.loads(payload)


def test_status_is_deny_by_default_without_identity_provider(tmp_path: Path) -> None:
    absent = tmp_path / "not-created.sqlite3"
    app = StatusApplication(absent, owner_subject=OWNER, now=lambda: NOW)
    assert _request(app)[0] == 401
    assert not absent.exists()


def test_authorized_response_is_bounded_redacted_local_data(tmp_path: Path) -> None:
    app = _app(tmp_path)
    code, headers, payload = _request(app)
    assert code == 200
    assert payload["source"] == "local_sqlite_intents"
    assert payload["external_confirmation"] == "not_observed"
    assert payload["local_data_age"] == "empty"
    assert "Access-Control-Allow-Origin" not in headers
    serialized = json.dumps(payload)
    for private in (str(tmp_path), OWNER, TOKEN, "credentials", "member_id"):
        assert private not in serialized


@pytest.mark.parametrize(
    "authorization",
    [None, "", "Bearer", "Basic abc", "Bearer bad token", "Bearer x\r\nInjected: true", "x" * 2049],
)
def test_bad_authorization_never_reads_database(tmp_path: Path, authorization: object) -> None:
    absent = tmp_path / "not-created.sqlite3"
    app = StatusApplication(absent, owner_subject=OWNER, verify_identity=_identity, now=lambda: NOW)
    assert _request(app, HTTP_AUTHORIZATION=authorization)[0] == 401
    assert not absent.exists()


@pytest.mark.parametrize("kind", ["foreign", "permission", "expired", "naive"])
def test_verified_identity_still_requires_owner_permission_and_expiry(
    tmp_path: Path, kind: str
) -> None:
    identity = VerifiedIdentity(
        "another-owner" if kind == "foreign" else OWNER,
        frozenset() if kind == "permission" else frozenset({"local-status:read"}),
        datetime(2026, 10, 31)
        if kind == "naive"
        else NOW
        if kind == "expired"
        else NOW + timedelta(1),
    )
    app = StatusApplication(
        tmp_path / "missing.sqlite3",
        owner_subject=OWNER,
        verify_identity=lambda token, now: identity,
        now=lambda: NOW,
    )
    assert _request(app)[0] == 403


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"wsgi.url_scheme": "http", "HTTP_X_FORWARDED_PROTO": "https"}, 400),
        ({"REQUEST_METHOD": "POST"}, 405),
        ({"PATH_INFO": "/api/v1/local-status/../../private"}, 404),
        ({"QUERY_STRING": "database=/private.sqlite3"}, 400),
        ({"CONTENT_LENGTH": "1"}, 400),
        ({"HTTP_TRANSFER_ENCODING": "chunked"}, 400),
        ({"HTTP_ORIGIN": "https://unapproved.invalid"}, 403),
        ({"HTTP_COOKIE": "session=untrusted"}, 400),
    ],
)
def test_request_cannot_select_database_or_relax_transport(
    tmp_path: Path, changes: dict[str, object], expected: int
) -> None:
    assert _request(_app(tmp_path), **changes)[0] == expected


def test_private_reader_and_identity_failures_are_generic(tmp_path: Path) -> None:
    app = StatusApplication(
        tmp_path / "private-secret.sqlite3",
        owner_subject=OWNER,
        verify_identity=_identity,
        now=lambda: NOW,
    )
    code, _, payload = _request(app)
    assert (code, payload) == (503, {"error": "local_status_unavailable"})

    def unavailable(token: str, now: datetime) -> VerifiedIdentity | None:
        raise RuntimeError("private token or provider configuration")

    app = StatusApplication(
        tmp_path / "missing.sqlite3",
        owner_subject=OWNER,
        verify_identity=unavailable,
        now=lambda: NOW,
    )
    assert _request(app)[0:3:2] == (503, {"error": "identity_unavailable"})


def test_malformed_provider_identity_fails_closed_without_traceback(tmp_path: Path) -> None:
    app = StatusApplication(
        tmp_path / "private.sqlite3",
        owner_subject=OWNER,
        verify_identity=lambda token, now: VerifiedIdentity(
            OWNER, frozenset({"local-status:read"}), cast(datetime, None)
        ),
        now=lambda: NOW,
    )
    assert _request(app)[0:3:2] == (403, {"error": "read_not_permitted"})


def test_repeated_authorized_reads_have_bounded_per_process_rate(tmp_path: Path) -> None:
    app = _app(tmp_path)
    assert _request(app)[0] == 200
    code, headers, payload = _request(app)
    assert code == 429
    assert headers["Retry-After"] == "1"
    assert payload == {"error": "read_rate_limited"}


def test_import_and_construction_open_no_listener_and_create_no_database(tmp_path: Path) -> None:
    path = tmp_path / "missing.sqlite3"
    StatusApplication(path, owner_subject=OWNER)
    assert not path.exists()
