"""Offline R247 protected-runner provenance; never opens GitHub or Boca host."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from boca_socios import host_boca_current_pair_v2 as current
from boca_socios import host_boca_retained_resources as retained_resources
from boca_socios import host_boca_upgrade_observation_bridge as observed
from boca_socios import host_boca_upgrade_release_bridge as release_bridge
from boca_socios import host_boca_upgrade_retained_bridge as retained_bridge
from boca_socios.host_boca_pair_upgrade_plan import CandidateRelease
from test_host_boca_current_pair_v2 import (
    HISTORICAL_SEED,
    NOW,
    FakeGitHub,
    _artifact,
    _inputs,
    _run_record,
    _zip,
)
from test_host_boca_upgrade_adapters import OBSERVER_SOURCE

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import attest_current_pair_v2 as runner  # noqa: E402

HISTORICAL_STEPS = retained_bridge._STEPS


def _retained_receipt(run_id: str) -> bytes:
    """Rebind real resource-creator evidence to a *later* READ_ONLY run."""
    value = json.loads(HISTORICAL_SEED.removeprefix(b"BOCA_RETAINED_RESOURCES "))
    value["observation_run_id"] = run_id
    return retained_resources.observe(run_id, snapshot_reader=lambda _run: value)


@dataclass
class OfflineCatalog:
    release: str
    results: list[str] | None = None
    reads: int = 0

    def unique_previous_release(self, source: str) -> str:
        assert source in {"b" * 40, "c" * 40}
        self.reads += 1
        if self.results is not None:
            return self.results.pop(0)
        return self.release


class CompleteGitHub(FakeGitHub):
    def __init__(self, step: int = 1) -> None:
        plan, previous, pair, original = _inputs(step=step)
        super().__init__(plan, previous, pair)
        self.retained_run = str(int(plan.observation_run_id) + 2)
        assert int(plan.observation_run_id) < int(self.retained_run) < int(plan.attempt_id)
        self.retained_raw = _retained_receipt(self.retained_run)
        self.runs[self.retained_run] = _run_record(
            self.retained_run, OBSERVER_SOURCE, release=False
        )
        self.jobs[self.retained_run] = {
            "total_count": 1,
            "jobs": [
                {
                    "run_id": int(self.retained_run),
                    "name": "approved-boca-manual-operation",
                    "head_sha": OBSERVER_SOURCE,
                    "status": "completed",
                    "conclusion": "success",
                    "steps": [
                        {"name": name, "status": "completed", "conclusion": "success"}
                        for name in sorted(HISTORICAL_STEPS)
                    ],
                }
            ],
        }
        archive = _zip("boca-retained-observation.receipt", self.retained_raw)
        self.archives[34] = archive
        self.retained_artifact = _artifact(
            "boca-retained-resources-observation", 34, self.retained_run, OBSERVER_SOURCE, archive
        )
        self._previous = previous
        self._pair = pair

    def get_json(self, path: str) -> object:
        if path == f"actions/runs/{self.retained_run}/artifacts?per_page=100":
            return {"total_count": 1, "artifacts": [self.retained_artifact]}
        return super().get_json(path)


def _release_files(gh: CompleteGitHub, folder: Path) -> None:
    folder.mkdir(mode=0o700)
    plan = gh.plan
    old_raw = gh.pair_raw
    proof = observed.authenticate_runner_observation(
        plan.new_source_sha,
        plan.observation_run_id,
        plan.attempt_id,
        plan.release_run_id,
        old_raw,
        gh,
        now=NOW,
    )
    candidate = CandidateRelease(
        plan.new_source_sha, plan.release_run_id, plan.controller_ref, plan.worker_ref
    )
    controller = {
        "image_ref": plan.controller_ref,
        "source_sha": plan.new_source_sha,
        "release_run_id": plan.release_run_id,
    }
    browser = {
        "source_sha": plan.new_source_sha,
        "run_id": plan.release_run_id,
        "controller_digest": plan.controller_ref,
        "browser_digest": plan.worker_ref,
    }
    source_controller = (
        json.dumps(controller, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    source_browser = (json.dumps(browser, sort_keys=True, separators=(",", ":")) + "\n").encode()
    release = release_bridge._canonical(
        {
            "schema": 1,
            "source_sha": plan.new_source_sha,
            "release_run_id": plan.release_run_id,
            "controller_ref": plan.controller_ref,
            "worker_ref": plan.worker_ref,
            "controller_manifest_sha256": hashlib.sha256(source_controller).hexdigest(),
            "paired_manifest_sha256": hashlib.sha256(source_browser).hexdigest(),
        }
    )
    release_bridge.verify_bundled_release(release, source_controller, source_browser, candidate)
    for name, data in (
        ("boca-release-manifest.json", source_controller),
        ("boca-browser-release-manifest.json", source_browser),
        ("runner-proof.json", release),
        ("boca-pair-observation.receipt", old_raw),
        ("observation-proof.json", proof),
    ):
        item = folder / name
        item.write_bytes(data)
        item.chmod(0o600)


def _inputs_for_runner(tmp_path: Path, *, step: int = 1):
    github = CompleteGitHub(step)
    folder = tmp_path / "private"
    _release_files(github, folder)
    plan = github.plan
    argv = (
        plan.new_source_sha,
        plan.observation_run_id,
        plan.attempt_id,
        plan.release_run_id,
        github.retained_run,
        plan.controller_ref,
        plan.worker_ref,
        str(folder),
    )
    catalog = OfflineCatalog(github._previous)
    return github, catalog, argv, folder


@pytest.mark.parametrize("step", [1, 2])
def test_runner_produces_historical_seed_and_current_pair_v2_without_host_go(
    tmp_path: Path, step: int
) -> None:
    github, catalog, argv, folder = _inputs_for_runner(tmp_path, step=step)
    runner.attest_runner(*argv, github=github, release_catalog=catalog, now=NOW)
    assert catalog.reads == 2
    assert (folder / "boca-retained-observation.receipt").read_bytes() == github.retained_raw
    assert (folder / "retained-proof.json").read_bytes() == b'{"state":"NO_GO"}\n'
    v2 = current.verify_current_pair_v2((folder / "current-pair-v2.receipt").read_bytes())
    assert v2["target_main_sha"] == github.plan.new_source_sha
    assert v2["previous_release_run"] == github._previous
    assert v2["apply_authorized"] is False
    assert v2["historical_resource_custody"]["original_observation_run"] == github.retained_run
    assert all(
        (folder / name).stat().st_mode & 0o777 == 0o600
        for name in (
            "boca-retained-observation.receipt",
            "retained-proof.json",
            "current-pair-v2.receipt",
        )
    )


@pytest.mark.parametrize(
    "tamper",
    [
        "historical_artifact",
        "historical_actor",
        "historical_job",
        "historical_rerun",
        "previous_run",
        "previous_manifest",
        "catalog_race",
    ],
)
def test_runner_failclosed_without_writing_any_proof(tmp_path: Path, tamper: str) -> None:
    github, catalog, argv, folder = _inputs_for_runner(tmp_path)
    if tamper == "historical_artifact":
        github.retained_artifact["expired"] = True
    elif tamper == "historical_actor":
        github.runs[github.retained_run]["actor"] = {"login": "someone-else"}
    elif tamper == "historical_job":
        github.jobs[github.retained_run]["jobs"][0]["steps"][0]["conclusion"] = "failure"
    elif tamper == "historical_rerun":
        github.runs[github.retained_run]["run_attempt"] = 2
    elif tamper == "previous_run":
        github.runs[github._previous]["conclusion"] = "failure"
    elif tamper == "previous_manifest":
        github.release_artifacts[1]["expired"] = True
    elif tamper == "catalog_race":
        catalog.results = [github._previous, "99999999999"]
    with pytest.raises(runner.RunnerCurrentPairNoGo):
        runner.attest_runner(*argv, github=github, release_catalog=catalog, now=NOW)
    assert set(p.name for p in folder.iterdir()) == {
        "boca-release-manifest.json",
        "boca-browser-release-manifest.json",
        "runner-proof.json",
        "boca-pair-observation.receipt",
        "observation-proof.json",
    }


def test_runner_preexisting_output_does_not_leave_partially_attested_files(
    tmp_path: Path,
) -> None:
    github, catalog, argv, folder = _inputs_for_runner(tmp_path)
    (folder / "current-pair-v2.receipt").write_bytes(b"FORGED")
    with pytest.raises(runner.RunnerCurrentPairNoGo):
        runner.attest_runner(*argv, github=github, release_catalog=catalog, now=NOW)
    assert not (folder / "boca-retained-observation.receipt").exists()
    assert not (folder / "retained-proof.json").exists()
    assert (folder / "current-pair-v2.receipt").read_bytes() == b"FORGED"


@pytest.mark.parametrize("retained_offset", [-1, 0, 1])
def test_runner_rejects_retained_observation_out_of_order_before_github_or_writes(
    tmp_path: Path, retained_offset: int
) -> None:
    github, catalog, argv, folder = _inputs_for_runner(tmp_path)
    submitted = list(argv)
    submitted[4] = str(
        int(submitted[1]) + retained_offset
        if retained_offset <= 0
        else int(submitted[2]) + retained_offset
    )
    with pytest.raises(runner.RunnerCurrentPairNoGo):
        runner.attest_runner(*submitted, github=github, release_catalog=catalog, now=NOW)
    assert catalog.reads == 0
    assert set(p.name for p in folder.iterdir()) == {
        "boca-release-manifest.json",
        "boca-browser-release-manifest.json",
        "runner-proof.json",
        "boca-pair-observation.receipt",
        "observation-proof.json",
    }


def test_release_catalog_accepts_exact_github_run_then_fails_on_second_result() -> None:
    source = "b" * 40
    run = _run_record("44000000011", source, release=True)

    class Catalog(runner.GitHubRestReleaseCatalog):
        def __init__(self, results: list[dict[str, object]]) -> None:
            self.results = results

        def _read(self, url: str, *, authenticated: bool, bound: int) -> bytes:
            assert authenticated and bound <= 200_000
            assert url.endswith("head_sha=" + source + "&event=workflow_dispatch&per_page=100")
            return json.dumps(
                {"total_count": len(self.results), "workflow_runs": self.results}
            ).encode()

    assert Catalog([run]).unique_previous_release(source) == "44000000011"
    with pytest.raises(runner.RunnerCurrentPairNoGo):
        Catalog([run, run]).unique_previous_release(source)
    with pytest.raises(runner.RunnerCurrentPairNoGo):
        Catalog([{**run, "actor": {"login": "untrusted"}}]).unique_previous_release(source)


@pytest.mark.parametrize("results", [[], [{"id": 1}], [{"id": 1}, {"id": 2}]])
def test_release_catalog_denies_missing_or_ambiguous_list_results(results: list[dict]) -> None:
    class FakeCatalog(runner.GitHubRestReleaseCatalog):
        def __init__(self):
            pass

        def _read(self, url: str, *, authenticated: bool, bound: int) -> bytes:
            assert url == (
                "https://api.github.com/repos/mbalbo2023/boca-socios-assistant/"
                "actions/workflows/release-image.yml/runs?head_sha="
                + "b" * 40
                + "&event=workflow_dispatch&per_page=100"
            )
            assert authenticated and bound <= 200_000
            return json.dumps({"total_count": len(results), "workflow_runs": results}).encode()

    with pytest.raises(runner.RunnerCurrentPairNoGo):
        FakeCatalog().unique_previous_release("b" * 40)
