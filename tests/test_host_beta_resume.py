"""Boca-only BETA stop/resume contract: no reinstall, browser or foreign service."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from boca_socios import host_first_deploy as host

SOURCE_SHA = "a" * 40
IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64
COMPOSE_SHA = "e" * 64
CONTAINER = "c" * 64
NETWORK = "d" * 64
ORIGIN = "http://localhost:8443"
OWNER = "synthetic-owner"


def _record() -> dict[str, object]:
    environment = {
        "BOCA_ENVIRONMENT": "staging",
        "BOCA_RUNTIME_MODE": "simulation",
        "BOCA_ENGINE_MODE": "off",
        "BOCA_PANEL_ORIGIN": ORIGIN,
        "BOCA_OWNER_SUBJECT": OWNER,
        "BOCA_DB_PATH": "/data/boca.sqlite3",
        "BOCA_MASTER_KEY_FILE": "/run/secrets/boca_master_key",
        "BOCA_PASSKEY_CREDENTIAL_ID_FILE": "/run/owner/credential_id",
        "BOCA_PASSKEY_PUBLIC_KEY_DER_FILE": "/run/owner/public_key.der",
        "BOCA_BIND_HOST": "0.0.0.0",  # noqa: S104 - offline container-only fixture
        "BOCA_BIND_PORT": "8443",
        "BOCA_HEALTH_MODE": "beta",
    }
    return {
        "Id": CONTAINER,
        "Name": "/boca-socios-controller-1",
        "Config": {
            "Image": IMAGE,
            "User": "10001:10001",
            "Cmd": ["python", "-m", "boca_socios.runtime", "serve-beta"],
            "Entrypoint": None,
            "Labels": {
                "com.docker.compose.project": host.PROJECT,
                "com.docker.compose.service": "controller",
                "com.docker.compose.container-number": "1",
                "org.opencontainers.image.revision": SOURCE_SHA,
            },
            "Env": [f"{name}={value}" for name, value in environment.items()],
        },
        "HostConfig": {
            "NetworkMode": "boca-socios_boca_private",
            "PortBindings": {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]},
            "PublishAllPorts": False,
            "NanoCpus": 500_000_000,
            "Memory": 268_435_456,
            "PidsLimit": 64,
            "ReadonlyRootfs": True,
            "Privileged": False,
            "CapDrop": ["ALL"],
            "CapAdd": None,
            "SecurityOpt": ["no-new-privileges:true"],
            "CgroupnsMode": "private",
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=16m"},  # noqa: S108 - exact mount contract
            "RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0},
        },
        "State": {"Running": False, "Restarting": False, "Status": "exited"},
        "NetworkSettings": {
            "Networks": {"boca-socios_boca_private": {"NetworkID": NETWORK}},
            "Ports": {"8443/tcp": None},
        },
        "Mounts": [
            {
                "Type": "volume",
                "Driver": "local",
                "Name": host.DATA_VOLUME,
                "Destination": "/data",
                "RW": True,
            },
            {
                "Type": "volume",
                "Driver": "local",
                "Name": host.KEY_VOLUME,
                "Destination": "/run/secrets",
                "RW": False,
            },
            {
                "Type": "volume",
                "Driver": "local",
                "Name": host.OWNER_VOLUME,
                "Destination": "/run/owner",
                "RW": False,
            },
        ],
    }


def _setup(
    monkeypatch: pytest.MonkeyPatch,
    *,
    record: dict[str, object] | None = None,
    volumes: set[str] | None = None,
    containers: list[str] | None = None,
) -> list[tuple[str, ...]]:
    metadata = copy.deepcopy(_record() if record is None else record)
    present = {host.DATA_VOLUME, host.KEY_VOLUME, host.OWNER_VOLUME} if volumes is None else volumes
    ids = [CONTAINER] if containers is None else containers
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(host, "_verify_beta_compose", lambda *_args: None)
    monkeypatch.setattr(host, "_validate_owner_context", lambda *_args: None)
    monkeypatch.setattr(host, "_validate_data_volume", lambda: None)
    monkeypatch.setattr(host, "_validate_key_volume", lambda: None)
    monkeypatch.setattr(host, "_validate_owner_volume", lambda: None)
    monkeypatch.setattr(host, "_telegram_volume", lambda: None)
    monkeypatch.setattr(host, "_beta_resume_port_available", lambda: None)
    monkeypatch.setattr(
        host,
        "_names",
        lambda kind, _label: present if kind == "volume" else {"boca-socios_boca_private"},
    )
    monkeypatch.setattr(
        host,
        "_validate_boca_network",
        lambda candidate, net: (
            None if candidate == "" and net == NETWORK else pytest.fail("unverified BETA network")
        ),
    )

    def run(*args: str, **_kwargs: object) -> str:
        commands.append(args)
        if args[:5] == ("docker", "ps", "-a", "-q", "--no-trunc"):
            return "\n".join(ids)
        if args[:4] == ("docker", "inspect", "--format", "{{json .}}"):
            assert args[-1] == CONTAINER
            return json.dumps(metadata)
        if args[:3] == ("docker", "image", "inspect"):
            if "{{json .RepoDigests}}" in args:
                return json.dumps([IMAGE])
            return SOURCE_SHA
        if args[:2] == ("docker", "compose"):
            assert args[-2:] == ("config", "-q")
            return ""
        pytest.fail(f"unexpected command {args!r}")

    monkeypatch.setattr(host, "_run", run)
    return commands


def test_stopped_exact_controller_can_be_resumed_without_effectful_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands = _setup(monkeypatch)
    assert host._beta_stopped_controller(IMAGE, SOURCE_SHA, COMPOSE_SHA, ORIGIN, OWNER) == CONTAINER
    assert not any(args[:2] == ("docker", "start") for args in commands)
    assert not any("pull" in args or "up" in args or "create" in args for args in commands)


@pytest.mark.parametrize(
    ("part", "key", "changed"),
    [
        ("State", "Running", True),
        ("State", "Status", "created"),
        ("Config", "Image", "wrong"),
        ("Config", "User", "0:0"),
        ("HostConfig", "NetworkMode", "bridge"),
        ("HostConfig", "Privileged", True),
        ("HostConfig", "Memory", 0),
        ("HostConfig", "PidsLimit", 0),
        ("HostConfig", "CapAdd", ["SYS_ADMIN"]),
        ("HostConfig", "PortBindings", {"8443/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8443"}]}),  # noqa: S104 - rejected exposure fixture
        ("NetworkSettings", "Ports", {"8443/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8443"}]}),  # noqa: S104 - rejected exposure fixture
    ],
)
def test_resume_rejects_stopped_controller_identity_drift(
    monkeypatch: pytest.MonkeyPatch, part: str, key: str, changed: object
) -> None:
    record = _record()
    part_data = record[part]
    assert isinstance(part_data, dict)
    part_data[key] = changed
    commands = _setup(monkeypatch, record=record)
    with pytest.raises(host.PreflightError):
        host._beta_stopped_controller(IMAGE, SOURCE_SHA, COMPOSE_SHA, ORIGIN, OWNER)
    assert not any(args[:2] == ("docker", "start") for args in commands)


@pytest.mark.parametrize(
    "bad_env",
    ["BOCA_ENGINE_MODE=live", "BOCA_BROWSER_BACKEND=ipc", "BOCA_SITE_BRIDGE_MODE=on"],
)
def test_resume_rejects_live_engine_or_unauthorized_browser_or_site(
    monkeypatch: pytest.MonkeyPatch, bad_env: str
) -> None:
    record = _record()
    config = record["Config"]
    assert isinstance(config, dict)
    values = config["Env"]
    assert isinstance(values, list)
    values[:] = [entry for entry in values if not entry.startswith(bad_env.split("=")[0] + "=")]
    values.append(bad_env)
    _setup(monkeypatch, record=record)
    with pytest.raises(host.PreflightError):
        host._beta_stopped_controller(IMAGE, SOURCE_SHA, COMPOSE_SHA, ORIGIN, OWNER)


def test_resume_rejects_foreign_controller_even_if_one_boca_name_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup(monkeypatch, containers=[CONTAINER, "f" * 64])
    with pytest.raises(host.PreflightError):
        host._beta_stopped_controller(IMAGE, SOURCE_SHA, COMPOSE_SHA, ORIGIN, OWNER)


def test_resume_rejects_any_unknown_volume_but_accepts_verified_telegram_custody(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unexpected = {host.DATA_VOLUME, host.KEY_VOLUME, host.OWNER_VOLUME, "foreign"}
    _setup(monkeypatch, volumes=unexpected)
    with pytest.raises(host.PreflightError):
        host._beta_stopped_controller(IMAGE, SOURCE_SHA, COMPOSE_SHA, ORIGIN, OWNER)
    _setup(
        monkeypatch,
        volumes={host.DATA_VOLUME, host.KEY_VOLUME, host.OWNER_VOLUME, host.TELEGRAM_VOLUME},
    )
    assert host._beta_stopped_controller(IMAGE, SOURCE_SHA, COMPOSE_SHA, ORIGIN, OWNER) == CONTAINER


def test_resume_refuses_unverified_telegram_volume(monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(
        monkeypatch,
        volumes={host.DATA_VOLUME, host.KEY_VOLUME, host.OWNER_VOLUME, host.TELEGRAM_VOLUME},
    )
    def bad_telegram() -> None:
        raise host.PreflightError("Telegram volume not verified")

    monkeypatch.setattr(host, "_telegram_volume", bad_telegram)
    with pytest.raises(host.PreflightError, match="Telegram volume"):
        host._beta_stopped_controller(IMAGE, SOURCE_SHA, COMPOSE_SHA, ORIGIN, OWNER)


def test_resume_reuses_stopped_controller_id_and_emits_bounded_receipt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(host, "_validate_owner_context", lambda *_args: None)
    monkeypatch.setattr(host, "_beta_stopped_controller", lambda *_args: CONTAINER)
    monkeypatch.setattr(
        host,
        "_beta_acceptance_status",
        lambda *_args: (SimpleNamespace(container_id=CONTAINER, health="healthy"), object()),
    )

    def run(*args: str) -> str:
        commands.append(args)
        if args == ("docker", "start", CONTAINER):
            return CONTAINER
        assert args == ("docker", "inspect", "--format", "{{.State.Health.Status}}", CONTAINER)
        return "healthy"

    monkeypatch.setattr(host, "_run", run)
    host._beta_resume_phase(IMAGE, SOURCE_SHA, COMPOSE_SHA, ORIGIN, OWNER)
    assert commands == [
        ("docker", "start", CONTAINER),
        ("docker", "inspect", "--format", "{{.State.Health.Status}}", CONTAINER),
    ]
    assert len(
        f"BOCA_BETA_START state=RUNNING source_sha={SOURCE_SHA} image={IMAGE}"
        " service=controller host=127.0.0.1:8443"
        " data=preserved key=preserved owner=preserved engine=off"
    ) <= 360
    assert capsys.readouterr().out.strip() == (
        f"BOCA_BETA_START state=RUNNING source_sha={SOURCE_SHA} image={IMAGE}"
        " service=controller host=127.0.0.1:8443"
        " data=preserved key=preserved owner=preserved engine=off"
    )


def test_resume_failure_stops_exact_controller_without_touching_volumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(host, "_validate_owner_context", lambda *_args: None)
    monkeypatch.setattr(host, "_beta_stopped_controller", lambda *_args: CONTAINER)
    monkeypatch.setattr(
        host, "_beta_acceptance_status", lambda *_args: pytest.fail("must not reach")
    )
    def run(*args: str) -> str:
        commands.append(args)
        if args == ("docker", "start", CONTAINER):
            return CONTAINER
        if args == ("docker", "stop", "--time", "30", CONTAINER):
            return CONTAINER
        if args == ("docker", "inspect", "--format", "{{.State.Health.Status}}", CONTAINER):
            return "unhealthy"
        pytest.fail("unexpected command")

    monkeypatch.setattr(host, "_run", run)
    with pytest.raises(host.PreflightError, match="health"):
        host._beta_resume_phase(IMAGE, SOURCE_SHA, COMPOSE_SHA, ORIGIN, OWNER)
    assert commands == [
        ("docker", "start", CONTAINER),
        ("docker", "inspect", "--format", "{{.State.Health.Status}}", CONTAINER),
        ("docker", "stop", "--time", "30", CONTAINER),
    ]


def test_beta_dispatch_resumes_without_entering_new_only_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(host, "_validate_owner_context", lambda *_args: None)
    monkeypatch.setattr(host, "_beta_resume_phase", lambda *args: calls.append(args))
    monkeypatch.setattr(
        host, "_beta_inventory", lambda **_kwargs: pytest.fail("new-only branch reached")
    )
    host._beta_phase("beta-start", IMAGE, SOURCE_SHA, COMPOSE_SHA, ORIGIN, OWNER)
    assert calls == [(IMAGE, SOURCE_SHA, COMPOSE_SHA, ORIGIN, OWNER)]


def test_protected_workflow_starts_daemon_before_new_install_and_resumes_after_acceptance() -> None:
    content = (
        Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
    ).read_text(encoding="utf-8")
    assert "beta-start" in content
    assert "if: inputs.operation == 'beta-install' || inputs.operation == 'beta-start'" in content
    assert content.index(
        "Start only previously prepared and stopped Boca rootless daemon"
    ) < content.index("Read-only BETA capacity, owner custody and empty app namespace")
    assert content.index(
        "Recheck current main immediately before BETA controller resume"
    ) < content.index("Resume only positively identified stopped BETA controller")
    assert content.index("Invoke bounded synthetic BETA acceptance") < content.index(
        "Stop positively identified Boca services after BETA acceptance"
    )
    assert "BOCA_BETA_START state=RUNNING" in content
    assert "steps.boca_beta_daemon_start.outputs.started == 'true'" in content
    assert "start-existing" in content and "beta-install" in content
    assert 'test "$BOCA_BETA_ENV_READY" = ready' in content
    assert "python scripts/check_release_run.py" in content


def test_pr_validation_does_not_serialize_obsolete_shas_or_cancel_host_runs() -> None:
    """Superseded PR checks cancel; protected physical dispatch stays exclusive."""
    workflows = Path(__file__).resolve().parents[1] / ".github/workflows"
    release = (workflows / "release-image.yml").read_text(encoding="utf-8")
    deploy = (workflows / "boca-first-deploy.yml").read_text(encoding="utf-8")
    conditional = "  cancel-in-progress: ${{ github.event_name == 'pull_request' }}"

    assert release.count(conditional) == 1
    assert deploy.count(conditional) == 1
    assert "  group: boca-image-release-${{ github.ref }}" in release
    assert "format('boca-first-deploy-pr-{0}', github.event.pull_request.number)" in deploy
    assert "|| 'boca-first-deploy'" in deploy
    assert "if: github.event_name == 'workflow_dispatch'" in release
    assert "if: github.event_name == 'workflow_dispatch'" in deploy
