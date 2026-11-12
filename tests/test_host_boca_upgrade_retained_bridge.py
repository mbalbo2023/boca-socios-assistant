"""R244 authenticates a second read-only retained-resource artifact."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_retained_resources as retained
from boca_socios import host_boca_upgrade_observation_bridge as observed
from boca_socios import host_boca_upgrade_retained_bridge as bridge
from boca_socios.host_boca_upgrade_release_auth import GitHubRestTransport
from test_host_boca_retained_resources import RUN as RETAINED_RUN
from test_host_boca_retained_resources import pair_receipt, snapshot
from test_host_boca_upgrade_observation_bridge import (
    APPLY_RUN,
    MAIN,
    NOW,
    RELEASE_RUN,
    FakeGitHub,
    archive,
)

PAIR_RUN = "43280000001"
RETAINED_ARTIFACT = "boca-retained-resources-observation"
RETAINED_MEMBER = "boca-retained-observation.receipt"
RETAINED_STEPS = (
    "Require verified protected environment and matching main commit",
    "Observe retained Boca resource provenance READ_ONLY",
    "Upload authenticated candidate for retained Boca resources READ_ONLY",
)


def _pair() -> tuple[bytes, bytes]:
    value = json.loads(pair_receipt().removeprefix(b"BOCA_INSTALLED_PAIR "))
    value["observation_run_id"] = PAIR_RUN
    raw = pair._canonical(value)
    pair.verify(raw, PAIR_RUN)
    proof = observed._pair_projection(raw, PAIR_RUN, MAIN)
    observed._runs_are_distinct(proof, APPLY_RUN, RELEASE_RUN)
    proof.update({"apply_attempt_id": APPLY_RUN, "release_run_id": RELEASE_RUN})
    trusted = observed._canonical(proof)
    observed.verify_bundled_observation(trusted, raw, MAIN, PAIR_RUN, APPLY_RUN, RELEASE_RUN)
    return trusted, raw


def _retained() -> bytes:
    return retained.observe(RETAINED_RUN, snapshot_reader=lambda _: snapshot())


class FakeRetainedGitHub(FakeGitHub):
    def __init__(self) -> None:
        super().__init__()
        self.receipt = _retained()
        self.zip_bytes = archive(self.receipt, name=RETAINED_MEMBER)
        self.run["id"] = int(RETAINED_RUN)
        self.jobs["jobs"][0]["run_id"] = int(RETAINED_RUN)
        self.jobs["jobs"][0]["steps"] = [
            {"name": name, "status": "completed", "conclusion": "success"}
            for name in RETAINED_STEPS
        ]
        self.artifact.update(
            name=RETAINED_ARTIFACT,
            size_in_bytes=len(self.zip_bytes),
            digest="sha256:" + hashlib.sha256(self.zip_bytes).hexdigest(),
            workflow_run={"id": int(RETAINED_RUN), "head_branch": "main", "head_sha": MAIN},
        )

    def get_json(self, path: str) -> object:
        return super().get_json(path.replace(RETAINED_RUN, "43058130210"))


def _auth(fake: FakeRetainedGitHub | None = None) -> tuple[bytes, bytes, bytes, bytes]:
    gh = FakeRetainedGitHub() if fake is None else fake
    pair_proof, pair_raw = _pair()
    proof = bridge.authenticate_runner_retained(
        MAIN,
        RETAINED_RUN,
        PAIR_RUN,
        APPLY_RUN,
        RELEASE_RUN,
        gh.receipt,
        pair_proof,
        pair_raw,
        gh,
        now=NOW,
    )
    return proof, gh.receipt, pair_proof, pair_raw


def test_second_artifact_binds_immutable_retained_resources_to_same_old_pair() -> None:
    proof, raw, pair_proof, pair_raw = _auth()
    custody = bridge.verify_bundled_retained(
        proof,
        raw,
        pair_proof,
        pair_raw,
        MAIN,
        RETAINED_RUN,
        PAIR_RUN,
        APPLY_RUN,
        RELEASE_RUN,
    )
    assert custody.resources.ipc_creator_attempt == "42806447101"
    assert custody.resources.site_creator_attempt == "43217075287"
    assert custody.resources.ipc_inode_sha256 == "1" * 64
    assert custody.control_directory_inode_sha256 == "3" * 64
    assert custody.observation_run_id == RETAINED_RUN
    assert custody.receipt_sha256 == hashlib.sha256(raw).hexdigest()
    assert b"authorized" not in proof


def test_host_transport_verification_does_not_forge_github_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner checked GitHub; host checks proof/bytes, not a synthetic run."""
    proof, raw, pair_proof, pair_raw = _auth()

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("host must not construct a fake successful GitHub run")

    monkeypatch.setattr(bridge.adapters, "verify_custody_seed", forbidden)
    custody = bridge.verify_bundled_retained(
        proof,
        raw,
        pair_proof,
        pair_raw,
        MAIN,
        RETAINED_RUN,
        PAIR_RUN,
        APPLY_RUN,
        RELEASE_RUN,
    )
    assert custody.apply_authorized is False
    assert custody.observation_run_id == RETAINED_RUN


def test_retained_run_attempt_mutating_during_job_listing_is_rejected() -> None:
    class MutatingRetainedGitHub(FakeRetainedGitHub):
        def get_json(self, path: str) -> object:
            if path == f"actions/runs/{RETAINED_RUN}/jobs?per_page=100":
                self.run["run_attempt"] = 2
            return super().get_json(path)

    with pytest.raises(bridge.UpgradeRetainedNoGo):
        _auth(MutatingRetainedGitHub())


def test_runner_downloads_to_memory_and_writes_only_authenticated_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "private"
    folder.mkdir(mode=0o700)
    pair_proof, pair_raw = _pair()
    (folder / "boca-pair-observation.receipt").write_bytes(pair_raw)
    (folder / "observation-proof.json").write_bytes(pair_proof)
    raw_path, proof_path = folder / RETAINED_MEMBER, folder / "retained-proof.json"
    monkeypatch.setenv("GH_TOKEN", "never-forward-secret")
    monkeypatch.setattr(bridge, "GitHubRestTransport", lambda token: FakeRetainedGitHub())
    args = [
        MAIN,
        RETAINED_RUN,
        PAIR_RUN,
        APPLY_RUN,
        RELEASE_RUN,
        str(folder / "boca-pair-observation.receipt"),
        str(folder / "observation-proof.json"),
        str(raw_path),
        str(proof_path),
    ]
    assert bridge.runner_main(args, now=NOW) == 0
    assert capsys.readouterr().out == "BOCA_RETAINED_AUTH state=VERIFIED host_authorized=false\n"
    assert raw_path.read_bytes() == _retained()
    assert b"never-forward-secret" not in proof_path.read_bytes()
    assert raw_path.stat().st_mode & 0o777 == 0o600
    assert bridge.runner_main(args, now=NOW) == 3
    assert "NO_GO" in capsys.readouterr().out


def test_rest_zip_transport_bound_handles_valid_48k_retained_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GitHubRestTransport("runner-only-token")

    def bounded(_url: str, *, authenticated: bool, bound: int) -> bytes:
        assert authenticated is True
        if bound < 50_000:
            raise ValueError("valid retained ZIP rejected before digest verification")
        return b"x" * 50_000

    monkeypatch.setattr(client, "_read", bounded)
    assert len(client.get_artifact_zip(3333)) == 50_000


@pytest.mark.parametrize(
    "mutation",
    (
        lambda gh: gh.run.update(run_attempt=2),
        lambda gh: gh.run.update(actor={"login": "foreign"}),
        lambda gh: gh.jobs["jobs"][0]["steps"][1].update(conclusion="skipped"),
        lambda gh: gh.artifact.update(name="unrelated"),
        lambda gh: gh.artifact.update(digest="sha256:" + "0" * 64),
        lambda gh: setattr(gh, "zip_bytes", archive(gh.receipt, extra=True, name=RETAINED_MEMBER)),
        lambda gh: gh.artifact.update(workflow_run={"id": 123}),
    ),
)
def test_second_run_failure_never_becomes_custody_seed(mutation: Any) -> None:
    fake = FakeRetainedGitHub()
    mutation(fake)
    with pytest.raises(bridge.UpgradeRetainedNoGo):
        _auth(fake)


@pytest.mark.parametrize("change", ("proof", "receipt", "other_pair", "replay"))
def test_retained_bridge_rejects_host_transport_tampering(change: str) -> None:
    proof, raw, pair_proof, pair_raw = _auth()
    apply_run = APPLY_RUN
    if change == "proof":
        proof += b"{}"
    elif change == "receipt":
        raw = raw.replace(b'"inode_sha256":"1', b'"inode_sha256":"9')
    elif change == "other_pair":
        pair_raw = pair_raw.replace(b'"source_sha":"', b'"source_sha":"f')
    else:
        apply_run = RETAINED_RUN
    with pytest.raises(bridge.UpgradeRetainedNoGo):
        bridge.verify_bundled_retained(
            proof,
            raw,
            pair_proof,
            pair_raw,
            MAIN,
            RETAINED_RUN,
            PAIR_RUN,
            apply_run,
            RELEASE_RUN,
        )
