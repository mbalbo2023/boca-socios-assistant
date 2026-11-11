"""The opt-in IPC overlay permits only dedicated Boca worker egress."""

from __future__ import annotations

import json
import runpy
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from boca_socios.deploy_contract import (
    ContractError,
    validate_beta_browser_contract,
    validate_beta_contract,
)
from boca_socios.host_first_deploy import _cutover_worker_create_argv
from test_beta_deploy_contract import ORIGIN, OWNER, beta_model
from test_deploy_contract import IMAGE

BROWSER_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "b" * 64
ATTEMPT = "123456"
SECCOMP = "/srv/boca-socios/seccomp_profile.json"
IPC_VOLUME = "boca-socios_boca_browser_ipc"
SITE_CONFIG_VOLUME = "boca-socios_boca_site_config"
WORKER_HEALTH = (
    "from boca_socios.browser.worker_health import check_worker_health; check_worker_health()"
)


def browser_model() -> dict[str, object]:
    candidate = deepcopy(beta_model())
    services = candidate["services"]  # type: ignore[index]
    controller = services["controller"]
    controller["restart"] = "no"
    controller["environment"]["BOCA_BROWSER_BACKEND"] = "ipc"
    controller["environment"]["BOCA_TELEGRAM_PAIRING_STAGE_MODE"] = "encrypted-only"
    controller["labels"] = {"boca.socios.browser-ipc-attempt": ATTEMPT}
    controller["volumes"].append(
        {
            "type": "volume",
            "source": "boca_browser_ipc",
            "target": "/run/boca-browser-ipc",
            "read_only": True,
        }
    )
    controller["volumes"].append(
        {
            "type": "volume",
            "source": "boca_site_config",
            "target": "/run/boca-site-config",
            "read_only": False,
        }
    )
    services["browser-worker"] = {
        "image": BROWSER_IMAGE,
        "command": ["python", "-m", "boca_socios.browser.ipc_server"],
        "entrypoint": None,
        "user": "10002:10002",
        "init": True,
        "restart": "no",
        "stop_grace_period": "8s",
        "logging": {"driver": "none"},
        "environment": {
            "BOCA_ENVIRONMENT": "staging",
            "BOCA_RUNTIME_MODE": "simulation",
            "BOCA_ENGINE_MODE": "off",
        },
        "labels": {"boca.socios.browser-ipc-attempt": ATTEMPT},
        "volumes": [
            {
                "type": "volume",
                "source": "boca_browser_ipc",
                "target": "/run/boca-browser-ipc",
                "read_only": False,
            },
            {
                "type": "volume",
                "source": "boca_site_config",
                "target": "/run/boca-site-config",
                "read_only": True,
            },
        ],
        "networks": {"boca_browser_egress": None},
        "cgroup": "private",
        "ipc": "private",
        "read_only": True,
        "tmpfs": [
            "/tmp:rw,noexec,nosuid,size=32m",  # noqa: S108 - container tmpfs
            "/home/boca-browser:rw,noexec,nosuid,size=16m",
        ],
        "shm_size": "67108864",
        "security_opt": ["no-new-privileges:true", f"seccomp={SECCOMP}"],
        "cap_drop": ["ALL"],
        "cap_add": ["SYS_CHROOT"],
        "pids_limit": 128,
        "mem_limit": "805306368",
        "cpus": 1,
        "healthcheck": {
            "test": ["CMD-SHELL", f"python -c '{WORKER_HEALTH}' >/dev/null 2>&1"],
            "interval": "2s",
            "timeout": "3s",
            "retries": 3,
            "start_period": "5s",
        },
    }
    candidate["volumes"]["boca_browser_ipc"] = {  # type: ignore[index]
        "name": IPC_VOLUME,
        "external": True,
    }
    candidate["volumes"]["boca_site_config"] = {  # type: ignore[index]
        "name": SITE_CONFIG_VOLUME,
        "external": True,
    }
    candidate["networks"]["boca_browser_egress"] = {  # type: ignore[index]
        "name": "boca-socios_boca_browser_egress",
        "driver": "bridge",
        "internal": False,
    }
    return candidate


def valid(model: object) -> None:
    validate_beta_browser_contract(model, IMAGE, BROWSER_IMAGE, ORIGIN, OWNER, SECCOMP, ATTEMPT)


def test_versioned_browser_overlay_passes_but_legacy_singleton_rejects_it() -> None:
    valid(browser_model())
    validate_beta_contract(beta_model(), IMAGE, ORIGIN, OWNER)
    with pytest.raises(ContractError):
        validate_beta_contract(browser_model(), IMAGE, ORIGIN, OWNER)
    with pytest.raises(ContractError):
        valid(beta_model())


def test_worker_cannot_inherit_daemon_logging() -> None:
    candidate = browser_model()
    del candidate["services"]["browser-worker"]["logging"]  # type: ignore[index]
    with pytest.raises(ContractError):
        valid(candidate)


@pytest.mark.parametrize(
    "test",
    [
        ["CMD", "python", "-c", WORKER_HEALTH],
        ["CMD-SHELL", f"python -c '{WORKER_HEALTH}' >/dev/null"],
        ["CMD-SHELL", f"python -c '{WORKER_HEALTH}' 2>&1 >/dev/null"],
        ["CMD-SHELL", f"python -c '{WORKER_HEALTH}' >/dev/null 2>&1 || true"],
    ],
)
def test_worker_health_rejects_output_or_masked_exit(test: list[str]) -> None:
    candidate = browser_model()
    candidate["services"]["browser-worker"]["healthcheck"]["test"] = test  # type: ignore[index]
    with pytest.raises(ContractError):
        valid(candidate)


@pytest.mark.parametrize("status", [0, 19])
def test_validated_worker_health_silences_both_streams_and_preserves_exit(
    status: int, tmp_path: Path
) -> None:
    candidate = browser_model()
    valid(candidate)
    check = candidate["services"]["browser-worker"]["healthcheck"]["test"]  # type: ignore[index]
    argv = _cutover_worker_create_argv(BROWSER_IMAGE, "a" * 40, ATTEMPT, "c" * 64)
    command = argv[argv.index("--health-cmd") + 1]
    assert check == ["CMD-SHELL", command]
    # Only this fixture can resolve as python. The protected modules are never loaded.
    interpreter = tmp_path / "python"
    interpreter.write_text(
        "#!/bin/sh\n"
        'test "$#" = 2 && test "$1" = -c && test "$2" = "$EXPECTED_PROBE" || exit 98\n'
        "printf fixture-output\n"
        "printf fixture-error >&2\n"
        'exit "$FIXTURE_STATUS"\n',
        encoding="ascii",
    )
    interpreter.chmod(0o700)
    result = subprocess.run(  # noqa: S603 - approved command, fixture-only PATH
        ["/bin/sh", "-c", command],
        env={"PATH": str(tmp_path), "EXPECTED_PROBE": WORKER_HEALTH, "FIXTURE_STATUS": str(status)},
        capture_output=True,
        timeout=3,
        check=False,
    )
    assert (result.returncode, result.stdout, result.stderr) == (status, b"", b"")


def test_compose_normalizes_one_cpu_to_json_integer_not_float() -> None:
    """Keep strict JSON-type checks aligned with actual Docker Compose config."""
    candidate = browser_model()
    cpu = candidate["services"]["browser-worker"]["cpus"]  # type: ignore[index]
    assert cpu == 1 and type(cpu) is int
    valid(candidate)
    candidate["services"]["browser-worker"]["cpus"] = 1.0  # type: ignore[index]
    with pytest.raises(ContractError):
        valid(candidate)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("image", IMAGE),
        ("image", "ghcr.io/mbalbo2023/boca-socios-assistant-browser:latest"),
        ("command", ["sh", "-c", "python -m boca_socios.browser.ipc_worker"]),
        ("entrypoint", ["/bin/sh"]),
        ("user", "0:0"),
        ("init", False),
        ("restart", "always"),
        ("logging", {"driver": "local"}),
        ("logging", {"driver": "none", "options": {"max-file": "2"}}),
        ("stop_grace_period", "60s"),
        ("network_mode", "bridge"),
        ("network_mode", "host"),
        ("networks", {"boca_private": None}),
        ("networks", {"boca_browser_egress": None, "boca_private": None}),
        ("cgroup", "host"),
        ("ipc", "host"),
        ("read_only", False),
        ("tmpfs", []),
        ("shm_size", "134217728"),
        ("security_opt", ["seccomp=unconfined"]),
        ("cap_drop", []),
        ("cap_add", ["NET_ADMIN"]),
        ("pids_limit", 129),
        ("mem_limit", "805306369"),
        ("cpus", 2.0),
        ("healthcheck", {"test": ["CMD", "true"]}),
        ("ports", [{"host_ip": "127.0.0.1", "published": "8444", "target": 8444}]),
        ("privileged", True),
        ("volumes", []),
        ("labels", {}),
    ],
)
def test_worker_mutations_fail_closed(field: str, value: object) -> None:
    candidate = browser_model()
    candidate["services"]["browser-worker"][field] = value  # type: ignore[index]
    with pytest.raises(ContractError):
        valid(candidate)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("BOCA_RUNTIME_MODE", "live"),
        ("BOCA_ENGINE_MODE", "on"),
        ("BOCA_PANEL_ORIGIN", ORIGIN),
        ("BOCA_OWNER_SUBJECT", OWNER),
        ("BOCA_TELEGRAM_TOKEN", "synthetic-fixture-token"),
    ],
)
def test_worker_environment_cannot_gain_live_or_private_context(field: str, value: str) -> None:
    candidate = browser_model()
    candidate["services"]["browser-worker"]["environment"][field] = value  # type: ignore[index]
    with pytest.raises(ContractError):
        valid(candidate)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("restart", "unless-stopped"),
        ("logging", {"driver": "none"}),
        ("image", BROWSER_IMAGE),
        ("cap_add", ["SYS_ADMIN"]),
        ("network_mode", "none"),
        ("ports", []),
        ("labels", {}),
    ],
)
def test_controller_cannot_change_reviewed_legacy_boundary(field: str, value: object) -> None:
    candidate = browser_model()
    candidate["services"]["controller"][field] = value  # type: ignore[index]
    with pytest.raises(ContractError):
        valid(candidate)


def test_controller_socket_must_be_readonly_and_only_one_new_mount() -> None:
    candidate = browser_model()
    candidate["services"]["controller"]["volumes"][3]["read_only"] = False  # type: ignore[index]
    with pytest.raises(ContractError):
        valid(candidate)
    candidate = browser_model()
    candidate["services"]["controller"]["volumes"].append(  # type: ignore[index]
        {"type": "bind", "source": "/var/run", "target": "/other"}
    )
    with pytest.raises(ContractError):
        valid(candidate)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("services", "foreign-worker", {}),
        ("networks", "default", {"name": "unreviewed"}),
        ("volumes", "shared", {"name": "another-app"}),
    ],
)
def test_no_extra_service_network_or_volume(section: str, field: str, value: object) -> None:
    candidate = browser_model()
    candidate[section][field] = value  # type: ignore[index]
    with pytest.raises(ContractError):
        valid(candidate)


@pytest.mark.parametrize(
    "value",
    [
        {"name": "boca-socios_boca_private", "driver": "bridge", "internal": False},
        {"name": "boca-socios_boca_browser_egress", "driver": "bridge", "internal": True},
        {"name": "boca-socios_boca_browser_egress", "driver": "host", "internal": False},
        {"name": "shared-egress", "driver": "bridge", "internal": False},
    ],
)
def test_worker_egress_must_be_dedicated_boca_bridge(value: object) -> None:
    candidate = browser_model()
    candidate["networks"]["boca_browser_egress"] = value  # type: ignore[index]
    with pytest.raises(ContractError):
        valid(candidate)


def test_compose_normalized_egress_defaults_are_equivalent_and_still_outbound() -> None:
    candidate = browser_model()
    candidate["networks"]["boca_browser_egress"] = {  # type: ignore[index]
        "name": "boca-socios_boca_browser_egress",
        "driver": "bridge",
        "ipam": {},
    }
    valid(candidate)


@pytest.mark.parametrize(
    "field,value", [("internal", True), ("ipam", {"driver": "custom"}), ("attachable", True)]
)
def test_compose_normalized_egress_rejects_nondefault_fields(field: str, value: object) -> None:
    candidate = browser_model()
    candidate["networks"]["boca_browser_egress"] = {  # type: ignore[index]
        "name": "boca-socios_boca_browser_egress",
        "driver": "bridge",
        "ipam": {},
        field: value,
    }
    with pytest.raises(ContractError):
        valid(candidate)


def test_ipc_volume_must_be_external_and_private_to_boca() -> None:
    for value in ({"name": IPC_VOLUME, "external": False}, {"name": "shared", "external": True}):
        candidate = browser_model()
        candidate["volumes"]["boca_browser_ipc"] = value  # type: ignore[index]
        with pytest.raises(ContractError):
            valid(candidate)


@pytest.mark.parametrize(
    "source",
    ["boca_data", "boca_key", "boca_owner", "foreign_bind", "/srv/boca-socios"],
)
def test_worker_mount_cannot_share_owner_key_data_or_host(source: str) -> None:
    candidate = browser_model()
    candidate["services"]["browser-worker"]["volumes"][0]["source"] = source  # type: ignore[index]
    with pytest.raises(ContractError):
        valid(candidate)


@pytest.mark.parametrize("attempt", ["", "0", "001", "1;id", "-1", "123456789012345678901"])
def test_protected_attempt_is_decimal_and_bounded(attempt: str) -> None:
    with pytest.raises(ContractError):
        validate_beta_browser_contract(
            browser_model(), IMAGE, BROWSER_IMAGE, ORIGIN, OWNER, SECCOMP, attempt
        )


@pytest.mark.parametrize(
    "path",
    [
        "relative/seccomp_profile.json",
        "/tmp/seccomp_profile.json",  # noqa: S108 - intentionally forbidden host path
        "/srv/boca-socios/../secret/seccomp_profile.json",
        "/srv/boca-socios/reviewed/seccomp_profile.json",
        "/srv/other-app/seccomp_profile.json",
        "/srv/boca-socios/docker//seccomp_profile.json",
    ],
)
def test_seccomp_path_is_fixed_boca_private_candidate(path: str) -> None:
    candidate = browser_model()
    candidate["services"]["browser-worker"]["security_opt"][1] = f"seccomp={path}"  # type: ignore[index]
    with pytest.raises(ContractError):
        validate_beta_browser_contract(
            candidate, IMAGE, BROWSER_IMAGE, ORIGIN, OWNER, path, ATTEMPT
        )


def test_unpinned_or_nonbrowser_companion_digest_is_rejected() -> None:
    for browser_image in (
        IMAGE,
        BROWSER_IMAGE + "suffix",
        BROWSER_IMAGE.replace("@sha256:", ":latest"),
    ):
        with pytest.raises(ContractError):
            validate_beta_browser_contract(
                browser_model(), IMAGE, browser_image, ORIGIN, OWNER, SECCOMP, ATTEMPT
            )


def test_cli_is_explicit_v2_without_relaxing_existing_legacy_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    checker = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "scripts/check_beta_deploy_contract.py")
    )["main"]
    document = tmp_path / "resolved.json"
    monkeypatch.setenv("BOCA_PANEL_ORIGIN", ORIGIN)
    monkeypatch.setenv("BOCA_OWNER_SUBJECT", OWNER)
    monkeypatch.setenv("BOCA_BROWSER_IMAGE", BROWSER_IMAGE)
    monkeypatch.setenv("BOCA_BROWSER_SECCOMP_PATH", SECCOMP)
    monkeypatch.setenv("BOCA_BROWSER_ATTEMPT_ID", ATTEMPT)
    document.write_text(json.dumps(beta_model()))
    monkeypatch.setattr(sys, "argv", ["check_beta_deploy_contract.py", str(document), IMAGE])
    assert checker() == 0
    assert "BETA_COMPOSE_PASS" in capsys.readouterr().out

    document.write_text(json.dumps(browser_model()))
    assert checker() == 1
    assert "BETA_COMPOSE_NO_GO" in capsys.readouterr().err
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_beta_deploy_contract.py", str(document), IMAGE, "--topology=browser-ipc-v2"],
    )
    assert checker() == 0
    assert "BETA_BROWSER_COMPOSE_PASS" in capsys.readouterr().out
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_beta_deploy_contract.py", str(document), IMAGE, "--topology=unreviewed"],
    )
    assert checker() == 1
    assert "BETA_COMPOSE_NO_GO" in capsys.readouterr().err


def test_ci_resolves_real_compose_overlay_and_validates_it_before_merge() -> None:
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text(
        encoding="utf-8"
    )
    assert "Validate optional dual-service IPC Compose resolution without host access" in workflow
    assert (
        "docker compose -p boca-socios -f compose.beta.yaml -f compose.beta.browser.yaml config --format json"
        in workflow
    )
    assert (
        'scripts/check_beta_deploy_contract.py "$RUNNER_TEMP/boca-ipc-v2-model.json" '
        '"$BOCA_IMAGE" --topology=browser-ipc-v2' in workflow
    )
    for required in (
        "BOCA_BROWSER_IMAGE:",
        'BOCA_BROWSER_ATTEMPT_ID: "123456"',
        "BOCA_BROWSER_SECCOMP_PATH: /srv/boca-socios/seccomp_profile.json",
        "BOCA_PANEL_ORIGIN: http://localhost:8443",
        "BOCA_OWNER_SUBJECT: synthetic-ci-owner",
    ):
        assert required in workflow
    assert workflow.index("Validate optional dual-service IPC Compose resolution") < workflow.index(
        "Lint"
    )


def on_demand_model():
    candidate = browser_model()
    controller = candidate["services"]["controller"]
    controller["restart"] = "unless-stopped"
    controller["environment"]["BOCA_BOT_CONTROL"] = "on-demand"
    controller["volumes"].append(
        {
            "type": "bind",
            "source": "/home/boca-deploy/.boca-on-demand/socket",
            "target": "/run/boca-bot-control",
            "read_only": True,
            "bind": {},
        }
    )
    candidate["services"]["browser-worker"]["healthcheck"]["test"] = [
        "CMD-SHELL",
        "python -m boca_socios.browser.worker_health >/dev/null 2>&1",
    ]
    return candidate


def test_on_demand_controller_survives_reboot_and_worker_stays_off() -> None:
    valid(on_demand_model())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("type", "volume"),
        ("source", "/var/run/docker.sock"),
        ("source", "/home/boca-deploy/.boca-on-demand"),
        ("target", "/run/boca-browser-ipc"),
        ("read_only", False),
        ("bind", {"create_host_path": True}),
        ("bind", {"propagation": "rshared"}),
    ],
)
def test_on_demand_control_mount_has_exact_private_scope(field, value) -> None:
    candidate = on_demand_model()
    candidate["services"]["controller"]["volumes"][-1][field] = value
    with pytest.raises(ContractError):
        valid(candidate)


def test_on_demand_cannot_silently_use_old_health_or_discard_control() -> None:
    candidate = on_demand_model()
    candidate["services"]["browser-worker"]["healthcheck"] = browser_model()["services"][
        "browser-worker"
    ]["healthcheck"]
    with pytest.raises(ContractError):
        valid(candidate)
    candidate = on_demand_model()
    del candidate["services"]["controller"]["environment"]["BOCA_BOT_CONTROL"]
    with pytest.raises(ContractError):
        valid(candidate)


@pytest.mark.parametrize(
    ("mode", "operation", "returncode"),
    [
        ("on-demand", "cutover-a-apply", 0),
        ("on-demand", "beta-browser-status", 0),
        ("on-demand", "beta-browser-start", 1),
        ("on-demand", "beta-browser-restart", 1),
        ("on-demand", "beta-browser-acceptance", 1),
        ("on-demand", "lifecycle-apply", 1),
        ("legacy", "lifecycle-apply", 0),
    ],
)
def test_reviewed_model_controls_effectful_legacy_routes(
    tmp_path: Path, mode: str, operation: str, returncode: int
) -> None:
    from textwrap import dedent

    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
    ).read_text()
    guard = workflow.split('          mode="$(jq -er', 1)[1].split("      - name:", 1)[0]
    guard = dedent('          mode="$(jq -er' + guard)
    assert workflow.index(guard.splitlines()[0]) < workflow.index(
        "      - name: Mark existing browser lifecycle attempt"
    )
    candidate = on_demand_model() if mode == "on-demand" else browser_model()
    (tmp_path / "boca-browser-runner-model.json").write_text(json.dumps(candidate))
    result = subprocess.run(  # noqa: S603 - reviewed workflow fragment against isolated fixture
        ["/bin/bash", "-eu", "-o", "pipefail", "-c", guard],
        env={
            "PATH": "/usr/bin:/bin",
            "BOCA_OPERATION": operation,
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(tmp_path / "output"),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        },
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert (result.returncode, result.stdout, result.stderr) == (returncode, b"", b"")
    assert (tmp_path / "output").read_text() == f"mode={mode}\n"
    assert (tmp_path / "summary").exists() == (returncode != 0)
