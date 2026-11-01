"""Bounded synthetic SSH-local HTTP journey inside one isolated Boca container.

The CLI never reads mounted application data, owner material or real Boca
credentials. It creates its own short-lived SQLite, key and
passkey in /tmp, connects only to container loopback and prints a small receipt.
It must be invoked by a separate reviewed protected Actions operation.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import math
import os
import re
import resource
import socket
import sqlite3
import statistics
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from urllib.parse import quote, urlencode
from uuid import UUID

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from boca_socios.config import Settings
from boca_socios.runtime import ServedBeta, build_beta_server, initialize_beta

_ORIGIN = "http://localhost:8443"
_HOST = "localhost"
_AUTHORITY = "localhost:8443"
_EVENT = "00000000-0000-4000-8000-000000000001"


class ProbeError(RuntimeError):
    """A synthetic assertion failed; public CLI output stays generic."""


@dataclass(frozen=True, slots=True)
class ProbeReceipt:
    requests: int
    median_ms: float
    p95_ms: float
    elapsed_ms: float
    cpu_ms: float
    process_peak_rss_kib: int
    scratch_bytes: int
    members: int
    intents: int
    notices: int

    def line(self) -> str:
        return (
            "BOCA_SYNTHETIC_ACCEPTANCE state=PASS scope=container_loopback "
            f"requests={self.requests} median_ms={self.median_ms:.2f} "
            f"p95_ms={self.p95_ms:.2f} elapsed_ms={self.elapsed_ms:.2f} "
            f"cpu_ms={self.cpu_ms:.2f} process_peak_rss_kib={self.process_peak_rss_kib} "
            f"scratch_bytes={self.scratch_bytes} "
            f"members={self.members} intents={self.intents} notices={self.notices} "
            "local_http=verified engine=off site=not_contacted telegram=not_sent"
        )


@dataclass(frozen=True, slots=True)
class _Material:
    settings: Settings
    passkey: ec.EllipticCurvePrivateKey
    credential_id: bytes


def _require(condition: bool) -> None:
    if not condition:
        raise ProbeError("synthetic assertion failed")


def _private(path: Path, data: bytes) -> Path:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o400)
    with os.fdopen(descriptor, "wb") as destination:
        destination.write(data)
    return path


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _material(directory: Path) -> _Material:
    passkey = ec.generate_private_key(ec.SECP256R1())
    credential_id = os.urandom(32)
    credential = _private(directory / "credential_id", credential_id)
    public = _private(
        directory / "public_key.der",
        passkey.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
    )
    master = _private(directory / "boca.key", base64.b64encode(os.urandom(32)) + b"\n")
    settings = Settings(
        environment="staging",
        runtime_mode="simulation",
        engine_mode="off",
        db_path=directory / "synthetic.sqlite3",
        master_key_file=master,
        panel_origin=_ORIGIN,
        owner_subject="synthetic_owner",
        passkey_credential_id_file=credential,
        passkey_public_key_der_file=public,
        bind_host="127.0.0.1",
        bind_port=_free_port(),
        site_bridge_mode="off",
    )
    return _Material(settings, passkey, credential_id)


class _LoopbackHTTP(http.client.HTTPConnection):
    def connect(self) -> None:
        self.sock = socket.create_connection(("127.0.0.1", self.port), timeout=self.timeout)


@contextmanager
def _serve(settings: Settings) -> Iterator[None]:
    served: ServedBeta = build_beta_server(settings)
    stopping = Event()
    errors: list[Exception] = []

    def run() -> None:
        try:
            served.serve_until(stopping)
        except Exception as exc:
            errors.append(exc)

    thread = Thread(target=run, name="boca-synthetic-http", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopping.set()
        thread.join(timeout=6)
        served.close()
        _require(not thread.is_alive() and not errors and not served.runtime.ready)


def _request(
    material: _Material,
    path: str,
    timings: list[float],
    *,
    method: str = "GET",
    cookie: str = "",
    fields: dict[str, str] | None = None,
    body: bytes | None = None,
    content_type: str = "application/x-www-form-urlencoded",
    origin: str = _ORIGIN,
) -> tuple[int, dict[str, str], bytes]:
    payload = (
        body if body is not None else urlencode(fields or {}).encode() if method == "POST" else None
    )
    connection = _LoopbackHTTP(_HOST, material.settings.bind_port, timeout=2)
    headers = {"Host": _AUTHORITY}
    if cookie:
        headers["Cookie"] = cookie
    if method == "POST":
        headers.update({"Origin": origin, "Content-Type": content_type})
    started = time.perf_counter_ns()
    try:
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        data = response.read(65537)
        result = response.status, dict(response.getheaders()), data
    finally:
        connection.close()
    timings.append((time.perf_counter_ns() - started) / 1_000_000)
    _require(
        len(data) <= 65536
        and result[1].get("Cache-Control") == "no-store"
        and result[1].get("Content-Length") == str(len(data))
    )
    return result


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _hidden(page: bytes, name: str) -> str:
    match = re.search(rb'name="' + name.encode("ascii") + rb'" value="([^\"]+)"', page)
    _require(match is not None)
    assert match is not None
    return match.group(1).decode("ascii")


def _login(material: _Material, timings: list[float]) -> str:
    status, _, page = _request(material, "/ingresar", timings)
    _require(status == 200)
    challenge = re.search(rb'data-challenge="([A-Za-z0-9_-]+)"', page)
    _require(challenge is not None)
    assert challenge is not None
    client = json.dumps(
        {"type": "webauthn.get", "challenge": challenge.group(1).decode(), "origin": _ORIGIN},
        separators=(",", ":"),
    ).encode()
    auth = hashlib.sha256(_HOST.encode()).digest() + b"\x05" + (1).to_bytes(4, "big")
    signature = material.passkey.sign(
        auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256())
    )
    proof = {
        "credential_id": _b64(material.credential_id),
        "client_data_json": _b64(client),
        "authenticator_data": _b64(auth),
        "signature": _b64(signature),
    }
    status, headers, body = _request(
        material,
        "/sesion",
        timings,
        method="POST",
        body=json.dumps(proof).encode(),
        content_type="application/json",
    )
    _require(status == 204 and not body and "Secure" in headers.get("Set-Cookie", ""))
    return headers["Set-Cookie"].split(";", 1)[0]


def _counts(path: Path) -> tuple[int, int, int, list[tuple[int, str]]]:
    _require(path.is_file() and not path.is_symlink())
    with sqlite3.connect(f"file:{quote(str(path), safe='/')}?mode=ro", uri=True) as db:
        members = int(db.execute("SELECT count(*) FROM members").fetchone()[0])
        requests = db.execute("SELECT quantity FROM ticket_requests").fetchall()
        notices = int(db.execute("SELECT count(*) FROM notification_outbox").fetchone()[0])
        migrations = db.execute(
            "SELECT version,checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
    _require(requests == [(1,)])
    return members, len(requests), notices, migrations


def _first_visit(material: _Material, timings: list[float]) -> tuple[str, str, str]:
    _require(_request(material, "/healthz", timings)[0:1] == (200,))
    _require(_request(material, "/socios", timings)[0] == 401)
    _require(_request(material, "/avisos", timings)[0] == 401)
    cookie = _login(material, timings)
    status, _, form = _request(material, "/socios/nuevo", timings, cookie=cookie)
    _require(status == 200)
    fields = {
        "csrf": _hidden(form, "csrf"),
        "operation_id": _hidden(form, "operation_id"),
        "alias": "Socio sintético",
        "email": "synthetic-member@example.test",
        "password": "synthetic-only-private-value",
        "consent": "yes",
    }
    denied = _request(
        material,
        "/socios",
        timings,
        method="POST",
        cookie=cookie,
        fields=fields,
        origin="https://foreign.example.test",
    )
    _require(denied[0] == 403)
    status, _, enrolled = _request(
        material, "/socios", timings, method="POST", cookie=cookie, fields=fields
    )
    _require(status == 201 and fields["password"].encode() not in enrolled)
    repeated = _request(material, "/socios", timings, method="POST", cookie=cookie, fields=fields)
    _require(repeated[0] == 201 and repeated[2] == enrolled)
    member_id = json.loads(enrolled)["member_id"]
    _require(isinstance(member_id, str) and str(UUID(member_id)) == member_id)
    listed = _request(material, "/socios", timings, cookie=cookie)
    _require(listed[0] == 200 and fields["email"].encode() not in listed[2])
    command_form = _request(material, "/comandos", timings, cookie=cookie)
    _require(command_form[0] == 200)
    command_id = _hidden(command_form[2], "operation_id")
    command = {
        "csrf": _hidden(command_form[2], "csrf"),
        "operation_id": command_id,
        "member_id": member_id,
        "event_id": _EVENT,
    }
    # The session bounds writes to one per second; the enrollment is complete.
    time.sleep(1.05)
    started = _request(material, "/comandos", timings, method="POST", cookie=cookie, fields=command)
    _require(started[0] == 303 and started[1].get("Location") == f"/comandos/{command_id}")
    replay = _request(material, "/comandos", timings, method="POST", cookie=cookie, fields=command)
    _require(replay[0] == 303 and replay[1].get("Location") == started[1].get("Location"))
    deadline = time.monotonic() + 3
    while True:
        detail = _request(material, f"/comandos/{command_id}", timings, cookie=cookie)
        _require(detail[0] == 200)
        if b"Estado: completed" in detail[2]:
            break
        _require(time.monotonic() < deadline)
        time.sleep(0.02)
    notice_deadline = time.monotonic() + 3
    while True:
        notices = _request(material, "/avisos", timings, cookie=cookie)
        _require(notices[0] == 200 and fields["email"].encode() not in notices[2])
        if b"Aviso local" in notices[2]:
            _require(b"Telegram no configurado" in notices[2])
            break
        _require(time.monotonic() < notice_deadline)
        time.sleep(0.02)
    state = _request(material, "/estado", timings, cookie=cookie)
    _require(state[0] == 200 and b"no observada" in state[2])
    stop = _request(
        material,
        f"/comandos/{command_id}/detener",
        timings,
        method="POST",
        cookie=cookie,
        fields={"csrf": command["csrf"]},
    )
    _require(stop[0] == 303 and stop[1].get("Location") == f"/comandos/{command_id}")
    return cookie, member_id, command_id


def _restart_visit(
    material: _Material, timings: list[float], old_cookie: str, member_id: str, command_id: str
) -> None:
    _require(_request(material, "/avisos", timings, cookie=old_cookie)[0] == 401)
    cookie = _login(material, timings)
    detail = _request(material, f"/comandos/{command_id}", timings, cookie=cookie)
    _require(detail[0] == 200 and b"Estado: completed" in detail[2])
    form = _request(material, "/comandos", timings, cookie=cookie)
    _require(form[0] == 200)
    new_id = _hidden(form[2], "operation_id")
    _require(new_id != command_id)
    command = {
        "csrf": _hidden(form[2], "csrf"),
        "operation_id": new_id,
        "member_id": member_id,
        "event_id": _EVENT,
    }
    alias = _request(material, "/comandos", timings, method="POST", cookie=cookie, fields=command)
    _require(alias[0] == 303 and alias[1].get("Location") == f"/comandos/{command_id}")
    _require(_request(material, "/avisos", timings, cookie=cookie)[0] == 200)


def _run_probe(root: Path) -> ProbeReceipt:
    """Test seam; the CLI passes only fixed /tmp and never caller-selected paths."""
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ProbeError("disposable root unavailable")
    timings: list[float] = []
    started = time.perf_counter()
    cpu_start = resource.getrusage(resource.RUSAGE_SELF)
    with TemporaryDirectory(prefix="boca-synthetic-", dir=root) as name:
        directory = Path(name)
        material = _material(directory)
        initialize_beta(material.settings)
        with _serve(material.settings):
            cookie, member_id, command_id = _first_visit(material, timings)
        members, intents, notices, before = _counts(material.settings.db_path)
        _require((members, intents, notices) == (1, 1, 1))
        with _serve(material.settings):
            _restart_visit(material, timings, cookie, member_id, command_id)
        _require(_counts(material.settings.db_path) == (members, intents, notices, before))
        scratch_bytes = sum(item.stat().st_size for item in directory.iterdir() if item.is_file())
        _require(scratch_bytes <= 8 * 1024 * 1024)
    cpu_end = resource.getrusage(resource.RUSAGE_SELF)
    ordered = sorted(timings)
    _require(len(ordered) >= 18)
    return ProbeReceipt(
        requests=len(ordered),
        median_ms=statistics.median(ordered),
        p95_ms=ordered[math.ceil(0.95 * len(ordered)) - 1],
        elapsed_ms=(time.perf_counter() - started) * 1000,
        cpu_ms=(cpu_end.ru_utime + cpu_end.ru_stime - cpu_start.ru_utime - cpu_start.ru_stime)
        * 1000,
        process_peak_rss_kib=cpu_end.ru_maxrss,
        scratch_bytes=scratch_bytes,
        members=members,
        intents=intents,
        notices=notices,
    )


def main() -> int:
    # Fixed invocation shape for the reviewed protected Docker exec operation.
    if (
        os.geteuid() != 10001
        or os.environ.get("BOCA_ENVIRONMENT") != "staging"
        or os.environ.get("BOCA_RUNTIME_MODE") != "simulation"
        or os.environ.get("BOCA_ENGINE_MODE") != "off"
        or os.environ.get("BOCA_DB_PATH") != "/data/boca.sqlite3"
    ):
        print("BOCA_SYNTHETIC_ACCEPTANCE state=NO_GO reason=container_boundary_unverified")
        return 1
    try:
        receipt = _run_probe(Path("/tmp"))  # noqa: S108 - isolated container tmpfs, unique dir
    except Exception:
        print("BOCA_SYNTHETIC_ACCEPTANCE state=NO_GO reason=synthetic_probe_failed")
        return 1
    print(receipt.line())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
