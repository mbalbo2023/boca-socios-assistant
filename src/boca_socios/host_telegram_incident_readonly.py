"""Fixed R304 read-only incident observation."""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Sequence
from typing import Any

from boca_socios import host_boca_binding_observe as binding
from boca_socios import host_boca_cleanup as cleanup
from boca_socios.telegram_maintenance_contract import MOUNTS

INCIDENT = "43705714873"
SOURCE = "845f31abfb1762dff27e6fc3274fcc40507f3f18"
APPLY = "43704768556"
CONTROLLER = "b0dd0fed57c55dbdeb9a6e833d913cb86c0868ae1587394a934450342114bfa1"
WORKER = "c9c882ff12666fb6cac130879925879cfc0c5c23173a843434adee96b4339dce"
IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:9fc622a3a7165ce03d1113b5f7f334d402a0dad0c6cbfe2da28075843d11bea0"
BROWSER = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:1a59e0b0cb5eb3621820aed635364076542b691fa6e9c73c0e344f09dacc3abe"
PREFIX = b"BOCA_TELEGRAM_INCIDENT_READONLY_V1 "
MAX_RECEIPT = 4096
MAX_FIELD = 8192
_HEX = re.compile(r"[a-f0-9]{64}\Z")
_SHA = re.compile(r"[a-f0-9]{40}\Z")
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_HELPER = re.compile(r"/boca-socios-telegram-maint-43705714873-[a-f0-9]{16}\Z")
_NAMES = {CONTROLLER: "/boca-socios-controller-1", WORKER: "/boca-socios-browser-worker-1"}
_PREPARE = frozenset(
    {"verify-schema", "owner-identity", "initialize-volume", "prepare", "publish-recipient"}
)
_STATUS = frozenset({"created", "running", "exited", "paused", "restarting", "dead", "removing"})
_HEALTH = frozenset({"NONE", "healthy", "unhealthy", "starting"})
_REASONS = {
    "identity": {"NAME_MISMATCH", "IMAGE_MISMATCH", "PROJECT_MISMATCH"},
    "command": {
        "MODULE_MISMATCH",
        "ARGV_MISMATCH",
        "UNKNOWN_OPERATION",
        "OPERATION_OUTSIDE_PREPARE",
    },
    "uid": {"UID_MISMATCH"},
    "caps": {"CAPDROP_MISMATCH", "CAPADD_MISMATCH"},
    "mounts": {
        "COUNT_MISMATCH",
        "SOURCE_MISMATCH",
        "TARGET_MISMATCH",
        "MODE_MISMATCH",
        "DRIVER_MISMATCH",
    },
    "network": {"MODE_MISMATCH", "ATTACHMENT_MISMATCH", "PORTS_PRESENT"},
    "resources": {"CPU_MISMATCH", "MEMORY_MISMATCH", "PIDS_MISMATCH"},
    "security": {
        "ROOTFS_WRITABLE",
        "PRIVILEGED",
        "NO_NEW_PRIVILEGES_MISSING",
        "RESTART_POLICY_MISMATCH",
        "LOG_DRIVER_MISMATCH",
    },
}
_PHASES = {"INPUT", "DAEMON", "BINDING", "INVENTORY", "FIELD", "DRIFT"}
_FAILURES = {"UNVERIFIED", "AMBIGUOUS", "MALFORMED", "MISSING", "OVERSIZED", "CHANGED"}
# Literal templates only; no caller fields.
_TEMPLATES = {
    "Id": "{{json .Id}}",
    "Name": "{{json .Name}}",
    "Image": "{{json .Image}}",
    "Config.Image": "{{json .Config.Image}}",
    "Config.User": "{{json .Config.User}}",
    "Config.Cmd": "{{json .Config.Cmd}}",
    "project": '{{json (index .Config.Labels "com.docker.compose.project")}}',
    "service": '{{json (index .Config.Labels "com.docker.compose.service")}}',
    "revision": '{{json (index .Config.Labels "org.opencontainers.image.revision")}}',
    "config": '{{json (index .Config.Labels "com.docker.compose.config-hash")}}',
    "attempt": '{{json (index .Config.Labels "boca.socios.browser-ipc-attempt")}}',
    "State.Status": "{{json .State.Status}}",
    "State.Running": "{{json .State.Running}}",
    "State.Restarting": "{{json .State.Restarting}}",
    "State.Pid": "{{json .State.Pid}}",
    "State.ExitCode": "{{json .State.ExitCode}}",
    "State.OOMKilled": "{{json .State.OOMKilled}}",
    "State.Health.Status": "{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}}",
    "HostConfig.NetworkMode": "{{json .HostConfig.NetworkMode}}",
    "HostConfig.ReadonlyRootfs": "{{json .HostConfig.ReadonlyRootfs}}",
    "HostConfig.Privileged": "{{json .HostConfig.Privileged}}",
    "HostConfig.LogConfig.Type": "{{json .HostConfig.LogConfig.Type}}",
    "HostConfig.CapDrop": "{{json .HostConfig.CapDrop}}",
    "HostConfig.CapAdd": "{{json .HostConfig.CapAdd}}",
    "HostConfig.PidsLimit": "{{json .HostConfig.PidsLimit}}",
    "HostConfig.Memory": "{{json .HostConfig.Memory}}",
    "HostConfig.NanoCpus": "{{json .HostConfig.NanoCpus}}",
    "HostConfig.PublishAllPorts": "{{json .HostConfig.PublishAllPorts}}",
    "HostConfig.PortBindings": "{{json .HostConfig.PortBindings}}",
    "HostConfig.RestartPolicy.Name": "{{json .HostConfig.RestartPolicy.Name}}",
    "HostConfig.SecurityOpt": "{{json .HostConfig.SecurityOpt}}",
    "Mounts": "{{json .Mounts}}",
    "NetworkSettings.Networks": "{{json .NetworkSettings.Networks}}",
}
_STATE_FIELDS = tuple(key for key in _TEMPLATES if key.startswith("State."))
_STATE_KEYS = ("status", "running", "restarting", "pid", "exit_code", "oom", "health")
_HELPER_FIELDS = (
    "Config.User",
    "Config.Cmd",
    *tuple(key for key in _TEMPLATES if key.startswith("HostConfig.")),
    "Mounts",
    "NetworkSettings.Networks",
)
_VOLUME = re.compile(r"boca-socios_boca_(data|owner|telegram)\Z")


class NoGo(ValueError):
    def __init__(self, phase: str, reason: str = "UNVERIFIED") -> None:
        self.phase, self.reason = phase, reason
        super().__init__("incident_observation_unverified")


def _unique(entries: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in entries:
        if key in result:
            raise ValueError("duplicate")
        result[key] = value
    return result


def _json(raw: str) -> Any:
    if type(raw) is not str or not 0 < len(raw.encode("utf-8")) <= MAX_FIELD:
        raise NoGo("FIELD", "OVERSIZED")
    try:
        return json.loads(
            raw,
            object_pairs_hook=_unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("constant")),
        )
    except (ValueError, UnicodeError, RecursionError):
        raise NoGo("FIELD", "MALFORMED") from None


def _field(cid: str, field: str) -> Any:
    return _json(cleanup._docker("inspect", "--format", _TEMPLATES[field], cid))


def _bound(value: Any, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _state(record: dict[str, Any]) -> dict[str, Any]:
    value = {key: record[field] for key, field in zip(_STATE_KEYS, _STATE_FIELDS, strict=True)}
    if value["health"] is None:
        value["health"] = "NONE"
    elif value["health"] == "NONE":
        raise NoGo("FIELD", "MALFORMED")
    try:
        _verify_state(value)
    except (ValueError, TypeError):
        raise NoGo("FIELD", "MALFORMED") from None
    return value


def _binding() -> Any:
    try:
        item = binding._read_host_binding()
        if (
            (
                item.source_sha,
                item.installation_run_id,
                item.controller_id,
                item.worker_id,
                item.controller_image,
                item.worker_image,
                item.pair.original_browser_attempt,
            )
            != (SOURCE, APPLY, CONTROLLER, WORKER, IMAGE, BROWSER, APPLY)
            or any((item.pair.sender_id, item.pair.sender_config_hash, item.pair.sender_attempt_id))
            or item.pair.sender_running is not False
        ):
            raise NoGo("BINDING")
        return item
    except Exception:
        raise NoGo("BINDING") from None


def _inventory() -> list[tuple[str, str]]:
    raw = cleanup._docker("ps", "-a", "--no-trunc", "--format", "{{.ID}} {{.Names}}")
    if type(raw) is not str or len(raw.encode("utf-8")) > MAX_FIELD:
        raise NoGo("INVENTORY", "OVERSIZED")
    items = [line.split(" ") for line in raw.splitlines()]
    if len(items) > 3 or any(len(item) != 2 or _HEX.fullmatch(item[0]) is None for item in items):
        raise NoGo("INVENTORY", "MALFORMED")
    pairs = [(cid, "/" + name) for cid, name in items]
    if len(set(cid for cid, _ in pairs)) != len(pairs) or len(
        set(name for _, name in pairs)
    ) != len(pairs):
        raise NoGo("INVENTORY", "AMBIGUOUS")
    extra = [(cid, name) for cid, name in pairs if cid not in _NAMES]
    if (
        len(extra) > 1
        or any(name != _NAMES[cid] for cid, name in pairs if cid in _NAMES)
        or any(_HELPER.fullmatch(name) is None for _, name in extra)
    ):
        raise NoGo("INVENTORY", "AMBIGUOUS")
    # Admit the whole set before inspection.
    for cid, _ in pairs:
        if _field(cid, "project") != "boca-socios":
            raise NoGo("INVENTORY", "UNVERIFIED")
    return sorted(pairs)


def _record(cid: str, name: str) -> dict[str, Any]:
    record = {
        key: _field(cid, key) for key in ("Id", "Name", "Image", "Config.Image", *_STATE_FIELDS)
    }
    if record["Id"] != cid or record["Name"] != name:
        raise NoGo("FIELD", "CHANGED")
    if (
        type(record["Image"]) is not str
        or re.fullmatch(r"sha256:[a-f0-9]{64}", record["Image"]) is None
        or type(record["Config.Image"]) is not str
    ):
        raise NoGo("FIELD", "MALFORMED")
    _state(record)
    return record


def _strings(value: Any, *, nullable: bool = False) -> bool:
    return (
        nullable
        and value is None
        or type(value) is list
        and len(value) <= 16
        and all(type(item) is str and len(item) <= 256 for item in value)
    )


def _profile(record: dict[str, Any]) -> dict[str, Any]:
    profile: dict[str, list[str]] = {key: [] for key in _REASONS}
    host = {
        key.removeprefix("HostConfig."): value
        for key, value in record.items()
        if key.startswith("HostConfig.")
    }

    def note(group: str, reason: str, bad: bool) -> None:
        if bad:
            profile[group].append(reason)

    command = record["Config.Cmd"]
    if (
        not _strings(command)
        or type(record["Config.User"]) is not str
        or len(record["Config.User"]) > 64
    ):
        raise NoGo("FIELD", "MALFORMED")
    if any(not _strings(host[key], nullable=True) for key in ("CapDrop", "CapAdd", "SecurityOpt")):
        raise NoGo("FIELD", "MALFORMED")
    for keys, required in (
        (("ReadonlyRootfs", "Privileged", "PublishAllPorts"), bool),
        (("NetworkMode", "LogConfig.Type", "RestartPolicy.Name"), str),
        (("PidsLimit", "Memory", "NanoCpus"), int),
    ):
        if any(
            type(host[key]) is not required or required is str and len(host[key]) > 256
            for key in keys
        ):
            raise NoGo("FIELD", "MALFORMED")
    mounts, networks, ports = (
        record["Mounts"],
        record["NetworkSettings.Networks"],
        host["PortBindings"],
    )
    if (
        type(mounts) is not list
        or len(mounts) > 8
        or type(networks) is not dict
        or len(networks) > 8
        or ports is not None
        and (type(ports) is not dict or len(ports) > 8)
    ):
        raise NoGo("FIELD", "MALFORMED")
    for mount in mounts:
        if (
            type(mount) is not dict
            or any(type(mount.get(key)) is not str for key in ("Type", "Source", "Destination"))
            or type(mount.get("RW")) is not bool
        ):
            raise NoGo("FIELD", "MALFORMED")
    operation = (
        command[3]
        if len(command) == 4 and command[:3] == ["python", "-m", "boca_socios.telegram_maintenance"]
        else "UNKNOWN"
    )
    known = operation in _PREPARE
    note(
        "command",
        "MODULE_MISMATCH",
        len(command) >= 3 and command[2] != "boca_socios.telegram_maintenance",
    )
    note("command", "ARGV_MISMATCH", not known and operation not in MOUNTS)
    note("command", "UNKNOWN_OPERATION", operation not in MOUNTS)
    note("command", "OPERATION_OUTSIDE_PREPARE", operation in MOUNTS and not known)
    note("identity", "IMAGE_MISMATCH", record["Config.Image"] != IMAGE)
    if known:
        root = operation == "initialize-volume"
        note("uid", "UID_MISMATCH", record["Config.User"] != ("0:0" if root else "10001:10001"))
        note("caps", "CAPDROP_MISMATCH", host["CapDrop"] != ["ALL"])
        note(
            "caps",
            "CAPADD_MISMATCH",
            host["CapAdd"] not in ((["CHOWN"],) if root else (None, [])),
        )
        expected = MOUNTS[operation]
        note("mounts", "COUNT_MISMATCH", len(mounts) != len(expected))
        volume_names = cleanup._names(
            "volume", "ls", "-q", "--filter", "label=com.docker.compose.project=boca-socios"
        )
        sources = {}
        for volume, _, _ in expected:
            name = "boca-socios_" + volume
            if _VOLUME.fullmatch(name) is None or name not in volume_names:
                raise NoGo("FIELD", "MISSING")
            sources[name] = _json(
                cleanup._docker("volume", "inspect", "--format", "{{json .Mountpoint}}", name)
            )
            if sources[name] != "/home/boca-deploy/.local/share/docker/volumes/" + name + "/_data":
                raise NoGo("FIELD", "UNVERIFIED")
        record["volume_sources"] = sources
        by_target = {target: ("boca-socios_" + volume, rw) for volume, target, rw in expected}
        for mount in mounts:
            target = by_target.get(mount["Destination"])
            note("mounts", "TARGET_MISMATCH", target is None)
            note(
                "mounts",
                "DRIVER_MISMATCH",
                mount["Type"] != "volume" or mount.get("Driver") != "local",
            )
            if target is not None:
                name, rw = target
                note(
                    "mounts",
                    "SOURCE_MISMATCH",
                    mount.get("Name") != name or mount["Source"] != sources[name],
                )
                note("mounts", "MODE_MISMATCH", mount["RW"] is not rw)
        note("network", "MODE_MISMATCH", host["NetworkMode"] != "none")
        note("network", "ATTACHMENT_MISMATCH", bool(set(networks) - {"none"}))
        note(
            "network",
            "PORTS_PRESENT",
            host["PublishAllPorts"] or ports not in (None, {}),
        )
        for group, key, reason, expected_value in (
            ("resources", "NanoCpus", "CPU_MISMATCH", 250000000),
            ("resources", "Memory", "MEMORY_MISMATCH", 67108864),
            ("resources", "PidsLimit", "PIDS_MISMATCH", 16),
            ("security", "ReadonlyRootfs", "ROOTFS_WRITABLE", True),
            ("security", "Privileged", "PRIVILEGED", False),
            ("security", "RestartPolicy.Name", "RESTART_POLICY_MISMATCH", "no"),
            ("security", "LogConfig.Type", "LOG_DRIVER_MISMATCH", "none"),
        ):
            note(group, reason, host[key] != expected_value)
        note(
            "security",
            "NO_NEW_PRIVILEGES_MISSING",
            host["SecurityOpt"] not in (["no-new-privileges"], ["no-new-privileges:true"]),
        )
    for group in profile:
        profile[group] = sorted(set(profile[group])) or (
            ["UNVERIFIED"] if not known and group not in {"identity", "command"} else ["MATCH"]
        )
    caps = host["CapAdd"]
    return {
        "operation": operation
        if known
        else "OUTSIDE_PREPARE"
        if operation in MOUNTS
        else "UNKNOWN",
        "profile": profile,
        "cap_add_observed": "ABSENT"
        if caps in (None, [])
        else "CHOWN"
        if caps == ["CHOWN"]
        else "CAP_CHOWN"
        if caps == ["CAP_CHOWN"]
        else "OTHER",
    }


def _snapshot() -> dict[str, Any]:
    try:
        daemon = cleanup._rootless_docker_disk_inodes()
    except Exception:
        raise NoGo("DAEMON") from None
    item = _binding()
    pairs = _inventory()
    services = {cid: {"cid": cid, "presence": "ABSENT"} for cid in _NAMES}
    records = {}
    helper: dict[str, Any] = {"presence": "ABSENT"}
    for cid, name in pairs:
        record = _record(cid, name)
        records[cid] = record
        if cid in _NAMES:
            labels = {key: _field(cid, key) for key in ("service", "revision", "config", "attempt")}
            record["labels"] = labels
            config = (
                item.pair.controller_config_hash
                if cid == CONTROLLER
                else item.pair.worker_config_hash
            )
            matched = record["Config.Image"] == (
                IMAGE if cid == CONTROLLER else BROWSER
            ) and labels == {
                "service": "controller" if cid == CONTROLLER else "browser-worker",
                "revision": SOURCE,
                "config": config,
                "attempt": APPLY,
            }
            services[cid] = {
                "cid": cid,
                "presence": "PRESENT",
                "identity": "MATCH" if matched else "MISMATCH",
                **_state(record),
            }
        else:
            for key in _HELPER_FIELDS:
                record[key] = _field(cid, key)
            helper = {
                "presence": "PRESENT",
                "cid": cid,
                **_state(record),
                **_profile(record),
            }
    if _binding() != item:
        raise NoGo("DRIFT", "CHANGED")
    return {
        "daemon": daemon[2:],
        "binding": item,
        "records": records,
        "services": [services[cid] for cid in sorted(services)],
        "helper": helper,
    }


def _canonical(value: dict[str, Any]) -> bytes:
    return (
        PREFIX
        + json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")
        + b"\n"
    )


def _base(run_id: str, workflow_sha: str) -> dict[str, Any]:
    return {
        "version": 1,
        "observation_run_id": run_id,
        "workflow_sha": workflow_sha,
        "incident_run_id": INCIDENT,
        "source_sha": SOURCE,
        "installation_run_id": APPLY,
        "observer_writes": 0,
        "engine": "UNVERIFIED",
        "restore_authorized": False,
        "cleanup_authorized": False,
        "deploy_authorized": False,
    }


def observe(run_id: str, workflow_sha: str) -> bytes:
    value: dict[str, Any] = {
        **_base(run_id, workflow_sha),
        "state": "INCOMPLETE_NO_GO",
        "phase": "INPUT",
        "reason": "UNVERIFIED",
        "services": [],
        "helper": {"presence": "UNVERIFIED"},
    }
    try:
        if (
            _RUN.fullmatch(run_id) is None
            or _SHA.fullmatch(workflow_sha) is None
            or (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (10001,) * 4
        ):
            raise NoGo("INPUT")
        first, second = _snapshot(), _snapshot()
        if first != second:
            raise NoGo("DRIFT", "CHANGED")
        value.update(
            state="OBSERVED_NO_GO",
            phase="COMPLETE",
            reason="NONE",
            services=first["services"],
            helper=first["helper"],
        )
    except NoGo as error:
        value.update(phase=error.phase, reason=error.reason)
    except Exception:
        value.update(phase="FIELD", reason="UNVERIFIED")
    raw = _canonical(value)
    return verify(raw, run_id, workflow_sha)


def _verify_state(value: dict[str, Any]) -> None:
    if (
        value["status"] not in _STATUS
        or type(value["status"]) is not str
        or value["health"] not in _HEALTH
        or type(value["health"]) is not str
        or any(type(value[key]) is not bool for key in ("running", "restarting", "oom"))
        or not _bound(value["pid"], 0, 2147483647)
        or not _bound(value["exit_code"], -1, 255)
    ):
        raise ValueError("state")


def _verify_helper(helper: dict[str, Any]) -> None:
    if helper == {"presence": "ABSENT"}:
        return
    if (
        set(helper)
        != set(_STATE_KEYS) | {"presence", "cid", "operation", "profile", "cap_add_observed"}
        or helper["presence"] != "PRESENT"
        or type(helper["cid"]) is not str
        or _HEX.fullmatch(helper["cid"]) is None
        or helper["cid"] in _NAMES
        or helper["operation"] not in _PREPARE | {"UNKNOWN", "OUTSIDE_PREPARE"}
        or helper["cap_add_observed"] not in {"ABSENT", "CHOWN", "CAP_CHOWN", "OTHER"}
    ):
        raise ValueError("helper")
    _verify_state(helper)
    profile = helper["profile"]
    if type(profile) is not dict or set(profile) != set(_REASONS):
        raise ValueError("profile")
    for key, reasons in profile.items():
        if (
            type(reasons) is not list
            or not 1 <= len(reasons) <= 5
            or any(
                type(reason) is not str or reason not in _REASONS[key] | {"MATCH", "UNVERIFIED"}
                for reason in reasons
            )
            or reasons != sorted(set(reasons))
            or len(reasons) > 1
            and ("MATCH" in reasons or "UNVERIFIED" in reasons)
        ):
            raise ValueError("reasons")
    known = helper["operation"] in _PREPARE
    if any(
        "UNVERIFIED" in reasons
        if known or key in {"identity", "command"}
        else reasons != ["UNVERIFIED"]
        for key, reasons in profile.items()
    ):
        raise ValueError("unrecognized")


def verify(raw: bytes, run_id: str, workflow_sha: str) -> bytes:
    try:
        if (
            type(raw) is not bytes
            or not 0 < len(raw) <= MAX_RECEIPT
            or not raw.startswith(PREFIX)
            or not raw.endswith(b"\n")
        ):
            raise ValueError("frame")
        value = json.loads(raw[len(PREFIX) :], object_pairs_hook=_unique)
        base = _base(run_id, workflow_sha)
        if (
            set(value) != set(base) | {"state", "phase", "reason", "services", "helper"}
            or any(
                type(value[key]) is not type(expected) or value[key] != expected
                for key, expected in base.items()
            )
            or _RUN.fullmatch(run_id) is None
            or _SHA.fullmatch(workflow_sha) is None
            or raw != _canonical(value)
        ):
            raise ValueError("coordinates")
        if value["state"] == "INCOMPLETE_NO_GO":
            if (
                value["phase"] not in _PHASES
                or value["reason"] not in _FAILURES
                or value["services"] != []
                or value["helper"] != {"presence": "UNVERIFIED"}
            ):
                raise ValueError("incomplete")
        elif value["state"] == "OBSERVED_NO_GO":
            if (
                value["phase"] != "COMPLETE"
                or value["reason"] != "NONE"
                or type(value["services"]) is not list
                or len(value["services"]) != 2
                or [item["cid"] for item in value["services"]] != sorted(_NAMES)
            ):
                raise ValueError("complete")
            for item in value["services"]:
                if item == {"cid": item["cid"], "presence": "ABSENT"}:
                    continue
                if (
                    set(item) != set(_STATE_KEYS) | {"cid", "presence", "identity"}
                    or item["presence"] != "PRESENT"
                    or item["identity"] not in {"MATCH", "MISMATCH"}
                ):
                    raise ValueError("service")
                _verify_state(item)
            _verify_helper(value["helper"])
        else:
            raise ValueError("class")
        return raw
    except Exception:
        raise ValueError("telegram_incident_receipt_unverified") from None


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(args) != 3 or args[0] not in {"host", "verify"}:
            raise ValueError("arguments")
        if args[0] == "host":
            raw = observe(args[1], args[2])
        else:
            raw = verify(sys.stdin.buffer.read(MAX_RECEIPT + 1), args[1], args[2])
        sys.stdout.buffer.write(raw)
        return 0 if json.loads(raw[len(PREFIX) :])["state"] == "OBSERVED_NO_GO" else 3
    except Exception:
        sys.stdout.buffer.write(
            b"BOCA_TELEGRAM_INCIDENT_READONLY_V1 state=INCOMPLETE_NO_GO phase=INPUT reason=UNVERIFIED observer_writes=0\n"
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
