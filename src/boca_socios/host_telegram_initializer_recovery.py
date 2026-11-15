"""One fixed Telegram initializer recovery; uncertainty never retries an effect."""

from __future__ import annotations

import json
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_telegram_incident_readonly as incident
from boca_socios.host_lifecycle_rootless_adapter import _mounts, panel_control_mount

HELPER = "ba6699b977623135224e0ab6de8a26a882cecda8bfa819458deace75cb282367"
OBSERVATION = "43725809501"
PREFIX = b"BOCA_TELEGRAM_INITIALIZER_RECOVERY_V1 "
MAX_RECEIPT = 4096
MAX_PIPE = 1024
_VOLUME = "boca-socios_boca_telegram"
_VOLUME_ROOT = "/home/boca-deploy/.local/share/docker/volumes/"
_ZERO = "0001-01-01T00:00:00Z"
_PAYLOAD = b'{"new_empty_volume":"boca-socios_boca_telegram"}'
_RESPONSE = b'{"initialized":true}'
_EXTRA = {
    "Config.Entrypoint": "{{json .Config.Entrypoint}}",
    "Config.WorkingDir": "{{json .Config.WorkingDir}}",
    "Config.OpenStdin": "{{json .Config.OpenStdin}}",
    "Config.Tty": "{{json .Config.Tty}}",
    "State.StartedAt": "{{json .State.StartedAt}}",
    "State.FinishedAt": "{{json .State.FinishedAt}}",
}
_VOLUME_FIELDS = {
    "Name": "{{json .Name}}",
    "Driver": "{{json .Driver}}",
    "Scope": "{{json .Scope}}",
    "Options": "{{json .Options}}",
    "Mountpoint": "{{json .Mountpoint}}",
    "project": '{{json (index .Labels "com.docker.compose.project")}}',
    "volume": '{{json (index .Labels "com.docker.compose.volume")}}',
}
_PAIR_MOUNTS = {
    incident.CONTROLLER: frozenset(
        {
            ("boca-socios_boca_data", "/data", True),
            ("boca-socios_boca_key", "/run/secrets", False),
            ("boca-socios_boca_owner", "/run/owner", False),
            ("boca-socios_boca_browser_ipc", "/run/boca-browser-ipc", False),
            ("boca-socios_boca_site_config", "/run/boca-site-config", True),
        }
    ),
    incident.WORKER: frozenset(
        {
            ("boca-socios_boca_browser_ipc", "/run/boca-browser-ipc", True),
            ("boca-socios_boca_site_config", "/run/boca-site-config", False),
        }
    ),
}


def _coordinates(run_id: str, workflow_sha: str) -> None:
    if (
        type(run_id) is not str
        or re.fullmatch(r"[1-9][0-9]{0,19}", run_id) is None
        or type(workflow_sha) is not str
        or re.fullmatch(r"[a-f0-9]{40}", workflow_sha) is None
    ):
        raise ValueError("recovery_coordinates_unverified")


def _canonical(value: dict[str, Any]) -> bytes:
    return (
        PREFIX
        + json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")
        + b"\n"
    )


def _base(run_id: str, workflow_sha: str) -> dict[str, Any]:
    return {
        "version": 1,
        "operation": "initialize-and-retire",
        "recovery_run_id": run_id,
        "workflow_sha": workflow_sha,
        "observation_run_id": OBSERVATION,
        "incident_run_id": incident.INCIDENT,
        "source_sha": incident.SOURCE,
        "installation_run_id": incident.APPLY,
        "helper_cid": HELPER,
        "engine": "UNVERIFIED",
    }


def _metric(value: object) -> dict[str, int]:
    if (
        type(value) is not tuple
        or len(value) != 4
        or any(type(number) is not int or not 0 <= number <= 2**63 - 1 for number in value)
    ):
        raise ValueError("recovery_metrics_unverified")
    return dict(zip(("bytes_free", "inodes_free", "device", "inode"), value, strict=True))


def _verify_metric(value: object) -> None:
    if type(value) is not dict or set(value) != {"bytes_free", "inodes_free", "device", "inode"}:
        raise ValueError("recovery_metrics_unverified")
    _metric(tuple(value[key] for key in ("bytes_free", "inodes_free", "device", "inode")))


def verify(raw: bytes, run_id: str, workflow_sha: str) -> bytes:
    try:
        _coordinates(run_id, workflow_sha)
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_RECEIPT or not raw.startswith(PREFIX):
            raise ValueError("frame")
        value = json.loads(raw[len(PREFIX) :], object_pairs_hook=incident._unique)
        base = _base(run_id, workflow_sha)
        if (
            type(value) is not dict
            or set(value)
            != set(base)
            | {
                "state",
                "phase",
                "initialization",
                "retirement",
                "pair_state",
                "sender_state",
                "disk_before",
                "disk_after",
            }
            or any(
                type(value[key]) is not type(expected) or value[key] != expected
                for key, expected in base.items()
            )
        ):
            raise ValueError("coordinates")
        if raw != _canonical(value):
            raise ValueError("canonical")
        phase, before, after = value["phase"], value["disk_before"], value["disk_after"]
        combination = tuple(
            value[key]
            for key in (
                "state",
                "phase",
                "initialization",
                "retirement",
                "pair_state",
                "sender_state",
            )
        )
        allowed = (
            {
                ("NO_GO", p, "NOT_ATTEMPTED", "NOT_ATTEMPTED", "UNVERIFIED", "UNVERIFIED")
                for p in ("INPUT", "PREFLIGHT")
            }
            | {
                ("NO_GO", p, "INDETERMINATE", "NOT_ATTEMPTED", "UNVERIFIED", "UNVERIFIED")
                for p in ("START", "VERIFY_INITIALIZATION")
            }
            | {
                ("NO_GO", "RETIRE", "ACCEPTED", r, "UNVERIFIED", "UNVERIFIED")
                for r in ("NOT_ATTEMPTED", "INDETERMINATE")
            }
            | {
                ("NO_GO", "POSTFLIGHT", "ACCEPTED", r, "UNVERIFIED", "UNVERIFIED")
                for r in ("INDETERMINATE", "RETIRED")
            }
            | {
                (
                    "ACCEPTED",
                    "COMPLETE",
                    "ACCEPTED",
                    "RETIRED",
                    "UNCHANGED_HEALTHY_WORKER_STOPPED",
                    "OFF",
                )
            }
        )
        if any(type(item) is not str for item in combination) or combination not in allowed:
            raise ValueError("state")
        for metric in (before, after):
            if metric is not None:
                _verify_metric(metric)
        if (
            phase == "INPUT"
            and (before is not None or after is not None)
            or phase not in {"INPUT", "PREFLIGHT"}
            and before is None
            or phase not in {"POSTFLIGHT", "COMPLETE"}
            and after is not None
            or phase == "COMPLETE"
            and (after is None or any(before[key] != after[key] for key in ("device", "inode")))
        ):
            raise ValueError("metrics")
        return raw
    except Exception:
        raise ValueError("telegram_initializer_receipt_unverified") from None


def _extra() -> dict[str, Any]:
    return {
        key: incident._json(cleanup._docker("inspect", "--format", template, HELPER))
        for key, template in _EXTRA.items()
    }


def _path(path: str) -> tuple[int, int]:
    target = Path(path)
    if target.resolve(strict=True) != target:
        raise ValueError("recovery_path_redirected")
    metadata = target.lstat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("recovery_path_unverified")
    return metadata.st_dev, metadata.st_ino


def _volume() -> dict[str, Any]:
    value = {
        key: incident._json(cleanup._docker("volume", "inspect", "--format", template, _VOLUME))
        for key, template in _VOLUME_FIELDS.items()
    }
    if any(
        value[key] != expected
        for key, expected in {
            "Name": _VOLUME,
            "Driver": "local",
            "Scope": "local",
            "project": "boca-socios",
            "volume": "boca_telegram",
            "Mountpoint": _VOLUME_ROOT + _VOLUME + "/_data",
        }.items()
    ) or value["Options"] not in (None, {}):
        raise ValueError("recovery_volume_unverified")
    value["identity"] = _path(value["Mountpoint"])
    return value


def _mount_witnesses() -> dict[str, Any]:
    values: dict[str, Any] = {}
    control = panel_control_mount()
    for cid, expected in _PAIR_MOUNTS.items():
        source = control if cid == incident.CONTROLLER else None
        raw = incident._field(cid, "Mounts")
        if source is not None:
            expected = expected | {(source, "/run/boca-bot-control", False)}
        if _mounts(raw, control_source=source) != expected:
            raise ValueError("recovery_mount_contract_unverified")
        raw = sorted(raw, key=lambda item: item["Destination"])
        identities = []
        for item in raw:
            actual = item.get("Source")
            wanted = control if item["Type"] == "bind" else _VOLUME_ROOT + item["Name"] + "/_data"
            if type(actual) is not str or actual != wanted:
                raise ValueError("recovery_mount_source_unverified")
            identities.append((actual, _path(actual)))
        values[cid] = (raw, identities)
    return values


def _timestamp(value: object) -> datetime:
    if (
        type(value) is not str
        or value == _ZERO
        or re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:[.][0-9]{1,9})?Z", value
        )
        is None
    ):
        raise ValueError("recovery_timestamp_unverified")
    return datetime.fromisoformat(value)


def _snapshot(expected_helper: str) -> dict[str, Any]:
    value = incident._snapshot()
    expected_ids = {incident.CONTROLLER, incident.WORKER}
    if expected_helper != "absent":
        expected_ids.add(HELPER)
    if set(value["records"]) != expected_ids:
        raise ValueError("recovery_topology_unverified")
    for service in value["services"]:
        controller = service["cid"] == incident.CONTROLLER
        if (
            service["presence"] != "PRESENT"
            or service["identity"] != "MATCH"
            or service["status"] != ("running" if controller else "created")
            or service["running"] is not controller
            or service["restarting"] is not False
            or service["oom"] is not False
            or service["exit_code"] != 0
            or service["health"] != ("healthy" if controller else "NONE")
            or (service["pid"] <= 0 if controller else service["pid"] != 0)
        ):
            raise ValueError("recovery_pair_unverified")
    value["mounts"] = _mount_witnesses()
    value["volume"] = _volume()
    if value["volume"]["identity"] in {
        identity for _, sources in value["mounts"].values() for _, identity in sources
    }:
        raise ValueError("recovery_telegram_volume_alias")
    if expected_helper == "absent":
        if value["helper"] != {"presence": "ABSENT"}:
            raise ValueError("recovery_helper_still_present")
        return value
    helper, record = value["helper"], value["records"][HELPER]
    if (
        helper["cid"] != HELPER
        or helper["presence"] != "PRESENT"
        or helper["operation"] != "initialize-volume"
        or helper["status"] != expected_helper
        or helper["running"] is not False
        or helper["restarting"] is not False
        or helper["oom"] is not False
        or helper["exit_code"] != 0
        or helper["pid"] != 0
        or expected_helper == "created"
        and helper["health"] != "NONE"
        or helper["cap_add_observed"] != "CAP_CHOWN"
        or helper["profile"]
        != {key: ["CAPADD_MISMATCH" if key == "caps" else "MATCH"] for key in incident._REASONS}
        or record["HostConfig.CapAdd"] != ["CAP_CHOWN"]
        or record["HostConfig.CapDrop"] != ["ALL"]
        or record["Config.Image"] != incident.IMAGE
        or record["Image"] != value["records"][incident.CONTROLLER]["Image"]
    ):
        raise ValueError("recovery_helper_unverified")
    extra = _extra()
    if (
        extra["Config.Entrypoint"] not in (None, [])
        or extra["Config.WorkingDir"] != "/app"
        or extra["Config.OpenStdin"] is not True
        or extra["Config.Tty"] is not False
    ):
        raise ValueError("recovery_execution_unverified")
    started, finished = extra["State.StartedAt"], extra["State.FinishedAt"]
    if expected_helper == "created":
        if started != _ZERO or finished != _ZERO:
            raise ValueError("recovery_already_started")
    elif _timestamp(finished) < _timestamp(started):
        raise ValueError("recovery_timestamp_unverified")
    value["extra"] = extra
    return value


def _unchanged(first: dict[str, Any], later: dict[str, Any], *, helper: bool) -> None:
    if any(
        first[key] != later[key] for key in ("daemon", "binding", "services", "mounts", "volume")
    ) or any(
        first["records"][cid] != later["records"][cid]
        for cid in (incident.CONTROLLER, incident.WORKER)
    ):
        raise ValueError("recovery_pair_or_volume_changed")
    if helper:

        def stable(record: dict[str, Any]) -> dict[str, Any]:
            return {
                key: value
                for key, value in record.items()
                if not key.startswith("State.") and key != "NetworkSettings.Networks"
            }

        if stable(first["records"][HELPER]) != stable(later["records"][HELPER]) or stable(
            first["extra"]
        ) != stable(later["extra"]):
            raise ValueError("recovery_helper_profile_changed")


def _recheck(lease: cleanup.BocaJobLease, run_id: str, snapshot: dict[str, Any]) -> None:
    cleanup.verify_protected_boca_job_lease(lease, run_id)
    if incident._binding() != snapshot["binding"]:
        raise ValueError("recovery_binding_changed")
    for field in ("State.Status", "State.Running", "State.Restarting", "State.Pid"):
        if incident._field(HELPER, field) != snapshot["records"][HELPER][field]:
            raise ValueError("recovery_helper_state_changed")
    if _extra() != snapshot["extra"]:
        raise ValueError("recovery_helper_execution_changed")


def _start() -> tuple[int, bytes, bytes]:
    """Bound both pipes while acquiring them; kill only the local Docker client."""
    child = subprocess.Popen(  # noqa: S603 - fixed exact-CID initializer and private pipe
        [
            "/usr/bin/docker",
            "--host",
            cleanup.DOCKER_SOCKET,
            "start",
            "--attach",
            "--interactive",
            HELPER,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        env={
            "DOCKER_HOST": cleanup.DOCKER_SOCKET,
            "XDG_RUNTIME_DIR": "/run/user/10001",
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
        },
    )
    try:
        assert child.stdin is not None and child.stdout is not None and child.stderr is not None
        deadline = monotonic() + 30
        if child.stdin.write(_PAYLOAD) != len(_PAYLOAD):
            raise ValueError("recovery_input_uncertain")
        child.stdin.close()
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ, "stdout")
            selector.register(child.stderr, selectors.EVENT_READ, "stderr")
            while selector.get_map():
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError("recovery_client_timeout")
                for key, _ in selector.select(remaining):
                    buffer = buffers[key.data]
                    chunk = os.read(key.fd, min(512, MAX_PIPE + 1 - len(buffer)))
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    buffer.extend(chunk)
                    if len(buffer) > MAX_PIPE:
                        raise ValueError("recovery_private_pipe_oversized")
        code = child.wait(timeout=max(0, deadline - monotonic()))
        return code, bytes(buffers["stdout"]), bytes(buffers["stderr"])
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream is not None:
                stream.close()


def recover(run_id: str, workflow_sha: str) -> bytes:
    _coordinates(run_id, workflow_sha)
    value = {
        **_base(run_id, workflow_sha),
        "state": "NO_GO",
        "phase": "INPUT",
        "initialization": "NOT_ATTEMPTED",
        "retirement": "NOT_ATTEMPTED",
        "pair_state": "UNVERIFIED",
        "sender_state": "UNVERIFIED",
        "disk_before": None,
        "disk_after": None,
    }
    try:
        if (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (10001,) * 4:
            raise ValueError("recovery_rootless_identity_required")
        value["phase"] = "PREFLIGHT"
        with cleanup.protected_boca_job_lease(run_id) as lease:
            cleanup.verify_protected_boca_job_lease(lease, run_id)
            before = _metric(cleanup._rootless_docker_disk_inodes())
            value["disk_before"] = before
            first, second = _snapshot("created"), _snapshot("created")
            if first != second or first["daemon"] != (before["device"], before["inode"]):
                raise ValueError("recovery_snapshot_changed")
            _recheck(lease, run_id, second)
            value.update(phase="START", initialization="INDETERMINATE")
            result = _start()
            value["phase"] = "VERIFY_INITIALIZATION"
            if result != (0, _RESPONSE, b""):
                raise ValueError("recovery_initialization_unverified")
            initialized = _snapshot("exited")
            _unchanged(first, initialized, helper=True)
            value.update(phase="RETIRE", initialization="ACCEPTED")
            retiring = _snapshot("exited")
            if retiring != initialized:
                raise ValueError("recovery_retirement_changed")
            _recheck(lease, run_id, retiring)
            value["retirement"] = "INDETERMINATE"
            if cleanup._docker("rm", HELPER) not in (HELPER, HELPER + "\n"):
                raise ValueError("recovery_retirement_ack_uncertain")
            value["phase"] = "POSTFLIGHT"
            if incident._inventory() != sorted(incident._NAMES.items()):
                raise ValueError("recovery_retirement_unverified")
            value["retirement"] = "RETIRED"
            after_snapshot = _snapshot("absent")
            _unchanged(first, after_snapshot, helper=False)
            after = _metric(cleanup._rootless_docker_disk_inodes())
            value["disk_after"] = after
            if after_snapshot["daemon"] != (after["device"], after["inode"]):
                raise ValueError("recovery_daemon_changed")
            cleanup.verify_protected_boca_job_lease(lease, run_id)
            if incident._binding() != first["binding"]:
                raise ValueError("recovery_binding_changed")
            value.update(
                state="ACCEPTED",
                phase="COMPLETE",
                pair_state="UNCHANGED_HEALTHY_WORKER_STOPPED",
                sender_state="OFF",
            )
    except Exception:
        # Preserve facts already proved, including a failure while releasing the lease.
        if value["phase"] == "COMPLETE":
            value["phase"] = "POSTFLIGHT"
        value.update(state="NO_GO", pair_state="UNVERIFIED", sender_state="UNVERIFIED")
    return verify(_canonical(value), run_id, workflow_sha)


def _interrupted(number: int, _frame: object) -> None:
    signal.signal(number, signal.SIG_IGN)
    raise RuntimeError("recovery_transport_interrupted")


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    previous: dict[int, Any] = {}
    try:
        if len(args) != 3 or args[0] not in {"host", "verify"}:
            raise ValueError("arguments")
        _coordinates(args[1], args[2])
        if args[0] == "host":
            for number in (signal.SIGTERM, signal.SIGHUP):
                previous[number] = signal.signal(number, _interrupted)
            raw = recover(args[1], args[2])
        else:
            raw = verify(sys.stdin.buffer.read(MAX_RECEIPT + 1), args[1], args[2])
        sys.stdout.buffer.write(raw)
        return 0 if json.loads(raw[len(PREFIX) :])["state"] == "ACCEPTED" else 3
    except Exception:
        sys.stdout.buffer.write(b"BOCA_TELEGRAM_INITIALIZER_RECOVERY_V1 state=NO_GO phase=INPUT\n")
        return 2
    finally:
        for signal_number, handler in previous.items():
            signal.signal(signal_number, handler)


if __name__ == "__main__":
    raise SystemExit(main())
