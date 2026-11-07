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
            child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
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
    version = obj.get("version") if isinstance(obj, dict) else None
    valid_version = (
        version == "boca-cutover-a-intent-v1"
        if kind == "intent"
        else version in (result_v1, result_v2)
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
        typed = version == result_v2
        typed_fields = {"worker_primary_phase", "worker_compensation"}
        allowed_phases = {
            "ATTEST",
            "STORAGE",
            "PULL",
            "IPC",
            "CREATE",
            "START",
            "HEALTH",
            "UNVERIFIED",
        }
        allowed_compensation = {"VERIFIED", "INDETERMINATE", "UNVERIFIED"}
        if (
            set(obj) != (base_fields | typed_fields if typed else base_fields)
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


def _host(run_id: str, prepared_id: str | None, *, source_sha: str | None = None) -> dict[str, Any]:
    if not RUN.fullmatch(run_id):
        raise ReconcileError("RUN_ID")
    if source_sha is None:
        if prepared_id is None or not RUN.fullmatch(prepared_id) or run_id == prepared_id:
            raise ReconcileError("RUN_ID")
    elif prepared_id is not None or not SOURCE.fullmatch(source_sha):
        raise ReconcileError("V3_SOURCE_ID")
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
    first = _docker_snapshot()
    second = _docker_snapshot()
    if first != second:
        raise ReconcileError("BOCA_RUNTIME_DRIFT")
    legacy = intent["legacy_id"] if intent is not None else ""
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
        "boca_containers": len(first),
        "port_8443": _ports(first),
        "prepared_go_marker": marker_status,
        "prepared_go_marker_reason": marker_reason,
        "stage_preflight": _stage_preflight(intent),
        **_staged_attempt(run_id),
        "runtime_attested": False,
        "go_for_retry": False,
        "foreign_resources_touched": False,
    }
    if source_sha is not None:
        receipt["version"] = "boca-postapply-reconcile-v2"
        receipt["incident_source_sha"] = source_sha
    return receipt


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
    if not 0 < len(raw) <= MAX_JSON:
        raise ReconcileError("RECEIPT_BOUNDS")
    try:
        record = json.loads(raw.decode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise ReconcileError("RECEIPT_JSON") from exc
    if (
        type(record) is not dict
        or record.get("version")
        != (
            "boca-postapply-reconcile-v2"
            if source_sha is not None
            else "boca-postapply-reconcile-v1"
        )
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
    return record


def verified_cleanup_legacy_id(raw: bytes, run_id: str, coordinate: str, *, v3: bool) -> str:
    """Resolve only the restored Boca CID from a verified post-Cutover receipt.

    `coordinate` is the authenticated incident SHA for V3; legacy v1 instead
    receives its PREPARE run. This never promotes or deletes Docker resources.
    """
    if type(v3) is not bool:
        raise ReconcileError("CLEANUP_RECEIPT_VERSION")
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
    if v3 and (
        receipt.get("terminal_state") != "NO_GO"
        or receipt.get("cleanup") != "INDETERMINATE"
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
        if mode in ("host", "host-v3"):
            result = _host(run_id, prepare_id, source_sha=source_sha)
            output = _canonical(result) + b"\n"
            if len(output) > MAX_JSON:
                raise ReconcileError("RECEIPT_BOUNDS")
            sys.stdout.buffer.write(output)
        else:
            raw = sys.stdin.buffer.read(MAX_JSON + 1)
            result = verify_runner(raw, run_id, prepare_id, source_sha=source_sha)
            print(
                "BOCA_POSTAPPLY_RECONCILE state=READ_ONLY_NO_GO"
                f" intent={result['intent']} result={result['result']}"
                f" terminal={result['terminal_state']} cleanup={result['cleanup']}"
                f" original={result['original'] is not None}"
                f" candidates={len(result['candidate_controllers'])}"
                f" workers={len(result['browser_workers'])}"
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
