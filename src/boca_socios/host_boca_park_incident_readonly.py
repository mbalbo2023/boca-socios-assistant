"""R278: bounded, host-only READ_ONLY witness of the failed #1085 PARK.

An exact authenticated Actions main streams these source bytes over pinned SSH.
Nothing is installed, started, stopped, renamed, deleted or written on host.
This is a *forensic* witness, never restoration authority. Its observation
does not substitute the new-lease, independently reviewed recovery gate.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import pwd
import re
import stat
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

INCIDENT = "43479367282"
INCIDENT_SOURCE_SHA = "3a933f0ac7f51043e9d69a185558345e0a31a77d"
PREVIOUS_SOURCE_SHA = "b61ca3e58d4f8ce69cd6d7575f2a8e1ce59bda72"
RELEASE_RUN = "43478524966"
CONTROLLER_REF = (
    "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:"
    "2c03ab0b74481c779e8f7b91f1d5b0109cd176d39f6a7c9cdbcd19d6972fe764"
)
WORKER_REF = (
    "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
    "f6deed38bd4fa88cff0b0114c407d90ae640e6c83d1d723c9ab19ec9324d62c4"
)
_HOME = Path("/home/boca-deploy")
_STAGE = Path("/srv/boca-socios")
_DOCKER_ROOT = "/home/boca-deploy/.local/share/docker"
_SOCKET = "unix:///run/user/10001/docker.sock"
_UID = 10001
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_PREFIX = b"BOCA_PARK_INCIDENT_READONLY_V1 "
_BOUND = 4096
_PHASES = frozenset(
    {
        "HOST_IDENTITY_UNVERIFIED",
        "JOURNAL_UNVERIFIED",
        "PARKED_BINDING_UNVERIFIED",
        "PAIR_UNVERIFIED",
        "RETAINED_NAMES_UNVERIFIED",
        "DOUBLE_READ_DRIFT",
        "PHYSICAL_UNVERIFIED",
    }
)


class ParkIncidentNoGo(ValueError):
    """Fixed public refusal, never an exception with host data."""

    def __init__(self, category: str = "PHYSICAL_UNVERIFIED") -> None:
        self.category = category if category in _PHASES else "PHYSICAL_UNVERIFIED"
        super().__init__("Boca incident custody NO_GO")


def _fail() -> ParkIncidentNoGo:
    return ParkIncidentNoGo()


@contextmanager
def _gate(category: str) -> Iterator[None]:
    """Preserve a closed failure phase without host exception text."""
    try:
        yield
    except Exception:
        raise ParkIncidentNoGo(category) from None


@dataclass(frozen=True)
class JournalPins:
    old_attempt_id: str
    old_source_sha: str
    old_controller_id: str
    old_worker_id: str
    old_controller_image_id: str
    old_worker_image_id: str
    control_inode_sha256: str
    observation_run_id: str


def _json(raw: bytes, *, limit: int) -> dict[str, object]:
    if not 0 < len(raw) <= limit:
        raise _fail()
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeError):
        raise _fail() from None
    if type(parsed) is not dict:
        raise _fail()
    return parsed


def _hex(value: object) -> bool:
    return type(value) is str and _HEX.fullmatch(value) is not None


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def verify_journal(
    evidence: bytes, intent: bytes, terminal: bytes, *, commit_present: bool
) -> JournalPins:
    """No COMMIT, exact hashed intent/evidence, immutable failed terminal."""
    try:
        if commit_present:
            raise _fail()
        body = _json(evidence, limit=4096)
        plan = body.get("plan")
        witness = body.get("witness")
        release = body.get("release")
        if (
            body.keys() != {"version", "plan", "witness", "release"}
            or body["version"] != "boca-successor-pair-intent-evidence-v1"
            or type(plan) is not dict
            or type(witness) is not dict
            or type(release) is not dict
            or plan.get("attempt_id") != INCIDENT
            or plan.get("new_source_sha") != INCIDENT_SOURCE_SHA
            or plan.get("old_source_sha") != PREVIOUS_SOURCE_SHA
            or plan.get("release_run_id") != RELEASE_RUN
            or plan.get("controller_ref") != CONTROLLER_REF
            or plan.get("worker_ref") != WORKER_REF
            or any(not _hex(plan.get(k)) for k in ("old_controller_id", "old_worker_id"))
            or any(
                not _hex(plan.get(k, "")[7:]) or not str(plan.get(k, "")).startswith("sha256:")
                for k in ("old_controller_image_id", "old_worker_image_id")
            )
        ):
            raise _fail()
        keys = (
            ("old_attempt_id", "old_attempt_id"),
            ("old_source_sha", "old_source_sha"),
            ("controller_id", "old_controller_id"),
            ("worker_id", "old_worker_id"),
            ("controller_image_id", "old_controller_image_id"),
            ("worker_image_id", "old_worker_image_id"),
            ("observation_run_id", "observation_run_id"),
        )
        if (
            any(witness.get(left) != plan.get(right) for left, right in keys)
            or not _hex(witness.get("control_inode_sha256"))
            or type(witness.get("retained")) is not dict
            or any(
                not _RUN.fullmatch(str(plan.get(k, "")))
                for k in ("old_attempt_id", "observation_run_id")
            )
            or plan["old_controller_id"] == plan["old_worker_id"]
        ):
            raise _fail()
        if (
            release.keys()
            != {
                "source_sha",
                "release_run_id",
                "controller_ref",
                "worker_ref",
                "controller_manifest_sha256",
                "paired_manifest_sha256",
            }
            or not _hex(release.get("controller_manifest_sha256"))
            or not _hex(release.get("paired_manifest_sha256"))
            or release.get("source_sha") != INCIDENT_SOURCE_SHA
            or release.get("release_run_id") != RELEASE_RUN
            or release.get("controller_ref") != CONTROLLER_REF
            or release.get("worker_ref") != WORKER_REF
        ):
            raise _fail()
        statement = _json(intent, limit=1024)
        if statement != {
            "attempt": INCIDENT,
            "evidence_sha256": hashlib.sha256(evidence).hexdigest(),
            "old_controller": plan["old_controller_id"],
            "old_worker": plan["old_worker_id"],
            "old_source": PREVIOUS_SOURCE_SHA,
            "new_source": INCIDENT_SOURCE_SHA,
            "release": RELEASE_RUN,
        }:
            raise _fail()
        if not terminal.startswith(b"BOCA_PAIR_UPGRADE ") or not terminal.endswith(b"\n"):
            raise _fail()
        result = _json(terminal[len(b"BOCA_PAIR_UPGRADE ") : -1], limit=1024)
        if result != {
            "schema": 1,
            "attempt_id": INCIDENT,
            "state": "NO_GO",
            "cleanup": "INDETERMINATE",
            "old_restored": False,
            "commit_started": False,
            "controller_id": None,
            "worker_id": None,
            "failed_phase": "CREATE_WORKER",
        }:
            raise _fail()
        return JournalPins(
            plan["old_attempt_id"],
            PREVIOUS_SOURCE_SHA,
            plan["old_controller_id"],
            plan["old_worker_id"],
            plan["old_controller_image_id"],
            plan["old_worker_image_id"],
            witness["control_inode_sha256"],
            plan["observation_run_id"],
        )
    except (KeyError, TypeError, AttributeError, IndexError, UnicodeError, ValueError):
        raise _fail() from None


def verify_parked_containers(
    pins: JournalPins, observed_ids: list[str], records: list[dict[str, object]]
) -> None:
    """Only the two original exact CIDs, parked names, source/role/image."""
    if (
        type(pins) is not JournalPins
        or type(observed_ids) is not list
        or len(observed_ids) != 2
        or set(observed_ids) != {pins.old_controller_id, pins.old_worker_id}
        or len(records) != 2
    ):
        raise _fail()
    by_id = {record.get("Id"): record for record in records if type(record) is dict}
    if len(by_id) != 2:
        raise _fail()
    for cid, role, image_id in (
        (pins.old_controller_id, "controller", pins.old_controller_image_id),
        (pins.old_worker_id, "browser-worker", pins.old_worker_image_id),
    ):
        record = by_id.get(cid)
        if type(record) is not dict:
            raise _fail()
        config, state, host = record.get("Config"), record.get("State"), record.get("HostConfig")
        labels = config.get("Labels") if type(config) is dict else None
        expected_name = f"/boca-socios-{role}-legacy-{INCIDENT}"
        if (
            record.get("Image") != image_id
            or record.get("Name") != expected_name
            or type(labels) is not dict
            or labels.get("com.docker.compose.project") != "boca-socios"
            or labels.get("com.docker.compose.service") != role
            or labels.get("boca.socios.browser-ipc-attempt") != pins.old_attempt_id
            or labels.get("org.opencontainers.image.revision") != pins.old_source_sha
            or type(state) is not dict
            or state.get("Status") != ("exited" if role == "controller" else "created")
            or state.get("Running") is not False
            or state.get("Pid") != 0
            or type(host) is not dict
            or host.get("RestartPolicy") != {"Name": "no", "MaximumRetryCount": 0}
        ):
            raise _fail()
        if role == "browser-worker" and state.get("ExitCode") != 0:
            raise _fail()


def _require_owner() -> None:
    owner = pwd.getpwuid(_UID)
    if (
        (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (_UID,) * 4
        or owner.pw_name != "boca-deploy"
        or owner.pw_dir != str(_HOME)
        or owner.pw_gid != _UID
        or any(
            key in os.environ
            for key in (
                "DOCKER_CONTEXT",
                "DOCKER_TLS_VERIFY",
                "DOCKER_CERT_PATH",
                "DOCKER_CONFIG",
                "DOCKER_TLS",
            )
        )
        or os.environ.get("DOCKER_HOST", _SOCKET) != _SOCKET
    ):
        raise _fail()


def _read_staged(name: str, *, limit: int) -> bytes:
    if name not in {
        f".boca-pair-upgrade-{INCIDENT}.{kind}" for kind in ("intent", "evidence", "terminal")
    }:
        raise _fail()
    folder = os.open(_STAGE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        meta = os.fstat(folder)
        if (
            not stat.S_ISDIR(meta.st_mode)
            or meta.st_uid != _UID
            or meta.st_gid != _UID
            or stat.S_IMODE(meta.st_mode) != 0o700
        ):
            raise _fail()
        fd = os.open(
            name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=folder
        )
        try:
            stat_before = os.fstat(fd)
            if (
                not stat.S_ISREG(stat_before.st_mode)
                or stat_before.st_uid != _UID
                or stat_before.st_gid != _UID
                or stat.S_IMODE(stat_before.st_mode) != 0o600
                or stat_before.st_nlink != 1
                or not 0 < stat_before.st_size <= limit
            ):
                raise _fail()
            raw = os.read(fd, limit + 1)
            stat_after = os.fstat(fd)
            if len(raw) != stat_before.st_size or (
                stat_before.st_dev,
                stat_before.st_ino,
                stat_before.st_size,
                stat_before.st_mtime_ns,
                stat_before.st_ctime_ns,
            ) != (
                stat_after.st_dev,
                stat_after.st_ino,
                stat_after.st_size,
                stat_after.st_mtime_ns,
                stat_after.st_ctime_ns,
            ):
                raise _fail()
            return raw
        finally:
            os.close(fd)
    finally:
        os.close(folder)


def _commit_present() -> bool:
    root = os.open(_STAGE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        try:
            os.stat(f".boca-pair-upgrade-{INCIDENT}.commit", dir_fd=root, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False
    finally:
        os.close(root)


def _path_inode(path: Path) -> str:
    """Equivalent to the original O_PATH nofollow identity hash, not path hash."""
    fd = os.open("/", os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        for component in path.parts[1:]:
            nxt = os.open(
                component, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd
            )
            os.close(fd)
            fd = nxt
        item = os.fstat(fd)
        if not stat.S_ISDIR(item.st_mode) or item.st_ino <= 0:
            raise _fail()
        return hashlib.sha256(
            _canonical(
                [
                    item.st_dev,
                    item.st_ino,
                    item.st_uid,
                    item.st_gid,
                    stat.S_IMODE(item.st_mode),
                    item.st_nlink,
                ]
            )
        ).hexdigest()
    finally:
        os.close(fd)


def _verify_parked_binding(pins: JournalPins) -> None:
    """Old control inode and installation files must remain parked byte-identically."""
    root = _HOME / f".boca-on-demand-parked-{INCIDENT}"
    if (_HOME / ".boca-on-demand").exists() or (_HOME / ".boca-on-demand").is_symlink():
        raise _fail()
    meta = root.lstat()
    if (
        not stat.S_ISDIR(meta.st_mode)
        or meta.st_uid != _UID
        or meta.st_gid != _UID
        or stat.S_IMODE(meta.st_mode) != 0o700
        or _path_inode(root / "socket") != pins.control_inode_sha256
    ):
        raise _fail()
    if set(os.listdir(root)) != {
        "attempt",
        "binding.json",
        "handler.pyz",
        "boca-bot-control.socket",
        "boca-bot-control@.service",
        "socket",
    }:
        raise _fail()
    marker = root / "attempt"
    if marker.is_symlink() or marker.read_text(encoding="ascii") != pins.old_attempt_id + "\n":
        raise _fail()
    binding = root / "binding.json"
    if binding.is_symlink() or binding.stat().st_size > 8192:
        raise _fail()
    obj = _json(binding.read_bytes(), limit=8192)
    installed = obj.get("installation")
    if (
        obj.get("version") != 1
        or type(installed) is not dict
        or installed.get("installation_run_id") != pins.old_attempt_id
        or installed.get("source_sha") != pins.old_source_sha
        or installed.get("controller_id") != pins.old_controller_id
        or installed.get("worker_id") != pins.old_worker_id
        or not _hex(obj.get("bundle_sha256"))
    ):
        raise _fail()
    archive = root / "handler.pyz"
    if archive.is_symlink() or not 0 < archive.stat().st_size <= 512000:
        raise _fail()
    if hashlib.sha256(archive.read_bytes()).hexdigest() != obj["bundle_sha256"]:
        raise _fail()
    socket_dir = root / "socket"
    if set(os.listdir(socket_dir)) not in (set(), {"control.sock"}):
        raise _fail()


def _docker(*args: str) -> str:
    env = {
        "DOCKER_HOST": _SOCKET,
        "XDG_RUNTIME_DIR": "/run/user/10001",
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
    }
    response = subprocess.run(  # noqa: S603 - fixed Boca socket, exact Docker CLI; never shell
        ["/usr/bin/docker", "--host", _SOCKET, *args],
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
        env=env,
    )
    if response.returncode != 0 or len(response.stdout) > 131072 or len(response.stderr) > 131072:
        raise _fail()
    return response.stdout


def _physical_containers(pins: JournalPins) -> None:
    if json.loads(_docker("info", "--format", "{{json .DockerRootDir}}")) != _DOCKER_ROOT:
        raise _fail()
    ids = _docker(
        "ps", "-aq", "--no-trunc", "--filter", "label=com.docker.compose.project=boca-socios"
    ).splitlines()
    if len(ids) != 2 or any(not _hex(cid) for cid in ids):
        raise _fail()
    records = []
    for cid in ids:
        value = json.loads(_docker("inspect", "--type", "container", cid))
        if type(value) is not list or len(value) != 1 or type(value[0]) is not dict:
            raise _fail()
        records.append(value[0])
    verify_parked_containers(pins, ids, records)


def _retained_names_present() -> None:
    """Only Docker name/driver existence, NOT inode, ownership or data attestation."""
    for name in (
        "boca-socios_boca_data",
        "boca-socios_boca_key",
        "boca-socios_boca_owner",
        "boca-socios_boca_browser_ipc",
        "boca-socios_boca_site_config",
    ):
        records = json.loads(_docker("volume", "inspect", name))
        if (
            type(records) is not list
            or len(records) != 1
            or type(records[0]) is not dict
            or records[0].get("Name") != name
            or records[0].get("Driver") != "local"
            or records[0].get("Mountpoint") != f"{_DOCKER_ROOT}/volumes/{name}/_data"
            or records[0].get("Options") not in (None, {})
        ):
            raise _fail()
    networks = json.loads(_docker("network", "inspect", "boca-socios_boca_browser_egress"))
    if (
        type(networks) is not list
        or len(networks) != 1
        or type(networks[0]) is not dict
        or networks[0].get("Name") != "boca-socios_boca_browser_egress"
        or not _hex(networks[0].get("Id"))
    ):
        raise _fail()


def _loopback_health() -> str:
    connection = http.client.HTTPConnection("127.0.0.1", 8443, timeout=3)
    try:
        connection.request("GET", "/healthz", headers={"Host": "localhost:8443"})
        return "HTTP_200" if connection.getresponse().status == 200 else "NON_200"
    except (OSError, TimeoutError, http.client.HTTPException):
        return "UNAVAILABLE"
    finally:
        connection.close()


def observe_host(run_id: str, source_sha: str) -> dict[str, object]:
    if _RUN.fullmatch(run_id) is None or _SHA.fullmatch(source_sha) is None:
        raise _fail()
    with _gate("HOST_IDENTITY_UNVERIFIED"):
        _require_owner()
    with _gate("JOURNAL_UNVERIFIED"):
        journal = (
            _read_staged(f".boca-pair-upgrade-{INCIDENT}.evidence", limit=4096),
            _read_staged(f".boca-pair-upgrade-{INCIDENT}.intent", limit=1024),
            _read_staged(f".boca-pair-upgrade-{INCIDENT}.terminal", limit=1024),
        )
        pins = verify_journal(*journal, commit_present=_commit_present())
    with _gate("PARKED_BINDING_UNVERIFIED"):
        _verify_parked_binding(pins)
    with _gate("PAIR_UNVERIFIED"):
        _physical_containers(pins)
    with _gate("RETAINED_NAMES_UNVERIFIED"):
        _retained_names_present()
    # A second full physical observation rejects changes during this read.
    with _gate("DOUBLE_READ_DRIFT"):
        if (
            journal
            != (
                _read_staged(f".boca-pair-upgrade-{INCIDENT}.evidence", limit=4096),
                _read_staged(f".boca-pair-upgrade-{INCIDENT}.intent", limit=1024),
                _read_staged(f".boca-pair-upgrade-{INCIDENT}.terminal", limit=1024),
            )
            or _commit_present()
        ):
            raise _fail()
        _verify_parked_binding(pins)
        _physical_containers(pins)
        _retained_names_present()
    return {
        "schema": 1,
        "state": "OBSERVED_PARKED",
        "incident": INCIDENT,
        "run_id": run_id,
        "source_sha": source_sha,
        "previous_source_sha": pins.old_source_sha,
        "old_attempt_id": pins.old_attempt_id,
        "controller_id": pins.old_controller_id,
        "worker_id": pins.old_worker_id,
        "control_inode_sha256": pins.control_inode_sha256,
        "journal": "PRECOMMIT_NO_GO_TERMINAL",
        "control": "PARKED_ORIGINAL_INODE",
        "rootless_pair": "EXACT_OLD_CIDS_PARKED",
        "retained": "NAMES_PRESENT_INODES_UNVERIFIED",
        "health": _loopback_health(),
        "observer_writes": 0,
        "restore_authorized": False,
        "deploy": "NO_GO",
    }


def classify(raw: bytes, run_id: str, source_sha: str) -> str:
    if not raw.startswith(_PREFIX) or not raw.endswith(b"\n") or len(raw) > _BOUND:
        raise _fail()
    record = _json(raw[len(_PREFIX) : -1], limit=_BOUND)
    expected = {
        "schema",
        "state",
        "incident",
        "run_id",
        "source_sha",
        "previous_source_sha",
        "old_attempt_id",
        "controller_id",
        "worker_id",
        "control_inode_sha256",
        "journal",
        "control",
        "rootless_pair",
        "retained",
        "health",
        "observer_writes",
        "restore_authorized",
        "deploy",
    }
    if (
        record.keys() != expected
        or record["schema"] != 1
        or record["state"] != "OBSERVED_PARKED"
        or record["incident"] != INCIDENT
        or record["run_id"] != run_id
        or record["source_sha"] != source_sha
        or record["previous_source_sha"] != PREVIOUS_SOURCE_SHA
        or not _RUN.fullmatch(str(record["old_attempt_id"]))
        or any(
            not _hex(record[key]) for key in ("controller_id", "worker_id", "control_inode_sha256")
        )
        or record["journal"] != "PRECOMMIT_NO_GO_TERMINAL"
        or record["control"] != "PARKED_ORIGINAL_INODE"
        or record["rootless_pair"] != "EXACT_OLD_CIDS_PARKED"
        or record["retained"] != "NAMES_PRESENT_INODES_UNVERIFIED"
        or record["health"] not in ("UNAVAILABLE", "NON_200", "HTTP_200")
        or record["observer_writes"] != 0
        or record["restore_authorized"] is not False
        or record["deploy"] != "NO_GO"
    ):
        raise _fail()
    return (_PREFIX + _canonical(record)).decode("ascii")


def classify_failure(raw: bytes) -> str:
    """Carry only a fixed failure category across SSH, never raw host output."""
    try:
        decoded = raw.decode("ascii")
    except UnicodeError:
        raise _fail() from None
    for category in sorted(_PHASES):
        expected = (
            f"BOCA_PARK_INCIDENT_READONLY state=NO_GO reason={category} "
            "observer_writes=0 deploy=NO_GO\n"
        )
        if decoded == expected:
            return expected.rstrip("\n")
    raise _fail()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 3 and args[0] == "host":
        try:
            found = observe_host(args[1], args[2])
            print((_PREFIX + _canonical(found)).decode("ascii"))
            return 0
        except ParkIncidentNoGo as exc:
            print(
                "BOCA_PARK_INCIDENT_READONLY state=NO_GO "
                f"reason={exc.category} observer_writes=0 deploy=NO_GO"
            )
            return 3
        except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired):
            print(
                "BOCA_PARK_INCIDENT_READONLY state=NO_GO reason=PHYSICAL_UNVERIFIED observer_writes=0 deploy=NO_GO"
            )
            return 3
    if len(args) == 3 and args[0] == "classify":
        try:
            raw = sys.stdin.buffer.read(_BOUND + 1)
            if raw.startswith(_PREFIX):
                print(classify(raw, args[1], args[2]))
                return 0
            print(classify_failure(raw))
            return 3
        except (OSError, ValueError, UnicodeError):
            print(
                "BOCA_PARK_INCIDENT_READONLY state=NO_GO reason=RECEIPT_UNVERIFIED observer_writes=0 deploy=NO_GO"
            )
            return 3
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
