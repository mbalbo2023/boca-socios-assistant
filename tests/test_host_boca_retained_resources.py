"""Read-only successor evidence; no host, Docker, credentials or effects."""

from __future__ import annotations

import importlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_postcommit as installed
from test_host_boca_pair_observe import _run

RUN = "43290000001"
IPC = "boca-socios_boca_browser_ipc"
SITE = "boca-socios_boca_site_config"
NETWORK = "boca-socios_boca_browser_egress"


def module():
    return importlib.import_module("boca_socios.host_boca_retained_resources")


def pair_receipt():
    value = json.loads(_run().removeprefix(b"BOCA_INSTALLED_PAIR "))
    value.update(
        source_sha=installed.SOURCE_SHA, attempt_id=installed.FAILED_ATTEMPT, observation_run_id=RUN
    )
    for item, cid, ref in zip(
        value["services"],
        (installed.CONTROLLER_ID, installed.WORKER_ID),
        (installed.CONTROLLER_IMAGE, installed.WORKER_IMAGE),
        strict=True,
    ):
        item.update(container_id=cid, image_ref=ref)
    from boca_socios import host_boca_pair_observe as pair

    return pair._canonical(value)


def inventory():
    labels = (("com.docker.compose.project", "boca-socios"),)
    return cleanup.Inventory(
        containers=(
            cleanup.Container(
                installed.CONTROLLER_ID,
                "/boca-socios-controller-1",
                "sha256:" + "d" * 64,
                True,
                labels,
                (IPC, SITE),
            ),
            cleanup.Container(
                installed.WORKER_ID,
                "/boca-socios-browser-worker-1",
                "sha256:" + "e" * 64,
                False,
                labels,
                (IPC, SITE),
            ),
        ),
        images=(
            cleanup.Image("sha256:" + "d" * 64, (installed.CONTROLLER_IMAGE,), cleanup.BOCA_SOURCE),
            cleanup.Image("sha256:" + "e" * 64, (installed.WORKER_IMAGE,), cleanup.BOCA_SOURCE),
            cleanup.Image("sha256:" + "f" * 64, (), cleanup.BOCA_SOURCE),
        ),
        networks=(
            cleanup.Network(
                NETWORK,
                "8" * 64,
                (),
                labels
                + (
                    ("com.docker.compose.network", "boca_browser_egress"),
                    ("boca.socios.browser-ipc-attempt", "43217075287"),
                ),
            ),
        ),
        volumes=tuple(
            cleanup.Volume(
                name,
                labels
                + (
                    ("com.docker.compose.volume", role),
                    ("boca.socios.browser-ipc-attempt", attempt),
                ),
            )
            for name, role, attempt in (
                (IPC, "boca_browser_ipc", "42806447101"),
                (SITE, "boca_site_config", "43217075287"),
            )
        ),
        disk=cleanup.DiskInodes(10, 20),
        global_image_ids=frozenset("sha256:" + c * 64 for c in "def"),
    )


def snapshot(inv=None, *, identities=None):
    identities = identities or {IPC: "1" * 64, SITE: "2" * 64, "control_socket_directory": "3" * 64}
    return module().snapshot(
        RUN,
        inventory_reader=lambda: inventory() if inv is None else inv,
        pair_reader=lambda run: pair_receipt(),
        identity_reader=identities.__getitem__,
        revision_reader=lambda image: installed.SOURCE_SHA,
    )


def test_retained_resources_keep_distinct_creation_provenance_and_image_references():
    value = snapshot()
    assert value["volumes"] == [
        {
            "name": IPC,
            "creator_attempt": "42806447101",
            "inode_sha256": "1" * 64,
            "container_references": 2,
        },
        {
            "name": SITE,
            "creator_attempt": "43217075287",
            "inode_sha256": "2" * 64,
            "container_references": 2,
        },
    ]
    assert value["egress"] == {
        "name": NETWORK,
        "id": "8" * 64,
        "creator_attempt": "43217075287",
        "peer_ids": [],
    }
    assert [item["container_references"] for item in value["images"]] == [1, 1, 0]
    assert value["control_socket_directory_inode_sha256"] == "3" * 64
    assert value["successor_apply_authorized"] is False


def test_observer_double_reads_and_never_promotes_observation_to_authority():
    value = snapshot()
    calls = []

    def reader(run):
        calls.append(run)
        return value

    raw = module().observe(RUN, snapshot_reader=reader)
    assert calls == [RUN, RUN]
    assert module().verify(raw, RUN) == raw
    assert b'"observer_writes":0' in raw
    assert b'"successor_apply_authorized":false' in raw
    assert b"Mounts" not in raw and b"/home" not in raw and b"Env" not in raw


@pytest.mark.parametrize(
    "field", ("volumes", "images", "egress", "control_socket_directory_inode_sha256")
)
def test_observer_rejects_drift_between_independent_captures(field):
    first = snapshot()
    second = dict(first)
    second[field] = None
    values = iter((first, second))
    with pytest.raises(module().ResourceNoGo):
        module().observe(RUN, snapshot_reader=lambda _: next(values))


@pytest.mark.parametrize("change", ("inode", "provenance", "image_reference"))
def test_observer_rejects_two_individually_valid_but_different_snapshots(change):
    first = snapshot()
    second = json.loads(json.dumps(first))
    if change == "inode":
        second["volumes"][0]["inode_sha256"] = "9" * 64
    elif change == "provenance":
        second["volumes"][0]["creator_attempt"] = "43219999999"
        second["expected_resource_provenance"] = False
    else:
        second["images"][2]["references"] = [
            "ghcr.io/mbalbo2023/boca-socios-assistant:sha-" + "a" * 40
        ]
    for value in (first, second):
        raw = (
            b"BOCA_RETAINED_RESOURCES "
            + json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
            + b"\n"
        )
        assert module().verify(raw, RUN) == raw
    values = iter((first, second))
    with pytest.raises(module().ResourceNoGo):
        module().observe(RUN, snapshot_reader=lambda _: next(values))


@pytest.mark.parametrize(
    "damage",
    ("foreign_container", "missing_volume", "wrong_role", "secret_reference", "active_peer"),
)
def test_resource_admission_rejects_ambiguity_without_publishing_untrusted_values(damage):
    inv = inventory()
    if damage == "foreign_container":
        inv = replace(
            inv, containers=inv.containers + (replace(inv.containers[0], ident="9" * 64),)
        )
    elif damage == "missing_volume":
        inv = replace(inv, volumes=inv.volumes[:1])
    elif damage == "wrong_role":
        inv = replace(
            inv, volumes=(replace(inv.volumes[0], labels=(("private", "secret"),)), inv.volumes[1])
        )
    elif damage == "secret_reference":
        inv = replace(
            inv, images=(replace(inv.images[0], references=("secret-token",)), *inv.images[1:])
        )
    else:
        inv = replace(inv, networks=(replace(inv.networks[0], attached_ids=("9" * 64,)),))
    with pytest.raises(module().ResourceNoGo, match="retained Boca resource evidence unverified"):
        snapshot(inv)


def test_original_labels_are_observed_not_silently_repinned():
    inv = inventory()
    changed = tuple(
        (k, "43219999999" if k == "boca.socios.browser-ipc-attempt" else v)
        for k, v in inv.volumes[0].labels
    )
    value = snapshot(
        replace(inv, volumes=(replace(inv.volumes[0], labels=changed), inv.volumes[1]))
    )
    assert value["volumes"][0]["creator_attempt"] == "43219999999"
    assert value["expected_resource_provenance"] is False
    assert value["successor_apply_authorized"] is False


def test_verifier_rejects_forged_authorization_and_duplicate_fields():
    raw = module().observe(RUN, snapshot_reader=lambda _: snapshot())
    for bad in (
        raw.replace(b'"successor_apply_authorized":false', b'"successor_apply_authorized":true'),
        raw.replace(b'"schema":1', b'"schema":1,"schema":1'),
    ):
        with pytest.raises(module().ResourceNoGo):
            module().verify(bad, RUN)


@pytest.mark.parametrize(
    "damage", ("missing_digest", "unverified_source", "different_revision", "different_network")
)
def test_inventory_cannot_disagree_with_verified_installed_pair(damage):
    inv = inventory()
    if damage == "missing_digest":
        inv = replace(inv, images=(replace(inv.images[0], references=()), *inv.images[1:]))
    elif damage == "unverified_source":
        inv = replace(inv, images=(replace(inv.images[0], source=None), *inv.images[1:]))
    elif damage == "different_network":
        inv = replace(inv, networks=(replace(inv.networks[0], ident="9" * 64),))
    with pytest.raises(module().ResourceNoGo):
        module().snapshot(
            RUN,
            inventory_reader=lambda: inv,
            pair_reader=lambda _: pair_receipt(),
            identity_reader=lambda _: "1" * 64,
            revision_reader=lambda _: (
                "a" * 40 if damage == "different_revision" else installed.SOURCE_SHA
            ),
        )


def test_inode_witness_uses_metadata_only_and_detects_replacement(tmp_path: Path, monkeypatch):
    observer = module()
    target = tmp_path / "volume"
    target.mkdir()
    monkeypatch.setattr(observer, "_PATHS", {IPC: target})
    monkeypatch.setattr(
        observer.cleanup,
        "_docker",
        lambda *args: (
            str(observer._ROOT)
            if args[0] == "info"
            else json.dumps(
                {
                    "name": IPC,
                    "driver": "local",
                    "scope": "local",
                    "options": {},
                    "mountpoint": str(target),
                }
            )
        ),
    )
    before = observer._identity(IPC)
    assert len(before) == 64 and observer._identity(IPC) == before
    target.rename(tmp_path / "retained")
    target.mkdir()
    assert observer._identity(IPC) != before


def test_inode_witness_rejects_symlink_ancestors(tmp_path: Path, monkeypatch):
    observer = module()
    actual = tmp_path / "actual"
    actual.mkdir()
    (actual / "volume").mkdir()
    (tmp_path / "alias").symlink_to(actual, target_is_directory=True)
    monkeypatch.setattr(observer, "_PATHS", {IPC: tmp_path / "alias" / "volume"})
    monkeypatch.setattr(
        observer.cleanup,
        "_docker",
        lambda *args: (
            str(observer._ROOT)
            if args[0] == "info"
            else json.dumps(
                {
                    "name": IPC,
                    "driver": "local",
                    "scope": "local",
                    "options": {},
                    "mountpoint": str(tmp_path / "alias" / "volume"),
                }
            )
        ),
    )
    with pytest.raises(OSError):
        observer._identity(IPC)


def test_volume_mountpoint_must_identify_the_directory_being_statted(tmp_path: Path, monkeypatch):
    observer = module()
    target = tmp_path / "volume"
    target.mkdir()
    monkeypatch.setattr(observer, "_PATHS", {IPC: target})
    monkeypatch.setattr(
        observer.cleanup,
        "_docker",
        lambda *args: (
            str(observer._ROOT)
            if args[0] == "info"
            else json.dumps(
                {
                    "name": IPC,
                    "driver": "local",
                    "scope": "local",
                    "options": {},
                    "mountpoint": "/foreign",
                }
            )
        ),
    )
    with pytest.raises(observer.ResourceNoGo):
        observer._identity(IPC)


def test_receipt_parser_rejects_active_image_with_missing_installed_digest():
    value = snapshot()
    value["images"][0]["references"] = []
    raw = (
        b"BOCA_RETAINED_RESOURCES "
        + json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )
    with pytest.raises(module().ResourceNoGo):
        module().verify(raw, RUN)
