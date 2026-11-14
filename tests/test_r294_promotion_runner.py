"""Current promotion uses real release864 bytes and explicit future fixtures.

Only the four checked-in ZIPs are historical evidence. GitHub records, future
observation runs and current inode/binding in this test are offline doubles.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from boca_socios import host_boca_current_pair_v2 as current
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_successor_integrations as integrations
from boca_socios import host_boca_upgrade_release_bridge as release_bridge
from boca_socios.host_boca_pair_upgrade import PairCoordinates
from test_host_boca_current_pair_v2 import (
    NOW,
    FakeGitHub,
    _artifact,
    _run_record,
    _zip,
)
from test_r294_current_retained import (
    APPLY,
    CONTROL,
    EVIDENCE,
    RUN,
    SOURCE,
    current_pair,
    fixture_snapshot,
    installation,
    module,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import attest_current_pair_v2 as runner  # noqa: E402

PREVIOUS_RELEASE = "43504444584"
PAIR_RUN = "43590000001"
TARGET_RELEASE = "43590000000"
NEW_APPLY = "43590000004"
MAIN = "f" * 40
CURRENT_STEPS = frozenset(
    {
        "Require verified protected environment and matching main commit",
        "Observe current Boca retained resources READ_ONLY",
        "Upload authenticated candidate for retained Boca resources READ_ONLY",
    }
)


class CurrentGitHub(FakeGitHub):
    def __init__(self, *, stopped: bool = False) -> None:
        raw = current_pair(run=PAIR_RUN, stopped=stopped)
        pair.verify(raw, PAIR_RUN)
        observed = json.loads(raw.removeprefix(pair._PREFIX))
        plan = PairCoordinates(
            attempt_id=NEW_APPLY,
            observation_run_id=PAIR_RUN,
            old_attempt_id=APPLY,
            old_source_sha=SOURCE,
            old_controller_id=observed["services"][0]["container_id"],
            old_worker_id=observed["services"][1]["container_id"],
            old_controller_image_id=observed["services"][0]["image_id"],
            old_worker_image_id=observed["services"][1]["image_id"],
            new_source_sha=MAIN,
            release_run_id=TARGET_RELEASE,
            controller_ref="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "1" * 64,
            worker_ref="ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "2" * 64,
        )
        super().__init__(plan, PREVIOUS_RELEASE, raw)
        for ident, filename in ((32, "release864-controller.zip"), (33, "release864-paired.zip")):
            self.archives[ident] = (EVIDENCE / filename).read_bytes()
            item = self.release_artifacts[ident - 32]
            item.update(
                size_in_bytes=len(self.archives[ident]),
                digest="sha256:" + hashlib.sha256(self.archives[ident]).hexdigest(),
            )
        current_snapshot = fixture_snapshot(stopped=stopped)
        current_snapshot["binding_fingerprint"] = installation().fingerprint()
        self.retained_raw = module().observe(RUN, snapshot_reader=lambda _run: current_snapshot)
        self.runs[RUN] = _run_record(RUN, MAIN, release=False)
        self.jobs[RUN] = {
            "total_count": 1,
            "jobs": [
                {
                    "run_id": int(RUN),
                    "name": "approved-boca-manual-operation",
                    "head_sha": MAIN,
                    "status": "completed",
                    "conclusion": "success",
                    "steps": [
                        {"name": name, "status": "completed", "conclusion": "success"}
                        for name in sorted(CURRENT_STEPS)
                    ],
                }
            ],
        }
        self.archives[34] = _zip("boca-retained-observation.receipt", self.retained_raw)
        self.retained_artifact = _artifact(
            "boca-retained-resources-observation", 34, RUN, MAIN, self.archives[34]
        )
        self.catalog_reads = 0

    def get_json(self, path: str) -> object:
        if path == f"actions/runs/{RUN}/artifacts?per_page=100":
            return {"total_count": 1, "artifacts": [self.retained_artifact]}
        return super().get_json(path)

    def unique_previous_release(self, source: str) -> str:
        assert source == SOURCE
        self.catalog_reads += 1
        return PREVIOUS_RELEASE


def inputs(tmp_path: Path, *, stopped: bool = False):
    gh = CurrentGitHub(stopped=stopped)
    plan = gh.plan
    folder = tmp_path / "private"
    folder.mkdir(mode=0o700)
    controller = json.dumps(
        {"image_ref": plan.controller_ref, "source_sha": MAIN, "release_run_id": TARGET_RELEASE}
    ).encode()
    worker = json.dumps(
        {
            "source_sha": MAIN,
            "run_id": TARGET_RELEASE,
            "controller_digest": plan.controller_ref,
            "browser_digest": plan.worker_ref,
        }
    ).encode()
    proof = release_bridge._canonical(
        {
            "schema": 1,
            "source_sha": MAIN,
            "release_run_id": TARGET_RELEASE,
            "controller_ref": plan.controller_ref,
            "worker_ref": plan.worker_ref,
            "controller_manifest_sha256": hashlib.sha256(controller).hexdigest(),
            "paired_manifest_sha256": hashlib.sha256(worker).hexdigest(),
        }
    )
    for name, data in (
        ("boca-release-manifest.json", controller),
        ("boca-browser-release-manifest.json", worker),
        ("runner-proof.json", proof),
    ):
        (folder / name).write_bytes(data)
        (folder / name).chmod(0o600)
    argv = (
        MAIN,
        PAIR_RUN,
        NEW_APPLY,
        TARGET_RELEASE,
        RUN,
        plan.controller_ref,
        plan.worker_ref,
        str(folder),
    )
    return gh, argv, folder


def bound_inputs(tmp_path: Path, *, stopped: bool = False):
    gh, argv, folder = inputs(tmp_path, stopped=stopped)
    runner.attest_runner(*argv, github=gh, release_catalog=gh, now=NOW)
    plan = gh.plan
    result = integrations.verify_runner_bound_host_inputs(
        attempt_id=plan.attempt_id,
        source_sha=plan.new_source_sha,
        controller_ref=plan.controller_ref,
        worker_ref=plan.worker_ref,
        release_run_id=plan.release_run_id,
        observation_run_id=plan.observation_run_id,
        **{
            key: (folder / filename).read_bytes()
            for key, filename in (
                ("release_proof", "runner-proof.json"),
                ("controller_manifest", "boca-release-manifest.json"),
                ("paired_manifest", "boca-browser-release-manifest.json"),
                ("observation_proof", "observation-proof.json"),
                ("observation_receipt", "boca-pair-observation.receipt"),
                ("retained_receipt", "boca-retained-observation.receipt"),
                ("current_pair_v2", "current-pair-v2.receipt"),
            )
        },
    )
    return result


def test_host_input_validation_preserves_current_stop_authority(tmp_path: Path) -> None:
    result = bound_inputs(tmp_path, stopped=True)
    assert result.custody.current_receipt is not None
    assert result.plan.old_attempt_id == APPLY
    assert result.custody.control_directory_inode_sha256 == CONTROL


@pytest.mark.parametrize("stopped", (False, True))
def test_runner_materializes_current_pair_from_release864_and_apply1102(
    tmp_path: Path, stopped: bool
) -> None:
    gh, argv, folder = inputs(tmp_path, stopped=stopped)
    runner.attest_runner(*argv, github=gh, release_catalog=gh, now=NOW)
    assert gh.catalog_reads == 2
    result = current.verify_current_pair_v2((folder / "current-pair-v2.receipt").read_bytes())
    assert result["previous_release_run"] == PREVIOUS_RELEASE
    assert result["previous_pair_source_sha"] == SOURCE
    assert result["previous_pair_attempt"] == APPLY
    assert result["historical_resource_custody"]["control_dir_inode_sha256"] == CONTROL
    assert (folder / "boca-pair-observation.receipt").read_bytes() == gh.pair_raw
    assert (folder / "boca-retained-observation.receipt").read_bytes() == gh.retained_raw
    assert len(list(folder.iterdir())) == 8


@pytest.mark.parametrize("damage", ("actor", "rerun", "old_steps", "different_main", "zip_digest"))
def test_current_runner_rejects_five_untrusted_origins_without_materializing(
    tmp_path: Path, damage: str
) -> None:
    gh, argv, folder = inputs(tmp_path, stopped=True)
    if damage == "actor":
        gh.runs[RUN]["actor"] = {"login": "someone-else"}
    elif damage == "rerun":
        gh.runs[RUN]["run_attempt"] = 2
    elif damage == "old_steps":
        gh.jobs[RUN]["jobs"][0]["steps"][1]["name"] = "Legacy observer"
    elif damage == "different_main":
        gh.runs[RUN]["head_sha"] = SOURCE
    else:
        gh.retained_artifact["digest"] = "sha256:" + "0" * 64
    with pytest.raises(runner.RunnerCurrentPairNoGo):
        runner.attest_runner(*argv, github=gh, release_catalog=gh, now=NOW)
    assert len(list(folder.iterdir())) == 3
