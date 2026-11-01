"""Fail-closed validation of a resolved simulation-only Compose model."""

from __future__ import annotations

import re
from collections.abc import Mapping

from boca_socios.owner_origin import SSH_LOOPBACK_ORIGIN


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
