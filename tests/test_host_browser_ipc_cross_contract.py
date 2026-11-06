"""Real host installer argv must be recognizable by the separate cleaner.

No Docker CLI, daemon, SSH, host filesystem or provider is contacted. The
installer produces the seven actual named ``docker run`` commands. An
independent command-line decoder then models the corresponding inspect record,
without consulting the cleanup module's expected probe specification.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from boca_socios import host_cleanup as cleanup
from boca_socios import host_first_deploy as installer

CONTROLLER_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64
BROWSER_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "b" * 64
SOURCE = "c" * 40
BETA_SHA = "d" * 64
OVERLAY_SHA = "e" * 64
SECCOMP_SHA = "f" * 64
ATTEMPT = "123456789"
ORIGIN = "http://localhost:8443"
OWNER = "synthetic-owner"
PROBES = (
    "ipc-dir-init",
    "synthetic-ipc",
    "owner-check",
    "key-init",
    "key-verify",
    "config-check",
    "data-init",
)


@pytest.fixture
def actual_named_runs(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    """Execute the *actual* C2c apply call graph, capturing only its Docker argv."""
    measured = object()
    marker = {"controller_image_absent": True, "browser_image_absent": True}
    for name, fake in (
        ("_browser_engine_version", lambda: None),
        ("_browser_read_marker", lambda *args: marker),
        ("_browser_verify_staged", lambda *args: None),
        ("_browser_staged_inventory", lambda **kwargs: None),
        ("_browser_inventory", lambda **kwargs: None),
        ("_browser_port_free", lambda: None),
        ("_browser_capacity", lambda **kwargs: (1_600_000, 2.0, 300, measured)),
        ("_browser_image_absent", lambda *args: True),
        ("_browser_compose_model", lambda *args: "{}"),
        ("_browser_pull_both", lambda *args: None),
        ("_browser_worker_network_inventory", lambda: set()),
        ("_browser_validate_ipc_volume", lambda *args: None),
        ("_browser_worker_postflight", lambda *args: None),
        ("_browser_controller_postflight", lambda *args: None),
        ("_beta_loopback_health", lambda *args: None),
        ("_beta_check_receipt", lambda *args: None),
        ("_validate_key_volume", lambda: None),
        ("_validate_owner_volume", lambda: None),
        ("_validate_data_volume", lambda: None),
        ("_storage_snapshot", lambda: measured),
        ("_validate_storage_continuity", lambda *args, **kwargs: None),
    ):
        monkeypatch.setattr(installer, name, fake)
    monkeypatch.setattr(
        installer,
        "_browser_service_id",
        lambda name, *args: "1" * 64 if name == "browser-worker" else "2" * 64,
    )

    runs: list[tuple[str, ...]] = []

    def no_docker(*args: str, **kwargs: object) -> str:
        if args[:2] == ("docker", "run"):
            runs.append(args)
            label = next(
                value for value in args if value.startswith("boca.socios.browser-ipc-phase=")
            )
            phase = label.partition("=")[2]
            return {
                "ipc-dir-init": "BOCA_BROWSER_IPC_DIR_PASS",
                "synthetic-ipc": "BOCA_BROWSER_IPC_SYNTHETIC_PASS",
                "key-init": "BOCA_KEY_READY",
                "key-verify": "BOCA_KEY_READY",
            }.get(phase, "")
        if args[:3] == ("docker", "volume", "create"):
            return args[-1]
        if args[:2] == ("docker", "compose") and "up" in args:
            assert args[-1] in {"browser-worker", "controller"}
            return ""
        raise AssertionError(f"Unreviewed Docker attempt: {args}")

    monkeypatch.setattr(installer, "_run", no_docker)
    installer._browser_apply(
        CONTROLLER_IMAGE,
        SOURCE,
        BETA_SHA,
        ORIGIN,
        OWNER,
        BROWSER_IMAGE,
        OVERLAY_SHA,
        SECCOMP_SHA,
        ATTEMPT,
    )
    return runs


def _option_values(
    command: tuple[str, ...],
) -> tuple[set[str], dict[str, list[str]], str, list[str]]:
    """Parse Docker's small reviewed CLI subset, without a C2b expected spec."""
    assert command[:2] == ("docker", "run")
    switches: set[str] = set()
    options: dict[str, list[str]] = {}
    takes_value = {
        "--name",
        "--label",
        "--pull",
        "--user",
        "--network",
        "--cap-drop",
        "--cap-add",
        "--security-opt",
        "--pids-limit",
        "--memory",
        "--cpus",
        "--env",
        "--mount",
    }
    index = 2
    while index < len(command) and command[index].startswith("--"):
        option = command[index]
        if option in {"--rm", "--read-only", "--ipc=private", "--cgroupns=private"}:
            assert option not in switches
            switches.add(option)
            index += 1
        else:
            assert option in takes_value and index + 1 < len(command)
            options.setdefault(option, []).append(command[index + 1])
            index += 2
    assert index < len(command)
    return switches, options, command[index], list(command[index + 1 :])


def _inspect_from_actual_run(command: tuple[str, ...], container_id: str) -> dict[str, Any]:
    """Model Docker's inspect fields from actual CLI flags, not cleaner constants."""
    switches, options, image, argv = _option_values(command)

    def single(name: str) -> str:
        values = options[name]
        assert len(values) == 1
        return values[0]

    labels = {"org.opencontainers.image.revision": SOURCE}  # inherited pinned image label
    for raw_label in options.get("--label", []):
        name, separator, value = raw_label.partition("=")
        assert separator == "=" and name not in labels
        labels[name] = value
    mounts: list[dict[str, object]] = []
    for value in options.get("--mount", []):
        fragments = value.split(",")
        attributes = dict(fragment.split("=", 1) for fragment in fragments if "=" in fragment)
        assert attributes.get("type") == "volume"
        mounts.append(
            {
                "Type": "volume",
                "Name": attributes["source"],
                "Destination": attributes["target"],
                "RW": "readonly" not in fragments,
                "Driver": "local",
            }
        )
    return {
        "Id": container_id,
        "Name": "/" + single("--name"),
        "Config": {
            "Image": image,
            "User": single("--user"),
            "Cmd": argv,
            "Entrypoint": None,
            "Labels": labels,
            "Env": options.get("--env", []),
        },
        "HostConfig": {
            "ReadonlyRootfs": "--read-only" in switches,
            "Privileged": False,
            "RestartPolicy": {"Name": "no"},
            "NetworkMode": single("--network"),
            "PidMode": "",  # Docker CLI default, no --pid parameter
            "IpcMode": "private" if "--ipc=private" in switches else "",
            "CgroupnsMode": "private" if "--cgroupns=private" in switches else "",
            "UsernsMode": "",
            "UTSMode": "",
            "Init": None,
            "AutoRemove": "--rm" in switches,
            "PortBindings": {},
            "CapDrop": options.get("--cap-drop", []),
            "CapAdd": options.get("--cap-add"),
            "SecurityOpt": options.get("--security-opt", []),
            "Devices": None,
            "PublishAllPorts": False,
            "PidsLimit": int(single("--pids-limit")),
            "Memory": int(single("--memory").removesuffix("m")) * 1024**2,
            "NanoCpus": int(Decimal(single("--cpus")) * 1_000_000_000),
        },
        "Mounts": mounts,
        "NetworkSettings": {"Ports": {}, "Networks": {"none": {}}},
        "State": {"Running": True, "Restarting": False},
    }


def _cleanup_probe_inventory(
    monkeypatch: pytest.MonkeyPatch, records: dict[str, dict[str, Any]]
) -> dict[str, str]:
    """Read-only fake Docker census returns records derived only from C2c argv."""
    ids = "\n".join(records)

    def no_docker(*args: str) -> str:
        if args[:2] == ("ps", "-a"):
            return ids
        if args[:2] == ("container", "inspect"):
            return json.dumps(records[args[-1]])
        raise AssertionError(f"Cleanup attempted a Docker mutation: {args}")

    monkeypatch.setattr(cleanup, "_run", no_docker)
    return cleanup._browser_ipc_container_ids(CONTROLLER_IMAGE, SOURCE, BROWSER_IMAGE, ATTEMPT, {})


def test_seven_actual_installer_probes_match_cleanup_positive_identity(
    actual_named_runs: list[tuple[str, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert len(actual_named_runs) == len(PROBES) == 7
    assert [
        next(
            value.partition("=")[2]
            for value in cmd
            if value.startswith("boca.socios.browser-ipc-phase=")
        )
        for cmd in actual_named_runs
    ] == list(PROBES)
    for command in actual_named_runs:
        switches, options, image, argv = _option_values(command)
        phase = next(
            value.partition("=")[2]
            for value in options["--label"]
            if value.startswith("boca.socios.browser-ipc-phase=")
        )
        spec = cleanup._browser_ipc_probe_spec(phase)
        assert spec is not None
        record = _inspect_from_actual_run(command, "1" * 64)
        actual_mounts = frozenset(
            (mount["Name"], mount["Destination"], mount["RW"]) for mount in record["Mounts"]
        )
        assert image == (BROWSER_IMAGE if spec.image_is_browser else CONTROLLER_IMAGE)
        assert record["Config"]["User"] == spec.user
        assert argv == list(spec.command)
        assert actual_mounts == spec.mounts
        assert tuple(options.get("--cap-add", [])) == spec.capabilities
        assert int(options["--pids-limit"][0]) == spec.pids
        assert record["HostConfig"]["Memory"] == spec.memory
        assert record["HostConfig"]["NanoCpus"] == spec.nano_cpus
        assert "--rm" in switches
        assert "--ipc=private" in switches and "--cgroupns=private" in switches
        assert _cleanup_probe_inventory(monkeypatch, {"1" * 64: record}) == {"probe": "1" * 64}


@pytest.mark.parametrize(
    "tamper",
    ["user", "image", "command", "mount", "capability", "labels", "autoremove"],
)
def test_cleanup_rejects_tampered_actual_probe_without_docker_mutation(
    actual_named_runs: list[tuple[str, ...]], monkeypatch: pytest.MonkeyPatch, tamper: str
) -> None:
    record = _inspect_from_actual_run(actual_named_runs[0], "1" * 64)
    if tamper == "user":
        record["Config"]["User"] = "30000:30000"
    elif tamper == "image":
        record["Config"]["Image"] = CONTROLLER_IMAGE
    elif tamper == "command":
        record["Config"]["Cmd"] = ["sh", "-c", "unreviewed"]
    elif tamper == "mount":
        record["Mounts"][0]["Destination"] = "/foreign"
    elif tamper == "capability":
        record["HostConfig"]["CapAdd"].append("SYS_ADMIN")
    elif tamper == "labels":
        record["Config"]["Labels"].pop(cleanup.BROWSER_IPC_PROBE_PHASE_LABEL)
    else:
        record["HostConfig"]["AutoRemove"] = False
    with pytest.raises(cleanup.CleanupError):
        _cleanup_probe_inventory(monkeypatch, {"1" * 64: record})


def test_overlapping_actual_named_probes_fail_closed_as_nonsequential(
    actual_named_runs: list[tuple[str, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    records = {
        "1" * 64: _inspect_from_actual_run(actual_named_runs[0], "1" * 64),
        "2" * 64: _inspect_from_actual_run(actual_named_runs[1], "2" * 64),
    }
    with pytest.raises(cleanup.CleanupError, match="multiple containers"):
        _cleanup_probe_inventory(monkeypatch, records)
