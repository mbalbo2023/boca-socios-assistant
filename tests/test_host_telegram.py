"""Post-install Telegram custody is stopped-state, sealed and Boca-only."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from boca_socios import host_first_deploy as host

SHA = "a" * 40
IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64
IMAGE_ID = "sha256:" + "c" * 64
CID = "d" * 64
COMPOSE_SHA = "e" * 64
ORIGIN = "https://boca.example.test:8443"
OWNER = "synthetic-owner"


def _envelope(**changed: object) -> str:
    payload = {
        "version": 1,
        "repository": "mbalbo2023/boca-socios-assistant",
        "purpose": "boca-telegram-bot-v1",
        "uid": 10001,
        "recipient_public_key": "a" * 43,
        "recipient_fingerprint": "b" * 64,
        "ephemeral_public_key": "c" * 43,
        "salt": "d" * 22,
        "nonce": "e" * 16,
        "ciphertext": "f" * 100,
        **changed,
    }
    return (
        base64.urlsafe_b64encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        )
        .rstrip(b"=")
        .decode()
    )


def _record() -> dict[str, object]:
    return {
        "Id": CID,
        "Image": IMAGE_ID,
        "Name": "/boca-socios-controller-1",
        "Config": {
            "Image": IMAGE,
            "User": "10001:10001",
            "Cmd": ["python", "-m", "boca_socios.runtime", "serve-beta"],
            "Env": [
                "BOCA_ENVIRONMENT=staging",
                "BOCA_RUNTIME_MODE=simulation",
                "BOCA_ENGINE_MODE=off",
                "BOCA_DB_PATH=/data/boca.sqlite3",
                "BOCA_MASTER_KEY_FILE=/run/secrets/boca_master_key",
                f"BOCA_PANEL_ORIGIN={ORIGIN}",
                f"BOCA_OWNER_SUBJECT={OWNER}",
            ],
            "Labels": {
                "com.docker.compose.project": "boca-socios",
                "com.docker.compose.service": "controller",
                "com.docker.compose.container-number": "1",
                "org.opencontainers.image.revision": SHA,
            },
        },
        "State": {"Running": False},
        "HostConfig": {
            "NanoCpus": 500_000_000,
            "Memory": 268_435_456,
            "PidsLimit": 64,
            "ReadonlyRootfs": True,
            "Privileged": False,
            "PublishAllPorts": False,
            "PortBindings": {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]},
            "NetworkMode": "boca-socios_boca_private",
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
        },
        "Mounts": [
            {"Type": "volume", "Name": name, "Destination": dest, "RW": writable}
            for name, dest, writable in (
                (host.DATA_VOLUME, "/data", True),
                (host.KEY_VOLUME, "/run/secrets", False),
                (host.OWNER_VOLUME, "/run/owner", False),
            )
        ],
    }


def _installed(
    monkeypatch: pytest.MonkeyPatch, *, record: dict[str, object] | None = None
) -> list[tuple[str, ...]]:
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(host, "_verify_beta_compose", lambda _sha: None)
    for name in ("_validate_data_volume", "_validate_key_volume", "_validate_owner_volume"):
        monkeypatch.setattr(host, name, lambda: None)
    monkeypatch.setattr(host, "_storage_snapshot", lambda: object())
    monkeypatch.setattr(host, "_validate_storage_capacity", lambda _snapshot: None)

    def fake_run(*args: str, **_kwargs: object) -> str:
        commands.append(args)
        if args[:4] == ("docker", "ps", "-a", "-q"):
            return CID
        if args[:2] == ("docker", "inspect"):
            return json.dumps(_record() if record is None else record)
        if args[:3] == ("docker", "image", "inspect"):
            return json.dumps(
                {
                    "Id": IMAGE_ID,
                    "RepoDigests": [IMAGE],
                    "Config": {"Labels": {"org.opencontainers.image.revision": SHA}},
                }
            )
        if args[:3] == ("docker", "volume", "ls"):
            return "\n".join((host.DATA_VOLUME, host.KEY_VOLUME, host.OWNER_VOLUME))
        if args[:3] == ("docker", "network", "ls"):
            return "bridge\nhost\nnone\nboca-socios_boca_private"
        if args[:3] == ("docker", "network", "inspect"):
            return json.dumps(
                {
                    "Name": "boca-socios_boca_private",
                    "Driver": "bridge",
                    "Scope": "local",
                    "Internal": False,
                    "Attachable": False,
                    "Ingress": False,
                    "Containers": {},
                    "Labels": {
                        "com.docker.compose.project": "boca-socios",
                        "com.docker.compose.network": "boca_private",
                    },
                }
            )
        pytest.fail(f"unexpected host command {args!r}")

    monkeypatch.setattr(host, "_run", fake_run)
    return commands


def test_exact_stopped_post_install_provenance_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    commands = _installed(monkeypatch)
    assert host._telegram_installed(IMAGE, SHA, COMPOSE_SHA, ORIGIN, OWNER) is False
    assert any(command[:3] == ("docker", "network", "inspect") for command in commands)
    assert all(command[1] not in {"run", "pull", "stop", "rm"} for command in commands)


@pytest.mark.parametrize(
    ("location", "key", "value"),
    [
        ("State", "Running", True),
        ("Config", "Image", "unreviewed:latest"),
        ("HostConfig", "NetworkMode", "host"),
        ("HostConfig", "PortBindings", {"8443/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8443"}]}),  # noqa: S104 - rejected
    ],
)
def test_changed_controller_blocks_custody_before_effect(
    monkeypatch: pytest.MonkeyPatch, location: str, key: str, value: object
) -> None:
    record = _record()
    record[location][key] = value  # type: ignore[index]
    commands = _installed(monkeypatch, record=record)
    with pytest.raises(host.PreflightError):
        host._telegram_installed(IMAGE, SHA, COMPOSE_SHA, ORIGIN, OWNER)
    assert all(command[1] not in {"run", "pull", "stop", "rm"} for command in commands)


def test_sealed_input_is_canonical_and_domain_separated() -> None:
    value = _envelope()
    assert '"purpose":"boca-telegram-bot-v1"' in host._telegram_envelope(value)
    for invalid in (
        _envelope(purpose="boca-site-bridge-machine-v1"),
        _envelope(uid=True),
        _envelope(unknown="field"),
        value + "=",
        "not-b64",
    ):
        with pytest.raises(host.PreflightError):
            host._telegram_envelope(invalid)


def test_only_sealed_install_keeps_container_stdin_open() -> None:
    install = host._telegram_container(IMAGE, "telegram_bootstrap", "install", writable=True)
    prepare = host._telegram_container(IMAGE, "telegram_bootstrap", "prepare", writable=True)
    verify = host._telegram_container(IMAGE, "telegram_bootstrap", "verify", writable=False)
    schema = host._telegram_container(IMAGE, "telegram_storage_gate", "migrate", writable=True)
    assert install[:5] == ("docker", "run", "--rm", "-i", "--pull")
    assert all("-i" not in command for command in (prepare, verify, schema))
    assert "--network" in install and install[install.index("--network") + 1] == "none"
    assert (
        f"type=volume,source={host.TELEGRAM_VOLUME},target=/run/telegram,volume-nocopy" in install
    )


def test_phase_rejects_telegram_envelope_on_other_operations_before_host_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host, "_validate_docker_boundary", lambda: pytest.fail("host accessed"))
    with pytest.raises(host.PreflightError):
        host.phase("beta-acceptance", IMAGE, SHA, COMPOSE_SHA, ORIGIN, OWNER, _envelope())
    with pytest.raises(host.PreflightError):
        host.phase("site-prepare", IMAGE, SHA, COMPOSE_SHA, telegram_envelope=_envelope())


def test_telegram_migration_cannot_create_volume_before_schema_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host, "_telegram_installed", lambda *_args: False)
    monkeypatch.setattr(host, "_run", lambda *_args, **_kwargs: "unverified")
    with pytest.raises(host.PreflightError, match="migration receipt unverified"):
        host._telegram_phase("telegram-migrate", IMAGE, SHA, COMPOSE_SHA, ORIGIN, OWNER, "")


def test_one_shot_container_is_capped_named_and_retained_for_stop_test() -> None:
    command = host._telegram_test_container(IMAGE, SHA, "12345", "e" * 64)
    assert command[:4] == ("docker", "run", "--pull", "never")
    assert "--rm" not in command
    assert command[command.index("--name") + 1] == "boca-socios-telegram-test-1"
    assert "com.docker.compose.service=telegram-test" in command
    assert command[command.index("--network") + 1] == host.TELEGRAM_NETWORK
    assert command[command.index("--memory") + 1] == "128m"
    assert command[command.index("--cpus") + 1] == "0.25"
    assert command[command.index("--pids-limit") + 1] == "32"
    assert f"type=volume,source={host.DATA_VOLUME},target=/data,volume-nocopy" in command
    assert (
        f"type=volume,source={host.TELEGRAM_VOLUME},target=/run/telegram,volume-nocopy,readonly"
        in command
    )
    assert command[-7:] == (
        "python",
        "-m",
        "boca_socios.telegram_one_shot",
        "test",
        SHA,
        "12345",
        "e" * 64,
    )


def test_telegram_test_requires_both_owner_assertions_before_host_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host, "_telegram_installed", lambda *_args: pytest.fail("host probed"))
    for bot, assertion in (("", "e" * 64), ("12345", ""), ("bot", "e" * 64)):
        with pytest.raises(host.PreflightError, match="owner assertion missing"):
            host._telegram_phase(
                "telegram-test", IMAGE, SHA, COMPOSE_SHA, ORIGIN, OWNER, "", bot, assertion
            )


def test_one_shot_result_must_be_verified_before_disposable_removal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host, "_telegram_installed", lambda *_args: True)
    monkeypatch.setattr(host, "_telegram_egress", lambda: None)
    monkeypatch.setattr(host, "_telegram_container", lambda *_args, **_kwargs: ("fixture",))
    monkeypatch.setattr(
        host, "_telegram_test_finished", lambda *_args: pytest.fail("false receipt")
    )
    commands: list[tuple[str, ...]] = []

    def fake_run(*args: str, **_kwargs: object) -> str:
        commands.append(args)
        if args == ("fixture",):
            return (
                "BOCA_TELEGRAM_BOOTSTRAP state=VERIFIED fingerprint=" + "a" * 64
                if len([command for command in commands if command == ("fixture",)]) == 1
                else "BOCA_TELEGRAM_STORAGE state=VERIFIED schema=0007"
            )
        if args[:2] == ("docker", "run"):
            return "BOCA_TELEGRAM_TEST state=NO_GO source_sha=" + SHA
        if args[:3] == ("docker", "network", "ls"):
            return "bridge\nhost\nnone\nboca-socios_boca_private\n" + host.TELEGRAM_NETWORK
        if args[:3] == ("docker", "ps", "-a"):
            return CID
        if args[:2] == ("docker", "rm"):
            pytest.fail("removed without positive one-shot receipt")
        pytest.fail(f"unexpected command {args!r}")

    monkeypatch.setattr(host, "_run", fake_run)
    with pytest.raises(host.PreflightError, match="API acceptance receipt unverified"):
        host._telegram_test_phase(IMAGE, SHA, COMPOSE_SHA, ORIGIN, OWNER, "12345", "e" * 64)
    assert all(command[:2] != ("docker", "rm") for command in commands)


def test_success_removes_only_verified_test_container_then_empty_boca_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host, "_telegram_installed", lambda *_args: True)
    monkeypatch.setattr(host, "_telegram_egress", lambda: None)
    monkeypatch.setattr(host, "_telegram_container", lambda *_args, **_kwargs: ("fixture",))
    monkeypatch.setattr(host, "_telegram_test_finished", lambda *_args: "f" * 64)
    commands: list[tuple[str, ...]] = []

    def fake_run(*args: str, **_kwargs: object) -> str:
        commands.append(args)
        if args == ("fixture",):
            return (
                "BOCA_TELEGRAM_BOOTSTRAP state=VERIFIED fingerprint=" + "a" * 64
                if len([command for command in commands if command == ("fixture",)]) == 1
                else "BOCA_TELEGRAM_STORAGE state=VERIFIED schema=0007"
            )
        if args[:3] == ("docker", "network", "ls"):
            return "bridge\nhost\nnone\nboca-socios_boca_private\n" + host.TELEGRAM_NETWORK
        if args[:3] == ("docker", "ps", "-a"):
            return CID
        if args[:2] == ("docker", "run"):
            return (
                f"BOCA_TELEGRAM_TEST state=API_ACCEPTED source_sha={SHA}"
                " synthetic=1 human_receipt=unverified"
            )
        if args[:2] == ("docker", "rm"):
            return "f" * 64
        if args[:3] == ("docker", "network", "rm"):
            return host.TELEGRAM_NETWORK
        pytest.fail(f"unexpected command {args!r}")

    monkeypatch.setattr(host, "_run", fake_run)
    host._telegram_test_phase(IMAGE, SHA, COMPOSE_SHA, ORIGIN, OWNER, "12345", "e" * 64)
    effects = [
        command[:3]
        for command in commands
        if command[:2] == ("docker", "rm") or command[:3] == ("docker", "network", "rm")
    ]
    assert effects == [("docker", "rm", "f" * 64), ("docker", "network", "rm")]


def test_finished_one_shot_requires_exact_disposable_identity_before_remove(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record()
    record["Name"] = "/boca-socios-telegram-test-1"
    record["Config"]["Cmd"] = [  # type: ignore[index]
        "python",
        "-m",
        "boca_socios.telegram_one_shot",
        "test",
        SHA,
        "12345",
        "e" * 64,
    ]
    record["Config"]["Labels"]["com.docker.compose.service"] = "telegram-test"  # type: ignore[index]
    record["Config"]["Healthcheck"] = {  # type: ignore[index]
        "Test": ["NONE"],
        "Interval": 30_000_000_000,
        "Timeout": 5_000_000_000,
        "StartPeriod": 15_000_000_000,
        "Retries": 3,
    }
    record["Config"]["Env"] = [  # type: ignore[index]
        "BOCA_ENVIRONMENT=staging",
        "BOCA_RUNTIME_MODE=simulation",
        "BOCA_ENGINE_MODE=off",
        "BOCA_TELEGRAM_DISPATCH_MODE=explicit",
    ]
    record["State"] = {"Running": False, "ExitCode": 0}
    record["HostConfig"] = {  # type: ignore[index]
        "NanoCpus": 250_000_000,
        "Memory": 134_217_728,
        "PidsLimit": 32,
        "ReadonlyRootfs": True,
        "Privileged": False,
        "PortBindings": {},
        "PublishAllPorts": False,
        "NetworkMode": host.TELEGRAM_NETWORK,
        "CapDrop": ["ALL"],
        "CapAdd": None,
        "SecurityOpt": ["no-new-privileges"],
        "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=8m"},  # noqa: S108 - private container
    }
    record["Mounts"] = [
        {"Type": "volume", "Name": name, "Destination": dest, "RW": writable, "Driver": "local"}
        for name, dest, writable in (
            (host.DATA_VOLUME, "/data", True),
            (host.TELEGRAM_VOLUME, "/run/telegram", False),
        )
    ]
    record["NetworkSettings"] = {"Ports": {}, "Networks": {}}
    record["Id"] = "f" * 64

    def fake_run(*args: str) -> str:
        if args[:3] == ("docker", "ps", "-a"):
            return CID + "\n" + "f" * 64
        if args[:2] == ("docker", "inspect"):
            return json.dumps(_record() if args[-1] == CID else record)
        if args[:3] == ("docker", "image", "inspect"):
            return IMAGE_ID
        pytest.fail(f"unexpected command {args!r}")

    monkeypatch.setattr(host, "_run", fake_run)
    assert host._telegram_test_finished(IMAGE, SHA, "12345", "e" * 64, CID) == "f" * 64
    record["Mounts"][1]["Name"] = "unrelated_volume"  # type: ignore[index]
    with pytest.raises(host.PreflightError, match="provenance changed"):
        host._telegram_test_finished(IMAGE, SHA, "12345", "e" * 64, CID)


def test_workflow_requires_release_owner_marker_and_same_job_stop() -> None:
    workflow = Path(".github/workflows/boca-first-deploy.yml").read_text()
    assert 'test "$BOCA_TELEGRAM_ENV_READY" = ready' in workflow
    assert "python scripts/check_release_run.py" in workflow
    assert 'start-existing "$BOCA_SOURCE_SHA"' in workflow
    assert "BOCA_TELEGRAM_ENVELOPE: ${{ inputs.telegram_envelope }}" in workflow
    assert (
        "BOCA_TELEGRAM_EXPECTED_CHAT_HMAC: ${{ secrets.BOCA_TELEGRAM_EXPECTED_CHAT_HMAC }}"
        in workflow
    )
    assert 'test "$BOCA_TELEGRAM_OWNER_READY" = ready' in workflow
    assert "telegram-test) pattern='^BOCA_TELEGRAM_TEST state=API_ACCEPTED" in workflow
    assert "sys.stdout.write(_telegram_envelope(sys.argv[1]))" in workflow
    assert "Mark Telegram host attempt before starting existing Boca daemon" in workflow
    assert "always() && startsWith(inputs.operation, 'telegram-')" in workflow
    assert (
        workflow.index("Start only stopped existing dedicated Boca daemon")
        < workflow.index("Execute protected Telegram schema, custody or one-shot test")
        < workflow.index("Stop positively identified Boca services after Telegram custody")
    )
    assert "telegram-test" in workflow and "sendMessage" not in workflow
