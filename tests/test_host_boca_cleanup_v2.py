"""Offline cleanup V2 evidence contract; never starts Docker or the droplet."""

from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import host_boca_cleanup as gc
from boca_socios import host_boca_cleanup_v2 as v2

ATTEMPT = "43217075287"
CONTROLLER = "1" * 64
WORKER = "2" * 64
CONTROLLER_IMAGE = "sha256:" + "a" * 64
WORKER_IMAGE = "sha256:" + "b" * 64
OLD_IMAGE = "sha256:" + "c" * 64
PRIVATE_NETWORK = "3" * 64
EGRESS_NETWORK = "4" * 64
DATA_VOLUME = "boca-socios_boca_data"
KEY_VOLUME = "boca-socios_boca_key"
OWNER_VOLUME = "boca-socios_boca_owner"
SITE_VOLUME = "boca-socios_boca_site_config"
BOCA_LABEL = (("com.docker.compose.project", "boca-socios"),)


def _image(ident: str) -> gc.Image:
    return gc.Image(
        ident,
        ("ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + ident[-64:],),
        gc.BOCA_SOURCE,
    )


def _inventory(*, with_stale: bool = True) -> gc.Inventory:
    controller = gc.Container(
        CONTROLLER,
        "/boca-socios-controller-1",
        CONTROLLER_IMAGE,
        True,
        (*BOCA_LABEL, ("com.docker.compose.service", "controller")),
        (DATA_VOLUME, KEY_VOLUME, OWNER_VOLUME),
        ("boca-socios_boca_private",),
    )
    worker = gc.Container(
        WORKER,
        "/boca-socios-browser-1",
        WORKER_IMAGE,
        False,
        (*BOCA_LABEL, ("com.docker.compose.service", "browser-worker")),
        (SITE_VOLUME,),
        ("boca-socios_boca_browser_egress",),
    )
    images = (_image(CONTROLLER_IMAGE), _image(WORKER_IMAGE))
    if with_stale:
        images = (*images, _image(OLD_IMAGE))
    return gc.Inventory(
        containers=(controller, worker),
        images=images,
        networks=(
            gc.Network("boca-socios_boca_private", PRIVATE_NETWORK, (CONTROLLER,), BOCA_LABEL),
            gc.Network("boca-socios_boca_browser_egress", EGRESS_NETWORK, (WORKER,), BOCA_LABEL),
        ),
        volumes=tuple(
            gc.Volume(name, BOCA_LABEL)
            for name in (
                DATA_VOLUME,
                KEY_VOLUME,
                OWNER_VOLUME,
                SITE_VOLUME,
            )
        ),
        disk=gc.DiskInodes(100_000, 700, 500_000, 900, 100, 101, 200, 201),
        global_image_ids=frozenset(image.ident for image in images),
    )


def _completed() -> tuple[gc.CleanupReceipt, gc.Inventory, gc.Inventory]:
    before = _inventory()
    after = replace(
        _inventory(with_stale=False),
        disk=replace(
            before.disk,
            bytes_free=101_000,
            docker_bytes_free=510_000,
            docker_inodes_free=901,
        ),
    )
    receipt = gc.CleanupReceipt(
        "SUCCESS",
        ATTEMPT,
        "ACCEPT",
        before.disk,
        after.disk,
        (gc.Target("image", OLD_IMAGE),),
        (),
        (),
    )
    return receipt, before, after


def test_v2_emits_canonical_positive_id_and_before_after_counts() -> None:
    """A successful exact image deletion must have a verifiable count delta."""
    receipt, before, after = _completed()
    raw = v2.canonical_cleanup_v2_receipt(
        receipt,
        before=before,
        after=after,
        protected_containers=frozenset({CONTROLLER, WORKER}),
        protected_images=frozenset({CONTROLLER_IMAGE, WORKER_IMAGE}),
    )
    body = json.loads(raw)
    assert body["version"] == 2
    assert body["scope"] == "boca-postdeploy-counted-v2"
    assert body["removed"] == [{"kind": "image", "id": OLD_IMAGE}]
    assert body["before_counts"] == {
        "containers": 2,
        "images": 3,
        "networks": 2,
        "volumes": 4,
        "global_images": 3,
    }
    assert body["after_counts"] == {
        "containers": 2,
        "images": 2,
        "networks": 2,
        "volumes": 4,
        "global_images": 2,
    }
    assert body["retained_attested"] == []
    assert body["protected_pair"] == {
        "controller": {"id": CONTROLLER, "image_id": CONTROLLER_IMAGE, "running": True},
        "worker": {"id": WORKER, "image_id": WORKER_IMAGE, "running": False},
    }
    assert v2.verify_cleanup_v2_receipt(raw, ATTEMPT) == body
    assert raw == json.dumps(body, sort_keys=True, separators=(",", ":")).encode("ascii")


def _emit(
    receipt: gc.CleanupReceipt,
    before: gc.Inventory,
    after: gc.Inventory,
) -> bytes:
    return v2.canonical_cleanup_v2_receipt(
        receipt,
        before=before,
        after=after,
        protected_containers=frozenset({CONTROLLER, WORKER}),
        protected_images=frozenset({CONTROLLER_IMAGE, WORKER_IMAGE}),
    )


@pytest.mark.parametrize(
    "case",
    [
        "delete_ack_without_absence",
        "protected_running_controller_deleted",
        "protected_parked_worker_deleted",
        "protected_worker_started_during_cleanup",
        "protected_controller_image_changed",
        "protected_sqlite_volume_deleted",
        "protected_image_deleted",
        "foreign_global_image_disappeared",
        "unproven_deleted_image_source",
        "untracked_resource_created",
        "disk_proof_does_not_match",
    ],
)
def test_v2_rejects_forged_deletion_or_unprotected_drift(case: str) -> None:
    """No count, Docker ACK, or guessed ID may substitute for immutable absence."""
    receipt, before, after = _completed()
    if case == "delete_ack_without_absence":
        after = replace(after, images=before.images, global_image_ids=before.global_image_ids)
    elif case == "protected_running_controller_deleted":
        after = replace(after, containers=after.containers[1:])
    elif case == "protected_parked_worker_deleted":
        after = replace(after, containers=after.containers[:1])
    elif case == "protected_worker_started_during_cleanup":
        after = replace(
            after,
            containers=(
                after.containers[0],
                replace(after.containers[1], running=True),
            ),
        )
    elif case == "protected_controller_image_changed":
        after = replace(
            after,
            containers=(
                replace(after.containers[0], image_id=WORKER_IMAGE),
                after.containers[1],
            ),
        )
    elif case == "protected_sqlite_volume_deleted":
        after = replace(after, volumes=after.volumes[1:])
    elif case == "protected_image_deleted":
        after = replace(
            after,
            images=after.images[1:],
            global_image_ids=after.global_image_ids - {CONTROLLER_IMAGE},
        )
    elif case == "foreign_global_image_disappeared":
        before = replace(before, global_image_ids=before.global_image_ids | {"sha256:" + "e" * 64})
    elif case == "unproven_deleted_image_source":
        before = replace(
            before,
            images=(
                *before.images[:2],
                replace(before.images[2], source=None),
            ),
        )
    elif case == "untracked_resource_created":
        after = replace(
            after,
            volumes=(
                *after.volumes,
                gc.Volume("boca-socios_fake-stage", BOCA_LABEL),
            ),
        )
    elif case == "disk_proof_does_not_match":
        after = replace(after, disk=replace(after.disk, docker_inode=999))
    with pytest.raises(gc.CleanupError):
        _emit(receipt, before, after)


def _historical(snapshot: gc.Inventory) -> gc.Inventory:
    image = gc.Image(
        gc.HISTORICAL_RETIRE_TARGET,
        ("ghcr.io/mbalbo2023/boca-socios-assistant:unverified",),
        None,
    )
    return replace(
        snapshot,
        images=(*snapshot.images, image),
        global_image_ids=snapshot.global_image_ids | {image.ident},
    )


def test_v2_explicitly_attests_r108_quarantine_without_deleting_it() -> None:
    """R108 is a named forensic exception, never another removable image."""
    receipt, before, after = _completed()
    proof = gc.HistoricalRetainedImageProof(
        gc.HISTORICAL_RETIRE_TARGET,
        gc.HISTORICAL_RETIRE_DIGEST,
        gc.HISTORICAL_RETIRE_REVISION,
    )
    receipt = replace(receipt, retained_attested=(proof,))
    raw = _emit(receipt, _historical(before), _historical(after))
    body = v2.verify_cleanup_v2_receipt(raw, ATTEMPT)
    assert body["before_counts"]["images"] == 4
    assert body["after_counts"]["images"] == 3
    assert body["retained_attested"] == [
        {
            "kind": "image",
            "id": gc.HISTORICAL_RETIRE_TARGET,
            "classification": "KNOWN_HISTORICAL_QUARANTINE",
            "release_run": "41559973013",
            "manifest_artifact": "13196392925",
            "digest": gc.HISTORICAL_RETIRE_DIGEST,
            "revision": gc.HISTORICAL_RETIRE_REVISION,
        }
    ]
    assert all(item["id"] != gc.HISTORICAL_RETIRE_TARGET for item in body["removed"])


@pytest.mark.parametrize(
    "case",
    [
        "historical_id_without_proof",
        "historical_id_disappeared",
        "historical_id_referenced",
        "historical_proof_without_id",
    ],
)
def test_v2_quarantine_requires_identity_and_preservation(case: str) -> None:
    """Missing or used historical evidence must fail instead of silently disappearing."""
    receipt, before, after = _completed()
    proof = gc.HistoricalRetainedImageProof(
        gc.HISTORICAL_RETIRE_TARGET,
        gc.HISTORICAL_RETIRE_DIGEST,
        gc.HISTORICAL_RETIRE_REVISION,
    )
    if case != "historical_id_without_proof":
        receipt = replace(receipt, retained_attested=(proof,))
    if case != "historical_proof_without_id":
        before = _historical(before)
        after = _historical(after)
    if case == "historical_id_disappeared":
        after = replace(
            after,
            images=after.images[:-1],
            global_image_ids=after.global_image_ids - {gc.HISTORICAL_RETIRE_TARGET},
        )
    elif case == "historical_id_referenced":
        after = replace(
            after,
            containers=(
                after.containers[0],
                replace(after.containers[1], image_id=gc.HISTORICAL_RETIRE_TARGET),
            ),
        )
    with pytest.raises(gc.CleanupError):
        _emit(receipt, before, after)


def test_v2_accepts_stopped_attempt_container_then_its_exclusive_resources() -> None:
    """References from the retired container cannot block its later safe cleanup."""
    receipt, before, after = _completed()
    stale_id = "5" * 64
    stale_network_id = "6" * 64
    stale_network_name = "boca-socios_stage_once"
    stale_volume = "boca-socios_stage_cache"
    owned = (*BOCA_LABEL, ("boca.socios.cutover-a-attempt", ATTEMPT))
    stale = gc.Container(
        stale_id,
        "/boca-socios-stage-once",
        OLD_IMAGE,
        False,
        owned,
        (stale_volume,),
        (stale_network_name,),
    )
    before = replace(
        before,
        containers=(*before.containers, stale),
        networks=(
            *before.networks,
            gc.Network(stale_network_name, stale_network_id, (stale_id,), owned),
        ),
        volumes=(*before.volumes, gc.Volume(stale_volume, owned)),
    )
    receipt = replace(
        receipt,
        removed=(
            gc.Target("container", stale_id),
            gc.Target("volume", stale_volume),
            gc.Target("network", stale_network_id),
            gc.Target("image", OLD_IMAGE),
        ),
    )
    body = v2.verify_cleanup_v2_receipt(_emit(receipt, before, after), ATTEMPT)
    assert body["before_counts"] == {
        "containers": 3,
        "images": 3,
        "networks": 3,
        "volumes": 5,
        "global_images": 3,
    }
    assert body["after_counts"] == {
        "containers": 2,
        "images": 2,
        "networks": 2,
        "volumes": 4,
        "global_images": 2,
    }
    assert len(body["removed"]) == 4


def _canonical(body: dict[str, object]) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("ascii")


@pytest.mark.parametrize(
    "case",
    [
        "extra_field",
        "missing_counts",
        "forged_before_count",
        "forged_after_count",
        "forged_global_count",
        "duplicate_removed_id",
        "unknown_removed_kind",
        "protected_volume_as_removed",
        "historical_proof_forged",
        "accepted_with_unknown_residue",
        "bad_filesystem_identity",
        "boolean_count",
        "negative_disk_bytes",
        "wrong_attempt",
    ],
)
def test_v2_parser_rejects_false_canonical_acceptance(case: str) -> None:
    """A forged runner-facing receipt cannot turn an uncertain cleanup green."""
    receipt, before, after = _completed()
    body = json.loads(_emit(receipt, before, after))
    if case == "extra_field":
        body["unreviewed"] = "go"
    elif case == "missing_counts":
        del body["after_counts"]
    elif case == "forged_before_count":
        body["before_counts"]["containers"] = 999
    elif case == "forged_after_count":
        body["after_counts"]["images"] = 99
    elif case == "forged_global_count":
        body["after_counts"]["global_images"] = 4
    elif case == "duplicate_removed_id":
        body["removed"].append(dict(body["removed"][0]))
    elif case == "unknown_removed_kind":
        body["removed"][0]["kind"] = "build-cache"
    elif case == "protected_volume_as_removed":
        body["removed"][0] = {"kind": "volume", "id": DATA_VOLUME}
    elif case == "historical_proof_forged":
        body["retained_attested"] = [{"id": gc.HISTORICAL_RETIRE_TARGET}]
    elif case == "accepted_with_unknown_residue":
        body["retained_uncertain"] = ["image:unverified-NO_GO"]
    elif case == "bad_filesystem_identity":
        body["after"]["docker_device"] = 999
    elif case == "boolean_count":
        body["before_counts"]["images"] = True
    elif case == "negative_disk_bytes":
        body["after"]["docker_bytes_free"] = -1
    elif case == "wrong_attempt":
        body["attempt_id"] = "1"
    with pytest.raises(gc.CleanupError):
        v2.verify_cleanup_v2_receipt(_canonical(body), ATTEMPT)


@pytest.mark.parametrize("case", ["duplicate_json_key", "noncanonical_spacing", "oversized"])
def test_v2_parser_rejects_noncanonical_or_unbounded_transport(case: str) -> None:
    """JSON ambiguity and output expansion cannot be accepted by the runner."""
    receipt, before, after = _completed()
    raw = _emit(receipt, before, after)
    if case == "duplicate_json_key":
        raw = raw.replace(b'"version":2', b'"version":2,"version":2')
    elif case == "noncanonical_spacing":
        raw = raw.replace(b'"version":2', b'"version": 2')
    elif case == "oversized":
        raw = raw + b" " * 8192
    with pytest.raises(gc.CleanupError):
        v2.verify_cleanup_v2_receipt(raw, ATTEMPT)


def test_v2_failed_install_keeps_failure_even_when_cleanup_is_accepted() -> None:
    """Successful remediation never upgrades a failed install to green."""
    receipt, before, after = _completed()
    raw = _emit(replace(receipt, outcome="FAILURE"), before, after)
    body = v2.verify_cleanup_v2_receipt(raw, ATTEMPT, require_install_success=False)
    assert body["status"] == "ACCEPT"
    assert body["outcome"] == "FAILURE"
    with pytest.raises(gc.CleanupError):
        v2.verify_cleanup_v2_receipt(raw, ATTEMPT)


def test_v2_zero_deletions_preserves_all_boca_resources() -> None:
    """No stale resource means a verified empty delta, never a prune command."""
    snapshot = _inventory(with_stale=False)
    receipt = gc.CleanupReceipt(
        "SUCCESS",
        ATTEMPT,
        "ACCEPT",
        snapshot.disk,
        snapshot.disk,
        (),
        (),
        (),
    )
    body = v2.verify_cleanup_v2_receipt(_emit(receipt, snapshot, snapshot), ATTEMPT)
    assert body["removed"] == []
    assert body["before_counts"] == body["after_counts"]


def test_v2_rejects_unremoved_unproven_boca_image_before_acceptance() -> None:
    """An unused image with only a Boca-looking tag remains uncertain/NO_GO."""
    snapshot = _inventory()
    unknown = replace(snapshot.images[2], source=None)
    snapshot = replace(snapshot, images=(*snapshot.images[:2], unknown))
    receipt = gc.CleanupReceipt(
        "SUCCESS",
        ATTEMPT,
        "ACCEPT",
        snapshot.disk,
        snapshot.disk,
        (),
        (),
        (),
    )
    with pytest.raises(gc.CleanupError):
        _emit(receipt, snapshot, snapshot)


def test_v2_rejects_unremoved_attempt_owned_stopped_container() -> None:
    """A known disposable container cannot be silently declared cleaned."""
    snapshot = _inventory(with_stale=False)
    stale = gc.Container(
        "7" * 64,
        "/boca-socios-stage-left",
        WORKER_IMAGE,
        False,
        (*BOCA_LABEL, ("boca.socios.cutover-a-attempt", ATTEMPT)),
    )
    snapshot = replace(snapshot, containers=(*snapshot.containers, stale))
    receipt = gc.CleanupReceipt(
        "SUCCESS",
        ATTEMPT,
        "ACCEPT",
        snapshot.disk,
        snapshot.disk,
        (),
        (),
        (),
    )
    with pytest.raises(gc.CleanupError):
        _emit(receipt, snapshot, snapshot)


def test_v2_rejects_unknown_kind_in_indeterminate_known_residue() -> None:
    """An invalid kind must produce a safe NO_GO, not an unhandled lookup."""
    receipt, before, after = _completed()
    receipt = replace(
        receipt,
        status="NO_GO",
        known_residue=(gc.Target("build_cache", "8" * 64),),
    )
    with pytest.raises(gc.CleanupError):
        _emit(receipt, before, after)


def test_v2_rejects_foreign_alias_on_historical_quarantine() -> None:
    """The forensic exception is not general authority for arbitrary aliases."""
    receipt, before, after = _completed()
    proof = gc.HistoricalRetainedImageProof(
        gc.HISTORICAL_RETIRE_TARGET,
        gc.HISTORICAL_RETIRE_DIGEST,
        gc.HISTORICAL_RETIRE_REVISION,
    )
    receipt = replace(receipt, retained_attested=(proof,))
    before = _historical(before)
    after = _historical(after)
    historical = replace(
        after.images[-1],
        references=("docker.io/unrelated/foreign:latest",),
    )
    before = replace(before, images=(*before.images[:-1], historical))
    after = replace(after, images=(*after.images[:-1], historical))
    with pytest.raises(gc.CleanupError):
        _emit(receipt, before, after)


def test_v2_parser_rejects_quarantine_when_image_count_is_zero() -> None:
    """A claimed retained image needs a nonempty physical image inventory."""
    receipt, before, after = _completed()
    body = json.loads(_emit(receipt, before, after))
    body["retained_attested"] = [
        {
            "kind": "image",
            "id": gc.HISTORICAL_RETIRE_TARGET,
            "classification": "KNOWN_HISTORICAL_QUARANTINE",
            "release_run": "41559973013",
            "manifest_artifact": "13196392925",
            "digest": gc.HISTORICAL_RETIRE_DIGEST,
            "revision": gc.HISTORICAL_RETIRE_REVISION,
        }
    ]
    body["before_counts"] = {
        "containers": 0,
        "images": 0,
        "networks": 0,
        "volumes": 0,
        "global_images": 0,
    }
    body["after_counts"] = {
        "containers": 0,
        "images": 0,
        "networks": 0,
        "volumes": 0,
        "global_images": 0,
    }
    body["removed"] = []
    with pytest.raises(gc.CleanupError):
        v2.verify_cleanup_v2_receipt(_canonical(body), ATTEMPT)


def test_v2_acceptance_rejects_empty_host_even_with_empty_protected_sets() -> None:
    """SUCCESS/ACCEPT requires the exact protected controller and browser-worker."""
    source = _inventory(with_stale=False)
    empty = replace(
        source,
        containers=(),
        images=(),
        networks=(),
        volumes=(),
        global_image_ids=frozenset(),
    )
    receipt = gc.CleanupReceipt(
        "SUCCESS",
        ATTEMPT,
        "ACCEPT",
        empty.disk,
        empty.disk,
        (),
        (),
        (),
    )
    with pytest.raises(gc.CleanupError):
        v2.canonical_cleanup_v2_receipt(
            receipt,
            before=empty,
            after=empty,
            protected_containers=frozenset(),
            protected_images=frozenset(),
        )


def test_v2_acceptance_rejects_missing_or_duplicate_role_in_protected_set() -> None:
    """Two arbitrary Boca containers never substitute for one controller/worker."""
    before = _inventory(with_stale=False)
    duplicate = replace(before.containers[1], labels=before.containers[0].labels)
    before = replace(before, containers=(before.containers[0], duplicate))
    receipt = gc.CleanupReceipt(
        "SUCCESS",
        ATTEMPT,
        "ACCEPT",
        before.disk,
        before.disk,
        (),
        (),
        (),
    )
    with pytest.raises(gc.CleanupError):
        _emit(receipt, before, before)


def test_v2_parser_rejects_empty_acceptance_even_when_counts_are_consistent() -> None:
    """The independent verifier must not trust zero-identity ACCEPT receipts."""
    receipt, before, after = _completed()
    body = json.loads(_emit(receipt, before, after))
    body["before_counts"] = {
        "containers": 0,
        "images": 0,
        "networks": 0,
        "volumes": 0,
        "global_images": 0,
    }
    body["after_counts"] = dict(body["before_counts"])
    body["removed"] = []
    body["protected_pair"] = None
    with pytest.raises(gc.CleanupError):
        v2.verify_cleanup_v2_receipt(_canonical(body), ATTEMPT)


def test_v2_failure_receipt_can_report_empty_cleanup_without_install_acceptance() -> None:
    """A failed preflight may report clean residue without inventing an active pair."""
    source = _inventory(with_stale=False)
    empty = replace(
        source,
        containers=(),
        images=(),
        networks=(),
        volumes=(),
        global_image_ids=frozenset(),
    )
    receipt = gc.CleanupReceipt(
        "FAILURE",
        ATTEMPT,
        "ACCEPT",
        empty.disk,
        empty.disk,
        (),
        (),
        (),
    )
    raw = v2.canonical_cleanup_v2_receipt(
        receipt,
        before=empty,
        after=empty,
        protected_containers=frozenset(),
        protected_images=frozenset(),
    )
    assert (
        v2.verify_cleanup_v2_receipt(raw, ATTEMPT, require_install_success=False)["protected_pair"]
        is None
    )
    with pytest.raises(gc.CleanupError):
        v2.verify_cleanup_v2_receipt(raw, ATTEMPT)


def test_v2_acceptance_rejects_extra_unknown_protected_container() -> None:
    """A broad preserve set cannot hide an uncertain third container from postflight."""
    snapshot = _inventory(with_stale=False)
    extra = gc.Container(
        "8" * 64,
        "/boca-socios-unknown-1",
        WORKER_IMAGE,
        False,
        BOCA_LABEL,
    )
    snapshot = replace(snapshot, containers=(*snapshot.containers, extra))
    receipt = gc.CleanupReceipt(
        "SUCCESS",
        ATTEMPT,
        "ACCEPT",
        snapshot.disk,
        snapshot.disk,
        (),
        (),
        (),
    )
    with pytest.raises(gc.CleanupError):
        v2.canonical_cleanup_v2_receipt(
            receipt,
            before=snapshot,
            after=snapshot,
            protected_containers=frozenset({CONTROLLER, WORKER, extra.ident}),
            protected_images=frozenset({CONTROLLER_IMAGE, WORKER_IMAGE}),
        )


def test_v2_acceptance_rejects_extra_protected_obsolete_image() -> None:
    """A fabricated image preserve allowlist cannot grant arbitrary quarantine."""
    receipt, before, after = _completed()
    receipt = gc.CleanupReceipt(
        "SUCCESS",
        ATTEMPT,
        "ACCEPT",
        before.disk,
        before.disk,
        (),
        (),
        (),
    )
    with pytest.raises(gc.CleanupError):
        v2.canonical_cleanup_v2_receipt(
            receipt,
            before=before,
            after=before,
            protected_containers=frozenset({CONTROLLER, WORKER}),
            protected_images=frozenset({CONTROLLER_IMAGE, WORKER_IMAGE, OLD_IMAGE}),
        )


def test_postdeploy_planner_never_targets_persistent_browser_ipc_volume() -> None:
    """The dedicated shared controller/worker socket volume is not disposable."""
    snapshot = _inventory(with_stale=False)
    ipc = gc.Volume(
        "boca-socios_boca_browser_ipc",
        (
            *BOCA_LABEL,
            ("boca.socios.cutover-a-attempt", ATTEMPT),
        ),
    )
    snapshot = replace(snapshot, volumes=(*snapshot.volumes, ipc))
    selected = gc.plan(
        snapshot,
        ATTEMPT,
        preserve_images=frozenset({CONTROLLER_IMAGE, WORKER_IMAGE}),
        preserve_containers=frozenset({CONTROLLER, WORKER}),
        retire_containers=frozenset(),
    )
    assert gc.Target("volume", ipc.name) not in selected.targets
    assert ipc.name in gc.PROTECTED_VOLUMES


def test_v2_host_modules_parse_under_python_310_syntax() -> None:
    """The host memfd bootstrap cannot import newer grammar than Python 3.10."""
    for module in (gc, v2):
        source = Path(module.__file__).read_text(encoding="utf-8")
        ast.parse(source, filename=module.__file__, feature_version=(3, 10))


def test_v2_parser_rejects_aggregate_inventory_over_object_budget() -> None:
    """Separate per-kind bounds cannot evade the host inventory's total 256 cap."""
    receipt, before, after = _completed()
    body = json.loads(_emit(receipt, before, after))
    body["before_counts"] = {
        "containers": 130,
        "images": 130,
        "networks": 0,
        "volumes": 0,
        "global_images": 130,
    }
    body["after_counts"] = {
        "containers": 130,
        "images": 129,
        "networks": 0,
        "volumes": 0,
        "global_images": 129,
    }
    with pytest.raises(gc.CleanupError):
        v2.verify_cleanup_v2_receipt(_canonical(body), ATTEMPT)


def test_protected_evidence_uses_first_and_last_internal_probes_without_extra_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Snapshots must come from this cleanup invocation, not a later census."""
    base = _inventory(with_stale=False)
    snapshots = [
        replace(base, disk=replace(base.disk, bytes_free=value))
        for value in (
            100_000,
            100_010,
            100_020,
        )
    ]
    reads: list[gc.Inventory] = []
    lease_attempts: list[str] = []

    def capture(**_kwargs: object) -> gc.Inventory:
        snapshot = snapshots[len(reads)]
        reads.append(snapshot)
        return snapshot

    monkeypatch.setattr(gc, "capture_inventory", capture)
    monkeypatch.setattr(
        gc,
        "verify_protected_boca_job_lease",
        lambda _lease, attempt: lease_attempts.append(attempt),
    )
    monkeypatch.setattr(gc, "delete_exact", lambda _target: pytest.fail("unexpected deletion"))
    evidence = gc.execute_protected_with_inventories(
        "SUCCESS",
        ATTEMPT,
        preserve_images=frozenset({CONTROLLER_IMAGE, WORKER_IMAGE}),
        preserve_containers=frozenset({CONTROLLER, WORKER}),
        retire_containers=frozenset(),
        lease=gc.BocaJobLease(ATTEMPT, 0, 0, True),
    )
    assert isinstance(evidence, gc.ProtectedCleanupEvidence)
    assert isinstance(evidence.receipt, gc.CleanupReceipt)
    assert evidence.receipt.status == "ACCEPT"
    assert evidence.before is snapshots[0]
    assert evidence.after is snapshots[2]
    assert evidence.receipt.before == snapshots[0].disk
    assert evidence.receipt.after == snapshots[2].disk
    assert reads == snapshots and lease_attempts == [ATTEMPT]
    body = v2.verify_cleanup_v2_receipt(
        v2.canonical_cleanup_v2_receipt(
            evidence.receipt,
            before=evidence.before,
            after=evidence.after,
            protected_containers=frozenset({CONTROLLER, WORKER}),
            protected_images=frozenset({CONTROLLER_IMAGE, WORKER_IMAGE}),
        ),
        ATTEMPT,
    )
    assert body["before_counts"] == body["after_counts"]


def test_original_execute_protected_return_type_and_probe_count_are_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing Cutover callers still receive CleanupReceipt, not an evidence tuple."""
    snapshot = _inventory(with_stale=False)
    reads = 0

    def capture(**_kwargs: object) -> gc.Inventory:
        nonlocal reads
        reads += 1
        return snapshot

    monkeypatch.setattr(gc, "capture_inventory", capture)
    monkeypatch.setattr(gc, "verify_protected_boca_job_lease", lambda *_args: None)
    monkeypatch.setattr(gc, "delete_exact", lambda _target: pytest.fail("unexpected deletion"))
    result = gc.execute_protected(
        "SUCCESS",
        ATTEMPT,
        preserve_images=frozenset({CONTROLLER_IMAGE, WORKER_IMAGE}),
        preserve_containers=frozenset({CONTROLLER, WORKER}),
        retire_containers=frozenset(),
        lease=gc.BocaJobLease(ATTEMPT, 0, 0, True),
    )
    assert type(result) is gc.CleanupReceipt
    assert result.status == "ACCEPT"
    assert reads == 3


def test_protected_evidence_r108_keeps_preprobe_outside_receipt_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R108's extra preflight stays, but it cannot become V2's 'before'."""
    base = _historical(_inventory(with_stale=False))
    snapshots = [
        replace(base, disk=replace(base.disk, bytes_free=value))
        for value in (
            90_000,
            100_000,
            100_010,
            100_020,
        )
    ]
    calls = 0
    attested = 0
    proof = gc.HistoricalRetainedImageProof(
        gc.HISTORICAL_RETIRE_TARGET,
        gc.HISTORICAL_RETIRE_DIGEST,
        gc.HISTORICAL_RETIRE_REVISION,
    )

    def capture(**_kwargs: object) -> gc.Inventory:
        nonlocal calls
        snapshot = snapshots[calls]
        calls += 1
        return snapshot

    def attest(snapshot: gc.Inventory) -> gc.HistoricalRetainedImageProof:
        nonlocal attested
        attested += 1
        assert gc.HISTORICAL_RETIRE_TARGET in snapshot.global_image_ids
        return proof

    monkeypatch.setattr(gc, "capture_inventory", capture)
    monkeypatch.setattr(gc, "attest_historical_retained_image", attest)
    monkeypatch.setattr(gc, "verify_protected_boca_job_lease", lambda *_args: None)
    monkeypatch.setattr(gc, "delete_exact", lambda _target: pytest.fail("unexpected deletion"))
    evidence = gc.execute_protected_with_inventories(
        "SUCCESS",
        ATTEMPT,
        preserve_images=frozenset({CONTROLLER_IMAGE, WORKER_IMAGE}),
        preserve_containers=frozenset({CONTROLLER, WORKER}),
        retire_containers=frozenset(),
        historical_retained=proof,
        lease=gc.BocaJobLease(ATTEMPT, 0, 0, True),
    )
    assert calls == attested == 4  # preprobe + the original three execute probes
    assert evidence.before is snapshots[1] and evidence.after is snapshots[3]
    assert evidence.receipt.retained_attested == (proof,)
    body = v2.verify_cleanup_v2_receipt(
        v2.canonical_cleanup_v2_receipt(
            evidence.receipt,
            before=evidence.before,
            after=evidence.after,
            protected_containers=frozenset({CONTROLLER, WORKER}),
            protected_images=frozenset({CONTROLLER_IMAGE, WORKER_IMAGE}),
        ),
        ATTEMPT,
    )
    assert body["retained_attested"][0]["classification"] == "KNOWN_HISTORICAL_QUARANTINE"


def test_protected_evidence_aborts_on_r108_midprobe_drift_without_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed forensic image cannot yield evidence or a cleanup ACCEPT."""
    snapshot = _historical(_inventory(with_stale=False))
    proof = gc.HistoricalRetainedImageProof(
        gc.HISTORICAL_RETIRE_TARGET,
        gc.HISTORICAL_RETIRE_DIGEST,
        gc.HISTORICAL_RETIRE_REVISION,
    )
    calls = 0
    deleted: list[gc.Target] = []

    def attest(_snapshot: gc.Inventory) -> gc.HistoricalRetainedImageProof:
        nonlocal calls
        calls += 1
        if calls >= 3:
            raise gc.CleanupError("historical quarantine drifted")
        return proof

    monkeypatch.setattr(gc, "capture_inventory", lambda **_kwargs: snapshot)
    monkeypatch.setattr(gc, "attest_historical_retained_image", attest)
    monkeypatch.setattr(gc, "verify_protected_boca_job_lease", lambda *_args: None)
    monkeypatch.setattr(gc, "delete_exact", deleted.append)
    with pytest.raises(gc.CleanupError, match="historical quarantine drifted"):
        gc.execute_protected_with_inventories(
            "SUCCESS",
            ATTEMPT,
            preserve_images=frozenset({CONTROLLER_IMAGE, WORKER_IMAGE}),
            preserve_containers=frozenset({CONTROLLER, WORKER}),
            retire_containers=frozenset(),
            historical_retained=proof,
            lease=gc.BocaJobLease(ATTEMPT, 0, 0, True),
        )
    # Existing execute() performs one final NO_GO reconciliation probe after
    # the third probe fails; it also reattests and remains non-mutating.
    assert calls == 4 and deleted == []


def test_protected_evidence_terminal_probe_error_cannot_be_filled_posthoc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing final Docker read produces NO_GO, not invented after counts."""
    snapshot = _inventory(with_stale=False)
    calls = 0

    def capture(**_kwargs: object) -> gc.Inventory:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise gc.CleanupError("terminal inventory unavailable")
        return snapshot

    monkeypatch.setattr(gc, "capture_inventory", capture)
    monkeypatch.setattr(gc, "verify_protected_boca_job_lease", lambda *_args: None)
    monkeypatch.setattr(gc, "delete_exact", lambda _target: pytest.fail("unexpected deletion"))
    with pytest.raises(gc.CleanupError, match="terminal inventory unavailable"):
        gc.execute_protected_with_inventories(
            "SUCCESS",
            ATTEMPT,
            preserve_images=frozenset({CONTROLLER_IMAGE, WORKER_IMAGE}),
            preserve_containers=frozenset({CONTROLLER, WORKER}),
            retire_containers=frozenset(),
            lease=gc.BocaJobLease(ATTEMPT, 0, 0, True),
        )
    assert calls == 3


def test_protected_evidence_lease_denial_prevents_all_docker_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The new entrypoint retains the original lease gate before its first probe."""
    calls = 0

    def capture(**_kwargs: object) -> gc.Inventory:
        nonlocal calls
        calls += 1
        return _inventory(with_stale=False)

    monkeypatch.setattr(gc, "capture_inventory", capture)
    monkeypatch.setattr(
        gc,
        "verify_protected_boca_job_lease",
        lambda *_args: (_ for _ in ()).throw(gc.CleanupError("lease rejected")),
    )
    with pytest.raises(gc.CleanupError, match="lease rejected"):
        gc.execute_protected_with_inventories(
            "SUCCESS",
            ATTEMPT,
            preserve_images=frozenset({CONTROLLER_IMAGE, WORKER_IMAGE}),
            preserve_containers=frozenset({CONTROLLER, WORKER}),
            retire_containers=frozenset(),
            lease=gc.BocaJobLease(ATTEMPT, 0, 0, True),
        )
    assert calls == 0
