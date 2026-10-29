"""A resolved deployment model may only contain the Boca controller boundary."""

from __future__ import annotations

from copy import deepcopy

import pytest

from boca_socios.deploy_contract import ContractError, validate_contract

IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64


def model() -> dict[str, object]:
    return {
        "name": "boca-socios",
        "services": {
            "controller": {
                "image": IMAGE,
                "command": None,
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
                "environment": {
                    "BOCA_ENVIRONMENT": "staging",
                    "BOCA_RUNTIME_MODE": "simulation",
                    "BOCA_ENGINE_MODE": "off",
                    "BOCA_DB_PATH": "/data/boca.sqlite3",
                    "BOCA_MASTER_KEY_FILE": "/run/secrets/boca_master_key",
                },
                "volumes": [
                    {"type": "volume", "source": "boca_data", "target": "/data"},
                    {
                        "type": "volume",
                        "source": "boca_key",
                        "target": "/run/secrets",
                        "read_only": True,
                    },
                ],
                "networks": {"boca_private": None},
                "tmpfs": ["/tmp:rw,noexec,nosuid,size=16m"],  # noqa: S108 - mount contract
                "healthcheck": {
                    "test": ["CMD", "python", "-m", "boca_socios.healthcheck"],
                    "interval": "30s",
                    "timeout": "5s",
                    "retries": 3,
                    "start_period": "15s",
                },
            }
        },
        "volumes": {
            "boca_data": {"name": "boca-socios_boca_data"},
            "boca_key": {"name": "boca-socios_boca_key"},
        },
        "networks": {
            "boca_private": {
                "name": "boca-socios_boca_private",
                "driver": "bridge",
                "ipam": {},
            }
        },
    }


def test_exact_isolated_controller_passes() -> None:
    validate_contract(model(), IMAGE)


def test_engine_activation_in_compose_is_rejected() -> None:
    candidate = model()
    candidate["services"]["controller"]["environment"]["BOCA_ENGINE_MODE"] = "on"  # type: ignore[index]
    with pytest.raises(ContractError):
        validate_contract(candidate, IMAGE)


@pytest.mark.parametrize(
    ("location", "field", "value"),
    [
        ("top", "name", "other"),
        ("service", "image", "ghcr.io/mbalbo2023/boca-socios-assistant:latest"),
        ("service", "build", {"context": "."}),
        ("service", "entrypoint", ["sh"]),
        ("service", "command", ["sh"]),
        ("service", "ports", [{"published": 8000, "target": 8000}]),
        ("service", "privileged", True),
        ("service", "user", "0:0"),
        ("service", "mem_limit", "536870912"),
        ("service", "cap_add", ["ALL"]),
        ("service", "network_mode", "host"),
        ("service", "volumes", [{"type": "bind", "source": "/", "target": "/data"}]),
        ("service", "read_only", False),
        ("service", "environment", {"BOCA_RUNTIME_MODE": "live"}),
    ],
)
def test_host_or_live_escape_is_rejected(location: str, field: str, value: object) -> None:
    candidate = deepcopy(model())
    target = candidate if location == "top" else candidate["services"]["controller"]  # type: ignore[index]
    target[field] = value  # type: ignore[index]
    with pytest.raises(ContractError):
        validate_contract(candidate, IMAGE)


def test_additional_service_and_unsafe_key_mount_are_rejected() -> None:
    candidate = model()
    candidate["services"]["worker"] = {"image": IMAGE}  # type: ignore[index]
    with pytest.raises(ContractError):
        validate_contract(candidate, IMAGE)

    candidate = model()
    candidate["services"]["controller"]["volumes"][1]["read_only"] = False  # type: ignore[index]
    with pytest.raises(ContractError):
        validate_contract(candidate, IMAGE)

    candidate = model()
    candidate["services"]["controller"]["volumes"][1] = {  # type: ignore[index]
        "type": "bind", "source": "/var/shared", "target": "/run/secrets", "read_only": True
    }
    with pytest.raises(ContractError):
        validate_contract(candidate, IMAGE)


def test_changed_healthcheck_or_network_is_rejected() -> None:
    candidate = model()
    candidate["services"]["controller"]["healthcheck"]["timeout"] = "60s"  # type: ignore[index]
    with pytest.raises(ContractError):
        validate_contract(candidate, IMAGE)

    candidate = model()
    candidate["networks"]["boca_private"]["ipam"] = {"config": [{"subnet": "0.0.0.0/0"}]}  # type: ignore[index]
    with pytest.raises(ContractError):
        validate_contract(candidate, IMAGE)
