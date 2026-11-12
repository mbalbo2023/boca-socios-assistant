"""Authenticate the actual prior READ_ONLY pair artifact before successor use."""

from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from boca_socios import host_boca_upgrade_observation_bridge as bridge
from test_host_boca_pair_observe import ATTEMPT as OLD_ATTEMPT
from test_host_boca_pair_observe import RUN_ID as OBS_RUN
from test_host_boca_pair_observe import SOURCE as OLD_SOURCE
from test_host_boca_pair_observe import _run as pair_receipt

MAIN = "a" * 40
APPLY_RUN = "44000000003"
RELEASE_RUN = "43123456789"
NOW = datetime(2026, 11, 12, 20, 0, tzinfo=timezone.utc)  # noqa: UP017 - host py3.10
ARTIFACT = "boca-installed-pair-observation"
MEMBER = "boca-pair-observation.receipt"
STEPS = (
    "Require verified protected environment and matching main commit",
    "Observe installed Boca controller and worker pair READ_ONLY",
    "Upload authenticated candidate for installed pair observation READ_ONLY",
)


def archive(raw: bytes, *, extra: bool = False, name: str = MEMBER) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as output:
        output.writestr(name, raw)
        if extra:
            output.writestr("untrusted.json", b"{}")
    return stream.getvalue()


class FakeGitHub:
    def __init__(self) -> None:
        self.main = MAIN
        self.main_reads = 0
        self.receipt = pair_receipt()
        self.zip_bytes = archive(self.receipt)
        self.run: dict[str, Any] = {
            "id": int(OBS_RUN),
            "run_attempt": 1,
            "name": "Boca first deploy",
            "event": "workflow_dispatch",
            "head_sha": MAIN,
            "head_branch": "main",
            "status": "completed",
            "conclusion": "success",
            "path": ".github/workflows/boca-first-deploy.yml",
            "created_at": "2026-11-12T15:00:00Z",
            "actor": {"login": "mbalbo2023"},
            "repository": {"full_name": "mbalbo2023/boca-socios-assistant"},
        }
        self.jobs = {
            "total_count": 1,
            "jobs": [
                {
                    "name": "approved-boca-manual-operation",
                    "run_id": int(OBS_RUN),
                    "head_sha": MAIN,
                    "status": "completed",
                    "conclusion": "success",
                    "steps": [
                        {"name": name, "status": "completed", "conclusion": "success"}
                        for name in STEPS
                    ],
                }
            ],
        }
        self.artifact: dict[str, Any] = {
            "id": 3333,
            "name": ARTIFACT,
            "size_in_bytes": len(self.zip_bytes),
            "digest": "sha256:" + hashlib.sha256(self.zip_bytes).hexdigest(),
            "expired": False,
            "archive_download_url": (
                "https://api.github.com/repos/mbalbo2023/boca-socios-assistant"
                "/actions/artifacts/3333/zip"
            ),
            "workflow_run": {"id": int(OBS_RUN), "head_branch": "main", "head_sha": MAIN},
        }

    def get_json(self, path: str) -> object:
        if path == "git/ref/heads/main":
            self.main_reads += 1
            return {
                "ref": "refs/heads/main",
                "object": {
                    "type": "commit",
                    "sha": self.main,
                    "url": "https://api.github.com/repos/mbalbo2023/boca-socios-assistant/git/commits/"
                    + self.main,
                },
            }
        if path == f"actions/runs/{OBS_RUN}":
            return self.run
        if path == f"actions/runs/{OBS_RUN}/jobs?per_page=100":
            return self.jobs
        if path == f"actions/runs/{OBS_RUN}/artifacts?per_page=100":
            return {"total_count": 1, "artifacts": [self.artifact]}
        raise AssertionError("unexpected GitHub endpoint")

    def get_artifact_zip(self, ident: int) -> bytes:
        assert ident == 3333
        return self.zip_bytes


def authenticate(fake: FakeGitHub | None = None) -> bytes:
    gh = fake if fake is not None else FakeGitHub()
    return bridge.authenticate_runner_observation(
        MAIN, OBS_RUN, APPLY_RUN, RELEASE_RUN, gh.receipt, gh, now=NOW
    )


def test_authentic_artifact_binds_old_pair_and_is_never_apply_authority() -> None:
    gh = FakeGitHub()
    proof = authenticate(gh)
    parsed = bridge.verify_bundled_observation(
        proof, gh.receipt, MAIN, OBS_RUN, APPLY_RUN, RELEASE_RUN
    )
    assert parsed["old_attempt_id"] == OLD_ATTEMPT
    assert parsed["old_source_sha"] == OLD_SOURCE
    assert parsed["observer_run_id"] == OBS_RUN
    assert parsed["observer_source_sha"] == MAIN
    assert parsed["apply_attempt_id"] == APPLY_RUN
    assert parsed["release_run_id"] == RELEASE_RUN
    assert parsed["observation_receipt_sha256"] == hashlib.sha256(gh.receipt).hexdigest()
    assert "authorized" not in proof.decode("ascii")
    assert gh.main_reads == 2


def test_run_attempt_cannot_change_between_job_artifact_and_final_runner_proof() -> None:
    class MutatingGitHub(FakeGitHub):
        def get_json(self, path: str) -> object:
            if path == f"actions/runs/{OBS_RUN}/jobs?per_page=100":
                self.run["run_attempt"] = 2
            return super().get_json(path)

    gh = MutatingGitHub()
    with pytest.raises(bridge.UpgradeObservationNoGo):
        authenticate(gh)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda gh: gh.run.update(run_attempt=2),
        lambda gh: gh.run.update(path=".github/workflows/other.yml"),
        lambda gh: gh.run.update(head_sha="f" * 40),
        lambda gh: gh.run.update(event="push"),
        lambda gh: gh.run.update(actor={"login": "foreigner"}),
        lambda gh: gh.run.update(conclusion="failure"),
        lambda gh: gh.run.update(created_at="2026-11-01T00:00:00Z"),
        lambda gh: gh.jobs["jobs"][0].update(conclusion="failure"),
        lambda gh: gh.jobs["jobs"][0]["steps"][1].update(conclusion="failure"),
        lambda gh: gh.jobs["jobs"][0].update(steps=[]),
        lambda gh: gh.artifact.update(digest="sha256:" + "0" * 64),
        lambda gh: gh.artifact.update(name="foreign"),
        lambda gh: gh.artifact.update(expired=True),
        lambda gh: gh.artifact.update(workflow_run={"id": 10}),
        lambda gh: setattr(gh, "main", "f" * 40),
        lambda gh: setattr(gh, "zip_bytes", archive(gh.receipt, extra=True)),
    ),
)
def test_untrusted_action_run_job_artifact_or_zip_never_authenticates(mutation: Any) -> None:
    gh = FakeGitHub()
    mutation(gh)
    with pytest.raises(bridge.UpgradeObservationNoGo):
        authenticate(gh)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda p, r: (p + b"{}", r),
        lambda p, r: (p.replace(b'"schema":1', b'"schema":true'), r),
        lambda p, r: (p, r.replace(b'"source_sha":"', b'"source_sha":"f')),
        lambda p, r: (p, r + b"{}"),
    ),
)
def test_host_rejects_transport_tampering_without_github_token(mutation: Any) -> None:
    fake = FakeGitHub()
    proof, raw = mutation(authenticate(fake), fake.receipt)
    with pytest.raises(bridge.UpgradeObservationNoGo):
        bridge.verify_bundled_observation(proof, raw, MAIN, OBS_RUN, APPLY_RUN, RELEASE_RUN)


@pytest.mark.parametrize(
    "apply,release",
    (
        (OBS_RUN, RELEASE_RUN),
        (APPLY_RUN, OBS_RUN),
        (OLD_ATTEMPT, RELEASE_RUN),
        (APPLY_RUN, OLD_ATTEMPT),
        (RELEASE_RUN, RELEASE_RUN),
    ),
)
def test_observation_id_must_be_separate_from_all_transaction_runs(
    apply: str, release: str
) -> None:
    fake = FakeGitHub()
    with pytest.raises(bridge.UpgradeObservationNoGo):
        bridge.verify_bundled_observation(
            authenticate(fake), fake.receipt, MAIN, OBS_RUN, apply, release
        )


def test_runner_reads_private_receipt_and_writes_exclusive_proof_without_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    receipt = directory / "boca-pair-observation.receipt"
    proof = directory / "observation-proof.json"
    monkeypatch.setenv("GH_TOKEN", "never-forward-this-secret")
    monkeypatch.setattr(bridge, "GitHubRestTransport", lambda _token: FakeGitHub())
    args = [MAIN, OBS_RUN, APPLY_RUN, RELEASE_RUN, str(receipt), str(proof)]
    assert bridge.runner_main(args, now=NOW) == 0
    assert capsys.readouterr().out == "BOCA_OBSERVATION_AUTH state=VERIFIED host_authorized=false\n"
    assert receipt.read_bytes() == FakeGitHub().receipt
    assert proof.stat().st_mode & 0o777 == 0o600
    assert b"never-forward-this-secret" not in proof.read_bytes()
    assert bridge.runner_main(args, now=NOW) == 3  # O_EXCL prevents replay.
    assert "NO_GO" in capsys.readouterr().out
