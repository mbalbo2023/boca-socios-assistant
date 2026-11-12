"""R183 forensic-only observation of the failed postcommit Boca pair."""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

from boca_socios import host_boca_census as census
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_pair_postcommit as post

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import boca_protected_memfd_bootstrap as bootstrap  # noqa: E402
import build_protected_boca_bundle as bundle  # noqa: E402


def _container(ident: str, service: str) -> census.CensusContainer:
    return census.CensusContainer(
        ident,
        f"/boca-socios-{service}-1",
        service == "controller",
        tuple(
            sorted(
                {
                    "com.docker.compose.project": "boca-socios",
                    "com.docker.compose.service": service,
                }.items()
            )
        ),
    )


def _census() -> census.CensusSnapshot:
    return census.CensusSnapshot(
        (
            _container(post.CONTROLLER_ID, "controller"),
            _container(post.WORKER_ID, "browser-worker"),
        ),
        frozenset({"a" * 64, "b" * 64}),
        frozenset({"boca-socios_boca_data"}),
        (12, 13),
    )


def _paths(_path: Path) -> str:
    # The test supplies only a type, not any host file contents.
    if _path.name == "control.sock":
        return "ABSENT"
    return (
        "DIRECTORY"
        if _path.name.startswith(".boca-on-demand-parked-") or _path.name == "socket"
        else "FILE"
    )


def _observe(*, pair_reader=None, inventory_reader=None, path_reader=None):
    return post.observe(
        "43219000000",
        inventory_reader=inventory_reader or _census,
        pair_reader=pair_reader
        or (
            lambda _run: (_ for _ in ()).throw(
                pair.PairNoGo("installed Boca mount profile unverified")
            )
        ),
        path_reader=path_reader or _paths,
        effective_uid=10001,
        effective_gid=10001,
    )


def _genuine_pair_receipt() -> bytes:
    return (
        b"BOCA_INSTALLED_PAIR "
        + json.dumps(
            {
                "source_sha": post.SOURCE_SHA,
                "attempt_id": post.FAILED_ATTEMPT,
                "services": [
                    {
                        "container_id": post.CONTROLLER_ID,
                        "image_ref": post.CONTROLLER_IMAGE,
                        "running": True,
                        "health": "healthy",
                        "port_8443": "LOOPBACK",
                    },
                    {
                        "container_id": post.WORKER_ID,
                        "image_ref": post.WORKER_IMAGE,
                        "status": "created",
                        "pid": 0,
                    },
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )


def test_postcommit_reason_is_redacted_and_always_non_authorizing():
    receipt = _observe()
    verified = post.verify(receipt, "43219000000")
    assert verified == receipt
    data = json.loads(receipt.removeprefix(post.PREFIX))
    assert data["pair"] == "NO_GO"
    assert data["pair_reason"] == "MOUNT_PROFILE"
    assert data["new_pair_only"] is True
    assert data["parked"] == "DIRECTORY"
    assert data["intent"] == "FILE"
    assert data["old_ids_absent"] is True
    assert data["observer_writes"] == data["foreign_resources_touched"] == 0
    assert data["cutover_authorized"] is False
    assert b"/home" not in receipt and b"token" not in receipt


def test_postcommit_catches_unexpected_exception_without_leaking_secret():
    def fail(_run):
        raise ValueError("PRIVATE_PASSWORD")

    receipt = _observe(pair_reader=fail)
    data = json.loads(receipt.removeprefix(post.PREFIX))
    assert data["pair_reason"] == "OTHER_UNVERIFIED"
    assert b"PRIVATE_PASSWORD" not in receipt


def test_postcommit_refuses_drift_and_foreign_rootless_identity():
    snapshots = iter((_census(), census.CensusSnapshot((), frozenset(), frozenset(), (12, 13))))
    with pytest.raises(post.PostcommitNoGo):
        _observe(inventory_reader=lambda: next(snapshots))
    with pytest.raises(post.PostcommitNoGo):
        post.observe("43219000000", inventory_reader=_census, effective_uid=0, effective_gid=0)


def test_postcommit_requires_exact_receipt_and_pair_pass(monkeypatch):
    monkeypatch.setattr(post.pair, "verify", lambda raw, _run: raw)
    receipt = _observe(pair_reader=lambda _run: _genuine_pair_receipt())
    data = json.loads(receipt.removeprefix(post.PREFIX))
    assert data["pair"] == "PASS"
    assert data["pair_reason"] == "NONE"
    with pytest.raises(post.PostcommitNoGo):
        post.verify(receipt, "43219000001")
    with pytest.raises(post.PostcommitNoGo):
        post.verify(receipt.replace(b'"observer_writes":0', b'"observer_writes":1'), "43219000000")
    mismatched = dict(data, new_pair_only=False, old_ids_absent=False)
    with pytest.raises(post.PostcommitNoGo):
        post.verify(post._canonical(mismatched), "43219000000")


def test_postcommit_does_not_read_socket_contents_and_rejects_unknown_file_type():
    def unsafe(path: Path) -> str:
        return "UNSAFE" if path.name == "control.sock" else _paths(path)

    receipt = _observe(path_reader=unsafe)
    data = json.loads(receipt.removeprefix(post.PREFIX))
    assert data["socket_node"] == "UNSAFE"
    assert data["state"] == "OBSERVED"


def test_postcommit_kind_never_follows_any_symlinked_parent(tmp_path, monkeypatch):
    owned = tmp_path / "owned"
    owned.mkdir()
    outside = tmp_path / "foreign"
    outside.mkdir()
    (outside / "socket").mkdir()
    parked = owned / "parked"
    parked.symlink_to(outside, target_is_directory=True)
    nested = parked / "socket"
    monkeypatch.setattr(post, "_PATHS", (parked, nested))
    assert post._kind(parked) == "UNSAFE"
    assert post._kind(nested) == "UNSAFE"


@pytest.mark.parametrize(
    "needle,replacement",
    [
        (post.SOURCE_SHA, "0" * 40),
        (post.FAILED_ATTEMPT, "43217075288"),
        (post.WORKER_ID, "e" * 64),
        (post.WORKER_IMAGE, "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "f" * 64),
        ('"health":"healthy"', '"health":"unhealthy"'),
    ],
)
def test_postcommit_never_calls_wrong_new_pair_a_verified_match(monkeypatch, needle, replacement):
    monkeypatch.setattr(post.pair, "verify", lambda raw, _run: raw)
    wrong = _genuine_pair_receipt().replace(needle.encode(), replacement.encode())
    receipt = _observe(pair_reader=lambda _run: wrong)
    data = json.loads(receipt.removeprefix(post.PREFIX))
    assert data["pair"] == "NO_GO"
    assert data["pair_reason"] == "PAIR_IDENTITY_MISMATCH"


def test_postcommit_pair_pass_cannot_override_census_mismatch(monkeypatch):
    monkeypatch.setattr(post.pair, "verify", lambda raw, _run: raw)
    wrong = _census()
    replaced = census.CensusSnapshot(
        (_container("f" * 64, "controller"), wrong.containers[1]),
        wrong.network_ids,
        wrong.volume_names,
        wrong.docker_root_identity,
    )
    receipt = _observe(
        pair_reader=lambda _run: _genuine_pair_receipt(),
        inventory_reader=lambda: replaced,
    )
    data = json.loads(receipt.removeprefix(post.PREFIX))
    assert data["pair"] == "NO_GO"
    assert data["pair_reason"] == "PAIR_IDENTITY_MISMATCH"
    assert data["new_pair_only"] is False


def test_postcommit_is_a_separate_read_only_sha_checked_memfd_variant(tmp_path):
    root = Path(__file__).resolve().parents[1]
    target = tmp_path / "incident.pyz"
    digest = bundle.build(root, target, postcommit_observe=True)
    bootstrap.verify(target.read_bytes(), digest, postcommit_observe=True)
    with zipfile.ZipFile(io.BytesIO(target.read_bytes()), "r") as archive:
        names = set(archive.namelist())
        assert names == bootstrap.POSTCOMMIT_ENTRIES
        assert "boca_socios/host_boca_pair_upgrade_backend.py" not in names
        assert "boca_socios/host_first_deploy.py" not in names
        assert "boca_socios/browser/ipc_worker.py" not in names
    with pytest.raises(ValueError):
        bootstrap.verify(target.read_bytes(), digest, pair_upgrade=True)


def test_postcommit_diagnostic_is_the_only_new_host_workflow_operation():
    flow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
    ).read_text()
    assert (
        "boca-postcommit-observe"
        in flow.split("      operation:\n", 1)[1].split("      source_sha:", 1)[0]
    )
    assert "if: inputs.operation == 'boca-postcommit-observe'" in flow
    step = flow.split("      - name: Observe exact R182 postcommit Boca state READ_ONLY\n", 1)[
        1
    ].split("      - name:", 1)[0]
    assert "--postcommit-observe" in step
    assert "boca_socios.host_boca_pair_postcommit verify" in step
    assert "scripts/check_main_ref.py" in step
    assert "observer_writes=0" in step
    assert "census_paths_double_read=STABLE" in step
    assert "docker rm" not in step and "docker start" not in step and "systemctl" not in step
