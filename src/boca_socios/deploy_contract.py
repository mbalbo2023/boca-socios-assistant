"""Fail-closed validation of a resolved simulation-only Compose model."""

from __future__ import annotations

import re
from collections.abc import Mapping


class ContractError(ValueError):
    """The proposed deployment model exceeds the Boca-only boundary."""


_IMAGE = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
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
