"""Cutover and official inventory observers: offline Boca rootless-only regression."""

from __future__ import annotations

import base64
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from boca_socios import host_cutover_inventory_observe as observe
from boca_socios.host_boca_cleanup import (
    BocaJobLease,
    Container,
    DiskInodes,
    Image,
    Inventory,
    Network,
    Volume,
)
from test_host_lifecycle_rootless_adapter import (
    CONTROLLER as OFFICIAL_CONTROLLER,
    CONTROLLER_REF as OFFICIAL_CONTROLLER_REF,
    SOURCE as OFFICIAL_SOURCE,
    WORKER as OFFICIAL_WORKER,
    WORKER_REF as OFFICIAL_WORKER_REF,
    FakeIO as OfficialFakeIO,
)

SOURCE = "a" * 40
TARGET_SOURCE = "b" * 40
CONTROLLER = "1" * 64
IMAGE_ID = "sha256:" + "2" * 64
LEGACY_REF = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "3" * 64
TARGET_REF = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "4" * 64
TARGET_WORKER = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "5" * 64
CONFIG = "6" * 64
PROJECT = "boca-socios"
PRIVATE = "boca-socios_boca_private"
DATA = "boca-socios_boca_data"
KEY = "boca-socios_boca_key"
OWNER = "boca-socios_boca_owner"
STAMP = datetime(2026, 11, 5, 17, 35, tzinfo=UTC)

CUTOVER_RELEASE = observe.ReviewedTargetRelease(
    target_source_sha=TARGET_SOURCE,
    target_controller_image=TARGET_REF,
    target_browser_image=TARGET_WORKER,
    target_release_run_id="42050001",
    observe_run_id="42050002",
)
OFFICIAL_RELEASE = observe.ReviewedTargetRelease(
    target_source_sha=OFFICIAL_SOURCE,
    target_controller_image=OFFICIAL_CONTROLLER_REF,
    target_browser_image=OFFICIAL_WORKER_REF,
    target_release_run_id="42050001",
    observe_run_id="42050002",
)


@pytest.fixture(autouse=True)
def no_real_host_flock(monkeypatch: pytest.MonkeyPatch) -> None:
    def held(lease: BocaJobLease, attempt: str) -> None:
        assert lease.attempt_id == attempt == "42050002" and lease.active

    monkeypatch.setattr(observe, "verify_protected_boca_job_lease", held)


def _lease() -> BocaJobLease:
    return BocaJobLease("42050002", 12, 1, True)


def _encoded(version: str = "boca-cutover-inventory-observe-v1", **changes: str) -> str:
    body = {
        "version": version,
        "target_source_sha": TARGET_SOURCE,
        "target_controller_image": TARGET_REF,
        "target_browser_image": TARGET_WORKER,
        "target_release_run_id": "42050001",
        "observe_run_id": "42050002",
    }
    body.update(changes)
    return (
        base64.urlsafe_b64encode(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("ascii")
        )
        .rstrip(b"=")
        .decode("ascii")
    )


class LegacyFakeIO:
    """Only field lookups, no Docker command, subprocess, network or write."""

    def __init__(self, data_root: Path) -> None:
        self.uid = self.gid = 10001
        labels = tuple(
            sorted(
                {
                    "com.docker.compose.project": PROJECT,
                    "com.docker.compose.service": "controller",
                    "com.docker.compose.container-number": "1",
                    "com.docker.compose.config-hash": CONFIG,
                    "org.opencontainers.image.revision": SOURCE,
                }.items()
            )
        )
        self.inventory_value = Inventory(
            containers=(
                Container(
                    CONTROLLER,
                    "/boca-socios-controller-1",
                    IMAGE_ID,
                    True,
                    labels,
                    tuple(sorted({DATA, KEY, OWNER})),
                    (PRIVATE,),
                ),
            ),
            images=(
                Image(
                    IMAGE_ID,
                    (LEGACY_REF,),
                    "https://github.com/mbalbo2023/boca-socios-assistant",
                ),
            ),
            networks=(Network(PRIVATE, "7" * 64, (CONTROLLER,), ()),),
            volumes=tuple(
                Volume(name, (("com.docker.compose.project", PROJECT),))
                for name in sorted((DATA, KEY, OWNER))
            ),
            disk=DiskInodes(100000, 10000),
        )
        self.reads: list[tuple[str, str, str]] = []
        self.inventory_calls = 0
        self.fields: dict[tuple[str, str, str], object] = {
            ("volume", DATA, "Mountpoint"): str(data_root),
        }
        mount = [
            {
                "Type": "volume",
                "Driver": "local",
                "Name": name,
                "Destination": where,
                "RW": write,
            }
            for name, where, write in (
                (DATA, "/data", True),
                (KEY, "/run/secrets", False),
                (OWNER, "/run/owner", False),
            )
        ]
        model: dict[str, object] = {
            "Config.Image": LEGACY_REF,
            "Config.User": "10001:10001",
            "Config.Cmd": ["python", "-m", "boca_socios.runtime", "serve-beta"],
            "HostConfig.NetworkMode": PRIVATE,
            "HostConfig.RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0},
            "HostConfig.ReadonlyRootfs": True,
            "HostConfig.Privileged": False,
            "HostConfig.PublishAllPorts": False,
            "HostConfig.Init": True,
            "HostConfig.CapDrop": ["ALL"],
            "HostConfig.CapAdd": [],
            "HostConfig.NanoCpus": 500_000_000,
            "HostConfig.Memory": 268_435_456,
            "HostConfig.PidsLimit": 64,
            "HostConfig.PortBindings": {
                "8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]
            },
            "NetworkSettings.Ports": {
                "8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]
            },
            "NetworkSettings.Networks": {PRIVATE: {}},
            "State.Running": True,
            "State.Restarting": False,
            "State.Health.Status": "healthy",
            "RestartCount": 0,
            "Mounts": mount,
        }
        for field, value in model.items():
            self.fields[("container", CONTROLLER, field)] = value

    def inventory(self) -> Inventory:
        self.inventory_calls += 1
        return self.inventory_value

    def field(self, kind: str, ident: str, field: str) -> object:
        self.reads.append((kind, ident, field))
        return self.fields[(kind, ident, field)]


def test_cutover_observe_exact_legacy_singleton_twice_without_effect(tmp_path: Path) -> None:
    io = LegacyFakeIO(tmp_path)
    found = observe.observe_cutover_inventory(
        CUTOVER_RELEASE, lease=_lease(), io=io, observed_at=STAMP
    )
    assert found["version"] == "boca-cutover-inventory-observe-v1"
    assert found["kind"] == "cutover-inventory"
    assert found["legacy_controller_id"] == CONTROLLER
    assert found["legacy_source_sha"] == SOURCE
    assert found["legacy_image_ref"] == LEGACY_REF
    assert found["legacy_image_id"] == IMAGE_ID
    assert found["legacy_compose_config_hash"] == CONFIG
    assert found["target_release_run_id"] == "42050001"
    assert found["observed_at_utc"] == "2026-11-05T17:35:00Z"
    assert found["port"] == "127.0.0.1:8443"
    assert "legacy_release_run_id" not in found
    assert "legacy_compose_file_sha256" not in found
    assert "password" not in found and "token" not in found
    assert io.inventory_calls == 2
    assert set(kind for kind, _, _ in io.reads) <= {"container", "volume"}
    assert all("Env" not in field for _, _, field in io.reads)


@pytest.mark.parametrize(
    "name",
    [
        "foreign_container",
        "stale_source",
        "wrong_image_digest",
        "unreviewed_image",
        "foreign_network",
        "wrong_project",
        "wrong_port",
        "unhealthy",
        "bad_uid",
        "owner_mount_changed",
        "other_volume",
        "missing_config_hash",
        "extra_cap",
        "different_target",
    ],
)
def test_cutover_refuses_unproven_topology_without_effect(
    tmp_path: Path, name: str
) -> None:
    io = LegacyFakeIO(tmp_path)
    release = CUTOVER_RELEASE
    container = io.inventory_value.containers[0]
    if name == "foreign_container":
        io.inventory_value = replace(
            io.inventory_value,
            containers=(
                container,
                replace(container, ident="a" * 64, name="/foreign-app-1"),
            ),
        )
    elif name == "stale_source":
        io.inventory_value = replace(
            io.inventory_value,
            containers=(
                replace(
                    container,
                    labels=tuple(
                        (key, "x" * 40 if key == "org.opencontainers.image.revision" else val)
                        for key, val in container.labels
                    ),
                ),
            ),
        )
    elif name == "wrong_image_digest":
        io.fields[("container", CONTROLLER, "Config.Image")] = TARGET_REF
    elif name == "unreviewed_image":
        io.inventory_value = replace(
            io.inventory_value,
            images=(replace(io.inventory_value.images[0], source="https://other.invalid"),),
        )
    elif name == "foreign_network":
        io.inventory_value = replace(
            io.inventory_value,
            networks=(
                *io.inventory_value.networks,
                Network("another-app", "9" * 64, (), ()),
            ),
        )
    elif name == "wrong_project":
        io.inventory_value = replace(
            io.inventory_value,
            containers=(
                replace(
                    container,
                    labels=tuple(
                        (key, "foreign" if key == "com.docker.compose.project" else val)
                        for key, val in container.labels
                    ),
                ),
            ),
        )
    elif name == "wrong_port":
        io.fields[("container", CONTROLLER, "HostConfig.PortBindings")] = {
            "8443/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8443"}]
        }
    elif name == "unhealthy":
        io.fields[("container", CONTROLLER, "State.Health.Status")] = "unhealthy"
    elif name == "bad_uid":
        io.uid = 0
    elif name == "owner_mount_changed":
        io.fields[("container", CONTROLLER, "Mounts")] = []
    elif name == "other_volume":
        io.inventory_value = replace(
            io.inventory_value,
            volumes=(
                *io.inventory_value.volumes,
                Volume("other-owner-data", (("com.docker.compose.project", "foreign"),)),
            ),
        )
    elif name == "missing_config_hash":
        io.inventory_value = replace(
            io.inventory_value,
            containers=(
                replace(
                    container,
                    labels=tuple(
                        (key, val)
                        for key, val in container.labels
                        if key != "com.docker.compose.config-hash"
                    ),
                ),
            ),
        )
    elif name == "extra_cap":
        io.fields[("container", CONTROLLER, "HostConfig.CapAdd")] = ["SYS_ADMIN"]
    elif name == "different_target":
        release = replace(CUTOVER_RELEASE, target_source_sha=SOURCE)
    with pytest.raises(observe.CutoverInventoryNoGo):
        observe.observe_cutover_inventory(release, lease=_lease(), io=io, observed_at=STAMP)
    assert all("Env" not in field for _, _, field in io.reads)


def test_cutover_fails_on_second_observation_identity_change(tmp_path: Path) -> None:
    class Drifting(LegacyFakeIO):
        def inventory(self) -> Inventory:
            result = super().inventory()
            if self.inventory_calls == 2:
                controller = result.containers[0]
                return replace(
                    result,
                    containers=(replace(controller, ident="8" * 64),),
                )
            return result

    with pytest.raises(observe.CutoverInventoryNoGo):
        observe.observe_cutover_inventory(
            CUTOVER_RELEASE, lease=_lease(), io=Drifting(tmp_path), observed_at=STAMP
        )


def test_reviewed_context_is_canonical_and_rejects_duplicate_or_unknown_fields() -> None:
    assert observe.decode_observe_input(_encoded()) == CUTOVER_RELEASE
    with pytest.raises(observe.CutoverInventoryNoGo):
        observe.decode_observe_input(_encoded(target_release_run_id="invalid"))
    with pytest.raises(observe.CutoverInventoryNoGo):
        observe.decode_observe_input(_encoded(source_sha=SOURCE))
    with pytest.raises(observe.CutoverInventoryNoGo):
        observe.decode_observe_input(_encoded(version="other-version"))
    with pytest.raises(observe.CutoverInventoryNoGo):
        observe.decode_observe_input(_encoded() + "=")
    duplicate = (
        b'{"observe_run_id":"42050002","observe_run_id":"42050002",'
        b'"target_browser_image":"x","target_controller_image":"y",'
        b'"target_release_run_id":"42050001","target_source_sha":"a","version":"z"}'
    )
    with pytest.raises(observe.CutoverInventoryNoGo):
        observe.decode_observe_input(
            base64.urlsafe_b64encode(duplicate).rstrip(b"=").decode("ascii")
        )
    assert (
        observe.decode_observe_input(
            _encoded(version="boca-official-inventory-observe-v1"),
            expected_version="boca-official-inventory-observe-v1",
        )
        == CUTOVER_RELEASE
    )
    with pytest.raises(observe.CutoverInventoryNoGo):
        observe.decode_observe_input(_encoded(), expected_version="unsupported")


def test_invalid_no_arg_cli_never_opens_host_lease(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def denied(_attempt: str) -> None:
        raise AssertionError("host lease must never open")

    monkeypatch.setattr(observe, "protected_boca_job_lease", denied)
    assert observe.main([]) == 3
    assert observe.official_main([]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("state=NO_GO") == 2


def test_utc_receipt_requires_known_utc_datetime(tmp_path: Path) -> None:
    io = LegacyFakeIO(tmp_path)
    with pytest.raises(observe.CutoverInventoryNoGo):
        observe.observe_cutover_inventory(
            CUTOVER_RELEASE,
            lease=_lease(),
            io=io,
            observed_at=datetime(2026, 11, 5),
        )


def _official_io(tmp_path: Path, *, sender_running: bool | None = None) -> OfficialFakeIO:
    io = OfficialFakeIO(tmp_path, sender_running=sender_running)
    io.inventory_value = replace(
        io.inventory_value,
        volumes=tuple(
            replace(volume, labels=(("com.docker.compose.project", PROJECT),))
            for volume in io.inventory_value.volumes
        ),
    )
    return io


@pytest.mark.parametrize("sender_running", [None, False, True])
def test_official_inventory_without_owner_request_or_engine_effects(
    tmp_path: Path, sender_running: bool | None
) -> None:
    io = _official_io(tmp_path, sender_running=sender_running)
    receipt = observe.observe_official_inventory(
        OFFICIAL_RELEASE, lease=_lease(), io=io, observed_at=STAMP
    )
    assert receipt["version"] == "boca-official-inventory-observe-v1"
    assert receipt["kind"] == "official-inventory"
    assert receipt["source_sha"] == OFFICIAL_SOURCE
    assert receipt["controller_id"] == OFFICIAL_CONTROLLER
    assert receipt["worker_id"] == OFFICIAL_WORKER
    assert receipt["controller_image"] == OFFICIAL_CONTROLLER_REF
    assert receipt["worker_image"] == OFFICIAL_WORKER_REF
    assert receipt["release_run_id"] == OFFICIAL_RELEASE.target_release_run_id
    assert receipt["observed_at_utc"] == "2026-11-05T17:35:00Z"
    assert ("sender_id" in receipt) is (sender_running is not None)
    assert io.effects == []


@pytest.mark.parametrize(
    "break_kind",
    ["wrong_current_sha", "wrong_image", "foreign_app", "wrong_port", "owner_volume"],
)
def test_official_refuses_current_topology_drift_without_mutations(
    tmp_path: Path, break_kind: str
) -> None:
    io = _official_io(tmp_path)
    if break_kind == "wrong_current_sha":
        wrong = replace(OFFICIAL_RELEASE, target_source_sha=TARGET_SOURCE)
        with pytest.raises(observe.CutoverInventoryNoGo):
            observe.observe_official_inventory(wrong, lease=_lease(), io=io)
        assert io.effects == []
        return
    if break_kind == "wrong_image":
        io.fields[("container", OFFICIAL_CONTROLLER, "Config.Image")] = TARGET_REF
    elif break_kind == "foreign_app":
        io.inventory_value = replace(
            io.inventory_value,
            containers=(
                *io.inventory_value.containers,
                replace(io.inventory_value.containers[0], ident="a" * 64),
            ),
        )
    elif break_kind == "wrong_port":
        io.fields[("container", OFFICIAL_CONTROLLER, "NetworkSettings.Ports")] = {
            "8443/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8443"}]
        }
    elif break_kind == "owner_volume":
        io.inventory_value = replace(
            io.inventory_value,
            volumes=tuple(volume for volume in io.inventory_value.volumes if volume.name != OWNER),
        )
    with pytest.raises(observe.CutoverInventoryNoGo):
        observe.observe_official_inventory(OFFICIAL_RELEASE, lease=_lease(), io=io)
    assert io.effects == []


def test_observer_official_selftests_are_pure_without_host() -> None:
    assert observe.selftest_main() == 0
    assert observe.official_selftest_main() == 0
