"""Offline post-install cleanup contract for #323; no Docker daemon or host."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from boca_socios import host_boca_cleanup as gc

ATTEMPT = "41897569929"
BOCA = (("com.docker.compose.project", "boca-socios"),)
OWNED = (*BOCA, ("boca.socios.cutover-a-attempt", ATTEMPT))
ACTIVE_ID = "1" * 64
OLD_ID = "2" * 64
FOREIGN_ID = "3" * 64
ACTIVE_IMAGE = "sha256:" + "a" * 64
OLD_IMAGE = "sha256:" + "b" * 64
FOREIGN_IMAGE = "sha256:" + "c" * 64
PRIVATE_NET = "4" * 64
STALE_NET = "5" * 64
DATA = "boca-socios_boca_data"
IPC = "boca-socios_boca_browser_ipc"


def _inventory() -> gc.Inventory:
    return gc.Inventory(
        containers=(
            gc.Container(
                ACTIVE_ID,
                "/boca-socios-controller-1",
                ACTIVE_IMAGE,
                True,
                BOCA,
                (DATA,),
                ("boca-socios_boca_private",),
            ),
            gc.Container(
                OLD_ID,
                "/boca-socios-browser-worker-old",
                OLD_IMAGE,
                False,
                OWNED,
            ),
            gc.Container(
                FOREIGN_ID,
                "/porota-worker",
                FOREIGN_IMAGE,
                True,
                (("com.docker.compose.project", "porota"),),
            ),
        ),
        images=(
            gc.Image(
                ACTIVE_IMAGE,
                ("ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "d" * 64,),
                gc.BOCA_SOURCE,
            ),
            gc.Image(
                OLD_IMAGE,
                ("ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "e" * 64,),
                gc.BOCA_SOURCE,
            ),
            gc.Image(FOREIGN_IMAGE, ("ghcr.io/example/porota@sha256:" + "f" * 64,), None),
        ),
        networks=(
            gc.Network("boca-socios_boca_private", PRIVATE_NET, (ACTIVE_ID,), BOCA),
            gc.Network("boca-socios_browser_old", STALE_NET, (), OWNED),
        ),
        volumes=(
            gc.Volume(DATA, BOCA),
            gc.Volume("boca-socios_boca_key", BOCA),
            gc.Volume("boca-socios_boca_owner", BOCA),
            gc.Volume(IPC, OWNED),
        ),
        disk=gc.DiskInodes(12_000_000, 44_000),
    )


def _probe_and_delete(
    inventory: gc.Inventory,
    *,
    delete_failure: bool = False,
    drift: bool = False,
) -> tuple[Callable[[], gc.Inventory], Callable[[gc.Target], None], list[gc.Target]]:
    live = {
        "containers": list(inventory.containers),
        "images": list(inventory.images),
        "networks": list(inventory.networks),
        "volumes": list(inventory.volumes),
    }
    deleted: list[gc.Target] = []

    def probe() -> gc.Inventory:
        # This is a fake rootless snapshot, not a live Docker invocation.
        return gc.Inventory(
            tuple(live["containers"]),
            tuple(live["images"]),
            tuple(live["networks"]),
            tuple(live["volumes"]),
            gc.DiskInodes(12_000_000 + len(deleted) * 12_345, 44_000 + len(deleted)),
        )

    def remove(target: gc.Target) -> None:
        if delete_failure:
            raise gc.CleanupError("synthetic lost removal receipt")
        attribute = {
            "container": "ident",
            "image": "ident",
            "network": "ident",
            "volume": "name",
        }[target.kind]
        rows = live[
            {
                "container": "containers",
                "image": "images",
                "network": "networks",
                "volume": "volumes",
            }[target.kind]
        ]
        assert sum(getattr(item, attribute) == target.ident for item in rows) == 1
        rows[:] = [item for item in rows if getattr(item, attribute) != target.ident]
        deleted.append(target)
        if drift:
            live["containers"][:] = [c for c in live["containers"] if c.ident != FOREIGN_ID]

    return probe, remove, deleted


@pytest.mark.parametrize("outcome", ["SUCCESS", "FAILURE"])
def test_always_cleanup_selectively_and_prove_zero_obsolete_images(outcome: str) -> None:
    probe, remove, deleted = _probe_and_delete(_inventory())
    receipt = gc.execute(
        outcome,
        ATTEMPT,
        preserve_images=frozenset({ACTIVE_IMAGE}),
        preserve_containers=frozenset({ACTIVE_ID}),
        retire_containers=frozenset({OLD_ID}),
        probe=probe,
        delete_exact=remove,
    )
    assert receipt.status == "ACCEPT"
    assert receipt.known_residue == ()
    assert receipt.removed == tuple(deleted)
    assert {x.kind for x in deleted} == {"container", "image", "network", "volume"}
    assert {x.ident for x in deleted} == {OLD_ID, OLD_IMAGE, STALE_NET, IPC}
    after = probe()
    assert {c.ident for c in after.containers} == {ACTIVE_ID, FOREIGN_ID}
    assert {i.ident for i in after.images} == {ACTIVE_IMAGE, FOREIGN_IMAGE}
    assert DATA in {v.name for v in after.volumes}
    assert receipt.after.bytes_free > receipt.before.bytes_free
    assert receipt.after.inodes_free > receipt.before.inodes_free


def test_known_obsolete_image_survives_delete_failure_and_is_no_go() -> None:
    inventory = replace(_inventory(), containers=_inventory().containers[:1])
    probe, remove, deleted = _probe_and_delete(inventory, delete_failure=True)
    receipt = gc.execute(
        "FAILURE",
        ATTEMPT,
        preserve_images=frozenset({ACTIVE_IMAGE}),
        preserve_containers=frozenset({ACTIVE_ID}),
        retire_containers=frozenset({OLD_ID}),
        probe=probe,
        delete_exact=remove,
    )
    assert receipt.status == "NO_GO"
    assert gc.Target("volume", IPC) in receipt.known_residue
    assert gc.Target("image", OLD_IMAGE) in receipt.known_residue
    assert deleted == []
    assert ACTIVE_IMAGE in {i.ident for i in probe().images}


def test_unknown_boca_image_retained_with_indeterminate_reason() -> None:
    inventory = _inventory()
    images = tuple(
        replace(image, source=None) if image.ident == OLD_IMAGE else image
        for image in inventory.images
    )
    inventory = replace(
        inventory,
        containers=tuple(c for c in inventory.containers if c.ident != OLD_ID),
        networks=inventory.networks[:1],
        volumes=tuple(v for v in inventory.volumes if v.name != IPC),
        images=images,
    )
    probe, remove, deleted = _probe_and_delete(inventory)
    receipt = gc.execute(
        "SUCCESS",
        ATTEMPT,
        preserve_images=frozenset({ACTIVE_IMAGE}),
        preserve_containers=frozenset({ACTIVE_ID}),
        retire_containers=frozenset({OLD_ID}),
        probe=probe,
        delete_exact=remove,
    )
    assert receipt.status == "INDETERMINATE"
    assert not deleted
    assert any(f"image:{OLD_IMAGE}" in reason for reason in receipt.retained_uncertain)
    assert OLD_IMAGE in {image.ident for image in probe().images}


@pytest.mark.parametrize("foreign_running", [True, False])
def test_other_app_reference_including_stopped_preserves_boca_image(
    foreign_running: bool,
) -> None:
    inventory = _inventory()
    foreign = replace(
        next(c for c in inventory.containers if c.ident == FOREIGN_ID),
        image_id=OLD_IMAGE,
        running=foreign_running,
    )
    inventory = replace(
        inventory,
        containers=(inventory.containers[0], foreign),
        networks=inventory.networks[:1],
        volumes=tuple(v for v in inventory.volumes if v.name != IPC),
    )
    probe, remove, _deleted = _probe_and_delete(inventory)
    receipt = gc.execute(
        "SUCCESS",
        ATTEMPT,
        preserve_images=frozenset({ACTIVE_IMAGE}),
        preserve_containers=frozenset({ACTIVE_ID}),
        retire_containers=frozenset({OLD_ID}),
        probe=probe,
        delete_exact=remove,
    )
    assert receipt.status == "ACCEPT"
    assert OLD_IMAGE in {image.ident for image in probe().images}


def test_multi_tag_image_uses_exact_id_and_failure_is_no_go() -> None:
    inventory = _inventory()
    old = next(image for image in inventory.images if image.ident == OLD_IMAGE)
    inventory = replace(
        inventory,
        containers=tuple(c for c in inventory.containers if c.ident != OLD_ID),
        networks=inventory.networks[:1],
        volumes=tuple(v for v in inventory.volumes if v.name != IPC),
        images=tuple(
            replace(
                old,
                references=(
                    "ghcr.io/mbalbo2023/boca-socios-assistant-browser:old",
                    "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "e" * 64,
                ),
            )
            if image.ident == OLD_IMAGE
            else image
            for image in inventory.images
        ),
    )
    plan = gc.plan(
        inventory,
        ATTEMPT,
        preserve_images=frozenset({ACTIVE_IMAGE}),
        preserve_containers=frozenset({ACTIVE_ID}),
        retire_containers=frozenset({OLD_ID}),
    )
    assert gc.Target("image", OLD_IMAGE) in plan.targets
    probe, remove, _deleted = _probe_and_delete(inventory, delete_failure=True)
    receipt = gc.execute(
        "SUCCESS",
        ATTEMPT,
        preserve_images=frozenset({ACTIVE_IMAGE}),
        preserve_containers=frozenset({ACTIVE_ID}),
        retire_containers=frozenset({OLD_ID}),
        probe=probe,
        delete_exact=remove,
    )
    assert receipt.status == "NO_GO"
    assert gc.Target("image", OLD_IMAGE) in receipt.known_residue


def test_image_remove_that_only_untags_does_not_pass_exact_id_postflight() -> None:
    inventory = _inventory()
    inventory = replace(
        inventory,
        containers=tuple(c for c in inventory.containers if c.ident != OLD_ID),
        networks=inventory.networks[:1],
        volumes=tuple(v for v in inventory.volumes if v.name != IPC),
        global_image_ids=frozenset({ACTIVE_IMAGE, OLD_IMAGE, FOREIGN_IMAGE}),
    )
    attempted: list[gc.Target] = []
    snapshots = [inventory]

    def probe() -> gc.Inventory:
        return snapshots[0]

    def only_untag(target: gc.Target) -> None:
        attempted.append(target)
        assert target == gc.Target("image", OLD_IMAGE)
        snapshots[0] = replace(
            inventory,
            images=tuple(
                replace(image, references=()) if image.ident == OLD_IMAGE else image
                for image in inventory.images
            ),
        )

    receipt = gc.execute(
        "SUCCESS",
        ATTEMPT,
        preserve_images=frozenset({ACTIVE_IMAGE}),
        preserve_containers=frozenset({ACTIVE_ID}),
        retire_containers=frozenset(),
        probe=probe,
        delete_exact=only_untag,
    )
    assert attempted == [gc.Target("image", OLD_IMAGE)]
    assert receipt.status == "NO_GO"
    assert gc.Target("image", OLD_IMAGE) in receipt.known_residue


@pytest.mark.parametrize("kind", ["container", "network", "volume"])
def test_noop_delete_with_changed_eligibility_cannot_claim_absent_id(kind: str) -> None:
    """Without ID-presence assertion, all three mutations falsely returned ACCEPT."""
    source = _inventory()
    selected = gc.Target(
        kind,
        {"container": OLD_ID, "network": STALE_NET, "volume": IPC}[kind],
    )
    snapshot = [
        replace(
            source,
            containers=(source.containers[0], source.containers[1])
            if kind == "container"
            else (source.containers[0],),
            images=(source.images[0], source.images[1])
            if kind == "container"
            else (source.images[0],),
            networks=source.networks if kind == "network" else source.networks[:1],
            volumes=source.volumes if kind == "volume" else source.volumes[:3],
        )
    ]
    attempted: list[gc.Target] = []

    def delete_but_drift(target: gc.Target) -> None:
        assert target == selected
        attempted.append(target)
        old = snapshot[0]
        if kind == "container":
            # Old ID remains but loses its Boca-prefixed name.
            snapshot[0] = replace(
                old,
                containers=(old.containers[0], replace(old.containers[1], name="/renamed")),
            )
        elif kind == "network":
            # Same network ID becomes attached; no longer a cleanup candidate.
            snapshot[0] = replace(
                old,
                networks=(old.networks[0], replace(old.networks[1], attached_ids=(ACTIVE_ID,))),
            )
        else:
            # Same IPC volume becomes referenced; the volume itself survives.
            snapshot[0] = replace(
                old,
                containers=(replace(old.containers[0], volumes=(DATA, IPC)),),
            )

    receipt = gc.execute(
        "FAILURE",
        ATTEMPT,
        preserve_images=frozenset({ACTIVE_IMAGE}),
        preserve_containers=frozenset({ACTIVE_ID}),
        retire_containers=frozenset({OLD_ID}) if kind == "container" else frozenset(),
        probe=lambda: snapshot[0],
        delete_exact=delete_but_drift,
    )
    assert attempted == [selected]
    assert receipt.status == "NO_GO"
    assert selected not in receipt.removed


def test_dangling_image_with_exact_boca_source_label_is_cleanable() -> None:
    inventory = _inventory()
    inventory = replace(
        inventory,
        containers=tuple(c for c in inventory.containers if c.ident != OLD_ID),
        networks=inventory.networks[:1],
        volumes=tuple(v for v in inventory.volumes if v.name != IPC),
        images=tuple(
            replace(image, references=()) if image.ident == OLD_IMAGE else image
            for image in inventory.images
        ),
    )
    probe, remove, deleted = _probe_and_delete(inventory)
    receipt = gc.execute(
        "FAILURE",
        ATTEMPT,
        preserve_images=frozenset({ACTIVE_IMAGE}),
        preserve_containers=frozenset({ACTIVE_ID}),
        retire_containers=frozenset({OLD_ID}),
        probe=probe,
        delete_exact=remove,
    )
    assert receipt.status == "ACCEPT"
    assert gc.Target("image", OLD_IMAGE) in deleted


def test_docker_image_listing_can_repeat_image_id_per_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gc, "_docker", lambda *_args: OLD_IMAGE + "\n" + OLD_IMAGE + "\n")
    assert gc._ids("image", "ls", "-a", "-q", "--no-trunc", dedupe=True) == [OLD_IMAGE]
    with pytest.raises(gc.CleanupError):
        gc._ids("ps", "-a", "-q", "--no-trunc")


def test_boca_protected_lease_exclusive_and_not_reusable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tmp_path.chmod(0o700)
    monkeypatch.setattr(gc, "LEASE_DIR", tmp_path)
    monkeypatch.setattr(gc, "EXPECTED_UID", os.geteuid())
    with gc.protected_boca_job_lease(ATTEMPT) as lease:
        assert lease.active
        with pytest.raises(gc.CleanupError, match="lease held"):
            with gc.protected_boca_job_lease(ATTEMPT):
                pytest.fail("nested Boca lease should not be granted")
        with pytest.raises(gc.CleanupError, match="requires one protected"):
            gc.execute_protected(
                "SUCCESS",
                "41897569930",
                preserve_images=frozenset({ACTIVE_IMAGE}),
                preserve_containers=frozenset({ACTIVE_ID}),
                retire_containers=frozenset({OLD_ID}),
                lease=lease,
            )
    assert not lease.active
    with pytest.raises(gc.CleanupError, match="requires one protected"):
        gc.execute_protected(
            "SUCCESS",
            ATTEMPT,
            preserve_images=frozenset({ACTIVE_IMAGE}),
            preserve_containers=frozenset({ACTIVE_ID}),
            retire_containers=frozenset({OLD_ID}),
            lease=lease,
        )


def test_unrelated_container_drift_causes_no_go_not_silent_accept() -> None:
    probe, remove, _deleted = _probe_and_delete(_inventory(), drift=True)
    receipt = gc.execute(
        "SUCCESS",
        ATTEMPT,
        preserve_images=frozenset({ACTIVE_IMAGE}),
        preserve_containers=frozenset({ACTIVE_ID}),
        retire_containers=frozenset({OLD_ID}),
        probe=probe,
        delete_exact=remove,
    )
    assert receipt.status == "NO_GO"


def test_wrong_attempt_does_not_delete_unknown_boca_resources() -> None:
    probe, remove, deleted = _probe_and_delete(_inventory())
    receipt = gc.execute(
        "FAILURE",
        "41897569930",
        preserve_images=frozenset({ACTIVE_IMAGE}),
        preserve_containers=frozenset({ACTIVE_ID}),
        retire_containers=frozenset(),
        probe=probe,
        delete_exact=remove,
    )
    assert receipt.status == "NO_GO"
    assert not deleted
    assert gc.Target("container", OLD_ID) not in deleted
    assert receipt.retained_uncertain


def test_stopped_installed_controller_and_parked_worker_are_never_auto_deleted() -> None:
    inventory = _inventory()
    protected_controller = replace(
        inventory.containers[0],
        running=False,
        labels=OWNED,
    )
    inventory = replace(
        inventory,
        containers=(protected_controller, inventory.containers[1], inventory.containers[2]),
    )
    probe, remove, deleted = _probe_and_delete(inventory)
    receipt = gc.execute(
        "SUCCESS",
        ATTEMPT,
        preserve_images=frozenset({ACTIVE_IMAGE, OLD_IMAGE}),
        preserve_containers=frozenset({ACTIVE_ID, OLD_ID}),
        retire_containers=frozenset(),
        probe=probe,
        delete_exact=remove,
    )
    assert receipt.status == "ACCEPT"
    assert {c.ident for c in probe().containers} >= {ACTIVE_ID, OLD_ID}
    assert {i.ident for i in probe().images} >= {ACTIVE_IMAGE, OLD_IMAGE}
    assert not any(target.kind in ("container", "image") for target in deleted)


def test_legacy_beta_stopped_without_attempt_label_requires_no_go() -> None:
    inventory = _inventory()
    unlabelled_legacy = replace(inventory.containers[1], labels=BOCA)
    inventory = replace(
        inventory,
        containers=(inventory.containers[0], unlabelled_legacy, inventory.containers[2]),
    )
    probe, remove, deleted = _probe_and_delete(inventory)
    receipt = gc.execute(
        "FAILURE",
        ATTEMPT,
        preserve_images=frozenset({ACTIVE_IMAGE}),
        preserve_containers=frozenset({ACTIVE_ID}),
        retire_containers=frozenset(),
        probe=probe,
        delete_exact=remove,
    )
    assert receipt.status == "NO_GO"
    assert not any(t.ident == OLD_ID for t in deleted)
    assert any("missing-or-unproven-attempt" in reason for reason in receipt.retained_uncertain)


def test_foreign_container_secret_never_inspected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_docker(*args: str) -> str:
        calls.append(args)
        if "inspect" in args or "Env" in " ".join(args):
            pytest.fail("attempted to inspect foreign workload secret")
        if args == ("ps", "-a", "-q", "--no-trunc"):
            return ACTIVE_ID + "\n" + FOREIGN_ID + "\n"
        if args == (
            "ps",
            "-a",
            "-q",
            "--no-trunc",
            "--filter",
            "label=com.docker.compose.project=boca-socios",
        ):
            return ACTIVE_ID + "\n"
        pytest.fail(f"unexpected Docker command {args!r}")

    monkeypatch.setattr(gc, "_docker", fake_docker)
    with pytest.raises(gc.CleanupError, match="foreign containers"):
        gc.capture_inventory()
    assert all("inspect" not in call for call in calls)


def test_narrow_docker_field_rejects_environment_read() -> None:
    with pytest.raises(gc.CleanupError, match="outside narrowly reviewed"):
        gc._inspect_field("container", ACTIVE_ID, "Config.Env")


def test_docker_context_override_cannot_select_foreign_daemon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gc, "EXPECTED_UID", os.geteuid())
    monkeypatch.setenv("DOCKER_CONTEXT", "foreign-porota")
    monkeypatch.setattr(
        gc.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("Docker executed")
    )
    with pytest.raises(gc.CleanupError, match="context/TLS overrides"):
        gc._docker("ps", "-a", "-q", "--no-trunc")


def test_docker_uses_explicit_rootless_host_and_scrubbed_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gc, "EXPECTED_UID", os.geteuid())
    for key in (
        "DOCKER_CONTEXT",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
        "DOCKER_TLS",
        "DOCKER_CONFIG",
        "DOCKER_HOST",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BOCA_SENSITIVE_TOKEN", "not-for-child-process")
    calls: list[tuple[list[str], dict[str, str]]] = []

    def synthetic_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        env = kwargs["env"]
        assert isinstance(env, dict)
        calls.append((args, env))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(gc.subprocess, "run", synthetic_run)
    assert gc._docker("ps", "-a", "-q", "--no-trunc") == ""
    assert calls[0][0][:3] == ["/usr/bin/docker", "--host", gc.DOCKER_SOCKET]
    assert calls[0][1]["DOCKER_HOST"] == gc.DOCKER_SOCKET
    assert "BOCA_SENSITIVE_TOKEN" not in calls[0][1]


def test_capture_inventory_reads_only_filtered_boca_subset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspections: list[tuple[str, str, str]] = []

    def filtered_docker(*args: str) -> str:
        assert "inspect" not in args
        if args[:1] == ("ps",):
            return ACTIVE_ID + "\n"
        if args[:2] == ("network", "ls"):
            return "" if "type=builtin" in args else PRIVATE_NET + "\n"
        if args[:2] == ("volume", "ls"):
            return DATA + "\n"
        if args[:2] == ("image", "ls"):
            return ACTIVE_IMAGE + "\n"
        pytest.fail(f"unexpected Docker query {args!r}")

    fields: dict[str, object] = {
        "Id": ACTIVE_ID,
        "Name": "/boca-socios-controller-1",
        "Image": ACTIVE_IMAGE,
        "State.Running": True,
        "Config.Labels": {"com.docker.compose.project": "boca-socios"},
        "Mounts": [{"Type": "volume", "Name": DATA}],
        "NetworkSettings.Networks": {"boca-socios_boca_private": {}},
        "RepoTags": ["ghcr.io/mbalbo2023/boca-socios-assistant:stable"],
        "RepoDigests": [],
        "Containers": {ACTIVE_ID: {}},
        "Labels": {"com.docker.compose.project": "boca-socios"},
    }

    def inspected(kind: gc.KIND, ident: str, field: str) -> object:
        inspections.append((kind, ident, field))
        assert ident in {ACTIVE_ID, ACTIVE_IMAGE, PRIVATE_NET, DATA}
        assert field != "Config.Env"
        if kind == "image" and field == "Config.Labels":
            return {"org.opencontainers.image.source": gc.BOCA_SOURCE}
        if kind == "network" and field == "Name":
            return "boca-socios_boca_private"
        if kind == "volume" and field == "Name":
            return DATA
        if kind == "network" and field == "Id":
            return PRIVATE_NET
        if kind == "image" and field == "Id":
            return ACTIVE_IMAGE
        return fields[field]

    monkeypatch.setattr(gc, "_docker", filtered_docker)
    monkeypatch.setattr(gc, "_inspect_field", inspected)
    monkeypatch.setattr(gc, "_disk_inodes", lambda: gc.DiskInodes(4000, 800))
    inventory = gc.capture_inventory()
    assert len(inventory.containers) == len(inventory.images) == 1
    assert len(inventory.networks) == len(inventory.volumes) == 1
    assert all(ident != FOREIGN_ID for _kind, ident, _field in inspections)
    assert inventory.disk.inodes_free == 800
    assert inventory.global_image_ids == frozenset({ACTIVE_IMAGE})


def test_disk_probe_rejects_symlinked_boca_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(gc, "DISK_ROOT", tmp_path)
    (tmp_path / "external").mkdir()
    (tmp_path / "boca-socios").symlink_to(tmp_path / "external", target_is_directory=True)
    with pytest.raises(gc.CleanupError, match="measurement unsafe"):
        gc._disk_inodes()


def test_postdeploy_measures_stage_and_verified_rootless_docker_storage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The approved always-finalizer contract requires *both* filesystems."""
    owner = tmp_path / "boca-owner"
    owner.mkdir(mode=0o700)
    docker_root = owner / ".local" / "share" / "docker"
    docker_root.mkdir(parents=True)
    for path in (owner, docker_root, *docker_root.parents[:2]):
        if path != tmp_path:
            path.chmod(0o700)
    stage_root = tmp_path / "srv"
    stage_root.mkdir(mode=0o700)
    (stage_root / "boca-socios").mkdir(mode=0o700)
    monkeypatch.setattr(gc, "DISK_ROOT", stage_root)
    monkeypatch.setattr(gc, "EXPECTED_UID", os.geteuid())
    monkeypatch.setattr(gc, "EXPECTED_GID", os.getegid())
    monkeypatch.setattr(
        gc.pwd,
        "getpwuid",
        lambda uid: SimpleNamespace(pw_dir=str(owner)),
    )
    rootless_info = {
        "SecurityOptions": ["name=rootless"],
        "CgroupVersion": "2",
        "CgroupDriver": "systemd",
        "Driver": "overlay2",
        "DriverStatus": [],
        "DockerRootDir": str(docker_root),
    }
    calls: list[tuple[str, ...]] = []

    def safe_info(*args: str) -> str:
        calls.append(args)
        assert args == ("info", "--format", "{{json .}}")
        return json.dumps(rootless_info)

    monkeypatch.setattr(gc, "_docker", safe_info)
    observed = gc._disk_inodes()
    assert calls == [("info", "--format", "{{json .}}")]
    assert observed.bytes_free > 0 and observed.inodes_free > 0
    assert observed.docker_bytes_free > 0 and observed.docker_inodes_free > 0
    assert observed.stage_device == (stage_root / "boca-socios").stat().st_dev
    assert observed.stage_inode == (stage_root / "boca-socios").stat().st_ino
    assert observed.docker_device == docker_root.stat().st_dev
    assert observed.docker_inode == docker_root.stat().st_ino


def test_postdeploy_refuses_rootless_data_dir_outside_private_owner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stage = tmp_path / "srv"
    stage.mkdir(mode=0o700)
    monkeypatch.setattr(gc, "DISK_ROOT", stage)
    owner = tmp_path / "owner"
    owner.mkdir(mode=0o700)
    forbidden = tmp_path / "unrelated-docker"
    forbidden.mkdir(mode=0o700)
    monkeypatch.setattr(gc, "EXPECTED_UID", os.geteuid())
    monkeypatch.setattr(gc, "EXPECTED_GID", os.getegid())
    monkeypatch.setattr(
        gc.pwd,
        "getpwuid",
        lambda uid: SimpleNamespace(pw_dir=str(owner)),
    )
    monkeypatch.setattr(
        gc,
        "_docker",
        lambda *args: json.dumps(
            {
                "SecurityOptions": ["name=rootless"],
                "CgroupVersion": "2",
                "CgroupDriver": "systemd",
                "Driver": "overlay2",
                "DriverStatus": [],
                "DockerRootDir": str(forbidden),
            }
        ),
    )
    with pytest.raises(gc.CleanupError, match="rootless Docker storage"):
        gc._disk_inodes()


def test_cleanup_refuses_changed_docker_storage_before_first_deletion() -> None:
    before = replace(
        _inventory(),
        disk=gc.DiskInodes(
            100_000,
            100,
            docker_bytes_free=200_000,
            docker_inodes_free=200,
            stage_device=1,
            stage_inode=2,
            docker_device=3,
            docker_inode=4,
        ),
    )
    after = replace(before, disk=replace(before.disk, docker_inode=9))
    observations = 0
    removed: list[gc.Target] = []

    def probe() -> gc.Inventory:
        nonlocal observations
        observations += 1
        return before if observations == 1 else after

    receipt = gc.execute(
        "FAILURE",
        ATTEMPT,
        preserve_images=frozenset({ACTIVE_IMAGE}),
        preserve_containers=frozenset({ACTIVE_ID}),
        retire_containers=frozenset({OLD_ID}),
        probe=probe,
        delete_exact=removed.append,
    )
    assert receipt.status == "NO_GO"
    assert removed == []
    assert any("storage-topology" in reason for reason in receipt.retained_uncertain)


@pytest.mark.parametrize("same_filesystem", [True, False])
def test_successful_cleanup_accepts_both_same_and_distinct_rootless_filesystems(
    same_filesystem: bool,
) -> None:
    """No hidden assumption that Docker's data root lives on the stage mount."""
    original_probe, remove, deleted = _probe_and_delete(_inventory())

    def dual_probe() -> gc.Inventory:
        snapshot = original_probe()
        return replace(
            snapshot,
            disk=gc.DiskInodes(
                snapshot.disk.bytes_free,
                snapshot.disk.inodes_free,
                docker_bytes_free=700_000 + len(deleted) * 40_000,
                docker_inodes_free=800 + len(deleted),
                stage_device=17,
                stage_inode=171,
                docker_device=17 if same_filesystem else 23,
                docker_inode=232,
            ),
        )

    receipt = gc.execute(
        "SUCCESS",
        ATTEMPT,
        preserve_images=frozenset({ACTIVE_IMAGE}),
        preserve_containers=frozenset({ACTIVE_ID}),
        retire_containers=frozenset({OLD_ID}),
        probe=dual_probe,
        delete_exact=remove,
    )
    assert receipt.status == "ACCEPT"
    assert receipt.before.docker_device == (17 if same_filesystem else 23)
    assert receipt.after.docker_bytes_free > receipt.before.docker_bytes_free
    assert receipt.after.docker_inodes_free > receipt.before.docker_inodes_free
    assert receipt.known_residue == ()


def test_postflight_public_receipt_tracks_exact_boca_removals_and_storage() -> None:
    """Public ACK must expose verifiable Boca-only IDs, never foreign resources."""
    before = gc.DiskInodes(1000, 100, 3000, 300, 8, 10, 16, 18)
    after = gc.DiskInodes(1400, 104, 3400, 304, 8, 10, 16, 18)
    receipt = gc.CleanupReceipt(
        "SUCCESS",
        ATTEMPT,
        "ACCEPT",
        before,
        after,
        (gc.Target("image", OLD_IMAGE), gc.Target("network", STALE_NET)),
        (),
        (),
    )
    data = json.loads(receipt.redacted_json())
    assert data["version"] == 1 and data["scope"] == "boca-postdeploy"
    assert data["attempt_id"] == ATTEMPT and data["status"] == "ACCEPT"
    assert data["outcome"] == "SUCCESS"
    assert data["before"]["stage_bytes_free"] == 1000
    assert data["after"]["stage_inodes_free"] == 104
    assert data["before"]["docker_bytes_free"] == 3000
    assert data["after"]["docker_inodes_free"] == 304
    assert data["removed"] == [
        {"kind": "image", "id": OLD_IMAGE},
        {"kind": "network", "id": STALE_NET},
    ]
    assert data["retained_uncertain"] == [] and data["known_residue"] == []
    assert "porota" not in receipt.redacted_json().lower()


@pytest.mark.parametrize(
    "unsafe",
    [
        gc.Target("volume", DATA),
        gc.Target("volume", "porota_data"),
        gc.Target("container", "short"),
    ],
)
def test_postflight_public_receipt_refuses_non_boca_or_persistent_targets(
    unsafe: gc.Target,
) -> None:
    disk = gc.DiskInodes(1000, 100, 3000, 300, 8, 10, 16, 18)
    receipt = gc.CleanupReceipt("SUCCESS", ATTEMPT, "ACCEPT", disk, disk, (unsafe,), (), ())
    with pytest.raises(gc.CleanupError):
        receipt.redacted_json()


def test_unlabelled_retired_legacy_image_requires_exact_precommit_attestation() -> None:
    """RCA #323: old revision-only release is not silently accepted after COMMITTED."""
    original = _inventory()
    retained = replace(
        original,
        containers=(original.containers[0],),
        networks=original.networks[:1],
        volumes=original.volumes[:3],
        images=tuple(
            replace(
                image,
                source=None,
                references=("ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "7" * 64,),
            )
            if image.ident == OLD_IMAGE
            else image
            for image in original.images
        ),
    )
    no_proof, no_remove, no_deleted = _probe_and_delete(retained)
    unverified = gc.execute(
        "SUCCESS",
        ATTEMPT,
        preserve_images=frozenset(),
        preserve_containers=frozenset({ACTIVE_ID}),
        retire_containers=frozenset(),
        probe=no_proof,
        delete_exact=no_remove,
    )
    assert unverified.status == "INDETERMINATE"
    assert no_deleted == []

    attested = replace(
        retained,
        images=tuple(
            replace(image, historical_legacy_attested=True) if image.ident == OLD_IMAGE else image
            for image in retained.images
        ),
    )
    probe, remove, deleted = _probe_and_delete(attested)
    receipt = gc.execute(
        "SUCCESS",
        ATTEMPT,
        preserve_images=frozenset(),
        preserve_containers=frozenset({ACTIVE_ID}),
        retire_containers=frozenset(),
        probe=probe,
        delete_exact=remove,
    )
    assert receipt.status == "ACCEPT"
    assert deleted == [gc.Target("image", OLD_IMAGE)]
    assert receipt.removed == tuple(deleted)
    assert OLD_IMAGE not in {image.ident for image in probe().images}
    assert ACTIVE_IMAGE in {image.ident for image in probe().images}


@pytest.mark.parametrize(
    "change",
    [
        "foreign-tag",
        "multiple-boca-tags",
        "multiple-digests",
        "wrong-revision",
        "missing-digest",
        "foreign-source",
        "wrong-id",
    ],
)
def test_legacy_image_attestation_rejects_foreign_alias_or_identity_drift(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    reference = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "1" * 64
    revision = "a" * 40
    fields: dict[str, object] = {
        "Id": OLD_IMAGE,
        "RepoTags": [],
        "RepoDigests": [reference],
        "Config.Labels": {"org.opencontainers.image.revision": revision},
    }
    if change == "foreign-tag":
        fields["RepoTags"] = ["ghcr.io/third-party/foreign:shared"]
    elif change == "multiple-boca-tags":
        fields["RepoTags"] = [
            "ghcr.io/mbalbo2023/boca-socios-assistant:old",
            "ghcr.io/mbalbo2023/boca-socios-assistant:older",
        ]
    elif change == "multiple-digests":
        fields["RepoDigests"] = [
            reference,
            "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "2" * 64,
        ]
    elif change == "wrong-revision":
        fields["Config.Labels"] = {"org.opencontainers.image.revision": "b" * 40}
    elif change == "missing-digest":
        fields["RepoDigests"] = []
    elif change == "foreign-source":
        fields["Config.Labels"] = {
            "org.opencontainers.image.revision": revision,
            "org.opencontainers.image.source": "https://github.com/elsewhere/project",
        }
    else:
        fields["Id"] = ACTIVE_IMAGE
    inspected: list[str] = []

    def narrow(kind: gc.KIND, ident: str, field: str) -> object:
        assert kind == "image" and ident == OLD_IMAGE
        inspected.append(field)
        assert field != "Config.Env"
        return fields[field]

    monkeypatch.setattr(gc, "_inspect_field", narrow)
    with pytest.raises(gc.CleanupError):
        gc.attest_historical_legacy_image(OLD_IMAGE, reference, revision)
    assert inspected


def test_legacy_image_attestation_reads_only_old_boca_image_allowlisted_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "1" * 64
    revision = "a" * 40
    fields: dict[str, object] = {
        "Id": OLD_IMAGE,
        "RepoTags": ["ghcr.io/mbalbo2023/boca-socios-assistant:legacy"],
        "RepoDigests": [reference],
        "Config.Labels": {"org.opencontainers.image.revision": revision},
    }
    calls: list[str] = []

    def narrow(kind: gc.KIND, ident: str, field: str) -> object:
        assert kind == "image" and ident == OLD_IMAGE
        assert field in {"Id", "RepoTags", "RepoDigests", "Config.Labels"}
        calls.append(field)
        return fields[field]

    monkeypatch.setattr(gc, "_inspect_field", narrow)
    proof = gc.attest_historical_legacy_image(OLD_IMAGE, reference, revision)
    assert proof == gc.LegacyImageProof(OLD_IMAGE, reference, revision)
    references, source = gc._verify_historical_legacy_image(proof)
    assert references == tuple(sorted((reference, fields["RepoTags"][0])))
    assert source is None
    assert "Config.Env" not in calls


def test_digest_only_legacy_image_is_inventoried_by_attested_id_not_reference_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The historical digest-only image may be omitted by Docker reference= filter."""
    reference = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "1" * 64
    revision = "a" * 40
    proof = gc.LegacyImageProof(OLD_IMAGE, reference, revision)
    inspected: list[tuple[str, str, str]] = []

    def docker(*args: str) -> str:
        if args[:1] == ("ps",):
            return ACTIVE_ID + "\n"
        if args[:2] == ("network", "ls"):
            return "" if "type=builtin" in args else PRIVATE_NET + "\n"
        if args[:2] == ("volume", "ls"):
            return DATA + "\n"
        if args[:2] == ("image", "ls"):
            if "label=org.opencontainers.image.source=" + gc.BOCA_SOURCE in args:
                return ACTIVE_IMAGE + "\n"
            if "reference=ghcr.io/mbalbo2023/boca-socios-assistant*" in args:
                return ACTIVE_IMAGE + "\n"
            return ACTIVE_IMAGE + "\n" + OLD_IMAGE + "\n" + FOREIGN_IMAGE + "\n"
        pytest.fail(f"unexpected Docker command {args!r}")

    def inspect(kind: gc.KIND, ident: str, field: str) -> object:
        inspected.append((kind, ident, field))
        assert ident != FOREIGN_IMAGE and field != "Config.Env"
        if kind == "container":
            return {
                "Id": ACTIVE_ID,
                "Name": "/boca-socios-controller-1",
                "Image": ACTIVE_IMAGE,
                "State.Running": True,
                "Config.Labels": {"com.docker.compose.project": "boca-socios"},
                "Mounts": [{"Type": "volume", "Name": DATA}],
                "NetworkSettings.Networks": {"boca-socios_boca_private": {}},
            }[field]
        if kind == "image" and ident == OLD_IMAGE:
            return {
                "Id": OLD_IMAGE,
                "RepoTags": [],
                "RepoDigests": [reference],
                "Config.Labels": {"org.opencontainers.image.revision": revision},
            }[field]
        if kind == "image":
            return {
                "Id": ACTIVE_IMAGE,
                "RepoTags": ["ghcr.io/mbalbo2023/boca-socios-assistant:stable"],
                "RepoDigests": [],
                "Config.Labels": {"org.opencontainers.image.source": gc.BOCA_SOURCE},
            }[field]
        if kind == "network":
            return {
                "Id": PRIVATE_NET,
                "Name": "boca-socios_boca_private",
                "Containers": {ACTIVE_ID: {}},
                "Labels": {"com.docker.compose.project": "boca-socios"},
            }[field]
        return {
            "Name": DATA,
            "Labels": {"com.docker.compose.project": "boca-socios"},
        }[field]

    monkeypatch.setattr(gc, "_docker", docker)
    monkeypatch.setattr(gc, "_inspect_field", inspect)
    monkeypatch.setattr(gc, "_disk_inodes", lambda: gc.DiskInodes(6000, 600))
    plain = gc.capture_inventory()
    assert OLD_IMAGE not in {image.ident for image in plain.images}
    verified = gc.capture_inventory(historical_legacy=proof)
    old = next(image for image in verified.images if image.ident == OLD_IMAGE)
    assert old.historical_legacy_attested and old.source is None
    assert old.references == (reference,)
    assert gc.Target("image", OLD_IMAGE) in gc.plan(
        verified,
        ATTEMPT,
        preserve_images=frozenset(),
        preserve_containers=frozenset({ACTIVE_ID}),
        retire_containers=frozenset(),
    ).targets
    assert not any(ident == FOREIGN_IMAGE for _kind, ident, _field in inspected)
