"""The optional served BETA package must stay inside Boca and host loopback."""

from __future__ import annotations

from copy import deepcopy

import pytest

from boca_socios.deploy_contract import ContractError, validate_beta_contract
from test_deploy_contract import IMAGE, model

ORIGIN = "https://localhost:8443"
OWNER = "synthetic-owner"


def beta_model() -> dict[str, object]:
    candidate = deepcopy(model())
    service = candidate["services"]["controller"]  # type: ignore[index]
    service["command"] = ["python", "-m", "boca_socios.runtime", "serve-beta"]
    service["ports"] = [
        {
            "mode": "ingress",
            "target": 8443,
            "published": "8443",
            "host_ip": "127.0.0.1",
            "protocol": "tcp",
        }
    ]
    service["environment"] = {
        "BOCA_ENVIRONMENT": "staging",
        "BOCA_RUNTIME_MODE": "simulation",
        "BOCA_ENGINE_MODE": "off",
        "BOCA_DB_PATH": "/data/boca.sqlite3",
        "BOCA_MASTER_KEY_FILE": "/run/secrets/boca_master_key",
        "BOCA_PANEL_ORIGIN": ORIGIN,
        "BOCA_OWNER_SUBJECT": OWNER,
        "BOCA_PASSKEY_CREDENTIAL_ID_FILE": "/run/owner/credential_id",
        "BOCA_PASSKEY_PUBLIC_KEY_DER_FILE": "/run/owner/public_key.der",
        "BOCA_TLS_CERT_FILE": "/run/owner/tls.crt",
        "BOCA_TLS_KEY_FILE": "/run/owner/tls.key",
        "BOCA_BIND_HOST": "0.0.0.0",  # noqa: S104 - isolated container bridge
        "BOCA_BIND_PORT": "8443",
        "BOCA_HEALTH_MODE": "beta",
        "BOCA_HEALTH_CA_FILE": "/run/owner/health-ca.pem",
    }
    service["volumes"].append(  # type: ignore[index]
        {
            "type": "volume",
            "source": "boca_owner",
            "target": "/run/owner",
            "read_only": True,
        }
    )
    candidate["volumes"]["boca_owner"] = {  # type: ignore[index]
        "name": "boca-socios_boca_owner",
        "external": True,
    }
    return candidate


def test_exact_served_beta_package_passes() -> None:
    validate_beta_contract(beta_model(), IMAGE, ORIGIN, OWNER)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("service", "command", None),
        ("service", "entrypoint", ["sh"]),
        ("service", "privileged", True),
        ("service", "network_mode", "host"),
        ("service", "user", "0:0"),
        ("service", "mem_limit", "536870912"),
        ("service", "read_only", False),
        (
            "service",
            "ports",
            [{"target": 8443, "published": "8443", "host_ip": "0.0.0.0"}],  # noqa: S104 - rejected
        ),
        ("service", "cap_add", ["NET_ADMIN"]),
        ("env", "BOCA_ENGINE_MODE", "on"),
        ("env", "BOCA_PANEL_ORIGIN", "http://localhost:8443"),
        ("env", "BOCA_BIND_HOST", "127.0.0.1"),
        ("env", "BOCA_TLS_KEY_FILE", "/var/shared/tls.key"),
        ("volume", "external", False),
    ],
)
def test_unsafe_beta_package_is_rejected(section: str, field: str, value: object) -> None:
    candidate = beta_model()
    service = candidate["services"]["controller"]  # type: ignore[index]
    if section == "service":
        service[field] = value
    elif section == "env":
        service["environment"][field] = value
    else:
        candidate["volumes"]["boca_owner"][field] = value  # type: ignore[index]
    with pytest.raises(ContractError):
        validate_beta_contract(candidate, IMAGE, ORIGIN, OWNER)


def test_beta_port_and_config_volume_cannot_grow() -> None:
    candidate = beta_model()
    service = candidate["services"]["controller"]  # type: ignore[index]
    service["ports"].append(  # type: ignore[index]
        {"target": 8080, "published": "8080", "host_ip": "127.0.0.1", "protocol": "tcp"}
    )
    with pytest.raises(ContractError):
        validate_beta_contract(candidate, IMAGE, ORIGIN, OWNER)

    candidate = beta_model()
    candidate["services"]["controller"]["volumes"][2]["read_only"] = False  # type: ignore[index]
    with pytest.raises(ContractError):
        validate_beta_contract(candidate, IMAGE, ORIGIN, OWNER)


def test_beta_requires_exact_explicit_origin_subject_and_digest() -> None:
    for image, origin, owner in (
        (IMAGE, "http://localhost:8443", OWNER),
        (IMAGE, ORIGIN + "/panel", OWNER),
        (IMAGE, ORIGIN, ""),
        ("ghcr.io/mbalbo2023/boca-socios-assistant:latest", ORIGIN, OWNER),
    ):
        with pytest.raises(ContractError):
            validate_beta_contract(beta_model(), image, origin, owner)


def test_dormant_contract_does_not_accept_beta_port_or_command() -> None:
    from boca_socios.deploy_contract import validate_contract

    with pytest.raises(ContractError):
        validate_contract(beta_model(), IMAGE)
