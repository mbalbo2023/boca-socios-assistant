"""Offline post-install cleanup contract for #323; no Docker daemon or host."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

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
    plan = gc.plan(inventory, ATTEMPT, preserve_images=frozenset({ACTIVE_IMAGE}))
    assert gc.Target("image", OLD_IMAGE) in plan.targets
    probe, remove, _deleted = _probe_and_delete(inventory, delete_failure=True)
    receipt = gc.execute(
        "SUCCESS",
        ATTEMPT,
        preserve_images=frozenset({ACTIVE_IMAGE}),
        probe=probe,
        delete_exact=remove,
    )
    assert receipt.status == "NO_GO"
    assert gc.Target("image", OLD_IMAGE) in receipt.known_residue


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
                lease=lease,
            )
    assert not lease.active
    with pytest.raises(gc.CleanupError, match="requires one protected"):
        gc.execute_protected(
            "SUCCESS",
            ATTEMPT,
            preserve_images=frozenset({ACTIVE_IMAGE}),
            lease=lease,
        )


def test_unrelated_container_drift_causes_no_go_not_silent_accept() -> None:
    probe, remove, _deleted = _probe_and_delete(_inventory(), drift=True)
    receipt = gc.execute(
        "SUCCESS",
        ATTEMPT,
        preserve_images=frozenset({ACTIVE_IMAGE}),
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
        probe=probe,
        delete_exact=remove,
    )
    assert receipt.status == "INDETERMINATE"
    assert not deleted
    assert gc.Target("container", OLD_ID) not in deleted
    assert receipt.retained_uncertain
