"""Offline evidence contracts; no GitHub, Docker, site or host operations."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import stat
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_postcommit as installed
from boca_socios import host_boca_pair_upgrade_plan as plans

SOURCE = "a" * 40
RELEASE = "44000000001"
CONTROLLER = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "1" * 64
WORKER = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "2" * 64


def module() -> Any:
    return importlib.import_module("boca_socios.host_boca_upgrade_adapters")


def candidate() -> plans.CandidateRelease:
    return plans.CandidateRelease(SOURCE, RELEASE, CONTROLLER, WORKER)


def manifests() -> tuple[bytes, bytes]:
    controller = {
        "image_ref": CONTROLLER,
        "source_sha": SOURCE,
        "release_run_id": RELEASE,
    }
    paired = {
        "source_sha": SOURCE,
        "run_id": RELEASE,
        "controller_digest": CONTROLLER,
        "browser_digest": WORKER,
    }
    return json.dumps(controller).encode(), json.dumps(paired).encode()


def metadata(*, source: str = SOURCE, run: str = RELEASE, observer: bool = False) -> dict[str, Any]:
    return {
        "id": int(run),
        "run_attempt": 1,
        "name": "Boca first deploy" if observer else "Boca image release",
        "event": "workflow_dispatch",
        "head_sha": source,
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
        "path": ".github/workflows/boca-first-deploy.yml"
        if observer
        else ".github/workflows/release-image.yml",
        "actor": {"login": "mbalbo2023"},
        "repository": {"full_name": "mbalbo2023/boca-socios-assistant"},
    }


class Authenticator:
    """Trusted-boundary fixture only, deliberately absent in production."""

    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.result = metadata() if result is None else result
        self.requests: list[Any] = []

    def authenticate(self, request: Any) -> object:
        self.requests.append(request)
        return self.result


def verify_release(
    authenticator: Any = None, *, controller: bytes | None = None, paired: bytes | None = None
) -> Any:
    first, second = manifests()
    return module().verify_release(
        candidate(),
        controller_manifest=first if controller is None else controller,
        paired_manifest=second if paired is None else paired,
        current_main_sha=SOURCE,
        authenticator=authenticator,
    )


def test_manifest_syntax_alone_cannot_authenticate_release() -> None:
    with pytest.raises(module().EvidenceNoGo):
        verify_release()


def test_release_authentication_binds_two_exact_payloads_and_does_not_authorize_apply() -> None:
    auth = Authenticator()
    evidence = verify_release(auth)
    assert evidence.apply_authorized is False
    assert evidence.source_sha == SOURCE
    assert evidence.release_run_id == RELEASE
    assert evidence.controller_ref == CONTROLLER
    assert evidence.worker_ref == WORKER
    assert [item.payload_sha256 for item in auth.requests] == [
        hashlib.sha256(raw).hexdigest() for raw in manifests()
    ]
    assert [item.kind for item in auth.requests] == ["controller-release", "paired-release"]


@pytest.mark.parametrize(
    "field,value",
    (
        ("head_sha", "b" * 40),
        ("head_branch", "foreign"),
        ("run_attempt", 2),
        ("conclusion", "failure"),
        ("event", "push"),
        ("path", ".github/workflows/foreign.yml"),
    ),
)
def test_authenticated_metadata_must_still_match_exact_release(field: str, value: object) -> None:
    run = metadata()
    run[field] = value
    with pytest.raises(module().EvidenceNoGo):
        verify_release(Authenticator(run))


@pytest.mark.parametrize(
    "change", ("source", "worker_role", "release_run", "duplicate", "trailing")
)
def test_both_manifests_reject_crossed_or_contaminated_coordinates(change: str) -> None:
    first, second = manifests()
    value = json.loads(second)
    if change == "source":
        value["source_sha"] = "b" * 40
    elif change == "worker_role":
        value["browser_digest"] = CONTROLLER
    elif change == "release_run":
        value["run_id"] = "44000000002"
    elif change == "duplicate":
        second = second[:-1] + b',"run_id":"44000000001"}'
    else:
        second += b"{}"
    if change in ("source", "worker_role", "release_run"):
        second = json.dumps(value).encode()
    with pytest.raises(module().EvidenceNoGo):
        verify_release(Authenticator(), controller=first, paired=second)


WITNESS_RUN = "44000000002"
ATTEMPT = "44000000003"
OBSERVER_SOURCE = "9" * 40
IPC = "boca-socios_boca_browser_ipc"
SITE = "boca-socios_boca_site_config"
EGRESS = "boca-socios_boca_browser_egress"


def witness() -> bytes:
    from boca_socios import host_boca_retained_resources as retained
    from test_host_boca_retained_resources import snapshot

    value = snapshot()
    value["observation_run_id"] = WITNESS_RUN
    return retained.observe(WITNESS_RUN, snapshot_reader=lambda _run: value)


def seed(*, raw: bytes | None = None, auth: Any = None) -> Any:
    return module().verify_custody_seed(
        witness() if raw is None else raw,
        observation_run_id=WITNESS_RUN,
        observer_source_sha=OBSERVER_SOURCE,
        authenticator=Authenticator(
            metadata(source=OBSERVER_SOURCE, run=WITNESS_RUN, observer=True)
        )
        if auth is None
        else auth,
    )


def test_witness_authenticates_observer_source_separately_from_installed_source() -> None:
    auth = Authenticator(metadata(source=OBSERVER_SOURCE, run=WITNESS_RUN, observer=True))
    result = seed(auth=auth)
    assert result.apply_authorized is False
    assert result.installed_source_sha == installed.SOURCE_SHA
    assert result.resources.ipc_creator_attempt == "42806447101"
    assert result.resources.site_creator_attempt == "43217075287"
    assert result.control_directory_inode_sha256 == "3" * 64
    assert auth.requests[0].source_sha == OBSERVER_SOURCE
    assert auth.requests[0].payload_sha256 == hashlib.sha256(witness()).hexdigest()


def test_observer_accepts_real_actions_metadata_with_extra_public_actor_fields() -> None:
    run = metadata(source=OBSERVER_SOURCE, run=WITNESS_RUN, observer=True)
    run["actor"] = {"login": "mbalbo2023", "id": 12345, "type": "User"}
    run["repository"] = {"full_name": "mbalbo2023/boca-socios-assistant", "id": 54321}
    assert seed(auth=Authenticator(run)).apply_authorized is False


@pytest.mark.parametrize("change", ("run", "creator", "failure", "auth", "control_inode"))
def test_seed_rejects_untrusted_or_negative_observation(change: str) -> None:
    raw = witness()
    auth = Authenticator(metadata(source=OBSERVER_SOURCE, run=WITNESS_RUN, observer=True))
    value = json.loads(raw.removeprefix(b"BOCA_RETAINED_RESOURCES "))
    if change == "run":
        value["observation_run_id"] = "44000000004"
    elif change == "creator":
        value["volumes"][0]["creator_attempt"] = "44000000004"
        value["expected_resource_provenance"] = False
    elif change == "control_inode":
        value["control_socket_directory_inode_sha256"] = "not_a_digest"
    elif change == "auth":
        auth.result["head_sha"] = "0" * 40
    if change in ("run", "creator", "control_inode"):
        raw = (
            b"BOCA_RETAINED_RESOURCES "
            + json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
            + b"\n"
        )
    elif change == "failure":
        raw = b'BOCA_RETAINED_RESOURCES_FAILURE {"state":"NO_GO"}\n'
    with pytest.raises(module().EvidenceNoGo):
        seed(raw=raw, auth=auth)


@pytest.fixture
def lease(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    stored_seed = seed()
    folder = tmp_path / "lease"
    folder.mkdir(mode=0o700)
    monkeypatch.setattr(cleanup, "LEASE_DIR", folder)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())
    with cleanup.protected_boca_job_lease(ATTEMPT) as held:
        yield held, stored_seed


def service(
    ident: str, role: str, *, attempt: str = "43217075287", source: str = installed.SOURCE_SHA
) -> Any:
    image = CONTROLLER if role == "controller" else WORKER
    if source == SOURCE:
        image = image.split("@", 1)[0] + "@sha256:" + ("6" if role == "controller" else "7") * 64
    return module().ExpectedService(
        ident,
        role,
        source,
        attempt,
        image,
    )


def graph(*, four: bool = False) -> Any:
    values = [service("a" * 64, "controller"), service("b" * 64, "browser-worker")]
    if four:
        values += [
            service("c" * 64, "controller", attempt=ATTEMPT, source=SOURCE),
            service("d" * 64, "browser-worker", attempt=ATTEMPT, source=SOURCE),
        ]
    return module().GraphExpectation(tuple(values))


class RetainedIO:
    def __init__(self, *, four: bool = False) -> None:
        from test_host_boca_pair_observe import CONTROLLER_ID, WORKER_ID, _fields

        self.expected = graph(four=four)
        self.identities = {IPC: "1" * 64, SITE: "2" * 64}
        self.worker = {"Status": "created", "Running": False, "Pid": 0, "ExitCode": 0}
        fields = _fields()
        self.mount_values = {
            "controller": fields[(CONTROLLER_ID, "Mounts")],
            "browser-worker": fields[(WORKER_ID, "Mounts")],
        }
        project = ("com.docker.compose.project", "boca-socios")
        containers, images = [], []
        for index, item in enumerate(self.expected.services):
            image_id = "sha256:" + str(index + 3) * 64
            labels = (
                project,
                ("com.docker.compose.service", item.role),
                ("org.opencontainers.image.revision", item.source_sha),
                ("boca.socios.browser-ipc-attempt", item.installation_attempt),
            )
            volumes = (
                (
                    "boca-socios_boca_data",
                    "boca-socios_boca_key",
                    "boca-socios_boca_owner",
                    IPC,
                    SITE,
                )
                if item.role == "controller"
                else (IPC, SITE)
            )
            containers.append(
                cleanup.Container(
                    item.ident,
                    f"/boca-socios-{item.role}-{index}",
                    image_id,
                    item.role == "controller",
                    labels,
                    tuple(sorted(volumes)),
                    ("boca-socios_boca_private",) if item.role == "controller" else (),
                )
            )
            images.append(cleanup.Image(image_id, (item.image_ref,), cleanup.BOCA_SOURCE))
        self.value = cleanup.Inventory(
            tuple(containers),
            tuple(images),
            (
                cleanup.Network(
                    EGRESS,
                    "8" * 64,
                    (),
                    (
                        project,
                        ("com.docker.compose.network", "boca_browser_egress"),
                        ("boca.socios.browser-ipc-attempt", "43217075287"),
                    ),
                ),
                cleanup.Network(
                    "boca-socios_boca_private",
                    "7" * 64,
                    tuple(c.ident for c in containers if c.running),
                    (project, ("com.docker.compose.network", "boca_private")),
                ),
            ),
            tuple(
                cleanup.Volume(
                    name,
                    (
                        project,
                        ("com.docker.compose.volume", role),
                        ("boca.socios.browser-ipc-attempt", creator),
                    ),
                )
                for name, role, creator in (
                    (IPC, "boca_browser_ipc", "42806447101"),
                    (SITE, "boca_site_config", "43217075287"),
                    ("boca-socios_boca_data", "boca_data", "42806447101"),
                    ("boca-socios_boca_key", "boca_key", "42806447101"),
                    ("boca-socios_boca_owner", "boca_owner", "42806447101"),
                )
            ),
            cleanup.DiskInodes(100, 100),
            frozenset(image.ident for image in images),
        )

    def rootless_identity(self) -> tuple[int, int, str]:
        return 10001, 10001, "/home/boca-deploy/.local/share/docker"

    def inventory(self) -> cleanup.Inventory:
        return self.value

    def identity(self, name: str) -> str:
        return self.identities[name]

    def worker_state(self, ident: str) -> object:
        return self.worker

    def mounts(self, ident: str) -> object:
        item = next(item for item in self.expected.services if item.ident == ident)
        return self.mount_values[item.role]


@pytest.mark.parametrize("four", (False, True))
def test_generic_reobservation_handles_only_the_journal_graph_without_relabeling(
    lease: Any, four: bool
) -> None:
    held, stored_seed = lease
    io = RetainedIO(four=four)
    observed = module().observe_retained(stored_seed.resources, io.expected, ATTEMPT, held, io=io)
    assert observed == stored_seed.resources
    assert observed.site_creator_attempt == "43217075287"


@pytest.mark.parametrize(
    "change",
    ("inode", "network", "peer", "foreign_container", "pid", "running", "creator", "mount"),
)
def test_live_resource_or_ownership_drift_is_never_adopted(lease: Any, change: str) -> None:
    held, stored_seed = lease
    io = RetainedIO()
    if change == "inode":
        io.identities[IPC] = "9" * 64
    elif change == "network":
        io.value = replace(io.value, networks=(replace(io.value.networks[0], ident="9" * 64),))
    elif change == "peer":
        io.value = replace(
            io.value, networks=(replace(io.value.networks[0], attached_ids=("f" * 64,)),)
        )
    elif change == "foreign_container":
        io.value = replace(
            io.value,
            containers=(*io.value.containers, replace(io.value.containers[0], ident="f" * 64)),
        )
    elif change == "pid":
        io.worker["Pid"] = 42
    elif change == "running":
        io.worker["Running"] = True
    elif change == "creator":
        first = io.value.volumes[0]
        io.value = replace(
            io.value,
            volumes=(
                replace(
                    first,
                    labels=first.labels[:-1] + (("boca.socios.browser-ipc-attempt", ATTEMPT),),
                ),
                *io.value.volumes[1:],
            ),
        )
    else:
        io.mount_values["browser-worker"] = io.mount_values["controller"]
    with pytest.raises(module().EvidenceNoGo):
        module().observe_retained(stored_seed.resources, io.expected, ATTEMPT, held, io=io)


def cleanup_case() -> tuple[
    bytes, cleanup.Inventory, cleanup.Inventory, tuple[cleanup.Target, ...]
]:
    before = RetainedIO().value
    disk = cleanup.DiskInodes(1000, 2000, 3000, 4000, 5, 6, 7, 8)
    obsolete = cleanup.Image(
        "sha256:" + "f" * 64,
        ("ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "e" * 64,),
        cleanup.BOCA_SOURCE,
    )
    before = replace(
        before,
        images=(*before.images, obsolete),
        global_image_ids=before.global_image_ids | {obsolete.ident},
        disk=disk,
    )
    after = replace(
        before,
        images=before.images[:-1],
        global_image_ids=before.global_image_ids - {obsolete.ident},
        disk=replace(disk, bytes_free=1100, docker_bytes_free=3100),
    )
    removed = (cleanup.Target("image", obsolete.ident),)
    raw = (
        cleanup.CleanupReceipt(
            "SUCCESS", ATTEMPT, "ACCEPT", before.disk, after.disk, removed, (), ()
        )
        .redacted_json()
        .encode()
    )
    return raw, before, after, removed


def test_cleanup_is_detailed_graph_evidence_not_an_accept_string() -> None:
    raw, before, after, removed = cleanup_case()
    proof = module().verify_cleanup(
        raw, ATTEMPT, before=before, after=after, expected_removed=removed
    )
    assert proof.status == "ACCEPT"
    assert proof.apply_authorized is False
    assert proof.coverage == "IMAGE_RECEIPT_ONLY"
    assert proof.receipt_sha256 == hashlib.sha256(raw).hexdigest()
    with pytest.raises(module().EvidenceNoGo):
        module().verify_cleanup(
            b"ACCEPT", ATTEMPT, before=before, after=after, expected_removed=removed
        )


@pytest.mark.parametrize(
    "change",
    (
        "missing_metrics",
        "duplicate",
        "other_attempt",
        "unrecorded_deletion",
        "referenced_image",
        "global_drift",
        "network_drift",
        "storage_drift",
        "foreign_alias",
    ),
)
def test_cleanup_rejects_uncertain_or_unaccounted_effects(change: str) -> None:
    raw, before, after, removed = cleanup_case()
    value = json.loads(raw)
    if change == "missing_metrics":
        del value["before"]["docker_inodes_free"]
    elif change == "duplicate":
        raw = raw[:-1] + b',"status":"ACCEPT"}'
    elif change == "other_attempt":
        value["attempt_id"] = "44000000099"
    elif change == "unrecorded_deletion":
        after = replace(after, volumes=after.volumes[1:])
    elif change == "referenced_image":
        before = replace(
            before,
            containers=(
                replace(before.containers[0], image_id=removed[0].ident),
                *before.containers[1:],
            ),
        )
    elif change == "global_drift":
        after = replace(after, global_image_ids=after.global_image_ids | {"sha256:" + "9" * 64})
    elif change == "network_drift":
        after = replace(after, networks=(replace(after.networks[0], ident="9" * 64),))
    elif change == "storage_drift":
        after = replace(after, disk=replace(after.disk, docker_inode=999))
    else:
        before = replace(
            before,
            images=(
                *before.images[:-1],
                replace(before.images[-1], references=("foreign/image:latest",)),
            ),
        )
    if change in ("missing_metrics", "other_attempt"):
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(module().EvidenceNoGo):
        module().verify_cleanup(raw, ATTEMPT, before=before, after=after, expected_removed=removed)


def test_cleanup_persistence_is_one_shot_under_the_same_lease(
    lease: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from boca_socios import host_cutover_stage as stage

    held, _seed = lease
    folder = tmp_path / "stage"
    folder.mkdir(mode=0o700)
    monkeypatch.setattr(stage, "ROOT", folder)
    monkeypatch.setattr(stage, "UID", os.geteuid())
    monkeypatch.setattr(stage, "GID", os.getegid())
    raw, before, after, removed = cleanup_case()
    proof = module().persist_cleanup(
        raw, ATTEMPT, held, before=before, after=after, expected_removed=removed
    )
    stored = folder / f".boca-upgrade-cleanup-{ATTEMPT}.json"
    assert stored.read_bytes() == raw
    assert stored.stat().st_mode & 0o777 == 0o600
    assert proof.receipt_sha256 == hashlib.sha256(raw).hexdigest()
    with pytest.raises(module().EvidenceNoGo):
        module().persist_cleanup(
            raw, ATTEMPT, held, before=before, after=after, expected_removed=removed
        )
    assert stored.read_bytes() == raw


def test_cleanup_persistence_never_follows_an_existing_symlink(
    lease: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from boca_socios import host_cutover_stage as stage

    held, _seed = lease
    folder = tmp_path / "stage"
    folder.mkdir(mode=0o700)
    monkeypatch.setattr(stage, "ROOT", folder)
    monkeypatch.setattr(stage, "UID", os.geteuid())
    monkeypatch.setattr(stage, "GID", os.getegid())
    owner = tmp_path / "preserved"
    owner.write_bytes(b"owner data")
    (folder / f".boca-upgrade-cleanup-{ATTEMPT}.json").symlink_to(owner)
    raw, before, after, removed = cleanup_case()
    with pytest.raises(module().EvidenceNoGo):
        module().persist_cleanup(
            raw, ATTEMPT, held, before=before, after=after, expected_removed=removed
        )
    assert owner.read_bytes() == b"owner data"


def test_worker_cannot_share_controller_network_even_when_it_has_no_process(lease: Any) -> None:
    held, stored_seed = lease
    io = RetainedIO()
    io.value = replace(
        io.value,
        containers=(
            io.value.containers[0],
            replace(io.value.containers[1], networks=("boca-socios_boca_private",)),
        ),
    )
    with pytest.raises(module().EvidenceNoGo):
        module().observe_retained(stored_seed.resources, io.expected, ATTEMPT, held, io=io)


def test_cleanup_directory_fsync_failure_keeps_receipt_but_never_reports_accept(
    lease: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from boca_socios import host_cutover_stage as stage

    held, _seed = lease
    folder = tmp_path / "stage"
    folder.mkdir(mode=0o700)
    monkeypatch.setattr(stage, "ROOT", folder)
    monkeypatch.setattr(stage, "UID", os.geteuid())
    monkeypatch.setattr(stage, "GID", os.getegid())
    real_fsync = os.fsync

    def fail_directory(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("uncertain fsync")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_directory)
    raw, before, after, removed = cleanup_case()
    with pytest.raises(module().EvidenceNoGo):
        module().persist_cleanup(
            raw, ATTEMPT, held, before=before, after=after, expected_removed=removed
        )
    assert (folder / f".boca-upgrade-cleanup-{ATTEMPT}.json").read_bytes() == raw


def test_v2_quarantine_cannot_be_accepted_without_its_historical_adapter() -> None:
    raw, before, after, removed = cleanup_case()
    proof = cleanup.HistoricalRetainedImageProof(
        cleanup.HISTORICAL_RETIRE_TARGET,
        cleanup.HISTORICAL_RETIRE_DIGEST,
        cleanup.HISTORICAL_RETIRE_REVISION,
    )
    raw = (
        cleanup.CleanupReceipt(
            "SUCCESS", ATTEMPT, "ACCEPT", before.disk, after.disk, removed, (), (), (proof,)
        )
        .redacted_json()
        .encode()
    )
    with pytest.raises(module().EvidenceNoGo):
        module().verify_cleanup(raw, ATTEMPT, before=before, after=after, expected_removed=removed)


def test_canonical_witness_alone_cannot_become_authenticated_custody() -> None:
    with pytest.raises(module().EvidenceNoGo):
        module().verify_custody_seed(
            witness(), observation_run_id=WITNESS_RUN, observer_source_sha=OBSERVER_SOURCE
        )


def test_same_immutable_reference_cannot_identify_two_different_images(lease: Any) -> None:
    held, stored_seed = lease
    io = RetainedIO(four=True)
    duplicate = replace(
        io.value.images[-1], references=(CONTROLLER, *io.value.images[-1].references)
    )
    io.value = replace(io.value, images=(*io.value.images[:-1], duplicate))
    with pytest.raises(module().EvidenceNoGo):
        module().observe_retained(stored_seed.resources, io.expected, ATTEMPT, held, io=io)


def test_revoked_lease_after_second_snapshot_cannot_return_verified_pins(lease: Any) -> None:
    held, stored_seed = lease
    io = RetainedIO()
    original_inventory = io.inventory
    reads = 0

    def revoke_after_second_read() -> cleanup.Inventory:
        nonlocal reads
        reads += 1
        if reads == 2:
            held.active = False
        return original_inventory()

    io.inventory = revoke_after_second_read
    with pytest.raises(module().EvidenceNoGo):
        module().observe_retained(stored_seed.resources, io.expected, ATTEMPT, held, io=io)
