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


def test_workflow_requires_release_owner_marker_and_same_job_stop() -> None:
    workflow = Path(".github/workflows/boca-first-deploy.yml").read_text()
    assert 'test "$BOCA_TELEGRAM_ENV_READY" = ready' in workflow
    assert "python scripts/check_release_run.py" in workflow
    assert 'start-existing "$BOCA_SOURCE_SHA"' in workflow
    assert "BOCA_TELEGRAM_ENVELOPE: ${{ inputs.telegram_envelope }}" in workflow
    assert "sys.stdout.write(_telegram_envelope(sys.argv[1]))" in workflow
    assert "Mark Telegram host attempt before starting existing Boca daemon" in workflow
    assert "always() && startsWith(inputs.operation, 'telegram-')" in workflow
    assert (
        workflow.index("Start only stopped existing dedicated Boca daemon")
        < workflow.index("Execute offline Telegram schema or sealed custody phase")
        < workflow.index("Stop positively identified Boca services after Telegram custody")
    )
    assert "telegram-test" not in workflow and "sendMessage" not in workflow
