"""Explicit protected setup in the exact installed controller; never a deploy.

The post-APPLY step may create only the sector sidecar and a redacted Telegram
observation. It does not migrate legacy SQLite, create a Docker resource,
start a worker, read a secret, contact a provider or infer delivered messages.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from boca_socios import host_boca_binding_observe as binding
from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_current_retained as current
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_on_demand_service as service
from boca_socios.host_on_demand_lifecycle import OnDemandInstallation, read_panel_status

PREFIX = b"BOCA_INSTALLED_ADMIN "
NO_GO = PREFIX + b"state=NO_GO reason=INSTALLED_ADMIN_UNVERIFIED\n"
LIMIT = 4096
_FILENAME = "boca_telegram_admin_status_v1.json"
_TELEGRAM_VOLUME = "boca-socios_boca_telegram"
_FIELDS = frozenset(
    {"schema", "state", "workflow_source_sha", "sector_schema", "legacy_writes", "telegram"}
)
_TELEGRAM_FIELDS = frozenset(
    {
        "version",
        "source_sha",
        "observation_run_id",
        "installation_run_id",
        "controller_id",
        "worker_id",
        "sender_id",
        "observed_at",
        "configured",
        "paired",
        "sender",
        "human_receipt",
    }
)


class AdminNoGo(ValueError):
    """Fixed redacted refusal; never forward exception or Docker text."""


def _fail() -> AdminNoGo:
    return AdminNoGo("installed Boca administrative setup unverified")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"


def _coordinates(workflow_sha: str, run: str, installation: str) -> None:
    if (
        type(workflow_sha) is not str
        or binding._SHA.fullmatch(workflow_sha) is None
        or type(run) is not str
        or binding._RUN.fullmatch(run) is None
        or installation != "current"
        and installation != run
    ):
        raise _fail()


def _telegram_checked(value: object, run: str) -> dict[str, Any]:
    if type(value) is not dict or value.keys() != _TELEGRAM_FIELDS:
        raise _fail()
    if (
        type(value["version"]) is not int
        or value["version"] != 1
        or value["observation_run_id"] != run
        or any(
            type(value[key]) is not str or pattern.fullmatch(value[key]) is None
            for key, pattern in (
                ("source_sha", binding._SHA),
                ("installation_run_id", binding._RUN),
                ("controller_id", binding._ID),
                ("worker_id", binding._ID),
            )
        )
        or value["controller_id"] == value["worker_id"]
        or value["sender_id"] is not None
        or value["sender"] != "ABSENT"
        or (value["configured"], value["paired"])
        not in (("ABSENT", "NOT_PAIRED"), ("UNVERIFIED", "UNVERIFIED"))
        or value["human_receipt"] != "UNVERIFIED"
        or type(value["observed_at"]) is not str
        or len(value["observed_at"]) > 40
    ):
        raise _fail()
    observed = datetime.fromisoformat(value["observed_at"])
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise _fail()
    return value


def verify(raw: bytes, workflow_sha: str, run: str, installation: str) -> dict[str, Any]:
    _coordinates(workflow_sha, run, installation)
    if type(raw) is not bytes or not 0 < len(raw) <= LIMIT or not raw.startswith(PREFIX):
        raise _fail()
    value = json.loads(raw[len(PREFIX) :], object_pairs_hook=binding._unique)
    if (
        type(value) is not dict
        or value.keys() != _FIELDS
        or raw != PREFIX + _canonical(value)
        or type(value["schema"]) is not int
        or value["schema"] != 1
        or value["state"] != "PROVISIONED"
        or value["workflow_source_sha"] != workflow_sha
        or type(value["sector_schema"]) is not int
        or value["sector_schema"] != 2
        or type(value["legacy_writes"]) is not int
        or value["legacy_writes"] != 0
    ):
        raise _fail()
    telegram = _telegram_checked(value["telegram"], run)
    if installation != "current" and (
        telegram["installation_run_id"] != installation or telegram["source_sha"] != workflow_sha
    ):
        raise _fail()
    return value


def _controller_boundary(item: OnDemandInstallation) -> None:
    from boca_socios.host_lifecycle_rootless_adapter import (
        ProductionRootlessDockerIO,
        RootlessLifecycleProbe,
    )

    # Existing exact user, mount, rootless, readonly-rootfs and restart guards.
    RootlessLifecycleProbe(
        item.pair, ProductionRootlessDockerIO(), on_demand=True
    )._service_boundary(item.controller_id, "controller", item.controller_image)


def _snapshot(run: str, lease: cleanup.BocaJobLease) -> tuple[OnDemandInstallation, bytes]:
    item = service.read_installed_binding(lease)
    observed = pair.observe(run)
    binding._attest(run, observed, item)
    worker = json.loads(observed[len(pair._PREFIX) :])["services"][1]
    current.idle_evidence(worker, read_panel_status(item) if worker["status"] == "exited" else None)
    _controller_boundary(item)
    return item, observed


def _controller_receipt(raw: bytes) -> str:
    return (
        "BOCA_INSTALLED_ADMIN_CONTROLLER state=PROVISIONED "
        f"receipt_sha256={hashlib.sha256(raw).hexdigest()} sector_schema=2 legacy_writes=0\n"
    )


def _execute(item: OnDemandInstallation, raw: bytes) -> str:
    return cleanup._docker(
        "exec",
        "--user",
        "10001:10001",
        item.controller_id,
        "/app/.venv/bin/python",
        "-I",
        "-B",
        "-m",
        "boca_socios.host_boca_installed_admin",
        "controller",
        raw.decode("ascii"),
    )


def provision(
    workflow_sha: str, run: str, expected_installation: str, *, now: datetime | None = None
) -> bytes:
    """One leased explicit write after two stable current binding/pair checks.

    Automatic post-APPLY pins installation==run and source==workflow. A later
    explicit refresh uses 'current', deriving installed coordinates again.
    Neither accepts caller-supplied CIDs, paths, categories or credentials.
    """
    _coordinates(workflow_sha, run, expected_installation)
    observed_at = datetime.now(UTC) if now is None else now
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise _fail()
    with cleanup.protected_boca_job_lease(run) as lease:
        item, observed = _snapshot(run, lease)
        if expected_installation != "current" and (
            item.installation_run_id != expected_installation or item.source_sha != workflow_sha
        ):
            raise _fail()
        if _snapshot(run, lease) != (item, observed):
            raise _fail()
        present = _TELEGRAM_VOLUME in json.loads(observed[len(pair._PREFIX) :])["volumes"]
        # The strict pair/binding proves no sender exists. With no custody
        # volume, absence is demonstrated. A present but unmounted custody
        # needs the separate existing telegram-verify helper; never guess.
        telegram = {
            "version": 1,
            "source_sha": item.source_sha,
            "observation_run_id": run,
            "installation_run_id": item.installation_run_id,
            "controller_id": item.controller_id,
            "worker_id": item.worker_id,
            "sender_id": None,
            "observed_at": observed_at.isoformat(),
            "configured": "UNVERIFIED" if present else "ABSENT",
            "paired": "UNVERIFIED" if present else "NOT_PAIRED",
            "sender": "ABSENT",
            "human_receipt": "UNVERIFIED",
        }
        _telegram_checked(telegram, run)
        raw = _canonical(telegram)
        if _execute(item, raw) != _controller_receipt(raw):
            raise _fail()
        if _snapshot(run, lease) != (item, observed):
            raise _fail()
    result = PREFIX + _canonical(
        {
            "schema": 1,
            "state": "PROVISIONED",
            "workflow_source_sha": workflow_sha,
            "sector_schema": 2,
            "legacy_writes": 0,
            "telegram": telegram,
        }
    )
    verify(result, workflow_sha, run, expected_installation)
    return result


def _existing(directory: int) -> tuple[int, int, int, int, int] | None:
    try:
        descriptor = os.open(
            _FILENAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
    except FileNotFoundError:
        return None
    try:
        meta = os.fstat(descriptor)
        if (
            not stat.S_ISREG(meta.st_mode)
            or stat.S_IMODE(meta.st_mode) != 0o600
            or meta.st_nlink != 1
            or (meta.st_uid, meta.st_gid) != (os.geteuid(), os.getegid())
            or not 0 < meta.st_size <= LIMIT
        ):
            raise _fail()
        return meta.st_dev, meta.st_ino, meta.st_size, meta.st_mtime_ns, meta.st_ctime_ns
    finally:
        os.close(descriptor)


def provision_local(database: Path, raw: bytes, *, expected_source_sha: str, now: datetime) -> str:
    """Controller-only implementation; production CLI fixes /data/boca.sqlite3.

    The one test seam is the database directory. Existing legacy SQLite is
    inspected for identity only by MemberSectorStore.migrate(), never opened
    for writes. The panel's own strict parser validates the exact receipt.
    """
    from boca_socios.notify.projection import parse_telegram_admin_receipt
    from boca_socios.panel.member_sector_store import MemberSectorStore

    parse_telegram_admin_receipt(raw, expected_source_sha=expected_source_sha, now=now)
    if raw != _canonical(json.loads(raw)) or not database.is_absolute():
        raise _fail()
    if database.parent.resolve(strict=True) != database.parent:
        raise _fail()
    directory = os.open(database.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = f".boca-admin-{os.getpid()}-{secrets.token_hex(8)}.tmp"
    created = False
    try:
        meta = os.fstat(directory)
        if (meta.st_uid, meta.st_gid) != (os.geteuid(), os.getegid()) or meta.st_mode & 0o022:
            raise _fail()
        before = _existing(directory)
        MemberSectorStore.for_database(database).migrate()
        if _existing(directory) != before:
            raise _fail()
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory
        )
        created = True
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            if _existing(directory) != before:
                raise _fail()
            os.replace(temporary, _FILENAME, src_dir_fd=directory, dst_dir_fd=directory)
            created = False
            os.fsync(directory)
            identity = _existing(directory)
            descriptor = os.open(_FILENAME, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            with os.fdopen(descriptor, "rb") as stream:
                readback = stream.read(LIMIT + 1)
            if readback != raw or _existing(directory) != identity:
                raise _fail()
        finally:
            if created:
                os.unlink(temporary, dir_fd=directory)
    except OSError:
        raise _fail() from None
    finally:
        os.close(directory)
    return _controller_receipt(raw)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(args) == 2 and args[0] == "controller":
            if (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (10001,) * 4:
                raise _fail()
            sys.stdout.write(
                provision_local(
                    Path("/data/boca.sqlite3"),
                    args[1].encode("ascii"),
                    expected_source_sha=os.environ.get("BOCA_SOURCE_SHA", ""),
                    now=datetime.now(UTC),
                )
            )
            return 0
        if len(args) != 4 or args[0] not in ("host", "verify"):
            raise _fail()
        raw = provision(*args[1:]) if args[0] == "host" else sys.stdin.buffer.read(LIMIT + 1)
        verify(raw, *args[1:])
        sys.stdout.buffer.write(raw)
        return 0
    except Exception:
        sys.stdout.buffer.write(NO_GO)
        return 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
