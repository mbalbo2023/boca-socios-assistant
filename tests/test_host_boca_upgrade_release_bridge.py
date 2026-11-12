"""Runner-authenticated dual release carried as bounded, non-secret bundle data."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import host_boca_upgrade_release_bridge as bridge
from boca_socios.host_boca_pair_upgrade_plan import CandidateRelease
from test_host_boca_upgrade_release_auth import (
    BROWSER,
    CONTROLLER,
    RUN,
    SOURCE,
    FakeGitHub,
)


def _candidate() -> CandidateRelease:
    return CandidateRelease(SOURCE, RUN, CONTROLLER, BROWSER)


def test_runner_authenticates_both_archives_before_issuing_bounded_proof() -> None:
    github = FakeGitHub()
    controller = github.payloads["controller-release"]
    worker = github.payloads["paired-release"]
    proof = bridge.authenticate_runner_release(_candidate(), controller, worker, github)
    assert github.main_reads == 4
    assert bridge.verify_bundled_release(proof, controller, worker, _candidate()) == (
        hashlib.sha256(controller).hexdigest(),
        hashlib.sha256(worker).hexdigest(),
    )
    decoded = json.loads(proof)
    assert decoded["schema"] == 1
    assert decoded["release_run_id"] == RUN
    assert decoded["controller_manifest_sha256"] == hashlib.sha256(controller).hexdigest()
    assert "token" not in proof.decode("ascii").lower()


@pytest.mark.parametrize("member", ["controller", "worker", "proof", "coordinates"])
def test_host_cannot_accept_substituted_bundle_proof_or_manifest(member: str) -> None:
    github = FakeGitHub()
    controller = github.payloads["controller-release"]
    worker = github.payloads["paired-release"]
    proof = bridge.authenticate_runner_release(_candidate(), controller, worker, github)
    candidate = _candidate()
    if member == "controller":
        controller += b" "
    elif member == "worker":
        worker += b" "
    elif member == "proof":
        proof += b" "
    else:
        candidate = replace(candidate, source_sha="f" * 40)
    with pytest.raises(bridge.UpgradeReleaseBridgeNoGo):
        bridge.verify_bundled_release(proof, controller, worker, candidate)


@pytest.mark.parametrize("breakage", ["first_zip", "second_zip", "main", "run"])
def test_no_runner_proof_if_either_release_role_is_unverified(breakage: str) -> None:
    github = FakeGitHub()
    if breakage == "first_zip":
        github.archive_bytes[81] = b"not a trusted ZIP"
    elif breakage == "second_zip":
        github.archive_bytes[82] = b"not a trusted ZIP"
    elif breakage == "main":
        github.main_sha = "f" * 40
    else:
        github.run["conclusion"] = "failure"
    with pytest.raises(bridge.UpgradeReleaseBridgeNoGo):
        bridge.authenticate_runner_release(
            _candidate(),
            github.payloads["controller-release"],
            github.payloads["paired-release"],
            github,
        )


def test_host_integrity_projection_does_not_claim_github_authority() -> None:
    github = FakeGitHub()
    controller = github.payloads["controller-release"]
    worker = github.payloads["paired-release"]
    invented = {
        "schema": 1,
        "source_sha": SOURCE,
        "release_run_id": RUN,
        "controller_ref": CONTROLLER,
        "worker_ref": BROWSER,
        "controller_manifest_sha256": hashlib.sha256(controller).hexdigest(),
        "paired_manifest_sha256": hashlib.sha256(worker).hexdigest(),
    }
    # The host projection checks integrity, not independently the provenance
    # of these bytes; the caller has no way to promote this to host authority.
    assert bridge.verify_bundled_release(
        (json.dumps(invented, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        controller,
        worker,
        _candidate(),
    ) == (
        hashlib.sha256(controller).hexdigest(),
        hashlib.sha256(worker).hexdigest(),
    )
    assert "apply_authorized" not in invented


def test_runner_entrypoint_writes_exclusive_nonsecret_proof_only_after_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    github = FakeGitHub()
    monkeypatch.setattr(bridge, "GitHubRestTransport", lambda token: github)
    monkeypatch.setenv("GH_TOKEN", "fixture-bearer-NOT-TO-TRANSFER")
    first, second, target = (tmp_path / name for name in ("controller", "browser", "proof"))
    first.write_bytes(github.payloads["controller-release"])
    second.write_bytes(github.payloads["paired-release"])
    args = [SOURCE, RUN, CONTROLLER, BROWSER, str(first), str(second), str(target)]
    assert bridge.runner_main(args) == 0
    assert capsys.readouterr().out == "BOCA_RELEASE_AUTH state=VERIFIED host_authorized=false\n"
    assert target.stat().st_mode & 0o777 == 0o600
    assert b"fixture-bearer" not in target.read_bytes()
    assert bridge.verify_bundled_release(
        target.read_bytes(), first.read_bytes(), second.read_bytes(), _candidate()
    )
    assert bridge.runner_main(args) == 3  # exclusive file, no overwrite or replay
    assert target.read_bytes().count(b"schema") == 1


@pytest.mark.parametrize("bad", ["symlink", "no_token", "wrong_sha"])
def test_runner_refuses_untrusted_inputs_without_creating_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bad: str,
) -> None:
    github = FakeGitHub()
    monkeypatch.setattr(bridge, "GitHubRestTransport", lambda token: github)
    monkeypatch.setenv("GH_TOKEN", "fixture-bearer")
    first, second, target = (tmp_path / name for name in ("controller", "browser", "proof"))
    first.write_bytes(github.payloads["controller-release"])
    second.write_bytes(github.payloads["paired-release"])
    source = SOURCE
    if bad == "symlink":
        second.unlink()
        second.symlink_to(first)
    elif bad == "no_token":
        monkeypatch.delenv("GH_TOKEN")
    else:
        source = "f" * 40
    assert (
        bridge.runner_main([source, RUN, CONTROLLER, BROWSER, str(first), str(second), str(target)])
        == 3
    )
    assert capsys.readouterr().out == "BOCA_RELEASE_AUTH state=NO_GO host_authorized=false\n"
    assert not target.exists()
