"""Fail-closed validation of a resolved simulation-only Compose model."""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping
from copy import deepcopy
from typing import cast

from boca_socios.owner_origin import SSH_LOOPBACK_ORIGIN


class ContractError(ValueError):
    """The proposed deployment model exceeds the Boca-only boundary."""


_IMAGE = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
_BROWSER_IMAGE = re.compile(
    r"ghcr\.io/mbalbo2023/boca-socios-assistant-browser@sha256:[0-9a-f]{64}\Z"
)
_BROWSER_ATTEMPT = re.compile(r"[1-9][0-9]{0,19}\Z")
_BROWSER_ATTEMPT_LABEL = "boca.socios.browser-ipc-attempt"
_BROWSER_HEALTH = (
    "from boca_socios.browser.on_demand import validate_worker_boundary; "
    "from boca_socios.browser.ipc_worker import validate_no_egress_namespace; "
    "from boca_socios.browser.ipc_protocol import SOCKET_PATH, socket_identity; "
    "validate_worker_boundary(); validate_no_egress_namespace(); socket_identity(SOCKET_PATH)"
)
_SERVICE_FIELDS = {
    "image",
    "command",
    "entrypoint",
    "user",
    "init",
    "restart",
    "environment",
    "volumes",
    "networks",
    "read_only",
    "tmpfs",
    "security_opt",
    "cap_drop",
    "pids_limit",
    "mem_limit",
    "cpus",
    "healthcheck",
}


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ContractError(f"invalid {field}")
    return value


def _list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ContractError(f"invalid {field}")
    return value


def _equal(value: object, expected: object, field: str) -> None:
    if value != expected or type(value) is not type(expected):
        raise ContractError(f"invalid {field}")


def _keys(value: Mapping[str, object], expected: set[str], field: str) -> None:
    if set(value) != expected:
        missing = ",".join(sorted(expected - set(value)))
        extra = ",".join(sorted(set(value) - expected))
        raise ContractError(f"invalid {field} keys (missing={missing}; extra={extra})")


def _volume(service: Mapping[str, object]) -> None:
    mounts = _list(service.get("volumes"), "controller volumes")
    if len(mounts) != 2:
        raise ContractError("invalid controller volumes")
    for index, (source, target, read_only) in enumerate(
        (("boca_data", "/data", False), ("boca_key", "/run/secrets", True))
    ):
        mount = _mapping(mounts[index], "controller volume")
        if set(mount) - {"type", "source", "target", "read_only", "volume"}:
            raise ContractError("invalid controller volume fields")
        for key, expected in {"type": "volume", "source": source, "target": target}.items():
            _equal(mount.get(key), expected, f"controller volume {key}")
        _equal(mount.get("read_only", False), read_only, "controller volume read_only")
        if "volume" in mount and _mapping(mount["volume"], "volume options"):
            raise ContractError("invalid controller volume options")


def validate_contract(model: object, expected_image: str) -> None:
    """Reject any resolved model outside the reviewed single-service contract."""
    if not _IMAGE.fullmatch(expected_image):
        raise ContractError("invalid approved image digest")
    root = _mapping(model, "Compose model")
    _keys(root, {"name", "services", "volumes", "networks"}, "Compose")
    _equal(root["name"], "boca-socios", "Compose project")

    services = _mapping(root["services"], "services")
    _keys(services, {"controller"}, "services")
    service = _mapping(services["controller"], "controller")
    _keys(service, _SERVICE_FIELDS, "controller")
    _equal(service["command"], None, "controller command override")
    _equal(service["entrypoint"], None, "controller entrypoint override")
    for key, expected in {
        "image": expected_image,
        "user": "10001:10001",
        "init": True,
        "restart": "unless-stopped",
        "read_only": True,
        "cpus": 0.5,
        "mem_limit": "268435456",
        "pids_limit": 64,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "tmpfs": ["/tmp:rw,noexec,nosuid,size=16m"],  # noqa: S108 - container tmpfs mount
    }.items():
        _equal(service[key], expected, f"controller {key}")
    _equal(
        service["environment"],
        {
            "BOCA_ENVIRONMENT": "staging",
            "BOCA_RUNTIME_MODE": "simulation",
            "BOCA_ENGINE_MODE": "off",
            "BOCA_DB_PATH": "/data/boca.sqlite3",
            "BOCA_MASTER_KEY_FILE": "/run/secrets/boca_master_key",
        },
        "controller environment",
    )
    _volume(service)
    health = _mapping(service["healthcheck"], "controller healthcheck")
    _keys(health, {"test", "interval", "timeout", "retries", "start_period"}, "healthcheck")
    for key, expected in {
        "test": ["CMD", "python", "-m", "boca_socios.healthcheck"],
        "interval": "30s",
        "timeout": "5s",
        "retries": 3,
        "start_period": "15s",
    }.items():
        _equal(health[key], expected, f"controller healthcheck {key}")

    volumes = _mapping(root["volumes"], "volumes")
    _keys(volumes, {"boca_data", "boca_key"}, "volumes")
    for name in ("boca_data", "boca_key"):
        volume = _mapping(volumes[name], "boca volume")
        _keys(volume, {"name"}, "boca volume")
        _equal(volume["name"], f"boca-socios_{name}", "boca volume name")

    networks = _mapping(root["networks"], "networks")
    _keys(networks, {"boca_private"}, "networks")
    network = _mapping(networks["boca_private"], "boca network")
    _keys(network, {"name", "driver", "ipam"}, "boca network")
    _equal(network["name"], "boca-socios_boca_private", "boca network name")
    _equal(network["driver"], "bridge", "boca network driver")
    _equal(network["ipam"], {}, "boca network IPAM")
    _equal(service["networks"], {"boca_private": None}, "controller networks")


def validate_beta_contract(
    model: object, expected_image: str, expected_origin: str, expected_owner: str
) -> None:
    """Validate a separate served package; this does not authorize host installation."""
    if not _IMAGE.fullmatch(expected_image):
        raise ContractError("invalid approved image digest")
    if expected_origin != SSH_LOOPBACK_ORIGIN:
        raise ContractError("BETA Compose is restricted to SSH-only localhost origin")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", expected_owner):
        raise ContractError("invalid owner subject")

    root = _mapping(model, "BETA Compose model")
    _keys(root, {"name", "services", "volumes", "networks"}, "BETA Compose")
    _equal(root["name"], "boca-socios", "BETA Compose project")
    services = _mapping(root["services"], "BETA services")
    _keys(services, {"controller"}, "BETA services")
    service = _mapping(services["controller"], "BETA controller")
    _keys(service, _SERVICE_FIELDS | {"ports"}, "BETA controller")
    for key, expected in {
        "image": expected_image,
        "command": ["python", "-m", "boca_socios.runtime", "serve-beta"],
        "entrypoint": None,
        "user": "10001:10001",
        "init": True,
        "restart": "unless-stopped",
        "read_only": True,
        "cpus": 0.5,
        "mem_limit": "268435456",
        "pids_limit": 64,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "tmpfs": ["/tmp:rw,noexec,nosuid,size=16m"],  # noqa: S108 - container tmpfs mount
        "ports": [
            {
                "mode": "ingress",
                "target": 8443,
                "published": "8443",
                "host_ip": "127.0.0.1",
                "protocol": "tcp",
            }
        ],
        "networks": {"boca_private": None},
    }.items():
        _equal(service[key], expected, f"BETA controller {key}")
    _equal(
        service["environment"],
        {
            "BOCA_ENVIRONMENT": "staging",
            "BOCA_RUNTIME_MODE": "simulation",
            "BOCA_ENGINE_MODE": "off",
            "BOCA_DB_PATH": "/data/boca.sqlite3",
            "BOCA_MASTER_KEY_FILE": "/run/secrets/boca_master_key",
            "BOCA_PANEL_ORIGIN": expected_origin,
            "BOCA_OWNER_SUBJECT": expected_owner,
            "BOCA_PASSKEY_CREDENTIAL_ID_FILE": "/run/owner/credential_id",
            "BOCA_PASSKEY_PUBLIC_KEY_DER_FILE": "/run/owner/public_key.der",
            "BOCA_BIND_HOST": "0.0.0.0",  # noqa: S104 - Boca bridge; host publishes loopback only
            "BOCA_BIND_PORT": "8443",
            "BOCA_HEALTH_MODE": "beta",
        },
        "BETA controller environment",
    )
    mounts = _list(service["volumes"], "BETA volumes")
    if len(mounts) != 3:
        raise ContractError("invalid BETA volume count")
    for index, (source, target, read_only) in enumerate(
        (
            ("boca_data", "/data", False),
            ("boca_key", "/run/secrets", True),
            ("boca_owner", "/run/owner", True),
        )
    ):
        mount = _mapping(mounts[index], "BETA volume")
        if set(mount) - {"type", "source", "target", "read_only", "volume"}:
            raise ContractError("invalid BETA volume fields")
        for key, expected in {"type": "volume", "source": source, "target": target}.items():
            _equal(mount.get(key), expected, f"BETA volume {key}")
        _equal(mount.get("read_only", False), read_only, "BETA volume read_only")
        if "volume" in mount and _mapping(mount["volume"], "BETA volume options"):
            raise ContractError("invalid BETA volume options")
    health = _mapping(service["healthcheck"], "BETA healthcheck")
    _keys(health, {"test", "interval", "timeout", "retries", "start_period"}, "BETA healthcheck")
    for key, health_expected in {
        "test": ["CMD", "python", "-m", "boca_socios.healthcheck"],
        "interval": "30s",
        "timeout": "5s",
        "retries": 3,
        "start_period": "15s",
    }.items():
        _equal(health[key], health_expected, f"BETA healthcheck {key}")

    volumes = _mapping(root["volumes"], "BETA volumes")
    _keys(volumes, {"boca_data", "boca_key", "boca_owner"}, "BETA volumes")
    for name in ("boca_data", "boca_key"):
        volume = _mapping(volumes[name], "BETA volume")
        _keys(volume, {"name"}, "BETA volume")
        _equal(volume["name"], f"boca-socios_{name}", "BETA volume name")
    owner_volume = _mapping(volumes["boca_owner"], "BETA owner volume")
    _keys(owner_volume, {"name", "external"}, "BETA owner volume")
    _equal(owner_volume["name"], "boca-socios_boca_owner", "BETA owner volume name")
    _equal(owner_volume["external"], True, "BETA owner volume external")

    networks = _mapping(root["networks"], "BETA networks")
    _keys(networks, {"boca_private"}, "BETA networks")
    network = _mapping(networks["boca_private"], "BETA network")
    _keys(network, {"name", "driver", "ipam"}, "BETA network")
    _equal(network["name"], "boca-socios_boca_private", "BETA network name")
    _equal(network["driver"], "bridge", "BETA network driver")
    _equal(network["ipam"], {}, "BETA network IPAM")


def _browser_ipc_mount(mount: object, *, readonly: bool, field: str) -> None:
    """Strict, external, Boca-only AF_UNIX volume; no host bind or shared data."""
    value = _mapping(mount, field)
    if set(value) - {"type", "source", "target", "read_only", "volume"}:
        raise ContractError(f"invalid {field} options")
    for name, expected in {
        "type": "volume",
        "source": "boca_browser_ipc",
        "target": "/run/boca-browser-ipc",
        "read_only": readonly,
    }.items():
        _equal(value.get(name, False if name == "read_only" else None), expected, field)
    if "volume" in value and _mapping(value["volume"], f"{field} options"):
        raise ContractError(f"invalid {field} volume options")


def _browser_seccomp_path(path: str) -> None:
    """Exact Boca-private host path; SHA/mode/owner need a separate host gate."""
    if type(path) is not str or path != "/srv/boca-socios/seccomp_profile.json":
        raise ContractError("invalid browser seccomp location")


def validate_beta_browser_contract(
    model: object,
    expected_image: str,
    expected_browser_image: str,
    expected_origin: str,
    expected_owner: str,
    expected_seccomp_path: str,
    expected_attempt_id: str,
) -> None:
    """Opt-in browser-ipc-v2 only; prove additions, then invoke legacy v1.

    The original `validate_beta_contract` remains byte-for-byte unchanged and
    must still reject an extra service when no explicit v2 topology is chosen.
    A resolved Compose model is **not** Docker or host attestation.
    """
    if not _IMAGE.fullmatch(expected_image):
        raise ContractError("invalid controller release image digest")
    if not _BROWSER_IMAGE.fullmatch(expected_browser_image):
        raise ContractError("invalid independent browser release image digest")
    if not _BROWSER_ATTEMPT.fullmatch(expected_attempt_id):
        raise ContractError("invalid protected browser attempt")
    _browser_seccomp_path(expected_seccomp_path)

    root = _mapping(model, "browser-ipc-v2 Compose model")
    _keys(root, {"name", "services", "volumes", "networks"}, "browser-ipc-v2 Compose")
    _equal(root["name"], "boca-socios", "browser-ipc-v2 project")
    services = _mapping(root["services"], "browser-ipc-v2 services")
    _keys(services, {"controller", "browser-worker"}, "browser-ipc-v2 services")
    controller = _mapping(services["controller"], "browser-ipc-v2 controller")
    _keys(controller, _SERVICE_FIELDS | {"ports", "labels"}, "browser-ipc-v2 controller")
    _equal(controller["image"], expected_image, "browser-ipc-v2 controller image")
    _equal(
        controller["labels"],
        {_BROWSER_ATTEMPT_LABEL: expected_attempt_id},
        "browser-ipc-v2 controller attempt label",
    )
    environment = _mapping(controller["environment"], "browser-ipc-v2 controller environment")
    _equal(environment.get("BOCA_BROWSER_BACKEND"), "ipc", "explicit IPC backend")
    on_demand = "BOCA_BOT_CONTROL" in environment
    if on_demand:
        _equal(environment["BOCA_BOT_CONTROL"], "on-demand", "Boca bot activation")
    _equal(controller["restart"], "unless-stopped" if on_demand else "no", "controller restart")
    _equal(
        environment.get("BOCA_TELEGRAM_PAIRING_STAGE_MODE"),
        "encrypted-only",
        "encrypted-only Telegram V2 staging on reviewed IPC controller",
    )
    mounts = _list(controller["volumes"], "browser-ipc-v2 controller mounts")
    if len(mounts) != (5 if on_demand else 4):
        raise ContractError("unexpected number of controller mounts")
    _browser_ipc_mount(mounts[3], readonly=True, field="controller IPC mount")
    if on_demand:
        control = _mapping(mounts[4], "Boca control socket directory")
        required = {"type", "source", "target", "read_only"}
        if not required <= control.keys() <= required | {"bind"}:
            raise ContractError("unexpected control socket mount options")
        for key, value in {
            "type": "bind",
            "source": "/home/boca-deploy/.boca-on-demand/socket",
            "target": "/run/boca-bot-control",
            "read_only": True,
        }.items():
            _equal(control[key], value, "Boca control mount " + key)
        options = _mapping(control.get("bind", {}), "Boca control bind options")
        if options:
            _keys(options, {"create_host_path"}, "Boca control bind options")
            _equal(options["create_host_path"], False, "Boca control directory creation")

    worker = _mapping(services["browser-worker"], "browser-ipc-v2 worker")
    _keys(
        worker,
        {
            "image",
            "command",
            "entrypoint",
            "user",
            "init",
            "restart",
            "stop_grace_period",
            "logging",
            "environment",
            "labels",
            "volumes",
            "network_mode",
            "cgroup",
            "ipc",
            "read_only",
            "tmpfs",
            "shm_size",
            "security_opt",
            "cap_drop",
            "cap_add",
            "pids_limit",
            "mem_limit",
            "cpus",
            "healthcheck",
        },
        "browser-ipc-v2 worker",
    )
    for field, expected in {
        "image": expected_browser_image,
        "command": ["python", "-m", "boca_socios.browser.ipc_worker"],
        "entrypoint": None,
        "user": "10002:10002",
        "init": True,
        "restart": "no",
        "stop_grace_period": "8s",
        "logging": {"driver": "none"},
        "network_mode": "none",
        "cgroup": "private",
        "ipc": "private",
        "read_only": True,
        "tmpfs": [
            "/tmp:rw,noexec,nosuid,size=32m",  # noqa: S108 - isolated container
            "/home/boca-browser:rw,noexec,nosuid,size=16m",
        ],
        "shm_size": "67108864",
        "security_opt": ["no-new-privileges:true", f"seccomp={expected_seccomp_path}"],
        "cap_drop": ["ALL"],
        "cap_add": ["SYS_CHROOT"],
        "pids_limit": 128,
        "mem_limit": "805306368",
        # Compose JSON writes integral CPU quota as the JSON integer 1.
        "cpus": 1,
        "healthcheck": {
            "test": [
                "CMD-SHELL",
                "python -m boca_socios.browser.worker_health >/dev/null 2>&1"
                if on_demand
                else f"python -c {shlex.quote(_BROWSER_HEALTH)} >/dev/null 2>&1",
            ],
            "interval": "2s",
            "timeout": "3s",
            "retries": 3,
            "start_period": "5s",
        },
    }.items():
        _equal(worker[field], expected, f"browser-ipc-v2 worker {field}")
    _equal(
        worker["environment"],
        {
            "BOCA_ENVIRONMENT": "staging",
            "BOCA_RUNTIME_MODE": "simulation",
            "BOCA_ENGINE_MODE": "off",
        },
        "browser-ipc-v2 worker environment",
    )
    _equal(
        worker["labels"],
        {_BROWSER_ATTEMPT_LABEL: expected_attempt_id},
        "browser-ipc-v2 worker attempt",
    )
    worker_mounts = _list(worker["volumes"], "browser-ipc-v2 worker mounts")
    if len(worker_mounts) != 1:
        raise ContractError("browser-ipc-v2 worker must have only the IPC mount")
    _browser_ipc_mount(worker_mounts[0], readonly=False, field="worker IPC mount")

    volumes = _mapping(root["volumes"], "browser-ipc-v2 volumes")
    _keys(
        volumes,
        {"boca_data", "boca_key", "boca_owner", "boca_browser_ipc"},
        "browser-ipc-v2 volumes",
    )
    ipc_volume = _mapping(volumes["boca_browser_ipc"], "browser-ipc-v2 volume")
    _keys(ipc_volume, {"name", "external"}, "browser-ipc-v2 volume")
    _equal(ipc_volume["name"], "boca-socios_boca_browser_ipc", "browser-ipc-v2 volume name")
    _equal(ipc_volume["external"], True, "browser-ipc-v2 disposable volume is external")

    # Restore *only* reviewed v2 additions and ask the legacy singleton
    # validator to prove every remaining field, port, network and mount.
    legacy = deepcopy(root)
    legacy_services = cast(dict[str, object], legacy["services"])
    legacy_controller = cast(dict[str, object], legacy_services["controller"])
    legacy_controller["restart"] = "unless-stopped"
    del legacy_controller["labels"]
    legacy_environment = cast(dict[str, object], legacy_controller["environment"])
    if on_demand:
        del legacy_environment["BOCA_BOT_CONTROL"]
    del legacy_environment["BOCA_BROWSER_BACKEND"]
    del legacy_environment["BOCA_TELEGRAM_PAIRING_STAGE_MODE"]
    legacy_mounts = cast(list[object], legacy_controller["volumes"])
    legacy_controller["volumes"] = legacy_mounts[:3]
    del legacy_services["browser-worker"]
    legacy_volumes = cast(dict[str, object], legacy["volumes"])
    del legacy_volumes["boca_browser_ipc"]
    validate_beta_contract(legacy, expected_image, expected_origin, expected_owner)
