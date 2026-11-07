"""Boca-only READ_ONLY diagnosis of one failed temporary worker preflight.

Streamed over the existing protected Boca Actions SSH channel. The observer
only uses lstat and rootless Docker ps/inspect scoped to exact Boca identities;
it never creates, starts, stops, executes or removes a host resource.
"""

from __future__ import annotations

import json
import os
import re
import selectors
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import MappingProxyType
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
# The sole failed #795 probe used these exact immutable release coordinates.
FAILED_WORKER_SOURCE = "92624ed6b7e75c6010f59670c866df00a29766dd"
FAILED_WORKER_IMAGE = (
    "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
    "3894cfff995858d7c0ffdb994180a0d28a8a92bb69a0526fb040db2297fd8bf9"
)
# The single later failed #807 probe was built from the independently
# authenticated, paired controller/browser release #723. These pins never
# derive from caller-controlled workflow inputs or a mutable image tag.
FAILED_WORKER_807_SOURCE = "1199c46fee8053e637b220ad9365ce3af15eb8e5"
FAILED_WORKER_807_IMAGE = (
    "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
    "c31b41f0fd6332d9d4946d4047c7eb1e58e53ba04ad2ffdedfbb7aa54bcaaa04"
)
# The single R85 preflight #819 reported CLEANUP/STOP INDETERMINATE. The
# paired browser digest belongs to independently authenticated release #732.
# This identity authorizes metadata observation only, NEVER physical cleanup.
FAILED_WORKER_819_SOURCE = "0538b3fb29cc0245a8387b7023c394883d0ea9a8"
FAILED_WORKER_819_IMAGE = (
    "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
    "d740c610d032aa20fecff1602cc96e49fd63c597c49855990a9bc081a6998619"
)
# One R89 preflight #827 reached cleanup but STOP returned an unexpected ACK.
# Only immutable metadata observation is authorized; no retry or removal.
FAILED_WORKER_827_SOURCE = "8a69d155354362e0712dab1229f7d7e4b3e24dd6"
FAILED_WORKER_827_IMAGE = (
    "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
    "902276a94bbec0ed0be30432baf97b5bd1298fc15e21eda750ccb785fa76bde0"
)
# The only R92 preflight #834 failed with STOP/ACK_MULTILINE; physical state
# remains unverified. Permit metadata reads only, NEVER cleanup or retries.
FAILED_WORKER_834_SOURCE = "79da7ebe9918d98216ac7eb46ff008d7f6e62429"
FAILED_WORKER_834_IMAGE = (
    "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
    "ed276066b108fad5b130d0fdffdd3f38a5a3d912253b1d4267bd4b6184992ba8"
)
KNOWN_FAILED_PROBES = MappingProxyType(
    {
        "42329475083": (FAILED_WORKER_SOURCE, FAILED_WORKER_IMAGE),
        "42341290485": (FAILED_WORKER_807_SOURCE, FAILED_WORKER_807_IMAGE),
        "42353468231": (FAILED_WORKER_819_SOURCE, FAILED_WORKER_819_IMAGE),
        "42368541950": (FAILED_WORKER_827_SOURCE, FAILED_WORKER_827_IMAGE),
        "42375050546": (FAILED_WORKER_834_SOURCE, FAILED_WORKER_834_IMAGE),
    }
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
INSPECT_NO_HEALTH = INSPECT.replace(
    '"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}}',
    '"health":null',
)
# Same full JSON serialization as the failed cleanup's inspect, but print only
# its length: never release Env, Mounts, labels beyond the fixed compact fields.
INSPECT_FULL_JSON_LENGTH = "{{len (json .)}}"
DOCKER_OUTPUT_LIMIT = 2048
DOCKER_TIMEOUT_SECONDS = 12
RECEIPT_KEYS = {
    "version",
    "attempt",
    "legacy_id",
    "socket",
    "docker",
    "probe",
    "probe_id",
    "probe_candidate_id",
    "probe_running",
    "probe_list_stage",
    "probe_list_rc",
    "probe_inspect_stage",
    "probe_inspect_rc",
    "probe_full_json_stage",
    "probe_full_json_rc",
    "seccomp",
    "original",
    "original_port",
    "original_inspect_stage",
    "original_inspect_rc",
    "observer_writes",
    "foreign_resources_touched",
    "cutover_authorized",
}

# R112: historical V3 Cutover #42422235097 ONLY. Docker keeps at most 256
# daemon events; absence is UNKNOWN, never proof of a clean worker shutdown.
# All query coordinates are fixed in reviewed source, not a workflow input.
R112_RUN = "42422235097"
R112_SHA = "c8bea3eb13695722ae294f454c7811395c159c26"
R112_SINCE = "2026-11-07T22:47:15Z"
R112_UNTIL = "2026-11-07T22:48:30Z"
R112_START_EPOCH = 1794091635
R112_END_EPOCH = 1794091710
R112_EVENT_OUTPUT_LIMIT = 8192
R112_EVENT_FLAGS = (
    f"--since={R112_SINCE}",
    f"--until={R112_UNTIL}",
    "--filter=type=container",
    "--filter=event=die",
    "--filter=event=oom",
    f"--filter=label=boca.socios.browser-ipc-attempt={R112_RUN}",
    "--format={{json .}}",
)
R112_RECEIPT_KEYS = {
    "version",
    "attempt",
    "state",
    "exit_code",
    "oom",
    "observer_writes",
    "foreign_resources_touched",
    "retry_authorized",
}


class InspectError(ValueError):
    """Invalid trusted-input contract, not evidence about host state."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _validate(attempt: str, original_id: str, original_sha: str, original_image: str) -> None:
    if (
        not RUN_ID.fullmatch(attempt)
        or attempt not in KNOWN_FAILED_PROBES
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
    """Allow exact metadata queries; bound both streams while the child runs."""
    if not (
        args[:3] == ("ps", "-a", "-q")
        and len(args) == 6
        and args[3:5] == ("--no-trunc", "--filter")
        and re.fullmatch(r"name=\^/boca-socios-cutover-preflight-[1-9][0-9]{0,19}\$", args[5])
        is not None
        or args[:2] == ("inspect", "--format")
        and len(args) == 4
        and args[2] in {INSPECT, INSPECT_NO_HEALTH, INSPECT_FULL_JSON_LENGTH}
        and CONTAINER_ID.fullmatch(args[3]) is not None
    ):
        raise InspectError("DOCKER_COMMAND")
    return _run_bounded(("docker", *args))


def _run_bounded(command: tuple[str, ...], *, stdout_limit: int = DOCKER_OUTPUT_LIMIT) -> str:
    """Rootless, no-shell, byte/deadline-bounded subprocess shared by guarded callers.

    The public observer still passes through `_docker`'s READ_ONLY allowlist.
    The recovery module separately pins the *only* allowed Docker write.
    """
    if not command or command[0] != "docker" or not 0 < stdout_limit <= 65535:
        raise InspectError("DOCKER_COMMAND")
    env = {
        "DOCKER_HOST": f"unix://{SOCKET}",
        "XDG_RUNTIME_DIR": str(RUNTIME),
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
    }
    # Rootless Docker is installed at this reviewed host path. A caller's PATH
    # or Docker context/credentials can never select a different executable.
    command = ("/usr/bin/docker", *command[1:])
    started = time.monotonic()
    process = subprocess.Popen(  # noqa: S603 - narrow READ_ONLY Docker metadata
        command,  # noqa: S607 - pinned rootless Docker socket, no shell
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    output = bytearray()
    stderr_size = 0
    try:
        with selectors.DefaultSelector() as selector:
            assert process.stdout is not None and process.stderr is not None
            for stream in (process.stdout, process.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map():
                remaining = DOCKER_TIMEOUT_SECONDS - (time.monotonic() - started)
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, DOCKER_TIMEOUT_SECONDS)
                ready = selector.select(remaining)
                if not ready:
                    raise subprocess.TimeoutExpired(command, DOCKER_TIMEOUT_SECONDS)
                for key, _event in ready:
                    chunk = os.read(key.fd, max(stdout_limit, DOCKER_OUTPUT_LIMIT) + 1)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    elif key.fileobj is process.stdout:
                        if len(output) + len(chunk) > stdout_limit:
                            raise InspectError("DOCKER_BOUNDS")
                        output.extend(chunk)
                    else:
                        stderr_size += len(chunk)
                        if stderr_size > DOCKER_OUTPUT_LIMIT:
                            raise InspectError("DOCKER_BOUNDS")
        remaining = DOCKER_TIMEOUT_SECONDS - (time.monotonic() - started)
        if remaining <= 0:
            raise subprocess.TimeoutExpired(command, DOCKER_TIMEOUT_SECONDS)
        rc = process.wait(timeout=remaining)
        if rc != 0:
            raise subprocess.CalledProcessError(rc, command)
        try:
            return output.decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise InspectError("DOCKER_ENCODING") from exc
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


def _named_id(name: str) -> str | None:
    if not name.startswith(PREFIX) or not RUN_ID.fullmatch(name.removeprefix(PREFIX)):
        raise InspectError("PROBE_NAME")
    rows = _docker("ps", "-a", "-q", "--no-trunc", "--filter", f"name=^/{name}$").splitlines()
    if len(rows) > 1 or any(not CONTAINER_ID.fullmatch(item) for item in rows):
        raise InspectError("PROBE_SET")
    return rows[0] if rows else None


def _unique_inspect_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject ambiguous Docker metadata instead of trusting JSON last-wins."""
    fields: dict[str, Any] = {}
    for key, value in pairs:
        if key in fields:
            raise InspectError("INSPECT_DUPLICATE_FIELD")
        fields[key] = value
    return fields


def _inspect_record(cid: str, template: str) -> dict[str, Any]:
    value = json.loads(
        _docker("inspect", "--format", template, cid), object_pairs_hook=_unique_inspect_fields
    )
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


def _inspect_id(cid: str) -> dict[str, Any]:
    return _inspect_record(cid, INSPECT)


def _inspect_no_health(cid: str) -> dict[str, Any]:
    return _inspect_record(cid, INSPECT_NO_HEALTH)


def _full_json_length(cid: str) -> int:
    value = _docker("inspect", "--format", INSPECT_FULL_JSON_LENGTH, cid)
    if re.fullmatch(r"[1-9][0-9]{0,8}", value) is None:
        raise InspectError("INSPECT_LENGTH")
    return int(value)


def _failure(exc: Exception) -> tuple[str, int | None]:
    """Never retain exception text, Docker stderr or unbounded exit status."""
    if isinstance(exc, subprocess.TimeoutExpired):
        return "TIMEOUT", None
    if isinstance(exc, subprocess.CalledProcessError):
        rc = exc.returncode
        return "COMMAND_FAILED", rc if type(rc) is int and 1 <= rc <= 255 else 255
    if isinstance(exc, OSError):
        return "OS_ERROR", None
    return "METADATA_INVALID", None


def _r112_empty_receipt() -> dict[str, Any]:
    return {
        "version": "boca-worker-events-r112-v1",
        "attempt": R112_RUN,
        "state": "UNKNOWN",
        "exit_code": None,
        "oom": "UNKNOWN",
        "observer_writes": 0,
        "foreign_resources_touched": False,
        "retry_authorized": False,
    }


def _r112_failed_receipt() -> dict[str, Any]:
    result = _r112_empty_receipt()
    result["state"] = "INDETERMINATE"
    return result


def summarize_worker_events(raw: str) -> dict[str, Any]:
    """Discard all raw Docker fields except positively scoped exit and OOM."""
    if type(raw) is not str or len(raw.encode("utf-8")) > R112_EVENT_OUTPUT_LIMIT:
        raise InspectError("EVENT_BOUNDS")
    dies: list[int] = []
    ooms = 0
    container_ids: set[str] = set()
    lines = raw.splitlines()
    if len(lines) > 16:
        raise InspectError("EVENT_BOUNDS")
    for line in lines:
        if not line or len(line) > 4096:
            raise InspectError("EVENT_FORMAT")
        try:
            event = json.loads(line, object_pairs_hook=_unique_inspect_fields)
        except (ValueError, TypeError) as exc:
            raise InspectError("EVENT_FORMAT") from exc
        if not isinstance(event, dict) or event.get("Type") != "container":
            raise InspectError("EVENT_TYPE")
        action = event.get("Action")
        if action not in {"die", "oom"}:
            raise InspectError("EVENT_ACTION")
        actor = event.get("Actor")
        attrs = actor.get("Attributes") if isinstance(actor, dict) else None
        timestamp = event.get("time")
        if (
            not isinstance(actor, dict)
            or not CONTAINER_ID.fullmatch(str(actor.get("ID", "")))
            or not isinstance(attrs, dict)
            or attrs.get("name")
            not in {"boca-socios-browser-worker-1", "/boca-socios-browser-worker-1"}
            or attrs.get("com.docker.compose.project") != PROJECT
            or attrs.get("com.docker.compose.service") != "browser-worker"
            or attrs.get("boca.socios.browser-ipc-attempt") != R112_RUN
            or type(timestamp) is not int
            or not R112_START_EPOCH <= timestamp <= R112_END_EPOCH
        ):
            raise InspectError("EVENT_IDENTITY")
        container_ids.add(actor["ID"])
        if action == "die":
            code = attrs.get("exitCode")
            if (
                not isinstance(code, str)
                or re.fullmatch(r"(?:0|[1-9][0-9]{0,2})", code) is None
                or int(code) > 255
            ):
                raise InspectError("EVENT_EXIT_CODE")
            dies.append(int(code))
        else:
            ooms += 1
    receipt = _r112_empty_receipt()
    if len(container_ids) > 1 or len(dies) > 1 or ooms > 1:
        receipt["state"] = "AMBIGUOUS"
    elif dies or ooms:
        receipt["state"] = "OBSERVED"
        receipt["exit_code"] = dies[0] if dies else None
        receipt["oom"] = "YES" if ooms else "UNKNOWN"
    return receipt


def observe_worker_events() -> dict[str, Any]:
    """Read only the fixed historical attempt on UID10001 rootless Docker."""
    if os.getuid() != UID or _runtime_stat("docker.sock") != "PRESENT_OWNED":
        return _r112_failed_receipt()
    try:
        raw = _run_bounded(
            ("docker", "events", *R112_EVENT_FLAGS), stdout_limit=R112_EVENT_OUTPUT_LIMIT
        )
        return summarize_worker_events(raw)
    except (
        OSError,
        ValueError,
        TimeoutError,
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError,
    ):
        return _r112_failed_receipt()


def verify_worker_events(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes or len(raw) > 512 or not raw.endswith(b"\n"):
        raise InspectError("EVENT_RECEIPT_BOUNDS")
    try:
        record = json.loads(raw.decode("ascii"), object_pairs_hook=_unique_inspect_fields)
    except (ValueError, UnicodeError, TypeError) as exc:
        raise InspectError("EVENT_RECEIPT_FORMAT") from exc
    if (
        type(record) is not dict
        or set(record) != R112_RECEIPT_KEYS
        or record["version"] != "boca-worker-events-r112-v1"
        or record["attempt"] != R112_RUN
        or record["state"] not in {"UNKNOWN", "OBSERVED", "AMBIGUOUS", "INDETERMINATE"}
        or record["oom"] not in {"UNKNOWN", "YES"}
        or (
            record["exit_code"] is not None
            and (type(record["exit_code"]) is not int or not 0 <= record["exit_code"] <= 255)
        )
        or (
            record["state"] != "OBSERVED"
            and (record["exit_code"] is not None or record["oom"] != "UNKNOWN")
        )
        or (
            record["state"] == "OBSERVED" and record["exit_code"] is None and record["oom"] != "YES"
        )
        or type(record["observer_writes"]) is not int
        or record["observer_writes"] != 0
        or record["foreign_resources_touched"] is not False
        or record["retry_authorized"] is not False
        or canonical(record) + b"\n" != raw
    ):
        raise InspectError("EVENT_RECEIPT_CONTRACT")
    return record


def authenticate_r112_incident(raw: bytes) -> None:
    """Authorize only documented failed main Cutover; no caller run selector."""
    try:
        run = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError, TypeError) as exc:
        raise InspectError("INCIDENT_FORMAT") from exc
    if not isinstance(run, dict) or any(
        run.get(key) != expected
        for key, expected in {
            "id": int(R112_RUN),
            "head_sha": R112_SHA,
            "head_branch": "main",
            "event": "workflow_dispatch",
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "failure",
            "display_title": "BOCA-SIMULATION-DEPLOY-V3",
            "path": ".github/workflows/boca-first-deploy.yml",
            "run_started_at": "2026-11-07T22:47:19Z",
            "updated_at": "2026-11-07T22:48:25Z",
        }.items()
    ):
        raise InspectError("INCIDENT_IDENTITY")


def observe(
    attempt: str, original_id: str, original_sha: str, original_image: str
) -> dict[str, Any]:
    _validate(attempt, original_id, original_sha, original_image)
    result: dict[str, Any] = {
        "version": "boca-worker-readonly-inspect-v3",
        "attempt": attempt,
        "legacy_id": original_id,
        "socket": _runtime_stat("docker.sock"),
        "seccomp": _runtime_stat(f"{PREFIX}{attempt}-seccomp.json"),
        "docker": "UNVERIFIED",
        "probe": "UNVERIFIED",
        "probe_id": None,
        "probe_candidate_id": None,
        "probe_running": None,
        "probe_list_stage": "SKIPPED",
        "probe_list_rc": None,
        "probe_inspect_stage": "SKIPPED",
        "probe_inspect_rc": None,
        "probe_full_json_stage": "SKIPPED",
        "probe_full_json_rc": None,
        "original": "UNVERIFIED",
        "original_port": "UNVERIFIED",
        "original_inspect_stage": "SKIPPED",
        "original_inspect_rc": None,
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
    probe_id: str | None = None
    try:
        probe_id = _named_id(name)
        result["probe_list_stage"] = "ABSENT" if probe_id is None else "OK"
        result["probe"] = "ABSENT" if probe_id is None else "PRESENT_UNVERIFIED"
        result["probe_candidate_id"] = probe_id
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, InspectError) as exc:
        result["probe_list_stage"], result["probe_list_rc"] = _failure(exc)

    if probe_id is not None:
        try:
            probe = _inspect_no_health(probe_id)
            expected_source, expected_image = KNOWN_FAILED_PROBES[attempt]
            if (
                probe["name"] == f"/{name}"
                and probe["project"] == PROJECT
                and probe["attempt"] == attempt
                and probe["image_ref"] == expected_image
                and probe["revision"] == expected_source
            ):
                # Matching immutable metadata is NOT sufficient authority to
                # clean up or launch Cutover: runtime ownership remains gated.
                result["probe"] = "PRESENT_PIN_MATCH"
                result["probe_id"] = probe_id
                result["probe_running"] = probe["running"]
                result["probe_inspect_stage"] = "OK"
            else:
                result["probe_inspect_stage"] = "IDENTITY_MISMATCH"
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            OSError,
            InspectError,
            ValueError,
            TypeError,
            KeyError,
        ) as exc:
            result["probe_inspect_stage"], result["probe_inspect_rc"] = _failure(exc)

        # Independent differential read, even if compact inspection fails.
        # Max: one exact-name ps + two probe inspect + one legacy inspect.
        try:
            size = _full_json_length(probe_id)
            result["probe_full_json_stage"] = (
                "BELOW_CLEANUP_LIMIT" if size < 65536 else "AT_OR_ABOVE_CLEANUP_LIMIT"
            )
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            OSError,
            InspectError,
        ) as exc:
            result["probe_full_json_stage"], result["probe_full_json_rc"] = _failure(exc)

    # Independent of probe lookup/inspection: never hide the legacy singleton
    # when a temporary worker was listed but could not be attested.
    try:
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
            result["original_inspect_stage"] = "OK"
        else:
            result["original_inspect_stage"] = "IDENTITY_MISMATCH"
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        OSError,
        InspectError,
        ValueError,
        TypeError,
        KeyError,
    ) as exc:
        result["original_inspect_stage"], result["original_inspect_rc"] = _failure(exc)
    result["docker"] = (
        "OBSERVED"
        if result["probe_list_stage"] in {"OK", "ABSENT"}
        and result["probe_inspect_stage"] in {"SKIPPED", "OK", "IDENTITY_MISMATCH"}
        and result["probe_full_json_stage"]
        in {"SKIPPED", "BELOW_CLEANUP_LIMIT", "AT_OR_ABOVE_CLEANUP_LIMIT"}
        and result["original_inspect_stage"] in {"OK", "IDENTITY_MISMATCH"}
        else "PARTIAL"
    )
    return result


def verify(raw: bytes, attempt: str, original_id: str) -> dict[str, Any]:
    if (
        not RUN_ID.fullmatch(attempt)
        or attempt not in KNOWN_FAILED_PROBES
        or not CONTAINER_ID.fullmatch(original_id)
        or not 0 < len(raw) <= 2048
    ):
        raise InspectError("RECEIPT_BOUNDS")
    record = json.loads(raw.decode("ascii"))
    list_states = {
        "SKIPPED",
        "OK",
        "ABSENT",
        "TIMEOUT",
        "COMMAND_FAILED",
        "OS_ERROR",
        "METADATA_INVALID",
    }
    inspect_states = {
        "SKIPPED",
        "OK",
        "IDENTITY_MISMATCH",
        "TIMEOUT",
        "COMMAND_FAILED",
        "OS_ERROR",
        "METADATA_INVALID",
    }
    size_states = {
        "SKIPPED",
        "BELOW_CLEANUP_LIMIT",
        "AT_OR_ABOVE_CLEANUP_LIMIT",
        "TIMEOUT",
        "COMMAND_FAILED",
        "OS_ERROR",
        "METADATA_INVALID",
    }
    if (
        type(record) is not dict
        or set(record) != RECEIPT_KEYS
        or record["version"] != "boca-worker-readonly-inspect-v3"
        or record["attempt"] != attempt
        or record["legacy_id"] != original_id
        or record["socket"] not in {"ABSENT", "PRESENT_OWNED", "PRESENT_UNVERIFIED", "UNVERIFIED"}
        or record["seccomp"] not in {"ABSENT", "PRESENT_OWNED", "PRESENT_UNVERIFIED", "UNVERIFIED"}
        or record["docker"] not in {"OBSERVED", "PARTIAL", "WRONG_UID", "SOCKET_UNVERIFIED"}
        or record["probe"]
        not in {"ABSENT", "PRESENT_PIN_MATCH", "PRESENT_UNVERIFIED", "UNVERIFIED"}
        or record["original"] not in {"RUNNING_HEALTHY", "RUNNING_OTHER", "STOPPED", "UNVERIFIED"}
        or record["original_port"] not in {"LOOPBACK_8443", "OTHER", "UNVERIFIED"}
        or record["probe_list_stage"] not in list_states
        or record["probe_inspect_stage"] not in inspect_states
        or record["original_inspect_stage"] not in inspect_states
        or record["probe_full_json_stage"] not in size_states
        or any(
            (type(record[key]) is not int or not 1 <= record[key] <= 255)
            if record[stage] == "COMMAND_FAILED"
            else record[key] is not None
            for key, stage in (
                ("probe_list_rc", "probe_list_stage"),
                ("probe_inspect_rc", "probe_inspect_stage"),
                ("probe_full_json_rc", "probe_full_json_stage"),
                ("original_inspect_rc", "original_inspect_stage"),
            )
        )
        or (
            record["probe_id"] is not None
            and (
                type(record["probe_id"]) is not str
                or not CONTAINER_ID.fullmatch(record["probe_id"])
            )
        )
        or (
            record["probe_candidate_id"] is not None
            and (
                type(record["probe_candidate_id"]) is not str
                or not CONTAINER_ID.fullmatch(record["probe_candidate_id"])
            )
        )
        or (record["probe_list_stage"] == "OK") != (record["probe_candidate_id"] is not None)
        or (record["probe_inspect_stage"] == "SKIPPED") != (record["probe_candidate_id"] is None)
        or (record["probe_full_json_stage"] == "SKIPPED") != (record["probe_candidate_id"] is None)
        or (record["probe_list_stage"] == "ABSENT") != (record["probe"] == "ABSENT")
        or (record["probe_list_stage"] not in {"ABSENT", "OK"} and record["probe"] != "UNVERIFIED")
        or (record["probe_candidate_id"] is not None and record["probe"] == "UNVERIFIED")
        or (record["probe_inspect_stage"] == "OK") != (record["probe"] == "PRESENT_PIN_MATCH")
        or (record["probe_id"] is not None and record["probe_id"] != record["probe_candidate_id"])
        or (record["original_inspect_stage"] == "OK") != (record["original"] != "UNVERIFIED")
        or (record["probe_running"] is not None and type(record["probe_running"]) is not bool)
        or (record["probe"] == "PRESENT_PIN_MATCH") != (record["probe_id"] is not None)
        or (record["probe_running"] is None) != (record["probe_id"] is None)
        or (record["original_port"] == "UNVERIFIED") != (record["original"] == "UNVERIFIED")
        or (
            record["docker"] in {"WRONG_UID", "SOCKET_UNVERIFIED"}
            and (
                record["probe"] != "UNVERIFIED"
                or record["original"] != "UNVERIFIED"
                or record["probe_list_stage"] != "SKIPPED"
                or record["original_inspect_stage"] != "SKIPPED"
            )
        )
        or (
            record["docker"] in {"OBSERVED", "PARTIAL"}
            and (
                record["probe_list_stage"] == "SKIPPED"
                or record["original_inspect_stage"] == "SKIPPED"
                or record["socket"] != "PRESENT_OWNED"
            )
        )
        or (record["docker"] == "SOCKET_UNVERIFIED" and record["socket"] == "PRESENT_OWNED")
        or (
            (record["docker"] == "OBSERVED")
            != (
                record["probe_list_stage"] in {"OK", "ABSENT"}
                and record["probe_inspect_stage"] in {"SKIPPED", "OK", "IDENTITY_MISMATCH"}
                and record["probe_full_json_stage"]
                in {"SKIPPED", "BELOW_CLEANUP_LIMIT", "AT_OR_ABOVE_CLEANUP_LIMIT"}
                and record["original_inspect_stage"] in {"OK", "IDENTITY_MISMATCH"}
            )
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
    if args in (["events-auth"], ["events-host"], ["events-verify"]):
        try:
            if args == ["events-auth"]:
                authenticate_r112_incident(sys.stdin.buffer.read(16385))
                print("BOCA_WORKER_EVENTS_R112 incident=AUTHENTICATED mode=READ_ONLY")
            elif args == ["events-host"]:
                sys.stdout.buffer.write(canonical(observe_worker_events()) + b"\n")
            else:
                record = verify_worker_events(sys.stdin.buffer.read(513))
                print(
                    f"BOCA_WORKER_EVENTS_R112 state={record['state']}"
                    f" attempt={R112_RUN} exit_code={record['exit_code']}"
                    f" oom={record['oom']} observer_writes=0"
                    " foreign_resources_touched=0 retry=NO_GO cutover=NO_GO"
                )
                if record["state"] == "INDETERMINATE":
                    return 3
            return 0
        except (OSError, InspectError, ValueError, TypeError, UnicodeError):
            print("BOCA_WORKER_EVENTS_R112 state=INDETERMINATE reason=UNVERIFIED", file=sys.stderr)
            return 3
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
                f" probe_list={record['probe_list_stage']} probe_inspect={record['probe_inspect_stage']}"
                f" probe_json_size={record['probe_full_json_stage']}"
                f" original_inspect={record['original_inspect_stage']}"
                f" seccomp={record['seccomp']} observer_writes=0 retry=NO_GO"
            )
        return 0
    except (OSError, InspectError, ValueError, TypeError, UnicodeError):
        print("BOCA_WORKER_INSPECT state=NO_GO reason=UNVERIFIED", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
