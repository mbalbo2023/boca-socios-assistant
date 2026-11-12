"""Offline post-install cleanup contract for #323; no Docker daemon or host."""

from __future__ import annotations

import io
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


def _physical_observer_fixture(*, stale: str = "none") -> gc.Inventory:
    """Boca-only synthetic snapshot; no production Docker or filesystem."""
    original = gc.Container(
        ACTIVE_ID,
        "/boca-socios-controller-1",
        ACTIVE_IMAGE,
        True,
        (*BOCA, ("com.docker.compose.service", "controller")),
        (DATA, "boca-socios_boca_key", "boca-socios_boca_owner"),
        ("boca-socios_boca_private",),
    )
    images = [
        gc.Image(
            ACTIVE_IMAGE,
            ("ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "d" * 64,),
            None,  # The installed 04-Nov controller lacks OCI source.
        )
    ]
    if stale != "none":
        images.append(
            gc.Image(
                OLD_IMAGE,
                ("ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "e" * 64,),
                gc.BOCA_SOURCE if stale == "known" else None,
            )
        )
    return gc.Inventory(
        containers=(original,),
        images=tuple(images),
        networks=(gc.Network("boca-socios_boca_private", PRIVATE_NET, (ACTIVE_ID,), BOCA),),
        volumes=tuple(
            gc.Volume(name, BOCA)
            for name in (DATA, "boca-socios_boca_key", "boca-socios_boca_owner")
        ),
        disk=gc.DiskInodes(100_000, 700, 500_000, 900, 100, 101, 200, 201),
        global_image_ids=frozenset({image.ident for image in images}),
    )


@pytest.mark.parametrize(
    ("stale", "classification", "target_count", "uncertain_count"),
    [
        ("none", "NO_CONFIRMED_REMNANTS", 0, 0),
        ("known", "BOCA_REMNANTS_IDENTIFIED", 1, 0),
        ("unknown", "INDETERMINATE", 0, 1),
    ],
)
def test_postapply_cleanup_readonly_plan_never_deletes(
    stale: str, classification: str, target_count: int, uncertain_count: int
) -> None:
    inventory = _physical_observer_fixture(stale=stale)
    calls = 0

    def probe() -> gc.Inventory:
        nonlocal calls
        calls += 1
        return inventory

    receipt = gc.observe_postapply_cleanup(ATTEMPT, ACTIVE_ID, probe=probe)
    assert calls == 2
    assert receipt["classification"] == classification
    assert receipt["status"] == "READ_ONLY_NO_GO"
    assert receipt["original_preserved"] is True
    assert receipt["go_for_retry"] is False
    assert receipt["cleanup_executed"] is False
    assert receipt["observer_writes"] == 0
    assert receipt["protected_image_id"] == ACTIVE_IMAGE
    assert len(receipt["known_remnants"]) == target_count
    assert len(receipt["retained_uncertain"]) == uncertain_count
    assert all(x["id"] not in (ACTIVE_ID, ACTIVE_IMAGE) for x in receipt["known_remnants"])
    raw = gc.canonical_readonly_cleanup_receipt(receipt)
    assert gc.verify_readonly_cleanup_receipt(raw, ATTEMPT, ACTIVE_ID) == receipt


def test_postapply_cleanup_readonly_rejects_legacy_or_storage_drift() -> None:
    baseline = _physical_observer_fixture()
    stopped = replace(baseline, containers=(replace(baseline.containers[0], running=False),))
    with pytest.raises(gc.CleanupError):
        gc.observe_postapply_cleanup(ATTEMPT, ACTIVE_ID, probe=lambda: stopped)
    with pytest.raises(gc.CleanupError):
        gc.observe_postapply_cleanup(ATTEMPT, OLD_ID, probe=lambda: baseline)
    with pytest.raises(gc.CleanupError):
        gc.observe_postapply_cleanup(ATTEMPT, ACTIVE_ID, probe=iter([baseline, stopped]).__next__)
    changed_storage = replace(baseline, disk=replace(baseline.disk, docker_inode=999))
    with pytest.raises(gc.CleanupError):
        gc.observe_postapply_cleanup(
            ATTEMPT, ACTIVE_ID, probe=iter([baseline, changed_storage]).__next__
        )


def test_postapply_cleanup_unknown_global_image_id_is_uncertain_without_inspection() -> None:
    baseline = _physical_observer_fixture()
    # A global ID is not proof of Boca provenance, nor is it removable.
    unknown = replace(baseline, global_image_ids=baseline.global_image_ids | {FOREIGN_IMAGE})
    result = gc.observe_postapply_cleanup(ATTEMPT, ACTIVE_ID, probe=lambda: unknown)
    assert result["classification"] == "INDETERMINATE"
    assert result["unclassified_image_id_count"] == 1
    assert result["known_remnants"] == []
    assert FOREIGN_IMAGE not in str(result)


def test_boca_reference_only_image_provenance_reads_only_public_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The uncertain image is not a deletion target or an invitation to read Env."""
    snapshot = _physical_observer_fixture(stale="unknown")
    source_sha = "e" * 40
    tag = "ghcr.io/mbalbo2023/boca-socios-assistant:sha-" + source_sha
    digest = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "f" * 64
    calls: list[tuple[str, ...]] = []

    def fake_docker(*args: str) -> str:
        calls.append(args)
        if args == (
            "image",
            "ls",
            "-a",
            "-q",
            "--no-trunc",
            "--filter",
            "reference=ghcr.io/mbalbo2023/boca-socios-assistant*",
        ):
            return OLD_IMAGE + "\n"
        assert args[:4] == ("image", "inspect", "--format", args[3])
        assert args[-1] == OLD_IMAGE and len(args) == 5
        template = args[3]
        if template == "{{json .Id}}":
            return json.dumps(OLD_IMAGE)
        if template == "{{json .RepoTags}}":
            return json.dumps([tag, "docker.io/private/foreign-alias:SECRET_SHOULD_NOT_LEAK"])
        if template == "{{json .RepoDigests}}":
            return json.dumps([digest])
        if template == "{{json .Size}}":
            return "734003200"
        if "org.opencontainers.image.source" in template:
            return "null"
        if "org.opencontainers.image.revision" in template:
            return json.dumps(source_sha)
        pytest.fail(f"unreviewed Docker field: {template}")

    monkeypatch.setattr(gc, "_docker", fake_docker)
    proof = gc._observe_boca_reference_image(OLD_IMAGE, snapshot)
    assert proof == {
        "id": OLD_IMAGE,
        "repo_tags": [tag],
        "repo_digests": [digest],
        "untrusted_alias_count": 1,
        "oci_source_status": "ABSENT",
        "oci_revision": source_sha,
        "logical_size_bytes": 734003200,
        "container_ref_count": 0,
        "deletion_authorized": False,
    }
    assert len(calls) == 8
    assert "SECRET_SHOULD_NOT_LEAK" not in str(proof)
    assert all("Config.Env" not in " ".join(call) for call in calls)
    assert all("{{json .Config.Labels}}" not in " ".join(call) for call in calls)
    assert all("rm" not in call and "prune" not in call for call in calls)


def test_boca_reference_only_provenance_stays_uncertain_and_rejects_tampering() -> None:
    snapshot = _physical_observer_fixture(stale="unknown")
    read_ids: list[str] = []
    evidence = {
        "id": OLD_IMAGE,
        "repo_tags": ["ghcr.io/mbalbo2023/boca-socios-assistant:sha-" + "d" * 40],
        "repo_digests": ["ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "e" * 64],
        "untrusted_alias_count": 0,
        "oci_source_status": "ABSENT",
        "oci_revision": "d" * 40,
        "logical_size_bytes": 400_000_000,
        "container_ref_count": 0,
        "deletion_authorized": False,
    }

    def observe_provenance(ident: str, _: gc.Inventory) -> dict[str, object]:
        read_ids.append(ident)
        return evidence.copy()

    with_foreign_unknown = replace(
        snapshot, global_image_ids=snapshot.global_image_ids | {FOREIGN_IMAGE}
    )
    receipt = gc.observe_postapply_cleanup(
        ATTEMPT,
        ACTIVE_ID,
        probe=lambda: with_foreign_unknown,
        probe_provenance=observe_provenance,
    )
    assert read_ids == [OLD_IMAGE, OLD_IMAGE]
    assert receipt["classification"] == "INDETERMINATE"
    assert receipt["known_remnants"] == []
    assert receipt["retained_uncertain"]
    assert receipt["image_provenance"] == [evidence]
    assert FOREIGN_IMAGE not in str(receipt)
    raw = gc.canonical_readonly_cleanup_receipt(receipt)
    assert gc.verify_readonly_cleanup_receipt(raw, ATTEMPT, ACTIVE_ID) == receipt
    for tampering in (
        {**evidence, "deletion_authorized": True},
        {**evidence, "repo_tags": ["docker.io/foreign:secret"]},
        {**evidence, "repo_tags": [{"non_string": "payload"}]},
        {**evidence, "oci_revision": "secret"},
        {**evidence, "container_ref_count": 1},
        {**evidence, "id": ACTIVE_IMAGE},
    ):
        forged = {**receipt, "image_provenance": [tampering]}
        with pytest.raises(gc.CleanupError):
            gc.verify_readonly_cleanup_receipt(
                gc.canonical_readonly_cleanup_receipt(forged), ATTEMPT, ACTIVE_ID
            )


def test_boca_reference_only_image_provenance_changed_second_read_no_go() -> None:
    snapshot = _physical_observer_fixture(stale="unknown")
    calls = 0

    def drift(_ident: str, _snapshot: gc.Inventory) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"logical_size_bytes": calls}

    with pytest.raises(gc.CleanupError, match="provenance drifted"):
        gc.observe_postapply_cleanup(
            ATTEMPT, ACTIVE_ID, probe=lambda: snapshot, probe_provenance=drift
        )


def _historical_quarantine_fixture() -> tuple[gc.Inventory, dict[str, object]]:
    original = _physical_observer_fixture()
    historical = gc.Image(
        gc.HISTORICAL_RETIRE_TARGET,
        ("ghcr.io/mbalbo2023/boca-socios-assistant:unverified",),
        None,
    )
    snapshot = replace(
        original,
        images=(*original.images, historical),
        global_image_ids=original.global_image_ids | {historical.ident},
    )
    provenance: dict[str, object] = {
        "id": gc.HISTORICAL_RETIRE_TARGET,
        "repo_tags": [],
        "repo_digests": [gc.HISTORICAL_RETIRE_DIGEST],
        "untrusted_alias_count": 0,
        "oci_source_status": "ABSENT",
        "oci_revision": gc.HISTORICAL_RETIRE_REVISION,
        "logical_size_bytes": gc.HISTORICAL_RETIRE_SIZE,
        "container_ref_count": 0,
        "deletion_authorized": False,
    }
    return snapshot, provenance


def test_cutover_historical_quarantine_accepts_only_attested_release_and_reports_retention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot, provenance = _historical_quarantine_fixture()
    observed: list[str] = []

    def observe(ident: str, _: gc.Inventory) -> dict[str, object]:
        observed.append(ident)
        return dict(provenance)

    monkeypatch.setattr(gc, "_observe_boca_reference_image", observe)
    monkeypatch.setattr(gc, "capture_inventory", lambda **_kw: snapshot)
    monkeypatch.setattr(gc, "verify_protected_boca_job_lease", lambda *_a: None)
    proof = gc.attest_historical_retained_image(snapshot)
    receipt = gc.execute_protected(
        "SUCCESS",
        ATTEMPT,
        preserve_images=frozenset(),
        preserve_containers=frozenset({ACTIVE_ID}),
        retire_containers=frozenset(),
        historical_retained=proof,
        lease=gc.BocaJobLease(ATTEMPT, 0, os.getpid(), True),
    )
    assert receipt.status == "ACCEPT"
    assert receipt.retained_attested == (proof,)
    report = json.loads(receipt.redacted_json())
    assert report["version"] == 2
    assert report["retained_attested"] == [
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
    assert report["retained_uncertain"] == [] and report["known_residue"] == []
    assert observed == [gc.HISTORICAL_RETIRE_TARGET] * 5


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("id", "sha256:" + "0" * 64),
        ("repo_tags", ["ghcr.io/third-party/alias:latest"]),
        ("repo_digests", ["ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "0" * 64]),
        ("untrusted_alias_count", 1),
        ("oci_source_status", "BOCA"),
        ("oci_revision", "0" * 40),
        ("logical_size_bytes", 1),
        ("container_ref_count", 1),
        ("deletion_authorized", True),
    ],
)
def test_historical_quarantine_rejects_any_changed_public_provenance(
    field: str, bad: object
) -> None:
    snapshot, provenance = _historical_quarantine_fixture()
    provenance[field] = bad
    with pytest.raises(gc.CleanupError, match="historical|quarantine"):
        gc.attest_historical_retained_image(
            snapshot, probe_provenance=lambda _ident, _snapshot: provenance
        )


def test_historical_quarantine_refuses_container_reference_or_missing_image() -> None:
    snapshot, provenance = _historical_quarantine_fixture()
    shared = replace(
        snapshot,
        containers=(replace(snapshot.containers[0], image_id=gc.HISTORICAL_RETIRE_TARGET),),
    )
    missing = replace(
        snapshot,
        images=snapshot.images[:1],
        global_image_ids=snapshot.global_image_ids - {gc.HISTORICAL_RETIRE_TARGET},
    )
    for changed in (shared, missing):
        with pytest.raises(gc.CleanupError):
            gc.attest_historical_retained_image(
                changed, probe_provenance=lambda _ident, _snapshot: provenance
            )


def test_cleanup_never_accepts_unclassified_global_image_without_inspection() -> None:
    snapshot = _physical_observer_fixture()
    another_image = replace(
        snapshot,
        global_image_ids=snapshot.global_image_ids | {FOREIGN_IMAGE},
    )
    selected = gc.plan(
        another_image,
        ATTEMPT,
        preserve_images=frozenset({ACTIVE_IMAGE}),
        preserve_containers=frozenset({ACTIVE_ID}),
        retire_containers=frozenset(),
    )
    assert selected.uncertain == ("image:global-unclassified-NO_GO",)
    assert FOREIGN_IMAGE not in repr(selected)


def test_cleanup_refuses_disappearing_foreign_global_image_without_disclosing_identity() -> None:
    baseline = _physical_observer_fixture()
    first = replace(baseline, global_image_ids=baseline.global_image_ids | {FOREIGN_IMAGE})
    snapshots = iter((first, baseline, baseline))
    deleted: list[gc.Target] = []
    receipt = gc.execute(
        "SUCCESS",
        ATTEMPT,
        preserve_images=frozenset({ACTIVE_IMAGE}),
        preserve_containers=frozenset({ACTIVE_ID}),
        retire_containers=frozenset(),
        probe=snapshots.__next__,
        delete_exact=deleted.append,
    )
    assert deleted == []
    assert receipt.status == "NO_GO"
    assert "image:global-census-drift-NO_GO" in receipt.retained_uncertain
    assert FOREIGN_IMAGE not in receipt.redacted_json()


def test_cutover_historical_quarantine_fails_on_second_probe_identity_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot, provenance = _historical_quarantine_fixture()
    proof = gc.attest_historical_retained_image(
        snapshot, probe_provenance=lambda _ident, _snapshot: provenance
    )
    attempts = 0

    def changing(_ident: str, _snapshot: gc.Inventory) -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        return dict(provenance, oci_revision="0" * 40) if attempts > 1 else dict(provenance)

    monkeypatch.setattr(gc, "_observe_boca_reference_image", changing)
    monkeypatch.setattr(gc, "capture_inventory", lambda **_kw: snapshot)
    monkeypatch.setattr(gc, "verify_protected_boca_job_lease", lambda *_a: None)
    with pytest.raises(gc.CleanupError, match="historical|quarantine"):
        gc.execute_protected(
            "SUCCESS",
            ATTEMPT,
            preserve_images=frozenset(),
            preserve_containers=frozenset({ACTIVE_ID}),
            retire_containers=frozenset(),
            historical_retained=proof,
            lease=gc.BocaJobLease(ATTEMPT, 0, os.getpid(), True),
        )


def test_rootless_disk_cache_audit_only_outputs_aggregate_not_foreign_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_docker(*args: str) -> str:
        calls.append(args)
        if args == ("system", "df", "--format", "{{json .}}"):
            return "\n".join(
                json.dumps(row)
                for row in (
                    {
                        "Type": "Images",
                        "TotalCount": "2",
                        "Active": "1",
                        "Size": "130.7MB",
                        "Reclaimable": "63MB (48%)",
                    },
                    {
                        "Type": "Containers",
                        "TotalCount": "1",
                        "Active": "1",
                        "Size": "2MB",
                        "Reclaimable": "0B",
                    },
                    {
                        "Type": "Local Volumes",
                        "TotalCount": "3",
                        "Active": "3",
                        "Size": "5GB",
                        "Reclaimable": "0 B",
                    },
                    {
                        "Type": "Build Cache",
                        "TotalCount": "2",
                        "Active": "0",
                        "Size": "1.8GB",
                        "Reclaimable": "1.6GB (89%)",
                    },
                )
            )
        if args == ("buildx", "ls", "--format", "{{.Builder.Name}}:{{.DriverEndpoint}}"):
            return "default: docker\ndefault: default\nforeign-porota: ssh://private.example\n"
        if args == ("buildx", "du", "--builder", "default", "--format=json"):
            return "\n".join(
                json.dumps(row)
                for row in (
                    {
                        "ID": "aa",
                        "Description": "PRIVATE_POROTA_SECRET",
                        "Size": "1800000000",
                        "Reclaimable": True,
                        "Shared": False,
                        "Mutable": False,
                    },
                    {
                        "ID": "bb",
                        "Description": "COPY PRIVATE_ENV",
                        "Size": "2000000",
                        "Reclaimable": False,
                        "Shared": True,
                        "Mutable": True,
                    },
                )
            )
        pytest.fail(f"unexpected Docker query: {args}")

    monkeypatch.setattr(gc, "_docker", fake_docker)
    accounting = gc._read_rootless_storage_usage()
    gc._validate_rootless_disk_accounting(accounting)
    assert accounting["system_df_status"] == "OBSERVED"
    assert accounting["buildx_status"] == "OBSERVED"
    assert accounting["buildx"] == {
        "records": 2,
        "total_record_bytes": 1_802_000_000,
        "reclaimable_record_bytes": 1_800_000_000,
        "shared_record_bytes": 2_000_000,
        "mutable_records": 1,
    }
    assert all("prune" not in args and "rm" not in args for args in calls)
    assert "PRIVATE_POROTA_SECRET" not in str(accounting)
    assert "PRIVATE_ENV" not in str(accounting)
    assert "ssh://private.example" not in str(accounting)
    assert calls[-1] == ("buildx", "du", "--builder", "default", "--format=json")


def test_rootless_df_accepts_official_docker_json_reclaimable_without_percent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Docker CLI system-df example has `158B` without `(...%)`."""

    def fake_docker(*args: str) -> str:
        if args == ("system", "df", "--format", "{{json .}}"):
            return "\n".join(
                json.dumps(row)
                for row in (
                    {
                        "Type": "Images",
                        "TotalCount": "6",
                        "Active": "2",
                        "Size": "2.631GB",
                        "Reclaimable": "2.498GB (94%)",
                    },
                    {
                        "Type": "Containers",
                        "TotalCount": "7",
                        "Active": "1",
                        "Size": "2.23kB",
                        "Reclaimable": "1.114kB (49%)",
                    },
                    {
                        "Type": "Local Volumes",
                        "TotalCount": "1",
                        "Active": "0",
                        "Size": "256.5MB",
                        "Reclaimable": "256.5MB (100%)",
                    },
                    {
                        "Type": "Build Cache",
                        "TotalCount": "5",
                        "Active": "0",
                        "Size": "158B",
                        "Reclaimable": "158B",
                    },
                )
            )
        if args[0:2] == ("buildx", "ls"):
            return "default:docker-container\n"
        pytest.fail("unexpected Docker query")

    monkeypatch.setattr(gc, "_docker", fake_docker)
    accounting = gc._read_rootless_storage_usage()
    gc._validate_rootless_disk_accounting(accounting)
    assert accounting["system_df_status"] == "OBSERVED"
    assert accounting["system_df"][0]["kind"] == "Build Cache"
    assert accounting["system_df"][0]["reclaimable_display"] == "158B"


def test_rootless_cache_audit_rejects_remote_buildx_and_receipt_forgery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_docker(*args: str) -> str:
        calls.append(args)
        if args[0:2] == ("system", "df"):
            return json.dumps(
                {
                    "Type": "Build Cache",
                    "TotalCount": "4",
                    "Active": "0",
                    "Size": "2GB",
                    "Reclaimable": "1.9GB (95%)",
                }
            )
        if args[0:2] == ("buildx", "ls"):
            return "default: docker-container\ndefault: ssh://other.host\n"
        pytest.fail("remote Buildx query forbidden")

    monkeypatch.setattr(gc, "_docker", fake_docker)
    accounting = gc._read_rootless_storage_usage()
    assert accounting["system_df_status"] == "OBSERVED"
    assert accounting["buildx_status"] == "UNAVAILABLE"
    assert all("du" not in call for call in calls)
    receipt = gc.observe_postapply_cleanup(
        ATTEMPT,
        ACTIVE_ID,
        probe=lambda: _physical_observer_fixture(stale="unknown"),
        probe_storage=lambda: accounting,
    )
    assert (
        gc.verify_readonly_cleanup_receipt(
            gc.canonical_readonly_cleanup_receipt(receipt), ATTEMPT, ACTIVE_ID
        )
        == receipt
    )
    for changed in (
        {**accounting, "system_df": [{"kind": "foreign-Porota"}]},
        {**accounting, "deletion_authorized": True},
        {**accounting, "buildx": {**accounting["buildx"], "records": 9999}},
    ):
        with pytest.raises(gc.CleanupError):
            gc.verify_readonly_cleanup_receipt(
                gc.canonical_readonly_cleanup_receipt({**receipt, "storage_accounting": changed}),
                ATTEMPT,
                ACTIVE_ID,
            )


def test_host_crypto_probe_imports_isolated_as_boca_owner_without_secret_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[object] = []
    monkeypatch.setattr(gc.os, "geteuid", lambda: gc.EXPECTED_UID)
    monkeypatch.setattr(gc.os, "getegid", lambda: gc.EXPECTED_GID)

    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        seen.extend((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="45.0.1\n", stderr="PRIVATE_SECRET")

    monkeypatch.setattr(gc.subprocess, "run", fake_run)
    receipt = gc._probe_host_python_crypto()
    gc._validate_host_python_crypto(receipt)
    assert receipt == {
        "scope": "HOST_PYTHON_UID10001",
        "status": "AVAILABLE",
        "version": "45.0.1",
        "probe_writes": 0,
    }
    args, kwargs = seen
    assert args == [
        gc.sys.executable,
        "-I",
        "-B",
        "-c",
        "import cryptography; print(cryptography.__version__)",
    ]
    assert kwargs["env"] == {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    assert kwargs["timeout"] == 5
    assert "PRIVATE_SECRET" not in str(receipt)


@pytest.mark.parametrize(
    ("exit_code", "stdout", "expected"),
    [(1, "secret", "IMPORT_FAILED"), (0, "bad\nsecret", "UNAVAILABLE")],
)
def test_host_crypto_probe_has_fail_closed_status_and_receipt_contract(
    monkeypatch: pytest.MonkeyPatch, exit_code: int, stdout: str, expected: str
) -> None:
    monkeypatch.setattr(gc.os, "geteuid", lambda: gc.EXPECTED_UID)
    monkeypatch.setattr(gc.os, "getegid", lambda: gc.EXPECTED_GID)
    monkeypatch.setattr(
        gc.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=exit_code, stdout=stdout),
    )
    receipt = gc._probe_host_python_crypto()
    assert receipt["status"] == expected
    assert receipt["version"] is None
    gc._validate_host_python_crypto(receipt)
    base = gc.observe_postapply_cleanup(
        ATTEMPT,
        ACTIVE_ID,
        probe=lambda: _physical_observer_fixture(stale="unknown"),
        probe_host_crypto=lambda: receipt,
    )
    gc.verify_readonly_cleanup_receipt(
        gc.canonical_readonly_cleanup_receipt(base), ATTEMPT, ACTIVE_ID
    )
    forged = {**base, "host_python_crypto": {**receipt, "status": "AVAILABLE"}}
    with pytest.raises(gc.CleanupError):
        gc.verify_readonly_cleanup_receipt(
            gc.canonical_readonly_cleanup_receipt(forged), ATTEMPT, ACTIVE_ID
        )


def test_host_crypto_probe_refuses_non_boca_uid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gc.os, "geteuid", lambda: 0)
    with pytest.raises(gc.CleanupError, match="rootless identity"):
        gc._probe_host_python_crypto()


def test_owner_volume_metadata_only_stats_two_public_files_and_no_contents(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    owner = tmp_path / "docker" / "volumes" / gc.OWNER_VOLUME / "_data"
    owner.mkdir(parents=True)
    (owner / "credential_id").write_bytes(b"SECRET_CREDENTIAL_VALUE")
    (owner / "public_key.der").write_bytes(b"PRIVATE_BUT_PUBLIC_CERT_BYTES")
    (owner / "private_secret.key").write_bytes(b"MUST_NOT_READ")
    root = tmp_path / "docker"
    recorded: list[tuple[str, ...]] = []
    uid, gid = os.geteuid(), os.getegid()
    monkeypatch.setattr(gc, "EXPECTED_UID", uid)
    monkeypatch.setattr(gc, "EXPECTED_GID", gid)
    monkeypatch.setattr(gc.pwd, "getpwuid", lambda _uid: SimpleNamespace(pw_dir=str(tmp_path)))

    def fake_docker(*args: str) -> str:
        recorded.append(args)
        if args == ("info", "--format", "{{json .}}"):
            return json.dumps({"DockerRootDir": str(root)})
        if args == (
            "volume",
            "inspect",
            "--format",
            "{{json .Mountpoint}}",
            gc.OWNER_VOLUME,
        ):
            return json.dumps(str(owner))
        pytest.fail("unapproved Docker command")

    monkeypatch.setattr(gc, "_docker", fake_docker)
    snapshot = _physical_observer_fixture(stale="unknown")
    snapshot = replace(
        snapshot,
        disk=replace(
            snapshot.disk,
            docker_device=root.stat().st_dev,
            docker_inode=root.stat().st_ino,
        ),
    )
    metadata = gc._read_owner_public_metadata(snapshot)
    gc._validate_owner_metadata(metadata)
    assert metadata["status"] == "OBSERVED"
    assert metadata["owner_directory"] == {"uid": uid, "gid": gid, "mode": 0o755}
    assert metadata["public_files"]["credential_id"]["status"] == "PRESENT"
    assert metadata["public_files"]["public_key.der"]["status"] == "PRESENT"
    assert metadata["deletion_authorized"] is False
    assert "SECRET_CREDENTIAL_VALUE" not in str(metadata)
    assert "PRIVATE_BUT_PUBLIC_CERT_BYTES" not in str(metadata)
    assert "MUST_NOT_READ" not in str(metadata)
    assert len(recorded) == 2
    assert all("exec" not in args and "rm" not in args for args in recorded)
    receipt = gc.observe_postapply_cleanup(
        ATTEMPT,
        ACTIVE_ID,
        probe=lambda: snapshot,
        probe_owner_metadata=lambda _snapshot: metadata,
    )
    gc.verify_readonly_cleanup_receipt(
        gc.canonical_readonly_cleanup_receipt(receipt), ATTEMPT, ACTIVE_ID
    )
    forged = {**metadata, "public_files": {"private_secret.key": {"status": "PRESENT"}}}
    with pytest.raises(gc.CleanupError):
        gc._validate_owner_metadata(forged)
    invisible = {
        **metadata,
        "public_files": {
            **metadata["public_files"],
            "public_key.der": {"status": "UNAVAILABLE"},
        },
    }
    with pytest.raises(gc.CleanupError, match="visibility"):
        gc._validate_owner_metadata(invisible)
    gc._validate_owner_metadata({**invisible, "status": "FILES_INACCESSIBLE"})


def test_owner_volume_metadata_refuses_other_mountpoints_without_file_inspection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    uid, gid = os.geteuid(), os.getegid()
    monkeypatch.setattr(gc, "EXPECTED_UID", uid)
    monkeypatch.setattr(gc, "EXPECTED_GID", gid)
    monkeypatch.setattr(gc.pwd, "getpwuid", lambda _uid: SimpleNamespace(pw_dir=str(tmp_path)))
    monkeypatch.setattr(
        gc,
        "_docker",
        lambda *_args: json.dumps({"DockerRootDir": str(tmp_path / "docker")}),
    )
    monkeypatch.setattr(gc, "_inspect_field", lambda *_args: str(tmp_path / "foreign"))
    snapshot = _physical_observer_fixture(stale="unknown")
    metadata = gc._read_owner_public_metadata(snapshot)
    gc._validate_owner_metadata(metadata)
    assert metadata["status"] == "UNAVAILABLE"
    assert metadata["owner_directory"] is None
    assert all(value is None for value in metadata["public_files"].values())


def test_owner_public_file_stat_rejects_symlinks_without_following_target(tmp_path: Path) -> None:
    (tmp_path / "private_secret").write_bytes(b"NEVER_EXPOSE_SECRET")
    (tmp_path / "credential_id").symlink_to(tmp_path / "private_secret")
    descriptor = os.open(tmp_path, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        result = gc._safe_public_file_stat(descriptor, "credential_id")
        assert result == {"status": "NOT_REGULAR"}
        with pytest.raises(gc.CleanupError):
            gc._safe_public_file_stat(descriptor, "private_secret")
    finally:
        os.close(descriptor)
    assert "NEVER_EXPOSE_SECRET" not in str(result)


def _pinned_historical_retire_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[gc.Inventory, dict[str, object]]:
    monkeypatch.setattr(gc, "HISTORICAL_RETIRE_INCIDENT", ATTEMPT)
    monkeypatch.setattr(gc, "HISTORICAL_RETIRE_CONTAINER", ACTIVE_ID)
    monkeypatch.setattr(gc, "HISTORICAL_RETIRE_KEEP_IMAGE", ACTIVE_IMAGE)
    monkeypatch.setattr(gc, "HISTORICAL_RETIRE_TARGET", OLD_IMAGE)
    digest = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "e" * 64
    monkeypatch.setattr(gc, "HISTORICAL_RETIRE_DIGEST", digest)
    monkeypatch.setattr(gc, "HISTORICAL_RETIRE_REVISION", "d" * 40)
    monkeypatch.setattr(gc, "HISTORICAL_RETIRE_SIZE", 66_021_451)
    fixture = _physical_observer_fixture(stale="unknown")
    fixture = replace(
        fixture,
        disk=gc.DiskInodes(6 * 1024**3, 100_000, 6 * 1024**3, 100_000, 100, 101, 200, 201),
    )
    proof = {
        "id": OLD_IMAGE,
        "repo_tags": [],
        "repo_digests": [digest],
        "untrusted_alias_count": 0,
        "oci_source_status": "ABSENT",
        "oci_revision": "d" * 40,
        "logical_size_bytes": 66_021_451,
        "container_ref_count": 0,
        "deletion_authorized": False,
    }
    return fixture, proof


def test_exact_historical_single_image_retire_under_real_flock_and_no_prune(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    snapshot, proof = _pinned_historical_retire_fixture(monkeypatch)
    monkeypatch.setattr(gc, "LEASE_DIR", tmp_path)
    monkeypatch.setattr(gc, "EXPECTED_UID", os.geteuid())
    monkeypatch.setattr(gc, "EXPECTED_GID", os.getegid())
    tmp_path.chmod(0o700)
    current = snapshot
    calls: list[tuple[str, ...]] = []

    def fake_docker(*args: str) -> str:
        nonlocal current
        calls.append(args)
        assert args == ("image", "rm", "--no-prune", OLD_IMAGE)
        current = replace(
            current,
            images=(current.images[0],),
            global_image_ids=frozenset({ACTIVE_IMAGE}),
            disk=replace(current.disk, docker_bytes_free=current.disk.docker_bytes_free + 2_000),
        )
        return ""

    monkeypatch.setattr(gc, "_docker", fake_docker)
    with gc.protected_boca_job_lease(ATTEMPT) as lease:
        result = gc.retire_single_attested_historical_image(
            lease,
            probe=lambda: current,
            provenance_probe=lambda _ident, _inventory: proof,
        )
    assert result.status == "ACCEPT"
    assert result.removed == (gc.Target("image", OLD_IMAGE),)
    assert result.after.docker_bytes_free > result.before.docker_bytes_free
    assert calls == [("image", "rm", "--no-prune", OLD_IMAGE)]
    assert "prune" not in " ".join(str(c) for c in calls if c != calls[0])
    assert "porota" not in result.redacted_json().lower()


@pytest.mark.parametrize(
    "failure", ["different_digest", "image_referenced", "storage_shortage", "drift"]
)
def test_exact_historical_retire_preflight_refuses_unproved_before_any_write(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    baseline, proof = _pinned_historical_retire_fixture(monkeypatch)
    seen = 0
    removed: list[str] = []
    monkeypatch.setattr(gc, "verify_protected_boca_job_lease", lambda _lease, _id: None)
    lease = gc.BocaJobLease(ATTEMPT, -1, os.getpid(), True)
    if failure == "different_digest":
        proof = {
            **proof,
            "repo_digests": ["ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "f" * 64],
        }
    if failure == "image_referenced":
        baseline = replace(
            baseline,
            containers=(
                baseline.containers[0],
                gc.Container(OLD_ID, "/boca-socios-browser-1", OLD_IMAGE, False, BOCA),
            ),
        )
    if failure == "storage_shortage":
        baseline = replace(baseline, disk=replace(baseline.disk, docker_bytes_free=3 * 1024**3))

    def probe() -> gc.Inventory:
        nonlocal seen
        seen += 1
        if failure == "drift" and seen >= 2:
            return replace(baseline, disk=replace(baseline.disk, docker_inode=9999))
        return baseline

    with pytest.raises(gc.CleanupError):
        gc.retire_single_attested_historical_image(
            lease,
            probe=probe,
            provenance_probe=lambda _ident, _inventory: proof,
            remove=removed.append,
        )
    assert removed == []


@pytest.mark.parametrize("failure", ["docker_refused", "lost_ack"])
def test_historical_retire_after_attempt_is_indeterminate_no_retry(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    snapshot, proof = _pinned_historical_retire_fixture(monkeypatch)
    monkeypatch.setattr(gc, "verify_protected_boca_job_lease", lambda _lease, _id: None)
    calls: list[str] = []

    def remove(ident: str) -> None:
        calls.append(ident)
        if failure == "docker_refused":
            raise gc.CleanupError("synthetic Docker refused")
        # Lost ACK fixture deliberately keeps the ID in postflight.

    result = gc.retire_single_attested_historical_image(
        gc.BocaJobLease(ATTEMPT, -1, os.getpid(), True),
        probe=lambda: snapshot,
        provenance_probe=lambda _ident, _inventory: proof,
        remove=remove,
    )
    assert calls == [OLD_IMAGE]
    assert result.status == "INDETERMINATE"
    assert result.removed == ()
    assert result.retained_uncertain == ("historical-exact-image-removal-ack-unverified",)


def _historical_retire_runner_receipt(
    monkeypatch: pytest.MonkeyPatch, *, status: str = "ACCEPT"
) -> bytes:
    snapshot, _ = _pinned_historical_retire_fixture(monkeypatch)
    accepted = status == "ACCEPT"
    receipt = gc.CleanupReceipt(
        "SUCCESS" if accepted else "FAILURE",
        ATTEMPT,
        "ACCEPT" if accepted else "INDETERMINATE",
        snapshot.disk,
        replace(snapshot.disk, docker_bytes_free=snapshot.disk.docker_bytes_free + 1024)
        if accepted
        else snapshot.disk,
        (gc.Target("image", OLD_IMAGE),) if accepted else (),
        () if accepted else ("historical-exact-image-removal-ack-unverified",),
        (),
    )
    return (receipt.redacted_json() + "\n").encode("ascii")


def test_historical_retire_runner_verifies_exact_boca_target_and_canonical_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _historical_retire_runner_receipt(monkeypatch)
    proof = gc.verify_historical_retire_receipt(raw, ATTEMPT)
    assert proof["removed"] == [{"kind": "image", "id": OLD_IMAGE}]
    assert proof["status"] == "ACCEPT"
    assert (
        gc.verify_historical_retire_receipt(
            _historical_retire_runner_receipt(monkeypatch, status="INDETERMINATE"), ATTEMPT
        )["status"]
        == "INDETERMINATE"
    )


@pytest.mark.parametrize(
    "fault",
    [
        "wrong_target",
        "wrong_incident",
        "ambiguous_removed",
        "extra_field",
        "status_forged",
        "storage_identity",
        "storage_capacity",
        "json_duplicate",
        "noncanonical",
        "multiple_receipts",
        "oversized",
    ],
)
def test_historical_retire_runner_rejects_unproved_or_forged_ack(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    raw = _historical_retire_runner_receipt(monkeypatch)
    original = json.loads(raw)
    if fault == "wrong_target":
        original["removed"][0]["id"] = ACTIVE_IMAGE
    elif fault == "wrong_incident":
        original["attempt_id"] = "42096941815"
    elif fault == "ambiguous_removed":
        original["removed"].append({"kind": "volume", "id": DATA})
    elif fault == "extra_field":
        original["retry"] = True
    elif fault == "status_forged":
        original["status"] = "ACCEPT"
        original["outcome"] = "FAILURE"
    elif fault == "storage_identity":
        original["after"]["docker_inode"] += 1
    elif fault == "storage_capacity":
        original["after"]["docker_bytes_free"] = 100
    elif fault == "json_duplicate":
        raw = raw.replace(b'"version":1', b'"version":1,"version":1')
    elif fault == "noncanonical":
        raw = raw.replace(b'"version":1', b'"version": 1')
    elif fault == "multiple_receipts":
        raw += raw
    elif fault == "oversized":
        raw += b"X" * gc.HISTORICAL_RETIRE_RECEIPT_LIMIT
    if fault in {
        "wrong_target",
        "wrong_incident",
        "ambiguous_removed",
        "extra_field",
        "status_forged",
        "storage_identity",
        "storage_capacity",
    }:
        raw = (json.dumps(original, sort_keys=True, separators=(",", ":")) + "\n").encode()
    with pytest.raises(gc.CleanupError):
        gc.verify_historical_retire_receipt(raw, ATTEMPT)


def test_historical_retire_cli_host_requires_real_lease_and_emits_one_exact_receipt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    raw = _historical_retire_runner_receipt(monkeypatch)
    snapshot, _ = _pinned_historical_retire_fixture(monkeypatch)
    tmp_path.chmod(0o700)
    monkeypatch.setattr(gc, "LEASE_DIR", tmp_path)
    monkeypatch.setattr(gc, "EXPECTED_UID", os.geteuid())
    monkeypatch.setattr(gc, "EXPECTED_GID", os.getegid())
    calls: list[str] = []

    def fake_retire(lease: gc.BocaJobLease) -> gc.CleanupReceipt:
        gc.verify_protected_boca_job_lease(lease, ATTEMPT)
        calls.append(lease.attempt_id)
        return gc.CleanupReceipt(
            "SUCCESS",
            ATTEMPT,
            "ACCEPT",
            snapshot.disk,
            replace(snapshot.disk, docker_bytes_free=snapshot.disk.docker_bytes_free + 1024),
            (gc.Target("image", OLD_IMAGE),),
            (),
            (),
        )

    monkeypatch.setattr(gc, "retire_single_attested_historical_image", fake_retire)
    assert (
        gc._historical_retire_main(
            ["historical-retire-host", ATTEMPT, gc.HISTORICAL_RETIRE_PREPARE]
        )
        == 0
    )
    assert capsys.readouterr().out.encode("ascii") == raw
    assert calls == [ATTEMPT]


def test_historical_retire_cli_runner_distinguishes_pass_and_uncertainty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = _historical_retire_runner_receipt(monkeypatch)
    monkeypatch.setattr(gc.sys, "stdin", io.TextIOWrapper(io.BytesIO(raw), encoding="ascii"))
    assert (
        gc._historical_retire_main(
            ["historical-retire-verify", ATTEMPT, gc.HISTORICAL_RETIRE_PREPARE]
        )
        == 0
    )
    assert "state=PASS" in capsys.readouterr().out
    ambiguous = _historical_retire_runner_receipt(monkeypatch, status="INDETERMINATE")
    monkeypatch.setattr(gc.sys, "stdin", io.TextIOWrapper(io.BytesIO(ambiguous), encoding="ascii"))
    assert (
        gc._historical_retire_main(
            ["historical-retire-verify", ATTEMPT, gc.HISTORICAL_RETIRE_PREPARE]
        )
        == 3
    )
    assert "state=INDETERMINATE" in capsys.readouterr().out


def test_historical_retire_cli_rejects_all_other_incident_ids_and_wrong_uid(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _pinned_historical_retire_fixture(monkeypatch)
    monkeypatch.setattr(gc.os, "geteuid", lambda: 10002)
    monkeypatch.setattr(gc.os, "getegid", lambda: 10002)
    assert (
        gc._historical_retire_main(
            ["historical-retire-host", ATTEMPT, gc.HISTORICAL_RETIRE_PREPARE]
        )
        == 3
    )
    assert (
        gc._historical_retire_main(
            ["historical-retire-host", "42096941815", gc.HISTORICAL_RETIRE_PREPARE]
        )
        == 3
    )
    assert gc._historical_retire_main(["historical-retire-host", ATTEMPT, "42096941815"]) == 3
    assert "NO_GO" in capsys.readouterr().err


def test_postapply_cleanup_readonly_receipt_rejects_tampering() -> None:
    receipt = gc.observe_postapply_cleanup(
        ATTEMPT, ACTIVE_ID, probe=lambda: _physical_observer_fixture()
    )
    raw = gc.canonical_readonly_cleanup_receipt(receipt)
    assert raw.endswith(b"\n")
    with pytest.raises(gc.CleanupError):
        gc.verify_readonly_cleanup_receipt(raw, ATTEMPT, OLD_ID)
    with pytest.raises(gc.CleanupError):
        gc.verify_readonly_cleanup_receipt(
            raw.replace(b'"go_for_retry":false', b'"go_for_retry":true'), ATTEMPT, ACTIVE_ID
        )
    with pytest.raises(gc.CleanupError):
        gc.verify_readonly_cleanup_receipt(raw + b"{}\n", ATTEMPT, ACTIVE_ID)


def test_postapply_cleanup_readonly_rejects_foreign_metadata_and_rootless_mismatch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inventory = _physical_observer_fixture()
    foreign = replace(
        inventory,
        networks=(
            replace(inventory.networks[0], labels=(("com.docker.compose.project", "other"),)),
        ),
    )
    with pytest.raises(gc.CleanupError):
        gc.observe_postapply_cleanup(ATTEMPT, ACTIVE_ID, probe=lambda: foreign)
    monkeypatch.setattr(gc.os, "geteuid", lambda: 0)
    assert gc._readonly_main(["host", ATTEMPT, ACTIVE_ID]) == 3
    output = capsys.readouterr()
    assert output.out == ""
    assert "NO_GO" in output.err and ACTIVE_ID not in output.err


def test_postapply_cleanup_workflow_uses_existing_only_readonly_dispatch() -> None:
    workflow = (Path(__file__).parents[1] / ".github/workflows/boca-first-deploy.yml").read_text(
        encoding="utf-8"
    )
    assert workflow.count("name: Boca first deploy") == 1
    assert "cutover-cleanup-reconcile" not in workflow  # No new privileged operation.
    # R47 added separate, explicitly effectful one-shot routes after this
    # READ_ONLY step. This slice must not include those disjoint routes.
    block = workflow.split("- name: Plan Boca-only Docker cleanup READ_ONLY", 1)[1].split(
        "- name: Recheck exact historical Cutover incident", 1
    )[0]
    assert "if: inputs.operation == 'cutover-a-reconcile'" in block
    assert "< src/boca_socios/host_boca_cleanup.py" in block
    assert "host_cutover_postapply_reconcile import verified_cleanup_legacy_id" in block
    assert "src/boca_socios/host_boca_cleanup.py verify" in block
    assert "cleanup_executed=false" in block
    assert not any(
        command in block
        for command in (
            "docker rm",
            "image rm",
            "volume rm",
            "network rm",
            "docker prune",
            "compose down",
        )
    )


def test_cutover_reconcile_budget_gate_accepts_only_exact_readonly_budget() -> None:
    """Execute the real host preflight's budget branch offline, not a guessed regex."""
    import subprocess

    workflow = (Path(__file__).parents[1] / ".github/workflows/boca-first-deploy.yml").read_text(
        encoding="utf-8"
    )
    budget_branch = workflow.split(
        '          if [[ "$BOCA_OPERATION" = infrastructure-preflight', 1
    )[1].split('          if [[ "$BOCA_OPERATION" != beta-browser-*', 1)[0]
    script = 'if [[ "$BOCA_OPERATION" = infrastructure-preflight' + budget_branch
    for budget, expected_code in (("1.5cpu-1024m-192pids", 0), ("0.5cpu-256m-64pids", 1)):
        result = subprocess.run(  # noqa: S603 - fixed offline bash and checkout YAML only
            ["/bin/bash", "-euo", "pipefail", "-c", script],
            env={
                "PATH": "/usr/bin:/bin",
                "BOCA_OPERATION": "cutover-a-reconcile",
                "BOCA_BUDGET": budget,
                "BOCA_BROWSER_IMAGE_REF": "",
                "BOCA_TELEGRAM_OWNER_READY": "",
            },
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == expected_code


def test_cutover_reconcile_full_preflight_passes_offline_without_host_credentials() -> None:
    """Exercise the entire manual job's immutable pre-SSH gate with synthetic inputs."""
    import re
    import subprocess

    workflow = (Path(__file__).parents[1] / ".github/workflows/boca-first-deploy.yml").read_text(
        encoding="utf-8"
    )
    step = workflow.split(
        "      - name: Require verified protected environment and matching main commit", 1
    )[1].split("      - name: Reject legacy install routes", 1)[0]
    command = step.split("        run: |\n", 1)[1]
    fake_env = {name[1:]: "" for name in re.findall(r"\$[A-Z][A-Z0-9_]+", command)}
    fake_env.update(
        {
            "PATH": "/usr/bin:/bin",
            "BOCA_OPERATION": "cutover-a-reconcile",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_RUN_ID": "42110047551",
            "GITHUB_SHA": "f" * 40,
            "BOCA_SOURCE_SHA": "f" * 40,
            "BOCA_SERVICE": "controller",
            "BOCA_BUDGET": "1.5cpu-1024m-192pids",
            "BOCA_PROTECTED_ACTION_CONTEXT": "42096941815",
            "BOCA_INCIDENT_PREPARE_RUN_ID": "42091200929",
            "BOCA_LEGACY_RELEASE_RUN_ID": "42091200929",
            "BOCA_HOST_READONLY_ENV_READY": "ready",
            "BOCA_DEPLOY_ENV_READY": "ready",
        }
    )
    result = subprocess.run(  # noqa: S603 - fixed offline bash and checkout YAML only
        ["/bin/bash", "-euo", "pipefail", "-c", command],
        env=fake_env,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr


def test_cleanup_readonly_continues_after_valid_stage_inode_no_go_observation() -> None:
    """Stage mismatch is a data result, not a reason to skip Boca Docker inventory."""
    import importlib.util

    script = Path(__file__).parents[1] / "scripts/host_cutover_postapply_reconcile.py"
    spec = importlib.util.spec_from_file_location("boca_stage_readonly_for_test", script)
    assert spec is not None and spec.loader is not None
    reconcile = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reconcile)

    observed = {
        "version": "boca-postapply-reconcile-v1",
        "incident_run_id": ATTEMPT,
        "prepare_run_id": "42091200929",
        "intent": "PRESENT",
        "result": "PRESENT",
        "terminal_state": "NO_GO",
        "cleanup": "INDETERMINATE",
        "worker_id_recorded": False,
        "candidate_id_recorded": False,
        "commit_started": False,
        "original_restored": True,
        "runtime_attested": False,
        "go_for_retry": False,
        "foreign_resources_touched": False,
        "stage_preflight": {"reason": "STAGE_COMPOSE_INODE_MODE"},
        "original": {"id": ACTIVE_ID, "running": True, "health": "healthy"},
        "legacy_id": ACTIVE_ID,
        "boca_inventory": [{"id": ACTIVE_ID, "running": True, "health": "healthy"}],
        "boca_containers": 1,
        "candidate_controllers": [],
        "browser_workers": [],
        "port_8443": "BOCA_CONTROLLER_DOCKER_BOUND",
        "prepared_go_marker": "PRESENT_VERIFIED",
        "prepared_go_marker_reason": "MARKER_SCHEMA_VALID",
        "stage": "ABSENT",
        "promotion_intent": "ABSENT",
        "promotion_result": "ABSENT",
    }
    raw = reconcile._canonical(observed) + b"\n"
    accepted = reconcile.verify_runner(raw, ATTEMPT, "42091200929")
    assert accepted["stage_preflight"]["reason"] == "STAGE_COMPOSE_INODE_MODE"
    workflow = (Path(__file__).parents[1] / ".github/workflows/boca-first-deploy.yml").read_text(
        encoding="utf-8"
    )
    step = workflow.split("      - name: Plan Boca-only Docker cleanup READ_ONLY", 1)[1].split(
        "      - name: Recheck exact historical Cutover incident", 1
    )[0]
    assert "if: inputs.operation == 'cutover-a-reconcile'" in step
    assert "always()" not in step  # Do not bypass failed SSH/identity checks.


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
    # ADR0094 / R244 custody correction: shared IPC is a durable bridge for
    # controller+worker, not disposable attempt staging even if unreferenced.
    assert {x.kind for x in deleted} == {"container", "image", "network"}
    assert {x.ident for x in deleted} == {OLD_ID, OLD_IMAGE, STALE_NET}
    assert gc.Target("volume", IPC) not in deleted
    after = probe()
    assert {c.ident for c in after.containers} == {ACTIVE_ID, FOREIGN_ID}
    assert {i.ident for i in after.images} == {ACTIVE_IMAGE, FOREIGN_IMAGE}
    assert DATA in {v.name for v in after.volumes}
    assert IPC in {v.name for v in after.volumes}
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
    # R244: an unsuccessful selective cleanup also preserves the IPC inode.
    assert gc.Target("volume", IPC) not in receipt.known_residue
    assert IPC in {v.name for v in probe().volumes}
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
    # ADR0094/R244: test the generic disposable-volume path with an actual
    # attempt volume, never the permanently retained Boca IPC volume.
    disposable_volume = "boca-socios_disposable_attempt_volume"
    if kind == "volume":
        source = replace(
            source,
            volumes=tuple(
                replace(volume, name=disposable_volume) if volume.name == IPC else volume
                for volume in source.volumes
            ),
        )
    selected = gc.Target(
        kind,
        {"container": OLD_ID, "network": STALE_NET, "volume": disposable_volume}[kind],
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
            # Same disposable volume becomes referenced; ID remains present.
            snapshot[0] = replace(
                old,
                containers=(replace(old.containers[0], volumes=(DATA, disposable_volume)),),
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
    assert (
        gc.Target("image", OLD_IMAGE)
        in gc.plan(
            verified,
            ATTEMPT,
            preserve_images=frozenset(),
            preserve_containers=frozenset({ACTIVE_ID}),
            retire_containers=frozenset(),
        ).targets
    )
    assert not any(ident == FOREIGN_IMAGE for _kind, ident, _field in inspected)
