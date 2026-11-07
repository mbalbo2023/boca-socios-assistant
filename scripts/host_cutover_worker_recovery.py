"""One-shot, stopped-only recovery of four separately gated Boca incidents.

No free-form Docker target, mutable input, stop/force/volume/image operation,
or Cutover authorization exists in this module. The only possible container
write is a single non-force ``docker container rm`` of the pinned full CID.
"""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
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
SECCOMP_SHA256 = "cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849"


@dataclass(frozen=True, slots=True)
class RecoveryTarget:
    """Internal, fixed recovery target; never derived from host or dispatch fields."""

    attempt: str
    cid: str
    source: str
    browser_image: str
    legacy_id: str
    legacy_source: str
    legacy_image: str


TARGET_795 = RecoveryTarget(
    ATTEMPT, CID, SOURCE, BROWSER_IMAGE, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE
)
TARGET_807 = RecoveryTarget(
    "42341290485",
    "06ac6e6b596c8286957cdfa21d6f4e3f6b7f19a7da4cff8b8c9ba47a1307a70d",
    observer.FAILED_WORKER_807_SOURCE,
    observer.FAILED_WORKER_807_IMAGE,
    LEGACY_ID,
    LEGACY_SOURCE,
    LEGACY_IMAGE,
)
TARGET_819 = RecoveryTarget(
    "42353468231",
    "4c2c40eaa7183e83440792466e844093a29c8b977e72c098c7be6a469f066547",
    "0538b3fb29cc0245a8387b7023c394883d0ea9a8",
    (
        "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
        "d740c610d032aa20fecff1602cc96e49fd63c597c49855990a9bc081a6998619"
    ),
    LEGACY_ID,
    LEGACY_SOURCE,
    LEGACY_IMAGE,
)
TARGET_827 = RecoveryTarget(
    "42368541950",
    "0ae6b61d97ccae77e8373a597f617df52b28ed63f6e49cae1df57f368e46e8e5",
    "8a69d155354362e0712dab1229f7d7e4b3e24dd6",
    (
        "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
        "902276a94bbec0ed0be30432baf97b5bd1298fc15e21eda750ccb785fa76bde0"
    ),
    LEGACY_ID,
    LEGACY_SOURCE,
    LEGACY_IMAGE,
)


def _known_target(target: RecoveryTarget) -> None:
    if (
        target is not TARGET_795
        and target is not TARGET_807
        and target is not TARGET_819
        and target is not TARGET_827
    ):
        raise RecoveryError("UNREVIEWED_TARGET")


def _invoke_target[T](fn: Callable[..., T], *args: Any, target: RecoveryTarget) -> T:
    """Preserve R80's original no-argument boundary while allowing R82 pins."""
    if target is TARGET_795:
        return fn(*args)
    return fn(*args, target=target)


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


def _observe(target: RecoveryTarget = TARGET_795) -> dict[str, Any]:
    return observer.observe(
        target.attempt, target.legacy_id, target.legacy_source, target.legacy_image
    )


def _validate_snapshot(
    record: dict[str, Any], *, removed: bool, target: RecoveryTarget = TARGET_795
) -> None:
    # The observer's existing parser checks every stage, key, type and flag.
    observer.verify(observer.canonical(record) + b"\n", target.attempt, target.legacy_id)
    if (
        record["socket"] != "PRESENT_OWNED"
        or record["seccomp"] != "ABSENT"
        or record["docker"] != "OBSERVED"
        or record["probe_list_stage"] != ("ABSENT" if removed else "OK")
        or record["probe"] != ("ABSENT" if removed else "PRESENT_PIN_MATCH")
        or record["probe_candidate_id"] != (None if removed else target.cid)
        or record["probe_id"] != (None if removed else target.cid)
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


def _inspect_full_exact(cid: str, target: RecoveryTarget = TARGET_795) -> dict[str, Any]:
    if cid != target.cid:
        raise RecoveryError("EXACT_CID_REQUIRED")
    raw = observer._run_bounded(
        ("docker", "inspect", "--format", FULL_FORMAT, target.cid), stdout_limit=65535
    )
    if not 0 < len(raw.encode("ascii")) < 65536:
        raise RecoveryError("FULL_INSPECT_BOUNDS")
    record = json.loads(raw, object_pairs_hook=_unique_pairs)
    if not isinstance(record, dict):
        raise RecoveryError("FULL_INSPECT_INVALID")
    return record


def _validate_isolation(
    record: dict[str, Any], profile: bytes, target: RecoveryTarget = TARGET_795
) -> None:
    if (target is TARGET_807 or target is TARGET_819 or target is TARGET_827) and hashlib.sha256(
        profile
    ).hexdigest() != SECCOMP_SHA256:
        raise RecoveryError("PROFILE_SHA_MISMATCH")
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
        record.get("Id") != target.cid
        or record.get("Name") != f"/{observer.PREFIX}{target.attempt}"
        or config.get("Image") != target.browser_image
        or config.get("User") != "10002:10002"
        or config.get("Cmd") != ["python", "-c", "import time; time.sleep(90)"]
        or not isinstance(labels, dict)
        or labels.get(observer.PROBE_LABEL) != target.attempt
        or labels.get("com.docker.compose.project") != observer.PROJECT
        or labels.get("org.opencontainers.image.revision") != target.source
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


def _remove_exact(cid: str, target: RecoveryTarget = TARGET_795) -> str:
    if cid != target.cid:
        raise RecoveryError("EXACT_CID_REQUIRED")
    return observer._run_bounded(("docker", "container", "rm", target.cid), stdout_limit=128)


def _cid_present(cid: str, target: RecoveryTarget = TARGET_795) -> bool:
    if cid != target.cid:
        raise RecoveryError("EXACT_CID_REQUIRED")
    rows = observer._run_bounded(
        ("docker", "ps", "-a", "-q", "--no-trunc", "--filter", f"id={target.cid}")
    ).splitlines()
    if len(rows) > 1 or any(not observer.CONTAINER_ID.fullmatch(row) for row in rows):
        raise RecoveryError("POST_CID_SET_INVALID")
    if rows and rows != [target.cid]:
        raise RecoveryError("POST_CID_MISMATCH")
    return bool(rows)


def execute(target: RecoveryTarget = TARGET_795) -> dict[str, Any]:
    """Exactly one attempt, full precheck twice under lease, no automatic retry."""
    _known_target(target)
    phase = "PRECHECK"
    attempts = 0
    verified = False
    try:
        with cleanup.protected_boca_job_lease(target.attempt) as lease:
            for _ in range(2):
                cleanup.verify_protected_boca_job_lease(lease, target.attempt)
                _validate_snapshot(
                    _invoke_target(_observe, target=target), removed=False, target=target
                )
                _validate_isolation(
                    _invoke_target(_inspect_full_exact, target.cid, target=target),
                    _profile(),
                    target=target,
                )
            cleanup.verify_protected_boca_job_lease(lease, target.attempt)
            phase = "REMOVE"
            attempts = 1  # Timeout or lost ACK after this point is indeterminate.
            if _invoke_target(_remove_exact, target.cid, target=target) != target.cid:
                raise RecoveryError("DOCKER_REMOVE_ACK_INVALID")
            phase = "POSTCHECK"
            if _invoke_target(_cid_present, target.cid, target=target):
                raise RecoveryError("CID_RETAINED")
            _validate_snapshot(_invoke_target(_observe, target=target), removed=True, target=target)
            cleanup.verify_protected_boca_job_lease(lease, target.attempt)
            verified = True
            phase = "COMPLETE"
    except Exception:  # noqa: BLE001 - fail closed without leaking Docker stderr or ENV
        verified = False
    return {
        "version": "boca-worker-recovery-v1",
        "attempt": target.attempt,
        "probe_id": target.cid,
        "legacy_id": target.legacy_id,
        "cleanup": "VERIFIED" if verified else "INDETERMINATE" if attempts else "NO_GO_PRECHECK",
        "phase": phase,
        "docker_writes": attempts,
        "foreign_resources_touched": False,
        "cutover_authorized": False,
        "retry_authorized": False,
        "original": "RUNNING_HEALTHY" if verified else "UNVERIFIED",
    }


def verify_runner(raw: bytes, target: RecoveryTarget = TARGET_795) -> dict[str, Any]:
    _known_target(target)
    if not 0 < len(raw) <= 1024:
        raise RecoveryError("RECEIPT_BOUNDS")
    record = json.loads(raw.decode("ascii"), object_pairs_hook=_unique_pairs)
    if (
        type(record) is not dict
        or set(record) != RECEIPT_KEYS
        or record["version"] != "boca-worker-recovery-v1"
        or record["attempt"] != target.attempt
        or record["probe_id"] != target.cid
        or record["legacy_id"] != target.legacy_id
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
        host_targets = {
            "host": TARGET_795,
            "host-807": TARGET_807,
            "host-819": TARGET_819,
            "host-827": TARGET_827,
        }
        verify_targets = {
            "verify": TARGET_795,
            "verify-807": TARGET_807,
            "verify-819": TARGET_819,
            "verify-827": TARGET_827,
        }
        if len(args) == 1 and args[0] in host_targets:
            result = execute(host_targets[args[0]])
            sys.stdout.buffer.write(observer.canonical(result) + b"\n")
            return 0 if result["cleanup"] == "VERIFIED" else 3
        if len(args) == 2 and args[0] in verify_targets:
            with Path(args[1]).open("rb") as file:
                verify_runner(file.read(1025), verify_targets[args[0]])
            print("BOCA_WORKER_RECOVERY_VERIFIED")
            return 0
    except (OSError, ValueError, TypeError, UnicodeError):
        pass
    print("BOCA_WORKER_RECOVERY state=NO_GO", file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
