"""One-shot, stopped-only recovery of the exact failed #795 Boca probe.

No free-form Docker target, mutable input, stop/force/volume/image operation,
or Cutover authorization exists in this module. The only possible container
write is a single non-force ``docker container rm`` of the pinned full CID.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path
from typing import Any

from boca_socios import host_boca_cleanup as cleanup
from scripts import host_cutover_worker_inspect as observer

ATTEMPT = "42329475083"
CID = "65d844edb438710f44ce83c397906932710ad7f04f3e7a52634f9eaaf1fcc504"
SOURCE = observer.FAILED_WORKER_SOURCE
BROWSER_IMAGE = observer.FAILED_WORKER_IMAGE
LEGACY_ID = "27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793"
LEGACY_SOURCE = "cabce9f1e452e63ded115f447559a358dc0f4d1b"
LEGACY_IMAGE = (
    "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:"
    "cf6e4266cfcfea0c07fa31301d59c7aaa3b9c2fefb9f6843baddd208cacd3b59"
)
NAME = f"{observer.PREFIX}{ATTEMPT}"
FULL_FORMAT = "{{json .}}"
RECEIPT_KEYS = frozenset(
    {
        "version",
        "attempt",
        "probe_id",
        "legacy_id",
        "cleanup",
        "phase",
        "docker_writes",
        "foreign_resources_touched",
        "cutover_authorized",
        "retry_authorized",
        "original",
    }
)


class RecoveryError(ValueError):
    """An identity, isolation, protocol or postcondition was not established."""


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RecoveryError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _profile() -> bytes:
    """Read only the reviewed, SHA-verified in-memory code package."""
    with zipfile.ZipFile(sys.argv[0], "r") as archive:
        data = archive.read("docker/seccomp_profile.json")
    if not 0 < len(data) <= 32768:
        raise RecoveryError("PROFILE_BOUNDS")
    if not isinstance(json.loads(data, object_pairs_hook=_unique_pairs), dict):
        raise RecoveryError("PROFILE_INVALID")
    return data


def _compact_json_profile(raw: bytes) -> str:
    """Match Docker's effective seccomp JSON, preserving quoted byte escapes."""
    json.loads(raw, object_pairs_hook=_unique_pairs)
    compact = bytearray()
    quoted = False
    escaped = False
    for char in raw:
        if quoted:
            compact.append(char)
            if escaped:
                escaped = False
            elif char == ord("\\"):
                escaped = True
            elif char == ord('"'):
                quoted = False
        elif char == ord('"'):
            quoted = True
            compact.append(char)
        elif char not in (ord(" "), ord("\t"), ord("\r"), ord("\n")):
            compact.append(char)
    if quoted or escaped:
        raise RecoveryError("PROFILE_INCOMPLETE")
    return "seccomp=" + compact.decode("utf-8")


def _observe() -> dict[str, Any]:
    return observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)


def _validate_snapshot(record: dict[str, Any], *, removed: bool) -> None:
    # The observer's existing parser checks every stage, key, type and flag.
    observer.verify(observer.canonical(record) + b"\n", ATTEMPT, LEGACY_ID)
    if (
        record["socket"] != "PRESENT_OWNED"
        or record["seccomp"] != "ABSENT"
        or record["docker"] != "OBSERVED"
        or record["probe_list_stage"] != ("ABSENT" if removed else "OK")
        or record["probe"] != ("ABSENT" if removed else "PRESENT_PIN_MATCH")
        or record["probe_candidate_id"] != (None if removed else CID)
        or record["probe_id"] != (None if removed else CID)
        or record["probe_running"] is not (None if removed else False)
        or record["probe_full_json_stage"] != ("SKIPPED" if removed else "BELOW_CLEANUP_LIMIT")
        or record["original"] != "RUNNING_HEALTHY"
        or record["original_port"] != "LOOPBACK_8443"
        or record["original_inspect_stage"] != "OK"
        or record["observer_writes"] != 0
        or record["foreign_resources_touched"] is not False
        or record["cutover_authorized"] is not False
    ):
        raise RecoveryError("SNAPSHOT_NO_GO")


def _inspect_full_exact(cid: str) -> dict[str, Any]:
    if cid != CID:
        raise RecoveryError("EXACT_CID_REQUIRED")
    raw = observer._run_bounded(
        ("docker", "inspect", "--format", FULL_FORMAT, CID), stdout_limit=65535
    )
    if not 0 < len(raw.encode("ascii")) < 65536:
        raise RecoveryError("FULL_INSPECT_BOUNDS")
    record = json.loads(raw, object_pairs_hook=_unique_pairs)
    if not isinstance(record, dict):
        raise RecoveryError("FULL_INSPECT_INVALID")
    return record


def _validate_isolation(record: dict[str, Any], profile: bytes) -> None:
    config = record.get("Config")
    host = record.get("HostConfig")
    state = record.get("State")
    network = record.get("NetworkSettings")
    if not all(isinstance(section, dict) for section in (config, host, state, network)):
        raise RecoveryError("INCOMPLETE_INSPECT")
    assert isinstance(config, dict) and isinstance(host, dict)
    assert isinstance(state, dict) and isinstance(network, dict)
    labels = config.get("Labels")
    restart = host.get("RestartPolicy")
    variables = config.get("Env")
    expected_boca = {
        "BOCA_ENVIRONMENT=staging",
        "BOCA_RUNTIME_MODE=simulation",
        "BOCA_ENGINE_MODE=off",
        "BOCA_OBSERVER_STOP=1",
    }
    if not isinstance(variables, list) or any(not isinstance(item, str) for item in variables):
        raise RecoveryError("PROBE_ENV_INVALID")
    observed_boca = [item for item in variables if item.startswith("BOCA_")]
    if len(observed_boca) != len(expected_boca) or set(observed_boca) != expected_boca:
        raise RecoveryError("PROBE_ENV_CHANGED")
    if (
        record.get("Id") != CID
        or record.get("Name") != f"/{NAME}"
        or config.get("Image") != BROWSER_IMAGE
        or config.get("User") != "10002:10002"
        or config.get("Cmd") != ["python", "-c", "import time; time.sleep(90)"]
        or not isinstance(labels, dict)
        or labels.get(observer.PROBE_LABEL) != ATTEMPT
        or labels.get("com.docker.compose.project") != observer.PROJECT
        or labels.get("org.opencontainers.image.revision") != SOURCE
        or state.get("Running") is not False
        or state.get("Restarting") is not False
        or state.get("Paused") is not False
        or state.get("Dead") is not False
        or state.get("OOMKilled") is not False
        or state.get("Status") not in ("created", "exited")
        or not isinstance(restart, dict)
        or restart.get("Name") != "no"
        or host.get("AutoRemove") is not False
        or host.get("PidMode") != ""
        or host.get("PublishAllPorts") is not False
        or host.get("Devices") not in (None, [])
        or host.get("DeviceRequests") not in (None, [])
        or host.get("ShmSize") != 67_108_864
        or host.get("Tmpfs")
        != {
            "/tmp": "rw,noexec,nosuid,size=32m",  # noqa: S108 - isolated worker tmpfs
            "/home/boca-browser": "rw,noexec,nosuid,size=16m",
        }
        or host.get("NetworkMode") != "none"
        or host.get("IpcMode") != "private"
        or host.get("CgroupnsMode") != "private"
        or host.get("ReadonlyRootfs") is not True
        or host.get("Privileged") is not False
        or host.get("Init") is not True
        or host.get("NanoCpus") != 1_000_000_000
        or host.get("Memory") != 805_306_368
        or host.get("PidsLimit") != 128
        or host.get("CapDrop") != ["ALL"]
        or host.get("CapAdd") not in (["SYS_CHROOT"], ["CAP_SYS_CHROOT"])
        or host.get("PortBindings") not in (None, {})
        or host.get("Binds") not in (None, [])
        or host.get("Mounts") not in (None, [])
        or host.get("VolumesFrom") not in (None, [])
        or record.get("Mounts") != []
        or network.get("Ports") not in (None, {})
        or not isinstance(network.get("Networks"), dict)
        or set(network["Networks"]) != {"none"}
        or host.get("SecurityOpt") != ["no-new-privileges:true", _compact_json_profile(profile)]
    ):
        raise RecoveryError("PROBE_ISOLATION_CHANGED")


def _remove_exact(cid: str) -> str:
    if cid != CID:
        raise RecoveryError("EXACT_CID_REQUIRED")
    return observer._run_bounded(("docker", "container", "rm", CID), stdout_limit=128)


def _cid_present(cid: str) -> bool:
    if cid != CID:
        raise RecoveryError("EXACT_CID_REQUIRED")
    rows = observer._run_bounded(
        ("docker", "ps", "-a", "-q", "--no-trunc", "--filter", f"id={CID}")
    ).splitlines()
    if len(rows) > 1 or any(not observer.CONTAINER_ID.fullmatch(row) for row in rows):
        raise RecoveryError("POST_CID_SET_INVALID")
    if rows and rows != [CID]:
        raise RecoveryError("POST_CID_MISMATCH")
    return bool(rows)


def execute() -> dict[str, Any]:
    """Exactly one attempt, full precheck twice under lease, no automatic retry."""
    phase = "PRECHECK"
    attempts = 0
    verified = False
    try:
        with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
            for _ in range(2):
                cleanup.verify_protected_boca_job_lease(lease, ATTEMPT)
                _validate_snapshot(_observe(), removed=False)
                _validate_isolation(_inspect_full_exact(CID), _profile())
            cleanup.verify_protected_boca_job_lease(lease, ATTEMPT)
            phase = "REMOVE"
            attempts = 1  # Timeout or lost ACK after this point is indeterminate.
            if _remove_exact(CID) != CID:
                raise RecoveryError("DOCKER_REMOVE_ACK_INVALID")
            phase = "POSTCHECK"
            if _cid_present(CID):
                raise RecoveryError("CID_RETAINED")
            _validate_snapshot(_observe(), removed=True)
            cleanup.verify_protected_boca_job_lease(lease, ATTEMPT)
            verified = True
            phase = "COMPLETE"
    except Exception:  # noqa: BLE001 - fail closed without leaking Docker stderr or ENV
        verified = False
    return {
        "version": "boca-worker-recovery-v1",
        "attempt": ATTEMPT,
        "probe_id": CID,
        "legacy_id": LEGACY_ID,
        "cleanup": "VERIFIED" if verified else "INDETERMINATE" if attempts else "NO_GO_PRECHECK",
        "phase": phase,
        "docker_writes": attempts,
        "foreign_resources_touched": False,
        "cutover_authorized": False,
        "retry_authorized": False,
        "original": "RUNNING_HEALTHY" if verified else "UNVERIFIED",
    }


def verify_runner(raw: bytes) -> dict[str, Any]:
    if not 0 < len(raw) <= 1024:
        raise RecoveryError("RECEIPT_BOUNDS")
    record = json.loads(raw.decode("ascii"), object_pairs_hook=_unique_pairs)
    if (
        type(record) is not dict
        or set(record) != RECEIPT_KEYS
        or record["version"] != "boca-worker-recovery-v1"
        or record["attempt"] != ATTEMPT
        or record["probe_id"] != CID
        or record["legacy_id"] != LEGACY_ID
        or record["cleanup"] != "VERIFIED"
        or record["phase"] != "COMPLETE"
        or type(record["docker_writes"]) is not int
        or record["docker_writes"] != 1
        or record["foreign_resources_touched"] is not False
        or record["cutover_authorized"] is not False
        or record["retry_authorized"] is not False
        or record["original"] != "RUNNING_HEALTHY"
        or observer.canonical(record) + b"\n" != raw
    ):
        raise RecoveryError("RECEIPT_NO_GO")
    return record


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        if args == ["host"]:
            result = execute()
            sys.stdout.buffer.write(observer.canonical(result) + b"\n")
            return 0 if result["cleanup"] == "VERIFIED" else 3
        if len(args) == 2 and args[0] == "verify":
            with Path(args[1]).open("rb") as file:
                verify_runner(file.read(1025))
            print("BOCA_WORKER_RECOVERY_VERIFIED")
            return 0
    except (OSError, ValueError, TypeError, UnicodeError):
        pass
    print("BOCA_WORKER_RECOVERY state=NO_GO", file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
