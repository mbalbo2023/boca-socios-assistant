"""Boca-only READ_ONLY physical reconciliation after an ambiguous Cutover A.

This standalone stdlib script is streamed by the existing manual Actions
workflow. It never creates a Docker resource, opens a provider URL, acquires
an effectful lease or modifies host files. Only fixed Boca receipt paths and
project-filtered rootless Docker metadata are read.
"""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import re
import stat
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any

UID = 10001
PROJECT = "boca-socios"
ROOTLESS_SOCKET = Path("/run/user/10001/docker.sock")
RECEIPT_DIR = ".boca-socios-cutover-receipts"
DATA_VOLUME = "boca-socios_boca_data"
RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
IDENT = re.compile(r"[0-9a-f]{64}\Z")
SOURCE = re.compile(r"[0-9a-f]{40}\Z")
MAX_JSON = 4096
R904 = "42742150879"
R904_SHA = "b6a53c3348ce39c4d8536487e2baed559c2ca42f"
R904_LIMIT = 16384
LEGACY904 = "27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793"
_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant"
_BASE = "b9e9465d6ec8e484b615d7bd65aab5a3c150d34a9893ad181167d2099893d811"
_OVERLAY = "3175803115f55dd99007739716fbaa1c7d677772f9ff658039f794023e708861"
_SECCOMP = "cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849"
_PINS904 = {
    "legacy_id": LEGACY904,
    "legacy_source_sha": "cabce9f1e452e63ded115f447559a358dc0f4d1b",
    "target_source_sha": R904_SHA,
    "legacy_compose_sha": _BASE,
    "target_compose_sha": _BASE,
    "overlay_sha": _OVERLAY,
    "seccomp_sha": _SECCOMP,
    "legacy_image_ref": _IMAGE
    + "@sha256:cf6e4266cfcfea0c07fa31301d59c7aaa3b9c2fefb9f6843baddd208cacd3b59",
    "target_image_ref": _IMAGE
    + "@sha256:40ceea681a8568e93bb2d22decb294e712e70de32b68156d998a0bf612b7569b",
    "browser_image_ref": _IMAGE
    + "-browser@sha256:8fb79002e937de1ca014db502af053a37046fa4361c44a7719f24e813faf185c",
}
_STAGE904 = "cutover-a-" + R904
_ACT = ".boca-on-demand"
_UNIT = "boca-bot-control.socket"
_SERVICE = "boca-bot-control@.service"
_USER = ".config/systemd/user"
_FILES904 = {
    "root": "",
    "compose": "compose.beta.yaml",
    "overlay": "compose.beta.browser.yaml",
    "seccomp": "seccomp_profile.json",
    "stage": _STAGE904,
    "stage_base": _STAGE904 + "/compose.beta.yaml",
    "stage_overlay": _STAGE904 + "/compose.beta.browser.yaml",
    "stage_seccomp": _STAGE904 + "/seccomp_profile.json",
    "stage_marker": _STAGE904 + "/cutover-a-marker.json",
    "promote_intent": _STAGE904 + "/cutover-a-commit-intent.json",
    "promote_result": _STAGE904 + "/cutover-a-commit-result.json",
}
_ACT904 = {
    "actuator": _ACT,
    "attempt": _ACT + "/attempt",
    "binding": _ACT + "/binding.json",
    "handler": _ACT + "/handler.pyz",
    "removing": _ACT + "/removing",
    "socket_dir": _ACT + "/socket",
    "endpoint": _ACT + "/socket/control.sock",
    "socket_unit": _ACT + "/" + _UNIT,
    "service_unit": _ACT + "/" + _SERVICE,
    "config_dir": ".config",
    "systemd_dir": ".config/systemd",
    "user_units": _USER,
    "wants_dir": _USER + "/default.target.wants",
    "installed_socket": _USER + "/" + _UNIT,
    "installed_service": _USER + "/" + _SERVICE,
    "enabled_socket": _USER + "/default.target.wants/" + _UNIT,
}
_DIGEST904 = {
    "compose": _BASE,
    "stage_base": _BASE,
    "overlay": _OVERLAY,
    "stage_overlay": _OVERLAY,
    "seccomp": _SECCOMP,
    "stage_seccomp": _SECCOMP,
}
_EXTRAS904 = {"root", "stage", "actuator", "socket_dir"}
# The positive compensation observed in #883 may unlock *only* a second
# read-only inventory, never another Cutover, cleanup or retry decision.
RECOVERED_INVENTORY_RUN = "42426260583"
RECOVERED_INVENTORY_SHA = "f57173862df3143062a136452f2ffc7e3cc51d35"
TERMINAL_V3 = "boca-cutover-a-terminal-v3"
TERMINAL_V4 = "boca-cutover-a-terminal-v4"
WORKER_SIGNATURE = re.compile(
    r"(?:EMPTY|PRESENT_UNCLASSIFIED|UNKNOWN)\."
    r"(?:EXITED|DEAD|OTHER|UNKNOWN)\."
    r"(?:EARLY_LT_5S|LATE_GE_5S|UNKNOWN)\."
    r"(?:NOT_RUN|RAN|UNKNOWN)\Z"
)
WORKER_EVIDENCE_FIELDS = frozenset(
    {
        "version",
        "worker_primary_phase",
        "worker_compensation",
        "worker_exit_code",
        "worker_oom_killed",
    }
)
WORKER_EVIDENCE_FIELDS_V4 = WORKER_EVIDENCE_FIELDS | {"worker_exit_signature"}
# Do not allow arbitrary runner-supplied fields into Actions job summaries.
# Historical v1/v2 envelopes remain verifiable byte-for-byte under their
# original schema; the added redacted evidence belongs only to receipt v3.
RECEIPT_FIELDS = frozenset(
    {
        "version",
        "incident_run_id",
        "prepare_run_id",
        "intent",
        "result",
        "terminal_state",
        "cleanup",
        "worker_id_recorded",
        "candidate_id_recorded",
        "commit_started",
        "original_restored",
        "legacy_id",
        "original",
        "candidate_controllers",
        "browser_workers",
        "boca_inventory",
        "boca_containers",
        "port_8443",
        "prepared_go_marker",
        "prepared_go_marker_reason",
        "stage_preflight",
        "stage",
        "promotion_intent",
        "promotion_result",
        "runtime_attested",
        "go_for_retry",
        "foreign_resources_touched",
    }
)
FIELDS = (
    "id",
    "name",
    "running",
    "health",
    "image_id",
    "revision",
    "service",
    "attempt",
    "port_binding",
)
INSPECT_FORMAT = (
    '{"id":{{json .Id}},"name":{{json .Name}},'
    '"running":{{json .State.Running}},'
    '"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}},'
    '"image_id":{{json .Image}},'
    '"revision":{{json (index .Config.Labels "org.opencontainers.image.revision")}},'
    '"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
    '"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
    '"attempt":{{json (index .Config.Labels "boca.socios.browser-ipc-attempt")}},'
    '"port_binding":{{json .HostConfig.PortBindings}}}'
)


class ReconcileError(ValueError):
    """Ambiguous/invalid read-only observation; preserve all host state."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _private_home() -> Path:
    account = pwd.getpwuid(UID)
    home = Path(account.pw_dir)
    if (
        account.pw_name != "boca-deploy"
        or not home.is_absolute()
        or ".." in home.parts
        or len(home.parts) < 3
        or home == Path("/srv/boca-socios")
        or Path("/srv/boca-socios") in home.parents
        or home.parts[1] in {"run", "tmp", "var", "dev", "proc", "sys"}
        or home.resolve(strict=True) != home
    ):
        raise ReconcileError("ROOTLESS_HOME")
    return home


def _read_private(
    name: str, *, directory: Path, owner: int = UID, private_directory: bool = True
) -> bytes | None:
    """No writes or symlink traversal, even for missing incident files."""
    if "/" in name or name in ("", ".", ".."):
        raise ReconcileError("PATH")
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        descriptor = os.fstat(fd)
        if (
            not stat.S_ISDIR(descriptor.st_mode)
            or descriptor.st_uid != owner
            or stat.S_IMODE(descriptor.st_mode) & (0o077 if private_directory else 0o022)
        ):
            raise ReconcileError("DIRECTORY")
        try:
            child = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fd
            )
        except FileNotFoundError:
            return None
        try:
            entry = os.fstat(child)
            if (
                not stat.S_ISREG(entry.st_mode)
                or entry.st_uid != owner
                or entry.st_nlink != 1
                or stat.S_IMODE(entry.st_mode) != 0o600
                or not 0 < entry.st_size <= 2048
            ):
                raise ReconcileError("MARKER_METADATA")
            data = os.read(child, 2049)
            if len(data) != entry.st_size or len(data) > 2048:
                raise ReconcileError("MARKER_SIZE")
            return data
        finally:
            os.close(child)
    finally:
        os.close(fd)


def _record(raw: bytes | None, run_id: str, *, kind: str) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        # Parse duplicate keys as an error, not a last-value-wins ambiguity.
        def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ReconcileError("DUPLICATE_MARKER_FIELD")
                result[key] = value
            return result

        obj = json.loads(raw.decode("ascii"), object_pairs_hook=unique)
    except (ValueError, UnicodeError) as exc:
        raise ReconcileError("MARKER_PARSE") from exc
    result_v1 = "boca-cutover-a-terminal-v1"
    result_v2 = "boca-cutover-a-terminal-v2"
    result_v3 = "boca-cutover-a-terminal-v3"
    result_v4 = "boca-cutover-a-terminal-v4"
    version = obj.get("version") if isinstance(obj, dict) else None
    valid_version = (
        version == "boca-cutover-a-intent-v1"
        if kind == "intent"
        else version in (result_v1, result_v2, result_v3, result_v4)
    )
    if (
        not isinstance(obj, dict)
        or not valid_version
        or obj.get("attempt_id") != run_id
        or _canonical(obj) != raw
    ):
        raise ReconcileError("MARKER_IDENTITY")
    if kind == "intent":
        if (
            set(obj)
            != {
                "version",
                "attempt_id",
                "legacy_id",
                "legacy_source_sha",
                "legacy_image_ref",
                "legacy_compose_sha",
                "target_source_sha",
                "target_image_ref",
                "browser_image_ref",
                "target_compose_sha",
                "overlay_sha",
                "seccomp_sha",
                "owner_subject_sha256",
                "origin",
            }
            or not isinstance(obj["legacy_id"], str)
            or not IDENT.fullmatch(obj["legacy_id"])
            or not isinstance(obj["target_source_sha"], str)
            or not SOURCE.fullmatch(obj["target_source_sha"])
        ):
            raise ReconcileError("INTENT_SCHEMA")
    else:
        base_fields = {
            "version",
            "attempt_id",
            "legacy_source_sha",
            "target_source_sha",
            "legacy_id",
            "intent_sha256",
            "state",
            "cleanup",
            "original_restored",
            "irreversible_commit_started",
            "candidate_id",
            "worker_id",
        }
        typed = version in (result_v2, result_v3, result_v4)
        exited = version in (result_v3, result_v4)
        typed_fields = {"worker_primary_phase", "worker_compensation"}
        exited_fields = {"worker_exit_code", "worker_oom_killed"}
        allowed_phases = {
            "ATTEST",
            "STORAGE",
            "PULL",
            "IPC",
            "CREATE",
            "START",
            "HEALTH",
            "HEALTH_WAIT",
            "HEALTH_EXITED",
            "HEALTH_UNHEALTHY",
            "HEALTH_TIMEOUT",
            "HEALTH_POSTFLIGHT",
            "UNVERIFIED",
        }
        allowed_compensation = {"VERIFIED", "INDETERMINATE", "UNVERIFIED"}
        if (
            set(obj)
            != (
                base_fields
                | (typed_fields if typed else set())
                | (exited_fields if exited else set())
                | ({"worker_exit_signature"} if version == result_v4 else set())
            )
            or obj.get("state") not in ("ACCEPTED", "RECOVERED", "NO_GO")
            or obj.get("cleanup") not in ("ACCEPT", "NO_GO", "INDETERMINATE")
            or type(obj.get("original_restored")) is not bool
            or type(obj.get("irreversible_commit_started")) is not bool
            or (
                typed
                and (
                    obj["state"] == "ACCEPTED"
                    or type(obj.get("worker_primary_phase")) is not str
                    or obj["worker_primary_phase"] not in allowed_phases
                    or type(obj.get("worker_compensation")) is not str
                    or obj["worker_compensation"] not in allowed_compensation
                )
            )
            or (
                exited
                and (
                    obj["worker_primary_phase"] != "HEALTH_EXITED"
                    or not (
                        type(obj.get("worker_exit_code")) is int
                        and 0 <= obj["worker_exit_code"] <= 255
                        or obj.get("worker_exit_code") == "UNKNOWN"
                    )
                    or not (
                        type(obj.get("worker_oom_killed")) is bool
                        or obj.get("worker_oom_killed") == "UNKNOWN"
                    )
                )
            )
            or (
                version == result_v4
                and (
                    type(obj.get("worker_exit_signature")) is not str
                    or WORKER_SIGNATURE.fullmatch(obj["worker_exit_signature"]) is None
                )
            )
            or any(
                value is not None and (type(value) is not str or not IDENT.fullmatch(value))
                for value in (obj.get("candidate_id"), obj.get("worker_id"))
            )
        ):
            raise ReconcileError("RESULT_SCHEMA")
    return obj


def _docker(*args: str, timeout: int = 15) -> str:
    """Read-only allowlist, rootless socket pinned; no exec/stop/prune/inspect Env."""
    accepted = (
        args[:3] == ("ps", "-a", "-q")
        or args[:2] == ("inspect", "--format")
        or args[:3] == ("volume", "ls", "-q")
        or args[:3] == ("volume", "inspect", "--format")
    )
    if not accepted:
        raise ReconcileError("DOCKER_COMMAND")
    environment = dict(os.environ)
    for name in tuple(environment):
        if name.startswith("DOCKER_"):
            environment.pop(name)
    environment["DOCKER_HOST"] = f"unix://{ROOTLESS_SOCKET}"
    try:
        out = subprocess.run(  # noqa: S603 - Boca-only read commands
            ("docker", *args),  # noqa: S607 - fixed Docker executable
            check=True,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=environment,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReconcileError("DOCKER_READ") from exc
    if len(out) > 8192:
        raise ReconcileError("DOCKER_BOUNDS")
    return out.strip()


def _docker_snapshot() -> list[dict[str, Any]]:
    ids = _docker(
        "ps",
        "-a",
        "-q",
        "--no-trunc",
        "--filter",
        f"label=com.docker.compose.project={PROJECT}",
    ).splitlines()
    if len(ids) > 8 or len(ids) != len(set(ids)) or any(not IDENT.fullmatch(x) for x in ids):
        raise ReconcileError("BOCA_CONTAINER_SET")
    containers: list[dict[str, Any]] = []
    for item in sorted(ids):
        try:
            record = json.loads(_docker("inspect", "--format", INSPECT_FORMAT, item))
        except (ValueError, TypeError) as exc:
            raise ReconcileError("DOCKER_CONTAINER_PARSE") from exc
        if (
            not isinstance(record, dict)
            or set(record) != set(FIELDS) | {"project"}
            or record.get("id") != item
            or record.get("project") != PROJECT
            or type(record.get("name")) is not str
            or not record["name"].startswith("/boca-socios-")
            or type(record.get("running")) is not bool
            or (record.get("health") is not None and type(record["health"]) is not str)
            or type(record.get("image_id")) is not str
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", record["image_id"])
        ):
            raise ReconcileError("DOCKER_CONTAINER_IDENTITY")
        containers.append({key: record[key] for key in FIELDS})
    return containers


def _ports(containers: list[dict[str, Any]]) -> str:
    bound = [
        item
        for item in containers
        if item["running"]
        and item["service"] == "controller"
        and item["port_binding"] == {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
    ]
    if len(bound) > 1:
        return "AMBIGUOUS"
    return "BOCA_CONTROLLER_DOCKER_BOUND" if len(bound) == 1 else "UNVERIFIED"


def _marker(prepared_id: str) -> tuple[str, str]:
    # Direct rootless volume mountpoint read only. Some rootless UID mappings
    # forbid opening this marker: report UNREADABLE, never create a helper
    # container or change the stored inode to work around permission.
    names = _docker("volume", "ls", "-q", "--filter", f"name=^{DATA_VOLUME}$").splitlines()
    if names != [DATA_VOLUME]:
        return "VOLUME_UNVERIFIED", "VOLUME_NAME_UNVERIFIED"
    try:
        raw = json.loads(
            _docker("volume", "inspect", "--format", "{{json .Mountpoint}}", DATA_VOLUME)
        )
        path = Path(raw)
        if (
            type(raw) is not str
            or not path.is_absolute()
            or path.name != "_data"
            or path.parent.name != DATA_VOLUME
            or path.is_symlink()
        ):
            return "VOLUME_UNVERIFIED", "MOUNTPOINT_IDENTITY_UNVERIFIED"
        blob = _read_private(
            f".boca-cutover-prepared-go-{prepared_id}.json",
            directory=path,
            private_directory=False,
        )
    except ReconcileError as exc:
        return "UNREADABLE", str(exc)
    except OSError as exc:
        return "UNREADABLE", "READ_PERMISSION" if exc.errno in (1, 13) else "READ_OS_ERROR"
    except (TypeError, ValueError):
        return "UNREADABLE", "MOUNTPOINT_PARSE"
    if blob is None:
        return "ABSENT", "MARKER_NOT_FOUND"
    try:
        marker = json.loads(blob.decode("ascii"))
    except (ValueError, UnicodeError):
        return "INVALID", "MARKER_PARSE"
    if (
        not isinstance(marker, dict)
        or marker.get("version") != "boca-cutover-prepared-use-v1"
        or marker.get("operation") != "cutover-a-apply"
        or marker.get("prepare_run_id") != prepared_id
        or _canonical(marker) != blob
    ):
        return "INVALID", "MARKER_SCHEMA"
    return "PRESENT_VERIFIED", "MARKER_SCHEMA_VALID"


def _stage_preflight(intent: dict[str, Any] | None) -> dict[str, Any]:
    """Repeat only strict stage preconditions; no mkdir, uploaded bytes or ZIP import."""
    result: dict[str, Any] = {
        "reason": "UNVERIFIED",
        "root_entries_count": None,
        "root_entries_expected": False,
        "compose_digest_match": False,
        "compose_digest_evaluated": False,
        "compose_inode_checks": None,
        "compose_inode_mode_octal": None,
        "compose_legacy_mode_accepted": None,
        "plan_hashes_unique": False,
    }
    if intent is None:
        result["reason"] = "INTENT_ABSENT"
        return result
    fields = (
        intent.get("legacy_compose_sha"),
        intent.get("target_compose_sha"),
        intent.get("overlay_sha"),
        intent.get("seccomp_sha"),
    )
    valid_digests = all(isinstance(value, str) and IDENT.fullmatch(value) for value in fields)
    # Existing CutoverPlan.validate permits byte-identical legacy/target Compose.
    # The stage's independently reviewed target/overlay/seccomp slots remain distinct;
    # legacy Compose must not alias either non-Compose slot.
    result["plan_hashes_unique"] = bool(
        valid_digests and len(set(fields[1:])) == 3 and fields[0] not in fields[2:]
    )
    result["legacy_target_compose_equal"] = bool(valid_digests and fields[0] == fields[1])
    # Report host root state even if plan policy fails: a second independent blocker
    # must not be hidden behind a digest check in this READ_ONLY investigation.
    try:
        root = os.open(
            "/srv/boca-socios", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
    except OSError:
        result["reason"] = "STAGE_ROOT_UNREADABLE"
        return result
    try:
        metadata = os.fstat(root)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != UID
            or metadata.st_gid != UID
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            result["reason"] = "STAGE_ROOT_OWNER_MODE"
            return result
        try:
            names = os.listdir(root)
        except OSError:
            result["reason"] = "STAGE_ROOT_LIST"
            return result
        result["root_entries_count"] = len(names) if len(names) <= 2048 else None
        result["root_entries_expected"] = set(names) == {"compose.beta.yaml"}
        if not result["root_entries_expected"]:
            result["reason"] = "STAGE_ROOT_ENTRIES"
            return result
        try:
            descriptor = os.open(
                "compose.beta.yaml",
                os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=root,
            )
        except OSError:
            result["reason"] = "STAGE_COMPOSE_UNREADABLE"
            return result
        try:
            before = os.fstat(descriptor)
            # Preserve the exact Stage admission policy. The six observations
            # come from this already-open, O_NOFOLLOW Compose FD, never from a
            # path-based stat (which could race or traverse another inode).
            checks = {
                "regular": stat.S_ISREG(before.st_mode),
                "uid_ok": before.st_uid == UID,
                "gid_ok": before.st_gid == UID,
                "nlink_one": before.st_nlink == 1,
                "mode_0600": stat.S_IMODE(before.st_mode) == 0o600,
                "size_ok": 0 < before.st_size <= 32768,
            }
            result["compose_inode_checks"] = checks
            result["compose_inode_mode_octal"] = f"{stat.S_IMODE(before.st_mode):04o}"
            # Historical beta-install used scp -p and admitted 0644. Stage now
            # accepts that exact observed legacy mode only; the original six
            # factual booleans (including mode_0600=false) remain unchanged.
            legacy_mode_allowed = stat.S_IMODE(before.st_mode) in (0o600, 0o644)
            result["compose_legacy_mode_accepted"] = legacy_mode_allowed
            if not legacy_mode_allowed or not all(
                value for name, value in checks.items() if name != "mode_0600"
            ):
                result["reason"] = "STAGE_COMPOSE_INODE_MODE"
                return result
            data = os.read(descriptor, 32769)
            after = os.fstat(descriptor)
            if len(data) != before.st_size or (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                result["reason"] = "STAGE_COMPOSE_CHANGED"
                return result
            result["compose_digest_evaluated"] = True
            result["compose_digest_match"] = hashlib.sha256(data).hexdigest() == fields[0]
            result["reason"] = (
                "PLAN_ROLE_DIGEST_INVALID"
                if not result["plan_hashes_unique"]
                else "STAGE_PREFLIGHT_MATCH"
                if result["compose_digest_match"]
                else "STAGE_COMPOSE_SHA"
            )
            return result
        except OSError:
            result["reason"] = "STAGE_COMPOSE_IO"
            return result
        finally:
            os.close(descriptor)
    finally:
        os.close(root)


def _staged_attempt(run_id: str) -> dict[str, str]:
    """Only inspect the exact Boca-staging path for this incident."""
    root = Path("/srv/boca-socios")
    name = f"cutover-a-{run_id}"
    try:
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        return {
            "stage": "UNVERIFIED",
            "promotion_intent": "UNVERIFIED",
            "promotion_result": "UNVERIFIED",
        }
    try:
        try:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
        except FileNotFoundError:
            return {"stage": "ABSENT", "promotion_intent": "ABSENT", "promotion_result": "ABSENT"}
        try:
            details = os.fstat(child)
            if not stat.S_ISDIR(details.st_mode) or details.st_uid != UID:
                raise ReconcileError("STAGE_IDENTITY")
            result = {"stage": "PRESENT"}
            for kind, filename in (
                ("promotion_intent", "cutover-a-commit-intent.json"),
                ("promotion_result", "cutover-a-commit-result.json"),
            ):
                try:
                    entry = os.stat(filename, dir_fd=child, follow_symlinks=False)
                except FileNotFoundError:
                    result[kind] = "ABSENT"
                else:
                    result[kind] = (
                        "PRESENT"
                        if stat.S_ISREG(entry.st_mode) and entry.st_uid == UID
                        else "UNVERIFIED"
                    )
            return result
        finally:
            os.close(child)
    finally:
        os.close(descriptor)


def _file904(base: Path, path: str, key: str, allowed: set[str], owner: int) -> tuple[Any, Any]:
    """Only named entries. Never follow a link or open payload, units, credentials or a socket."""
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    pieces = path.split("/") if path else []
    try:
        with ExitStack() as stack:
            parent = os.open(base, flags | os.O_DIRECTORY)
            stack.callback(os.close, parent)
            for part in pieces[:-1]:
                perm = os.fstat(parent)
                if (perm.st_uid, perm.st_gid) != (owner, owner) or perm.st_mode & 0o022:
                    return "UNSAFE", None
                parent = os.open(part, flags | os.O_DIRECTORY, dir_fd=parent)
                stack.callback(os.close, parent)
            parent_stat = os.fstat(parent)
            if pieces and (
                (parent_stat.st_uid, parent_stat.st_gid) != (owner, owner)
                or parent_stat.st_mode & 0o022
            ):
                return "UNSAFE", None
            leaf = pieces[-1] if pieces else "."
            meta = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
            kind = next(
                (
                    name
                    for name, test in (
                        ("file", stat.S_ISREG),
                        ("dir", stat.S_ISDIR),
                        ("link", stat.S_ISLNK),
                        ("socket", stat.S_ISSOCK),
                    )
                    if test(meta.st_mode)
                ),
                "other",
            )
            owned = (meta.st_uid, meta.st_gid) == (owner, owner)
            facts = [
                kind,
                meta.st_dev,
                meta.st_ino,
                stat.S_IMODE(meta.st_mode),
                meta.st_nlink,
                owned,
            ]
            detail: Any = None
            if owned and kind == "link" and key == "enabled_socket":
                detail = os.readlink(leaf, dir_fd=parent) == "../" + _UNIT
            elif owned and kind == "dir" and key in _EXTRAS904 and not meta.st_mode & 0o022:
                child = os.open(leaf, flags | os.O_DIRECTORY, dir_fd=parent)
                stack.callback(os.close, child)
                if not os.path.samestat(meta, os.fstat(child)):
                    return "UNSTABLE", None
                with os.scandir(child) as entries:
                    count = 0
                    for index, entry in enumerate(entries):
                        if index >= 256:
                            return facts, "LIMIT"
                        count += entry.name not in allowed
                    detail = count
            elif (
                owned
                and kind == "file"
                and key in {*_DIGEST904, "stage_marker", "attempt"}
                and meta.st_nlink == 1
                and stat.S_IMODE(meta.st_mode) in (0o600, 0o644)
                and 0 < meta.st_size <= (32768 if key in _DIGEST904 else 2048)
            ):
                child = os.open(leaf, flags, dir_fd=parent)
                stack.callback(os.close, child)
                if not os.path.samestat(meta, os.fstat(child)):
                    return "UNSTABLE", None
                data = os.read(child, meta.st_size + 1)
                after = os.fstat(child)
                if (len(data), after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
                    meta.st_size,
                    meta.st_size,
                    meta.st_mtime_ns,
                    meta.st_ctime_ns,
                ):
                    return "UNSTABLE", None
                if key in _DIGEST904:
                    detail = hashlib.sha256(data).hexdigest() == _DIGEST904[key]
                elif key == "attempt":
                    detail = data == (R904 + "\n").encode()
                else:
                    try:
                        marker = json.loads(data)
                    except (ValueError, UnicodeError):
                        marker = None
                    if (
                        type(marker) is dict
                        and _canonical(marker) == data
                        and all(
                            marker.get(k) == v
                            for k, v in {
                                "version": "cutover-a-stage-v1",
                                "attempt_id": R904,
                                "legacy_controller_id": LEGACY904,
                                "legacy_source_sha": _PINS904["legacy_source_sha"],
                                "target_source_sha": R904_SHA,
                                "legacy_compose_sha": _BASE,
                                "target_compose_sha": _BASE,
                                "overlay_compose_sha": _OVERLAY,
                                "seccomp_sha": _SECCOMP,
                                "target_image": _PINS904["target_image_ref"],
                                "browser_image": _PINS904["browser_image_ref"],
                            }.items()
                        )
                    ):
                        ident = [marker.get("legacy_compose_dev"), marker.get("legacy_compose_ino")]
                        if all(type(n) is int and 0 <= n < 2**64 for n in ident):
                            detail = ident
            return facts, detail
    except FileNotFoundError:
        return "ABSENT", None
    except NotADirectoryError:
        return "UNSAFE", None
    except OSError:
        return "UNREADABLE", None


def _files904(root: Path, home: Path, owner: int = UID) -> dict[str, Any]:
    entries = {}
    details = {}
    for base, slots in ((root, _FILES904), (home, _ACT904)):
        for key, path in slots.items():
            allowed = {
                p.rpartition("/")[2] for p in slots.values() if p and p.rpartition("/")[0] == path
            }
            entry, detail = _file904(base, path, key, allowed, owner)
            entries[key] = entry
            if key in _EXTRAS904 | _DIGEST904.keys() | {
                "attempt",
                "enabled_socket",
                "stage_marker",
            }:
                details[key] = detail
    return {"inodes": entries, "checks": details}


def _safe_inventory904(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """No free Docker labels, container names, health output or addresses in this receipt."""
    port = {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
    allowed = {
        "name": (
            "/boca-socios-controller-1",
            "/boca-socios-controller-legacy-" + R904,
            "/boca-socios-browser-worker-1",
            "/boca-socios-telegram-1",
        ),
        "health": (None, "healthy", "starting", "unhealthy"),
        "revision": (_PINS904["legacy_source_sha"], R904_SHA),
        "service": ("controller", "browser-worker", "telegram"),
        "attempt": (None, "", R904),
        "port_binding": (None, {}, port),
    }
    result = []
    for row in items:
        if (
            type(row) is not dict
            or set(row) != set(FIELDS)
            or type(row["id"]) is not str
            or not IDENT.fullmatch(row["id"])
            or type(row["image_id"]) is not str
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", row["image_id"])
            or type(row["running"]) is not bool
        ):
            raise ReconcileError("R904_INVENTORY")
        result.append(
            {
                **row,
                **{
                    key: row[key] if row[key] in values else "OTHER"
                    for key, values in allowed.items()
                },
            }
        )
    return result


def _processes904(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for row in rows:
        try:
            fields = json.loads(
                _docker(
                    "inspect",
                    "--format",
                    "[{{json .Id}},{{json .State.Status}},{{json .State.Pid}},{{json .Config.Image}},{{json .HostConfig.RestartPolicy.Name}},{{json .RestartCount}}]",
                    row["id"],
                )
            )
            if type(fields) is not list or len(fields) != 6 or fields[0] != row["id"]:
                raise ReconcileError("R904_CONTAINER")
            _, phase, pid, image, restart, restarts = fields
            if (
                phase
                not in ("created", "running", "paused", "exited", "dead", "restarting", "removing")
                or type(pid) is not int
                or not 0 <= pid < 2**31
            ):
                raise ReconcileError("R904_CONTAINER")
            role = next(
                (
                    k
                    for k in ("legacy_image_ref", "target_image_ref", "browser_image_ref")
                    if image == _PINS904[k]
                ),
                "OTHER",
            )
            result[row["id"]] = [
                phase,
                pid,
                role,
                restart if restart in ("no", "unless-stopped") else "OTHER",
                restarts if type(restarts) is int and 0 <= restarts < 2**63 else "UNKNOWN",
            ]
        except (OSError, TypeError, ValueError):
            result[row["id"]] = "INDETERMINATE"
    return result


def _host(run_id: str, prepared_id: str | None, *, source_sha: str | None = None) -> dict[str, Any]:
    if not RUN.fullmatch(run_id):
        raise ReconcileError("RUN_ID")
    if source_sha is None:
        if prepared_id is None or not RUN.fullmatch(prepared_id) or run_id == prepared_id:
            raise ReconcileError("RUN_ID")
    elif prepared_id is not None or not SOURCE.fullmatch(source_sha):
        raise ReconcileError("V3_SOURCE_ID")
    if run_id == R904 and source_sha != R904_SHA:
        raise ReconcileError("R904_PROVENANCE")
    if os.geteuid() != UID or os.getegid() != UID:
        raise ReconcileError("ROOTLESS_UID")
    home = _private_home()
    folder = home / RECEIPT_DIR
    if folder.is_dir() and not folder.is_symlink():
        intent_bytes = _read_private(f"boca-cutover-a-intent-{run_id}.json", directory=folder)
        result_bytes = _read_private(f"boca-cutover-a-result-{run_id}.json", directory=folder)
    elif not folder.exists():
        intent_bytes = result_bytes = None
    else:
        raise ReconcileError("RECEIPT_DIRECTORY")
    intent = _record(intent_bytes, run_id, kind="intent")
    result = _record(result_bytes, run_id, kind="result")
    # Terminal V3/V4 is produced only by the single-dispatch, no-PREPARE
    # protocol. Never reinterpret its exit evidence as legacy PREPARE proof.
    if (
        source_sha is None
        and result is not None
        and result["version"] in (TERMINAL_V3, TERMINAL_V4)
    ):
        raise ReconcileError("TERMINAL_PROTOCOL_MISMATCH")
    if source_sha is not None and intent is not None:
        if intent["target_source_sha"] != source_sha:
            raise ReconcileError("V3_SOURCE_MISMATCH")
    if result is not None and (
        intent is None
        or result["legacy_id"] != intent["legacy_id"]
        or result["intent_sha256"] != hashlib.sha256(intent_bytes or b"").hexdigest()
        or result["target_source_sha"] != intent["target_source_sha"]
    ):
        raise ReconcileError("RESULT_INTENT_CONFLICT")
    if run_id == R904:
        if intent is not None and any(intent[k] != value for k, value in _PINS904.items()):
            raise ReconcileError("R904_INTENT")
        if result is not None and (
            result["version"] != "boca-cutover-a-terminal-v1"
            or result["legacy_source_sha"] != _PINS904["legacy_source_sha"]
            or result["state"] not in ("RECOVERED", "NO_GO")
            or result["irreversible_commit_started"]
            or result["state"] == "RECOVERED"
            and (not result["original_restored"] or result["cleanup"] != "ACCEPT")
            or len({result["legacy_id"], result["worker_id"], result["candidate_id"]}) != 3
            or any(result[k] is None for k in ("worker_id", "candidate_id"))
        ):
            raise ReconcileError("R904_TERMINAL")
    inventory_state = "OBSERVED"
    if run_id == R904:
        try:
            first = _safe_inventory904(_docker_snapshot())
            if _safe_inventory904(_docker_snapshot()) != first:
                raise ReconcileError("BOCA_RUNTIME_DRIFT")
        except (OSError, TypeError, ValueError):
            first = []
            inventory_state = "INDETERMINATE"
        try:
            staged = _staged_attempt(run_id)
        except (OSError, ValueError):
            staged = dict.fromkeys(("stage", "promotion_intent", "promotion_result"), "UNVERIFIED")
    else:
        first = _docker_snapshot()
        if first != _docker_snapshot():
            raise ReconcileError("BOCA_RUNTIME_DRIFT")
        staged = _staged_attempt(run_id)
    legacy = intent["legacy_id"] if intent is not None else LEGACY904 if run_id == R904 else ""
    originals = [item for item in first if item["id"] == legacy] if legacy else []
    candidates = [
        item
        for item in first
        if item["service"] == "controller"
        and intent is not None
        and item["revision"] == intent["target_source_sha"]
        and item["id"] != legacy
    ]
    workers = [item for item in first if item["service"] == "browser-worker"]
    marker_status, marker_reason = (
        _marker(prepared_id)
        if prepared_id is not None
        else ("NOT_APPLICABLE", "V3_DISPATCH_WITHOUT_PREPARE")
    )
    receipt: dict[str, Any] = {
        "version": "boca-postapply-reconcile-v1",
        "incident_run_id": run_id,
        "prepare_run_id": prepared_id,
        "intent": "PRESENT" if intent is not None else "ABSENT",
        "result": "PRESENT" if result is not None else "ABSENT",
        "terminal_state": result["state"] if result is not None else "UNVERIFIED",
        "cleanup": result["cleanup"] if result is not None else "UNVERIFIED",
        # Durable terminal slots identify the last completed phase without
        # exposing transient Docker IDs or inferring a reason from final topology.
        "worker_id_recorded": result["worker_id"] is not None if result is not None else None,
        "candidate_id_recorded": result["candidate_id"] is not None if result is not None else None,
        "commit_started": result["irreversible_commit_started"] if result is not None else None,
        "original_restored": result["original_restored"] if result is not None else None,
        "legacy_id": legacy or None,
        "original": originals[0] if len(originals) == 1 else None,
        "candidate_controllers": candidates,
        "browser_workers": workers,
        "boca_inventory": first,
        "boca_containers": len(first) if inventory_state == "OBSERVED" else None,
        "port_8443": _ports(first),
        "prepared_go_marker": marker_status,
        "prepared_go_marker_reason": marker_reason,
        "stage_preflight": _stage_preflight(intent),
        **staged,
        "runtime_attested": False,
        "go_for_retry": False,
        "foreign_resources_touched": False,
    }
    if source_sha is not None:
        receipt["version"] = "boca-postapply-reconcile-v3"
        receipt["incident_source_sha"] = source_sha
        # Only bounded, typed external terminal facts. Never copy Docker
        # stdout, environment, exception messages or protected module bytes.
        receipt["terminal_worker_evidence"] = (
            {
                field: result[field]
                for field in (
                    WORKER_EVIDENCE_FIELDS_V4
                    if result["version"] == TERMINAL_V4
                    else WORKER_EVIDENCE_FIELDS
                )
            }
            if result is not None and result["version"] in (TERMINAL_V3, TERMINAL_V4)
            else None
        )
    if run_id == R904:
        receipt["version"] = "boca-postapply-reconcile-904-v1"
        situation = _files904(Path("/srv/boca-socios"), home)
        second_files = _files904(Path("/srv/boca-socios"), home)
        for key, entry in situation["inodes"].items():
            if entry != second_files["inodes"][key] or situation["checks"].get(key) != second_files[
                "checks"
            ].get(key):
                situation["inodes"][key] = "UNSTABLE"
                if key in situation["checks"]:
                    situation["checks"][key] = None
        receipt["incident_files"] = situation
        processes = _processes904(first)
        second_processes = _processes904(first)
        receipt["processes"] = {
            cid: value if value == second_processes[cid] else "INDETERMINATE"
            for cid, value in processes.items()
        }
        receipt["inventory_state"] = inventory_state
        receipt["terminal_ids"] = {
            key: result[key] if result is not None else None
            for key in ("candidate_id", "worker_id")
        }
    return receipt


def _verify904(record: dict[str, Any]) -> None:
    """Exact public projection for this incident, including every nested field."""
    if (
        record["legacy_id"] != LEGACY904
        or record["intent"] not in ("PRESENT", "ABSENT")
        or record["result"] not in ("PRESENT", "ABSENT")
        or record["terminal_worker_evidence"] is not None
    ):
        raise ReconcileError("R904_SCHEMA")
    terminal = record["terminal_ids"]
    if type(terminal) is not dict or set(terminal) != {"candidate_id", "worker_id"}:
        raise ReconcileError("R904_TERMINAL")
    if record["result"] == "PRESENT":
        if (
            record["intent"] != "PRESENT"
            or record["terminal_state"] not in ("NO_GO", "RECOVERED")
            or record["cleanup"] not in ("ACCEPT", "NO_GO", "INDETERMINATE")
            or type(record["original_restored"]) is not bool
            or record["commit_started"] is not False
            or not all(record[k] is True for k in ("worker_id_recorded", "candidate_id_recorded"))
            or (
                record["terminal_state"] == "RECOVERED"
                and (not record["original_restored"] or record["cleanup"] != "ACCEPT")
            )
            or not all(type(v) is str and IDENT.fullmatch(v) for v in terminal.values())
            or len({*terminal.values(), LEGACY904}) != 3
        ):
            raise ReconcileError("R904_TERMINAL")
    elif (
        record["terminal_state"] != "UNVERIFIED"
        or record["cleanup"] != "UNVERIFIED"
        or any(v is not None for v in terminal.values())
        or any(record[k] is not None for k in ("commit_started", "original_restored"))
    ):
        raise ReconcileError("R904_TERMINAL")
    items = record["boca_inventory"]
    if type(items) is not list or len(items) > 8 or _safe_inventory904(items) != items:
        raise ReconcileError("R904_INVENTORY")
    state = record["inventory_state"]
    if (
        state not in ("OBSERVED", "INDETERMINATE")
        or state == "INDETERMINATE"
        and (items or record["boca_containers"] is not None)
        or state == "OBSERVED"
        and (type(record["boca_containers"]) is not int or record["boca_containers"] != len(items))
    ):
        raise ReconcileError("R904_INVENTORY")
    ids = [x["id"] for x in items]
    actual = next((x for x in items if x["id"] == LEGACY904), None)
    if (
        ids != sorted(set(ids))
        or record["original"] != actual
        or record["browser_workers"] != [x for x in items if x["service"] == "browser-worker"]
        or record["candidate_controllers"]
        != [
            x
            for x in items
            if record["intent"] == "PRESENT"
            and x["service"] == "controller"
            and x["revision"] == R904_SHA
            and x["id"] != LEGACY904
        ]
        or record["port_8443"] != _ports(items)
    ):
        raise ReconcileError("R904_INVENTORY")
    processes = record["processes"]
    if (
        type(processes) is not dict
        or set(processes) != set(ids)
        or any(
            type(p) is not list
            or len(p) != 5
            or p[0]
            not in ("created", "running", "paused", "exited", "dead", "restarting", "removing")
            or type(p[1]) is not int
            or not 0 <= p[1] < 2**31
            or p[2] not in ("legacy_image_ref", "target_image_ref", "browser_image_ref", "OTHER")
            or p[3] not in ("no", "unless-stopped", "OTHER")
            or p[4] != "UNKNOWN"
            and (type(p[4]) is not int or not 0 <= p[4] < 2**63)
            for p in processes.values()
            if p != "INDETERMINATE"
        )
    ):
        raise ReconcileError("R904_CONTAINER")
    evidence = record["incident_files"]
    if type(evidence) is not dict or set(evidence) != {"inodes", "checks"}:
        raise ReconcileError("R904_FILES")
    entries, details = evidence["inodes"], evidence["checks"]
    if (
        type(entries) is not dict
        or set(entries) != (_FILES904.keys() | _ACT904.keys())
        or type(details) is not dict
        or set(details)
        != _EXTRAS904 | _DIGEST904.keys() | {"attempt", "enabled_socket", "stage_marker"}
    ):
        raise ReconcileError("R904_FILES")
    for item in entries.values():
        if item in ("ABSENT", "UNSAFE", "UNSTABLE", "UNREADABLE"):
            continue
        if (
            type(item) is not list
            or len(item) != 6
            or item[0] not in ("dir", "file", "link", "socket", "other")
            or any(type(n) is not int or not 0 <= n < 2**64 for n in item[1:5])
            or item[3] > 0o7777
            or type(item[5]) is not bool
        ):
            raise ReconcileError("R904_FILES")
    for key, detail in details.items():
        if detail is None:
            continue
        entry = entries[key]
        if type(entry) is not list or entry[-1] is not True:
            raise ReconcileError("R904_FILES")
        if key in _EXTRAS904:
            valid = entry[0] == "dir" and (
                detail == "LIMIT" or type(detail) is int and 0 <= detail <= 256
            )
        elif key == "stage_marker":
            valid = (
                entry[0] == "file"
                and type(detail) is list
                and len(detail) == 2
                and all(type(n) is int and 0 <= n < 2**64 for n in detail)
            )
        else:
            valid = (
                entry[0] == ("link" if key == "enabled_socket" else "file") and type(detail) is bool
            )
        if not valid:
            raise ReconcileError("R904_FILES")
    stage = record["stage_preflight"]
    empty_stage = _stage_preflight(None)
    if type(stage) is not dict or set(stage) not in (
        set(empty_stage),
        set(empty_stage) | {"legacy_target_compose_equal"},
    ):
        raise ReconcileError("R904_STAGE")
    if (
        stage["reason"]
        not in (
            "INTENT_ABSENT",
            "STAGE_ROOT_UNREADABLE",
            "STAGE_ROOT_OWNER_MODE",
            "STAGE_ROOT_LIST",
            "STAGE_ROOT_ENTRIES",
            "STAGE_COMPOSE_UNREADABLE",
            "STAGE_COMPOSE_INODE_MODE",
            "STAGE_COMPOSE_CHANGED",
            "PLAN_ROLE_DIGEST_INVALID",
            "STAGE_PREFLIGHT_MATCH",
            "STAGE_COMPOSE_SHA",
            "STAGE_COMPOSE_IO",
        )
        or any(
            type(stage[k]) is not bool
            for k in (
                "root_entries_expected",
                "compose_digest_match",
                "compose_digest_evaluated",
                "plan_hashes_unique",
            )
        )
        or (
            "legacy_target_compose_equal" in stage
            and stage["legacy_target_compose_equal"] is not True
        )
        or stage["root_entries_count"] is not None
        and (
            type(stage["root_entries_count"]) is not int
            or not 0 <= stage["root_entries_count"] <= 2048
        )
        or stage["compose_inode_mode_octal"] is not None
        and (
            type(stage["compose_inode_mode_octal"]) is not str
            or not re.fullmatch(r"[0-7]{4}", stage["compose_inode_mode_octal"])
        )
        or stage["compose_legacy_mode_accepted"] is not None
        and type(stage["compose_legacy_mode_accepted"]) is not bool
        or any(
            record[k] not in ("PRESENT", "ABSENT", "UNVERIFIED")
            for k in ("stage", "promotion_intent", "promotion_result")
        )
    ):
        raise ReconcileError("R904_STAGE")
    checks = stage["compose_inode_checks"]
    if checks is not None and (
        type(checks) is not dict
        or set(checks) != {"regular", "uid_ok", "gid_ok", "nlink_one", "mode_0600", "size_ok"}
        or any(type(v) is not bool for v in checks.values())
    ):
        raise ReconcileError("R904_STAGE")


def verify_runner(
    raw: bytes, run_id: str, prepared_id: str | None, *, source_sha: str | None = None
) -> dict[str, Any]:
    if not RUN.fullmatch(run_id):
        raise ReconcileError("RUN_ID")
    if source_sha is None:
        if prepared_id is None or not RUN.fullmatch(prepared_id) or run_id == prepared_id:
            raise ReconcileError("RUN_ID")
    elif prepared_id is not None or not SOURCE.fullmatch(source_sha):
        raise ReconcileError("V3_SOURCE_ID")
    if run_id == R904 and source_sha != R904_SHA:
        raise ReconcileError("R904_PROVENANCE")
    if not 0 < len(raw) <= (R904_LIMIT if run_id == R904 else MAX_JSON):
        raise ReconcileError("RECEIPT_BOUNDS")
    try:
        record = json.loads(raw.decode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise ReconcileError("RECEIPT_JSON") from exc
    version = record.get("version") if type(record) is dict else None
    allowed_versions = (
        ("boca-postapply-reconcile-904-v1",)
        if run_id == R904
        else ("boca-postapply-reconcile-v2", "boca-postapply-reconcile-v3")
        if source_sha is not None
        else ("boca-postapply-reconcile-v1",)
    )
    expected_fields = (
        RECEIPT_FIELDS
        | ({"incident_source_sha"} if source_sha is not None else set())
        | (
            {"terminal_worker_evidence"}
            if version == "boca-postapply-reconcile-v3" or run_id == R904
            else set()
        )
        | (
            {"incident_files", "processes", "terminal_ids", "inventory_state"}
            if run_id == R904
            else set()
        )
    )
    worker_evidence = record.get("terminal_worker_evidence") if type(record) is dict else None
    evidence_valid = worker_evidence is None or (
        type(worker_evidence) is dict
        and worker_evidence.get("version") in (TERMINAL_V3, TERMINAL_V4)
        and set(worker_evidence)
        == (
            WORKER_EVIDENCE_FIELDS_V4
            if worker_evidence.get("version") == TERMINAL_V4
            else WORKER_EVIDENCE_FIELDS
        )
        and (
            worker_evidence.get("version") != TERMINAL_V4
            or (
                type(worker_evidence.get("worker_exit_signature")) is str
                and WORKER_SIGNATURE.fullmatch(worker_evidence["worker_exit_signature"]) is not None
            )
        )
        and worker_evidence.get("worker_primary_phase") == "HEALTH_EXITED"
        and worker_evidence.get("worker_compensation")
        in ("VERIFIED", "INDETERMINATE", "UNVERIFIED")
        and (
            type(worker_evidence.get("worker_exit_code")) is int
            and 0 <= worker_evidence["worker_exit_code"] <= 255
            or worker_evidence.get("worker_exit_code") == "UNKNOWN"
        )
        and (
            type(worker_evidence.get("worker_oom_killed")) is bool
            or worker_evidence.get("worker_oom_killed") == "UNKNOWN"
        )
    )
    if (
        type(record) is not dict
        or version not in allowed_versions
        or set(record) != expected_fields
        or record.get("incident_run_id") != run_id
        or record.get("prepare_run_id") != prepared_id
        or (
            source_sha is not None
            and (
                record.get("incident_source_sha") != source_sha
                or record.get("prepared_go_marker") != "NOT_APPLICABLE"
                or record.get("prepared_go_marker_reason") != "V3_DISPATCH_WITHOUT_PREPARE"
            )
        )
        or (source_sha is None and "incident_source_sha" in record)
        or (version == "boca-postapply-reconcile-v3" and not evidence_valid)
        or (source_sha is None and "terminal_worker_evidence" in record)
        or record.get("go_for_retry") is not False
        or record.get("runtime_attested") is not False
        or record.get("foreign_resources_touched") is not False
        or (
            record.get("result") == "PRESENT"
            and (
                type(record.get("worker_id_recorded")) is not bool
                or type(record.get("candidate_id_recorded")) is not bool
                or (record["candidate_id_recorded"] and not record["worker_id_recorded"])
            )
        )
        or (
            record.get("result") != "PRESENT"
            and (
                record.get("worker_id_recorded") is not None
                or record.get("candidate_id_recorded") is not None
            )
        )
        or _canonical(record) + b"\n" != raw
    ):
        raise ReconcileError("RECEIPT_CONTRACT")
    if run_id == R904:
        _verify904(record)
    return record


def _recovered_preflight_verified(raw: Any) -> bool:
    """Match the prior unmodified Stage policy, including legacy 0644 Compose."""
    if type(raw) is not dict:
        return False
    checks = raw.get("compose_inode_checks")
    mode = raw.get("compose_inode_mode_octal")
    return bool(
        raw.get("reason") == "STAGE_PREFLIGHT_MATCH"
        and type(raw.get("root_entries_count")) is int
        and raw["root_entries_count"] == 1
        and raw.get("root_entries_expected") is True
        and raw.get("compose_digest_match") is True
        and raw.get("compose_digest_evaluated") is True
        and raw.get("compose_legacy_mode_accepted") is True
        and raw.get("plan_hashes_unique") is True
        and mode in ("0600", "0644")
        and type(checks) is dict
        and set(checks) == {"regular", "uid_ok", "gid_ok", "nlink_one", "mode_0600", "size_ok"}
        and all(
            checks.get(key) is True
            for key in ("regular", "uid_ok", "gid_ok", "nlink_one", "size_ok")
        )
        and checks.get("mode_0600") is (mode == "0600")
    )


def verified_cleanup_legacy_id(raw: bytes, run_id: str, coordinate: str, *, v3: bool) -> str:
    """Resolve only the restored Boca CID from a verified post-Cutover receipt.

    `coordinate` is the authenticated incident SHA for V3; legacy v1 instead
    receives its PREPARE run. This never promotes or deletes Docker resources.
    """
    if type(v3) is not bool:
        raise ReconcileError("CLEANUP_RECEIPT_VERSION")
    if run_id == R904:
        raise ReconcileError("R904_OBSERVER_ONLY")
    receipt = verify_runner(
        raw,
        run_id,
        None if v3 else coordinate,
        source_sha=coordinate if v3 else None,
    )
    original = receipt.get("original")
    legacy_id = receipt.get("legacy_id")
    if (
        receipt.get("intent") != "PRESENT"
        or receipt.get("result") != "PRESENT"
        or receipt.get("original_restored") is not True
        or receipt.get("commit_started") is not False
        or type(original) is not dict
        or type(legacy_id) is not str
        or IDENT.fullmatch(legacy_id) is None
        or original.get("id") != legacy_id
        or original.get("running") is not True
        or original.get("health") != "healthy"
    ):
        raise ReconcileError("CLEANUP_ORIGINAL_UNVERIFIED")
    if v3:
        # Historical #853 NO_GO/INDETERMINATE admission is unchanged.
        historical = (
            receipt.get("terminal_state") == "NO_GO" and receipt.get("cleanup") == "INDETERMINATE"
        )
        # #878's positive recovery is *not* a Cutover acceptance. Recheck the
        # precise external worker failure, full Boca topology and Stage state.
        # Images, volumes and networks intentionally remain for the *next*
        # read-only planner to inventory independently.
        recovered = (
            run_id == RECOVERED_INVENTORY_RUN
            and coordinate == RECOVERED_INVENTORY_SHA
            and receipt.get("terminal_state") == "RECOVERED"
            and receipt.get("cleanup") == "ACCEPT"
            and receipt.get("terminal_worker_evidence")
            == {
                "version": TERMINAL_V3,
                "worker_primary_phase": "HEALTH_EXITED",
                "worker_compensation": "VERIFIED",
                "worker_exit_code": 1,
                "worker_oom_killed": False,
            }
            and receipt.get("worker_id_recorded") is False
            and receipt.get("candidate_id_recorded") is False
            and type(receipt.get("boca_containers")) is int
            and receipt["boca_containers"] == 1
            and receipt.get("boca_inventory") == [original]
            and receipt.get("candidate_controllers") == []
            and receipt.get("browser_workers") == []
            and receipt.get("stage") == "ABSENT"
            and receipt.get("promotion_intent") == "ABSENT"
            and receipt.get("promotion_result") == "ABSENT"
            and _recovered_preflight_verified(receipt.get("stage_preflight"))
        )
        if (
            not (historical or recovered)
            or receipt.get("port_8443") != "BOCA_CONTROLLER_DOCKER_BOUND"
            or original.get("name") != "/boca-socios-controller-1"
            or original.get("service") != "controller"
            or original.get("port_binding")
            != {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
        ):
            raise ReconcileError("CLEANUP_V3_ORIGINAL_UNVERIFIED")
    return legacy_id


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3 or args[0] not in ("host", "verify", "host-v3", "verify-v3"):
        print("BOCA_POSTAPPLY_RECONCILE state=NO_GO reason=INPUT", file=sys.stderr)
        return 3
    mode, run_id, coordinate = args
    is_v3 = mode.endswith("-v3")
    prepare_id = None if is_v3 else coordinate
    source_sha = coordinate if is_v3 else None
    try:
        limit = R904_LIMIT if run_id == R904 else MAX_JSON
        if mode in ("host", "host-v3"):
            result = _host(run_id, prepare_id, source_sha=source_sha)
            output = _canonical(result) + b"\n"
            if len(output) > limit:
                raise ReconcileError("RECEIPT_BOUNDS")
            sys.stdout.buffer.write(output)
        else:
            raw = sys.stdin.buffer.read(limit + 1)
            result = verify_runner(raw, run_id, prepare_id, source_sha=source_sha)
            unverified = result.get("inventory_state") == "INDETERMINATE"
            original = "UNVERIFIED" if unverified else str(result["original"] is not None)
            candidates = "UNVERIFIED" if unverified else str(len(result["candidate_controllers"]))
            workers = "UNVERIFIED" if unverified else str(len(result["browser_workers"]))
            print(
                "BOCA_POSTAPPLY_RECONCILE state=READ_ONLY_NO_GO"
                f" intent={result['intent']} result={result['result']}"
                f" terminal={result['terminal_state']} cleanup={result['cleanup']}"
                f" original={original} candidates={candidates} workers={workers}"
                f" port={result['port_8443']}"
                f" marker={result['prepared_go_marker']}"
                f" worker_phase={result['worker_id_recorded']}"
                f" candidate_phase={result['candidate_id_recorded']}"
                " scope=OBSERVER_ONLY observer_writes=0"
                " prior_apply_effects=UNKNOWN retry=NO_GO"
            )
        return 0
    except (OSError, ReconcileError, ValueError, TypeError):
        print("BOCA_POSTAPPLY_RECONCILE state=NO_GO reason=UNVERIFIED", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
