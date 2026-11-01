"""Issue #225: owner URL enrollment must remain entirely Boca scoped."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from boca_socios import host_first_deploy as host

IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64
SHA = "b" * 40
DIGEST = "c" * 64
ORIGIN = "http://localhost:8443"
SUBJECT = "synthetic-owner"
CONTAINER_ID = "d" * 64


def test_enrollment_container_has_one_host_loopback_port_and_disposable_mount() -> None:
    args = host._owner_enroll_container(IMAGE, SHA, SUBJECT, DIGEST, "A" * 43, "b" * 64)
    assert args[:3] == ("docker", "run", "--detach")
    assert args[args.index("--publish") + 1] == "127.0.0.1:8443:8443/tcp"
    assert args[args.index("--network") + 1] == host.ENROLL_NETWORK
    assert args[args.index("--user") + 1] == "10001:10001"
    assert args[args.index("--cap-drop") + 1] == "ALL"
    assert "--read-only" in args and "--privileged" not in args
    assert "--restart" in args and args[args.index("--restart") + 1] == "no"
    mounts = [args[index + 1] for index, part in enumerate(args[:-1]) if part == "--mount"]
    assert mounts == [
        f"type=volume,source={host.ENROLL_VOLUME},target=/run/enrollment,volume-nocopy"
    ]
    assert all("boca_owner" not in a and "boca_key" not in a and "boca_data" not in a for a in args)
    assert not any("docker.sock" in a or "--network=host" in a for a in args)
    assert args[-5:] == ("boca_socios.owner_enrollment", SUBJECT, DIGEST, "A" * 43, "b" * 64)


def test_offline_staged_import_is_no_network_with_readonly_staging() -> None:
    args = host._owner_container(IMAGE, "install-staged", ORIGIN, SUBJECT)
    mounts = [args[index + 1] for index, part in enumerate(args[:-1]) if part == "--mount"]
    assert len(mounts) == 2
    assert f"type=volume,source={host.OWNER_VOLUME},target=/run/owner,volume-nocopy" in mounts
    assert (
        f"type=volume,source={host.ENROLL_VOLUME},target=/run/enrollment,volume-nocopy,readonly"
        in mounts
    )
    assert args[args.index("--network") + 1] == "none"
    assert args[args.index("--user") + 1] == "10001:10001"
    assert "-i" not in args and "--publish" not in args and "--rm" in args


def test_inspect_prepared_is_offline_readonly_owner_and_not_mutating() -> None:
    args = host._owner_container(IMAGE, "inspect-prepared", ORIGIN, SUBJECT)
    mounts = [args[index + 1] for index, part in enumerate(args[:-1]) if part == "--mount"]
    assert mounts == [
        f"type=volume,source={host.OWNER_VOLUME},target=/run/owner,volume-nocopy,readonly"
    ]
    assert args[args.index("--network") + 1] == "none"
    assert args[-3:] == (
        "inspect-prepared",
        ORIGIN,
        SUBJECT,
    )


def test_invalid_capability_digest_rejected_before_docker_or_host_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host, "_validate_docker_boundary", lambda: pytest.fail("Docker queried"))
    with pytest.raises(host.PreflightError, match="capability"):
        host.phase(
            "owner-enroll-start",
            IMAGE,
            SHA,
            "d" * 64,
            ORIGIN,
            SUBJECT,
            enroll_digest="not-a-256-bit-digest",
        )


def test_busy_8443_blocks_staging_and_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(host, "_owner_enroll_preflight", lambda *_: calls.append("preflight"))
    monkeypatch.setattr(host, "_owner_enroll_port_free", lambda: False)
    monkeypatch.setattr(host, "_run", lambda *_a, **_k: pytest.fail("Docker mutated"))
    with pytest.raises(host.PreflightError, match="port"):
        host._owner_enroll_start(IMAGE, SHA, ORIGIN, SUBJECT, DIGEST)
    assert calls == ["preflight"]


def test_preexisting_image_detection_uses_exact_inspect_not_digest_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []

    def available(*argv: str) -> str:
        commands.append(argv)
        return '{"RepoDigests":[]}'  # Missing from image-ls text is not absence.

    monkeypatch.setattr(host, "_run", available)
    assert host._owner_enroll_image_preexisting(IMAGE) is True
    assert commands == [("docker", "image", "inspect", "--format", "{{json .}}", IMAGE)]


@pytest.mark.parametrize(
    ("error", "absent"),
    [
        ("Error response from daemon: No such image: ", True),
        ("Cannot connect to the Docker daemon: ", False),
        ("Error: permission denied for ", False),
    ],
)
def test_image_absence_does_not_misclassify_docker_errors_as_disposable(
    monkeypatch: pytest.MonkeyPatch, error: str, absent: bool
) -> None:
    def failure(*argv: str) -> str:
        command = subprocess.CalledProcessError(1, argv, stderr=error + IMAGE)
        raise host.PreflightError("query failed") from command

    monkeypatch.setattr(host, "_run", failure)
    if absent:
        assert host._owner_enroll_image_preexisting(IMAGE) is False
    else:
        with pytest.raises(host.PreflightError, match="query failed"):
            host._owner_enroll_image_preexisting(IMAGE)


def _container_metadata() -> dict[str, object]:
    return {
        "Id": CONTAINER_ID,
        "Name": "/" + host.ENROLL_CONTAINER,
        "Config": {
            "Image": IMAGE,
            "User": "10001:10001",
            "Labels": {
                "com.docker.compose.project": host.PROJECT,
                "com.docker.compose.service": "owner-enroll",
                "org.opencontainers.image.revision": SHA,
            },
        },
        "HostConfig": {
            "NetworkMode": host.ENROLL_NETWORK,
            "PortBindings": {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]},
            "ReadonlyRootfs": True,
            "Privileged": False,
            "CapDrop": ["ALL"],
            "PidsLimit": 32,
            "Memory": 128 * 1024**2,
            "NanoCpus": 500_000_000,
        },
        "NetworkSettings": {"Networks": {host.ENROLL_NETWORK: {}}},
        "Mounts": [
            {
                "Type": "volume",
                "Name": host.ENROLL_VOLUME,
                "Destination": "/run/enrollment",
                "RW": True,
            }
        ],
        "State": {"Running": True, "Restarting": False, "ExitCode": 0},
    }


@pytest.mark.parametrize(
    "tamper", ["foreign-port", "foreign-mount", "root-user", "wrong-image", "other-network"]
)
def test_container_inspection_refuses_foreign_identity_before_offline_import(
    monkeypatch: pytest.MonkeyPatch, tamper: str
) -> None:
    metadata = _container_metadata()
    config = metadata["Config"]
    host_config = metadata["HostConfig"]
    mounts = metadata["Mounts"]
    assert isinstance(config, dict) and isinstance(host_config, dict) and isinstance(mounts, list)
    if tamper == "foreign-port":
        host_config["PortBindings"] = {"8443/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8443"}]}  # noqa: S104 - rejected fixture
    elif tamper == "foreign-mount":
        mounts.append(
            {"Type": "volume", "Name": host.OWNER_VOLUME, "Destination": "/run/owner", "RW": True}
        )
    elif tamper == "root-user":
        config["User"] = "0:0"
    elif tamper == "other-network":
        networks = metadata["NetworkSettings"]
        assert isinstance(networks, dict) and isinstance(networks["Networks"], dict)
        networks["Networks"]["foreign"] = {}
    else:
        config["Image"] = IMAGE.replace("a" * 64, "f" * 64)

    def fake_run(*argv: str, **_kwargs: object) -> str:
        if argv[1:4] == ("ps", "-a", "-q"):
            return CONTAINER_ID
        if argv[1:3] == ("container", "inspect"):
            return json.dumps(metadata)
        pytest.fail(f"unexpected Docker command: {argv}")

    monkeypatch.setattr(host, "_run", fake_run)
    with pytest.raises(host.PreflightError, match="identity or exposure"):
        host._owner_enroll_container_state(IMAGE, SHA)


def test_offline_install_happens_only_after_http_stops_and_verify_matches(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    actions: list[str] = []
    states = iter([(CONTAINER_ID, True, 0), (CONTAINER_ID, False, 0), (CONTAINER_ID, False, 0)])
    monkeypatch.setattr(host, "_owner_enroll_read_marker", lambda *_args: False)
    monkeypatch.setattr(host, "_validate_owner_volume", lambda: actions.append("owner-validated"))
    monkeypatch.setattr(host, "_owner_enroll_container_state", lambda *_args: next(states))
    monkeypatch.setattr(
        host, "_owner_enroll_network", lambda *_args: actions.append("network-validated")
    )
    monkeypatch.setattr(host, "_owner_enroll_volume", lambda: actions.append("staging-validated"))
    monkeypatch.setattr(host, "_owner_container", lambda _image, phase, *_args: ("docker", phase))

    def fake_run(*argv: str, input_data: str | None = None, timeout: float = 120) -> str:
        actions.append(argv[1])
        if argv[1] == "wait":
            assert timeout == 930 and input_data is None
            return "0"
        if argv[1] == "install-staged":
            assert input_data is None
            return "BOCA_OWNER_BOOTSTRAP state=CONFIGURED fingerprint=" + "e" * 64
        if argv[1] == "verify":
            assert input_data is None
            return "BOCA_OWNER_BOOTSTRAP state=VERIFIED fingerprint=" + "e" * 64
        pytest.fail(f"unexpected command {argv}")

    monkeypatch.setattr(host, "_run", fake_run)
    host._owner_enroll_wait(IMAGE, SHA, "f" * 64, ORIGIN, SUBJECT, DIGEST)
    host._owner_enroll_finish(IMAGE, SHA, "f" * 64, ORIGIN, SUBJECT, DIGEST)
    assert actions.index("wait") < actions.index("install-staged") < actions.index("verify")
    receipt = capsys.readouterr().out
    assert "state=PROOF_STAGED" in receipt
    assert "state=CONFIGURED_VERIFIED" in receipt
    assert "ciphertext" not in receipt


def test_failed_browser_proof_never_reaches_owner_volume_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host, "_owner_enroll_read_marker", lambda *_args: False)
    monkeypatch.setattr(host, "_validate_owner_volume", lambda: None)
    monkeypatch.setattr(
        host, "_owner_enroll_container_state", lambda *_args: (CONTAINER_ID, True, 0)
    )
    monkeypatch.setattr(host, "_owner_enroll_network", lambda *_args: None)
    monkeypatch.setattr(host, "_owner_container", lambda *_args: pytest.fail("private volume used"))
    monkeypatch.setattr(host, "_run", lambda *_args, **_kwargs: "1")
    with pytest.raises(host.PreflightError, match="not completed"):
        host._owner_enroll_wait(IMAGE, SHA, "f" * 64, ORIGIN, SUBJECT, DIGEST)


def test_lifecycle_workflow_enforces_same_job_cleanup_before_daemon_stop() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
    ).read_text(encoding="utf-8")
    assert "options: [inspect-prerequisites" in workflow and "owner-enroll" in workflow
    assert "owner_capability_sha256:" in workflow
    assert "BOCA_OWNER_CAPABILITY_SHA256" in workflow
    assert "if: always() && inputs.operation == 'owner-enroll'" in workflow
    start = workflow.index("Start disposable owner enrollment only on Boca loopback 8443")
    wait = workflow.index("Wait only for one-use Chrome proof to reach offline staging")
    final_gate = workflow.index("Recheck current main after Chrome proof")
    finish = workflow.index("Finish one-use Chrome enrollment with offline owner custody")
    cleanup = workflow.index("Clean Boca-only disposable owner enrollment artifacts")
    stop = workflow.index("Stop only Boca services and daemon after owner custody")
    assert start < wait < final_gate < finish < cleanup < stop
    assert "--enroll" in workflow[cleanup:stop]
    assert "src/boca_socios/host_cleanup.py" in workflow[cleanup:stop]
    assert (
        "owner-enroll"
        not in workflow[
            workflow.index(
                "Prepare, install or verify only Boca owner-volume public passkey custody"
            ) : start
        ]
        .split("if:", 1)[1]
        .split("\n", 1)[0]
    )
