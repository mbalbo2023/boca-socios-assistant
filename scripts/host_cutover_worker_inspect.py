"""Boca-only READ_ONLY diagnosis of one failed temporary worker preflight.

Streamed over the existing protected Boca Actions SSH channel. The observer
only uses lstat and rootless Docker ps/inspect scoped to exact Boca identities;
it never creates, starts, stops, executes or removes a host resource.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

UID = 10001
RUNTIME = Path("/run/user/10001")
SOCKET = RUNTIME / "docker.sock"
PREFIX = "boca-socios-cutover-preflight-"
PROBE_LABEL = "boca.socios.cutover-preflight-attempt"
PROJECT = "boca-socios"
ORIGINAL_NAME = "/boca-socios-controller-1"
RUN_ID = re.compile(r"[1-9][0-9]{0,19}\Z")
CONTAINER_ID = re.compile(r"[0-9a-f]{64}\Z")
SOURCE_SHA = re.compile(r"[0-9a-f]{40}\Z")
IMAGE = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
BROWSER_IMAGE = re.compile(
    r"ghcr\.io/mbalbo2023/boca-socios-assistant-browser@sha256:[0-9a-f]{64}\Z"
)
INSPECT = (
    '{"id":{{json .Id}},"name":{{json .Name}},'
    '"image_ref":{{json .Config.Image}},'
    '"revision":{{json (index .Config.Labels "org.opencontainers.image.revision")}},'
    '"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
    '"attempt":{{json (index .Config.Labels "boca.socios.cutover-preflight-attempt")}},'
    '"running":{{json .State.Running}},'
    '"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}},'
    '"ports":{{json .HostConfig.PortBindings}}}'
)
RECEIPT_KEYS = {
    "version",
    "attempt",
    "legacy_id",
    "socket",
    "docker",
    "probe",
    "probe_id",
    "probe_running",
    "seccomp",
    "original",
    "original_port",
    "observer_writes",
    "foreign_resources_touched",
    "cutover_authorized",
}


class InspectError(ValueError):
    """Invalid trusted-input contract, not evidence about host state."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _validate(attempt: str, original_id: str, original_sha: str, original_image: str) -> None:
    if (
        not RUN_ID.fullmatch(attempt)
        or not CONTAINER_ID.fullmatch(original_id)
        or not SOURCE_SHA.fullmatch(original_sha)
        or not IMAGE.fullmatch(original_image)
    ):
        raise InspectError("COORDINATES")


def _runtime_stat(name: str) -> str:
    """Check only a single fixed entry under the dedicated Boca UID runtime."""
    try:
        directory = os.open(RUNTIME, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        return "UNVERIFIED"
    try:
        root = os.fstat(directory)
        if root.st_uid != UID or not stat.S_ISDIR(root.st_mode):
            return "UNVERIFIED"
        try:
            entry = os.stat(name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            return "ABSENT"
        except OSError:
            return "UNVERIFIED"
        if name == "docker.sock":
            return (
                "PRESENT_OWNED"
                if stat.S_ISSOCK(entry.st_mode) and entry.st_uid == UID
                else "PRESENT_UNVERIFIED"
            )
        return (
            "PRESENT_OWNED"
            if stat.S_ISREG(entry.st_mode)
            and entry.st_uid == UID
            and stat.S_IMODE(entry.st_mode) == 0o600
            else "PRESENT_UNVERIFIED"
        )
    finally:
        os.close(directory)


def _docker(*args: str) -> str:
    """Permit only exact-name container listing or exact-ID metadata inspection."""
    if not (
        args[:3] == ("ps", "-a", "-q")
        and len(args) == 6
        and args[3:5] == ("--no-trunc", "--filter")
        and re.fullmatch(r"name=\^/boca-socios-cutover-preflight-[1-9][0-9]{0,19}\$", args[5])
        is not None
        or args[:2] == ("inspect", "--format")
        and len(args) == 4
        and args[2] == INSPECT
        and CONTAINER_ID.fullmatch(args[3]) is not None
    ):
        raise InspectError("DOCKER_COMMAND")
    env = {key: value for key, value in os.environ.items() if not key.startswith("DOCKER_")}
    env["DOCKER_HOST"] = f"unix://{SOCKET}"
    completed = subprocess.run(  # noqa: S603 - narrow READ_ONLY Docker metadata
        ("docker", *args),  # noqa: S607 - pinned rootless Docker socket, no shell
        capture_output=True,
        text=True,
        timeout=12,
        check=True,
        env=env,
    )
    if len(completed.stdout) > 2048:
        raise InspectError("DOCKER_BOUNDS")
    return completed.stdout.strip()


def _named_id(name: str) -> str | None:
    if not name.startswith(PREFIX) or not RUN_ID.fullmatch(name.removeprefix(PREFIX)):
        raise InspectError("PROBE_NAME")
    rows = _docker("ps", "-a", "-q", "--no-trunc", "--filter", f"name=^/{name}$").splitlines()
    if len(rows) > 1 or any(not CONTAINER_ID.fullmatch(item) for item in rows):
        raise InspectError("PROBE_SET")
    return rows[0] if rows else None


def _inspect_id(cid: str) -> dict[str, Any]:
    value = json.loads(_docker("inspect", "--format", INSPECT, cid))
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "id",
            "name",
            "image_ref",
            "revision",
            "project",
            "attempt",
            "running",
            "health",
            "ports",
        }
        or value["id"] != cid
        or type(value["running"]) is not bool
    ):
        raise InspectError("INSPECT_IDENTITY")
    return value


def observe(
    attempt: str, original_id: str, original_sha: str, original_image: str
) -> dict[str, Any]:
    _validate(attempt, original_id, original_sha, original_image)
    result: dict[str, Any] = {
        "version": "boca-worker-readonly-inspect-v1",
        "attempt": attempt,
        "legacy_id": original_id,
        "socket": _runtime_stat("docker.sock"),
        "seccomp": _runtime_stat(f"{PREFIX}{attempt}-seccomp.json"),
        "docker": "UNVERIFIED",
        "probe": "UNVERIFIED",
        "probe_id": None,
        "probe_running": None,
        "original": "UNVERIFIED",
        "original_port": "UNVERIFIED",
        "observer_writes": 0,
        "foreign_resources_touched": False,
        "cutover_authorized": False,
    }
    if os.geteuid() != UID or os.getegid() != UID:
        result["docker"] = "WRONG_UID"
        return result
    if result["socket"] != "PRESENT_OWNED":
        result["docker"] = "SOCKET_UNVERIFIED"
        return result
    name = f"{PREFIX}{attempt}"
    try:
        probe_id = _named_id(name)
        result["probe"] = "ABSENT" if probe_id is None else "PRESENT_UNVERIFIED"
        if probe_id is not None:
            probe = _inspect_id(probe_id)
            if (
                probe["name"] == f"/{name}"
                and probe["project"] == PROJECT
                and probe["attempt"] == attempt
                and type(probe["image_ref"]) is str
                and BROWSER_IMAGE.fullmatch(probe["image_ref"])
            ):
                # Matching labels and repository prove scope, not an exact
                # immutable image identity; never use this to authorize cleanup.
                result["probe"] = "PRESENT_LABEL_MATCH"
                result["probe_id"] = probe_id
                result["probe_running"] = probe["running"]
        original = _inspect_id(original_id)
        if (
            original["name"] == ORIGINAL_NAME
            and original["project"] == PROJECT
            and original["revision"] == original_sha
            and original["image_ref"] == original_image
        ):
            result["original"] = (
                "RUNNING_HEALTHY"
                if original["running"] and original["health"] == "healthy"
                else "RUNNING_OTHER"
                if original["running"]
                else "STOPPED"
            )
            result["original_port"] = (
                "LOOPBACK_8443"
                if original["ports"] == {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
                else "OTHER"
            )
        result["docker"] = "OBSERVED"
    except subprocess.TimeoutExpired:
        result["docker"] = "TIMEOUT"
    except (subprocess.CalledProcessError, OSError):
        result["docker"] = "READ_FAILED"
    except (InspectError, TypeError, ValueError, KeyError):
        result["docker"] = "METADATA_INVALID"
    return result


def verify(raw: bytes, attempt: str, original_id: str) -> dict[str, Any]:
    if (
        not RUN_ID.fullmatch(attempt)
        or not CONTAINER_ID.fullmatch(original_id)
        or not 0 < len(raw) <= 2048
    ):
        raise InspectError("RECEIPT_BOUNDS")
    record = json.loads(raw.decode("ascii"))
    if (
        type(record) is not dict
        or set(record) != RECEIPT_KEYS
        or record["version"] != "boca-worker-readonly-inspect-v1"
        or record["attempt"] != attempt
        or record["legacy_id"] != original_id
        or record["socket"] not in {"ABSENT", "PRESENT_OWNED", "PRESENT_UNVERIFIED", "UNVERIFIED"}
        or record["seccomp"] not in {"ABSENT", "PRESENT_OWNED", "PRESENT_UNVERIFIED", "UNVERIFIED"}
        or record["docker"]
        not in {
            "OBSERVED",
            "WRONG_UID",
            "SOCKET_UNVERIFIED",
            "TIMEOUT",
            "READ_FAILED",
            "METADATA_INVALID",
            "UNVERIFIED",
        }
        or record["probe"]
        not in {"ABSENT", "PRESENT_LABEL_MATCH", "PRESENT_UNVERIFIED", "UNVERIFIED"}
        or record["original"] not in {"RUNNING_HEALTHY", "RUNNING_OTHER", "STOPPED", "UNVERIFIED"}
        or record["original_port"] not in {"LOOPBACK_8443", "OTHER", "UNVERIFIED"}
        or (
            record["probe_id"] is not None
            and (
                type(record["probe_id"]) is not str
                or not CONTAINER_ID.fullmatch(record["probe_id"])
            )
        )
        or (record["probe_running"] is not None and type(record["probe_running"]) is not bool)
        or (record["probe"] == "PRESENT_LABEL_MATCH") != (record["probe_id"] is not None)
        or (record["probe_running"] is None) != (record["probe_id"] is None)
        or (record["original_port"] == "UNVERIFIED") != (record["original"] == "UNVERIFIED")
        or (
            record["docker"] in {"WRONG_UID", "SOCKET_UNVERIFIED"}
            and (record["probe"] != "UNVERIFIED" or record["original"] != "UNVERIFIED")
        )
        or type(record["observer_writes"]) is not int
        or record["observer_writes"] != 0
        or record["foreign_resources_touched"] is not False
        or record["cutover_authorized"] is not False
        or canonical(record) + b"\n" != raw
    ):
        raise InspectError("RECEIPT_CONTRACT")
    return record


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 5 or args[0] not in {"host", "verify"}:
        print("BOCA_WORKER_INSPECT state=NO_GO reason=INPUT", file=sys.stderr)
        return 3
    mode, attempt, original_id, source, image = args
    try:
        _validate(attempt, original_id, source, image)
        if mode == "host":
            sys.stdout.buffer.write(canonical(observe(attempt, original_id, source, image)) + b"\n")
        else:
            record = verify(sys.stdin.buffer.read(2049), attempt, original_id)
            print(
                f"BOCA_WORKER_INSPECT state=READ_ONLY_NO_GO attempt={attempt}"
                f" socket={record['socket']} docker={record['docker']}"
                f" probe={record['probe']} original={record['original']}"
                f" seccomp={record['seccomp']} observer_writes=0 retry=NO_GO"
            )
        return 0
    except (OSError, InspectError, ValueError, TypeError, UnicodeError):
        print("BOCA_WORKER_INSPECT state=NO_GO reason=UNVERIFIED", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
