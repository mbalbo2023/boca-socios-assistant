"""R246: authenticated current pair is NOT fixed to the historical R186 pair.

Synthetic GitHub transports never reach the network or a Docker host.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from boca_socios import host_boca_current_pair_v2 as current
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_upgrade_adapters as adapters
from boca_socios.host_boca_pair_upgrade import PairCoordinates
from test_host_boca_pair_observe import _run as pair_observation
from test_host_boca_upgrade_adapters import (
    OBSERVER_SOURCE,
    WITNESS_RUN,
    Authenticator,
    metadata,
    witness,
)

NOW = datetime(2026, 11, 12, 20, 0, tzinfo=timezone.utc)  # noqa: UP017
HISTORICAL_SEED = witness()
CONTROLLER_REPO = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:"
WORKER_REPO = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
PROTECTED = "https://api.github.com/repos/mbalbo2023/boca-socios-assistant/"
STEPS_RELEASE = (
    "Require verified protected release environment",
    "Scan the image that will be published",
    "Scan browser image before any publication",
    "Publish both scanned images and record immutable digests",
    "Preserve exact published digest for the guarded install",
    "Preserve paired browser release evidence for a future guarded install",
)
STEPS_OBSERVATION = (
    "Require verified protected environment and matching main commit",
    "Observe installed Boca controller and worker pair READ_ONLY",
    "Upload authenticated candidate for installed pair observation READ_ONLY",
)


def _zip(name: str, raw: bytes) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, raw)
    return output.getvalue()


def _run_record(ident: str, source: str, *, release: bool) -> dict[str, object]:
    return {
        "id": int(ident),
        "run_attempt": 1,
        "name": "Boca image release" if release else "Boca first deploy",
        "event": "workflow_dispatch",
        "head_sha": source,
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
        "path": (
            ".github/workflows/release-image.yml"
            if release
            else ".github/workflows/boca-first-deploy.yml"
        ),
        "created_at": "2026-11-12T15:00:00Z",
        "actor": {"login": "mbalbo2023"},
        "repository": {"full_name": "mbalbo2023/boca-socios-assistant"},
    }


def _job(ident: str, source: str, *, release: bool) -> dict[str, object]:
    return {
        "total_count": 1,
        "jobs": [
            {
                "run_id": int(ident),
                "name": "publish-reviewed-image" if release else "approved-boca-manual-operation",
                "head_sha": source,
                "status": "completed",
                "conclusion": "success",
                "steps": [
                    {"name": name, "status": "completed", "conclusion": "success"}
                    for name in STEPS_RELEASE
                    if release
                ]
                if release
                else [
                    {"name": name, "status": "completed", "conclusion": "success"}
                    for name in STEPS_OBSERVATION
                ],
            }
        ],
    }


def _artifact(name: str, ident: int, run: str, source: str, data: bytes) -> dict[str, object]:
    return {
        "id": ident,
        "name": name,
        "size_in_bytes": len(data),
        "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
        "expired": False,
        "archive_download_url": PROTECTED + f"actions/artifacts/{ident}/zip",
        "workflow_run": {"id": int(run), "head_branch": "main", "head_sha": source},
    }


def _pair_receipt(old_source: str, old_attempt: str, observation: str, *, serial: int) -> bytes:
    prior = json.loads(pair_observation().removeprefix(pair._PREFIX))
    prior["source_sha"] = old_source
    prior["attempt_id"] = old_attempt
    prior["observation_run_id"] = observation
    prior["services"][0].update(
        {
            "container_id": str(serial) * 64,
            "image_id": "sha256:" + str(serial + 2) * 64,
            "image_ref": CONTROLLER_REPO + str(serial + 4) * 64,
        }
    )
    prior["services"][1].update(
        {
            "container_id": str(serial + 1) * 64,
            "image_id": "sha256:" + str(serial + 3) * 64,
            "image_ref": WORKER_REPO + str(serial + 5) * 64,
        }
    )
    raw = pair._canonical(prior)
    pair.verify(raw, observation)
    return raw


class FakeGitHub:
    """Externally trusted GitHub transport double with separate past release."""

    def __init__(self, plan: PairCoordinates, old_release: str, pair_raw: bytes) -> None:
        self.plan = plan
        self.old_release = old_release
        self.pair_raw = pair_raw
        current_pair = json.loads(pair_raw.removeprefix(pair._PREFIX))
        self.old_controller_ref = current_pair["services"][0]["image_ref"]
        self.old_worker_ref = current_pair["services"][1]["image_ref"]
        self.runs = {
            plan.observation_run_id: _run_record(
                plan.observation_run_id, plan.new_source_sha, release=False
            ),
            old_release: _run_record(old_release, plan.old_source_sha, release=True),
        }
        self.jobs = {
            ident: _job(ident, self.runs[ident]["head_sha"], release=ident == old_release)
            for ident in self.runs
        }
        manifests = (
            (
                "boca-release-manifest",
                "boca-release-manifest.json",
                {
                    "image_ref": self.old_controller_ref,
                    "source_sha": plan.old_source_sha,
                    "release_run_id": old_release,
                },
            ),
            (
                "boca-browser-release-manifest",
                "boca-browser-release-manifest.json",
                {
                    "source_sha": plan.old_source_sha,
                    "run_id": old_release,
                    "controller_digest": self.old_controller_ref,
                    "browser_digest": self.old_worker_ref,
                },
            ),
        )
        self.archives = {31: _zip("boca-pair-observation.receipt", pair_raw)}
        self.observation_artifact = _artifact(
            "boca-installed-pair-observation",
            31,
            plan.observation_run_id,
            plan.new_source_sha,
            self.archives[31],
        )
        self.release_artifacts = []
        for index, (name, member, payload) in enumerate(manifests, start=32):
            self.archives[index] = _zip(
                member, (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
            )
            self.release_artifacts.append(
                _artifact(name, index, old_release, plan.old_source_sha, self.archives[index])
            )
        self.main_reads = 0

    def get_json(self, path: str) -> object:
        if path == "git/ref/heads/main":
            self.main_reads += 1
            return {
                "ref": "refs/heads/main",
                "object": {
                    "type": "commit",
                    "sha": self.plan.new_source_sha,
                    "url": PROTECTED + "git/commits/" + self.plan.new_source_sha,
                },
            }
        for ident, value in self.runs.items():
            if path == f"actions/runs/{ident}":
                return value
            if path == f"actions/runs/{ident}/jobs?per_page=100":
                return self.jobs[ident]
            if path == f"actions/runs/{ident}/artifacts?per_page=100":
                result = (
                    self.release_artifacts
                    if ident == self.old_release
                    else [self.observation_artifact]
                )
                return {"total_count": len(result), "artifacts": result}
        raise AssertionError("unexpected GitHub API path")

    def get_artifact_zip(self, ident: int) -> bytes:
        return self.archives[ident]


def _inputs(*, step: int = 1) -> tuple[PairCoordinates, str, bytes, FakeGitHub]:
    # A -> B, then B -> C: the same R186 resource seed survives both.
    old_source, new_source = ("b" * 40, "c" * 40) if step == 1 else ("c" * 40, "d" * 40)
    old_attempt, observation, new_release, new_attempt, old_release = (
        ("44100000011", "44200000011", "44200000012", "44300000011", "44000000011")
        if step == 1
        else ("44300000011", "44400000011", "44400000012", "44500000011", "44200000012")
    )
    raw = _pair_receipt(old_source, old_attempt, observation, serial=step * 2)
    record = json.loads(raw.removeprefix(pair._PREFIX))
    plan = PairCoordinates(
        attempt_id=new_attempt,
        observation_run_id=observation,
        old_attempt_id=old_attempt,
        old_source_sha=old_source,
        old_controller_id=record["services"][0]["container_id"],
        old_worker_id=record["services"][1]["container_id"],
        old_controller_image_id=record["services"][0]["image_id"],
        old_worker_image_id=record["services"][1]["image_id"],
        new_source_sha=new_source,
        release_run_id=new_release,
        controller_ref=CONTROLLER_REPO + "1" * 64,
        worker_ref=WORKER_REPO + "2" * 64,
    )
    return plan, old_release, raw, FakeGitHub(plan, old_release, raw)


def _authenticate(
    *,
    step: int = 1,
    plan: PairCoordinates | None = None,
    pair_raw: bytes | None = None,
    github: FakeGitHub | None = None,
    historical_seed: bytes = HISTORICAL_SEED,
    historical_authenticator: Authenticator | None = None,
) -> bytes:
    fixture_plan, release, fixture_raw, fixture_gh = _inputs(step=step)
    observer_source = OBSERVER_SOURCE
    return current.authenticate_current_pair_v2(
        fixture_plan if plan is None else plan,
        previous_release_run_id=release,
        pair_receipt=fixture_raw if pair_raw is None else pair_raw,
        current_main_sha=fixture_plan.new_source_sha,
        historical_receipt=historical_seed,
        historical_observation_run_id=WITNESS_RUN,
        historical_observer_source_sha=observer_source,
        historical_authenticator=(
            Authenticator(metadata(source=observer_source, run=WITNESS_RUN, observer=True))
            if historical_authenticator is None
            else historical_authenticator
        ),
        github=fixture_gh if github is None else github,
        now=NOW,
    )


def test_two_consecutive_upgrades_bind_previous_authenticated_release_and_r188_creators() -> None:
    first = current.verify_current_pair_v2(_authenticate(step=1))
    second = current.verify_current_pair_v2(_authenticate(step=2))
    assert first["schema"] == second["schema"] == 2
    assert first["previous_pair_source_sha"] == "b" * 40
    assert second["previous_pair_source_sha"] == "c" * 40
    assert first["previous_pair_attempt"] == "44100000011"
    assert second["previous_pair_attempt"] == first["apply_attempt"] == "44300000011"
    assert first["previous_controller_id"] != second["previous_controller_id"]
    assert first["previous_worker_id"] != second["previous_worker_id"]
    assert first["historical_resource_custody"] == second["historical_resource_custody"]
    assert first["historical_resource_custody"]["historical_installed_source_sha"] not in (
        first["previous_pair_source_sha"],
        second["previous_pair_source_sha"],
    )
    assert first["previous_release_run"] == "44000000011"
    assert second["previous_release_run"] == first["target_release_run"]
    assert first["apply_authorized"] is second["apply_authorized"] is False
    assert first["requires_fresh_same_lease_reproof"] is True
    assert second["requires_fresh_same_lease_reproof"] is True


def test_stale_prior_pair_and_previous_release_proof_are_rejected_after_first_upgrade() -> None:
    second_plan, second_release, second_raw, _gh = _inputs(step=2)
    _first_plan, _release, first_raw, first_github = _inputs(step=1)
    with pytest.raises(current.CurrentPairV2NoGo):
        _authenticate(step=1, plan=second_plan, pair_raw=first_raw, github=first_github)
    # The observation for B is entirely correct, with current CIDs/source.
    # Only the *old release manifest* is stale from A. Its forged ZIP gets
    # fresh, self-consistent GitHub artifact metadata so the manifest binding
    # is responsible for rejecting it, not the observation transport.
    second_github = FakeGitHub(second_plan, second_release, second_raw)
    stale_archive = first_github.archives[32]
    second_github.archives[32] = stale_archive
    second_github.release_artifacts[0].update(
        size_in_bytes=len(stale_archive),
        digest="sha256:" + hashlib.sha256(stale_archive).hexdigest(),
    )
    with pytest.raises(current.CurrentPairV2NoGo):
        _authenticate(step=2, github=second_github)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda gh: gh.runs[gh.old_release].update(conclusion="failure"),
        lambda gh: gh.runs[gh.old_release].update(run_attempt=2),
        lambda gh: gh.runs[gh.old_release].update(head_sha="f" * 40),
        lambda gh: gh.runs[gh.old_release].update(path=".github/workflows/other.yml"),
        lambda gh: gh.jobs[gh.old_release]["jobs"][0]["steps"][2].update(conclusion="failure"),
        lambda gh: gh.release_artifacts[0].update(expired=True),
        lambda gh: gh.release_artifacts[1].update(digest="sha256:" + "0" * 64),
        lambda gh: gh.release_artifacts[1].update(
            workflow_run={"id": int(gh.old_release), "head_sha": "f" * 40}
        ),
        lambda gh: gh.archives.__setitem__(32, b"TAMPERED"),
    ),
)
def test_unverified_previous_release_never_qualifies(mutation: object) -> None:
    _plan, _release, _raw, gh = _inputs(step=1)
    mutation(gh)  # type: ignore[operator]
    with pytest.raises(current.CurrentPairV2NoGo, match="current Boca pair provenance unverified"):
        _authenticate(github=gh)


def test_wrong_old_id_and_missing_historical_authentication_fail_closed() -> None:
    plan, _release, _raw, _gh = _inputs()
    with pytest.raises(current.CurrentPairV2NoGo):
        _authenticate(plan=replace(plan, old_controller_id="9" * 64))
    with pytest.raises(current.CurrentPairV2NoGo):
        _authenticate(historical_authenticator=Authenticator({}))


def _v2_bytes(value: dict[str, object], *, recompute_checksum: bool) -> bytes:
    payload = dict(value)
    if recompute_checksum:
        without_checksum = {k: v for k, v in payload.items() if k != "integrity_sha256"}
        serialized = json.dumps(without_checksum, sort_keys=True, separators=(",", ":")) + "\n"
        payload["integrity_sha256"] = hashlib.sha256(serialized.encode()).hexdigest()
    return (
        b"BOCA_CURRENT_PAIR_V2 "
        + json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )


def test_v2_parser_is_integrity_only_not_git_hub_authentication() -> None:
    valid = json.loads(_authenticate().removeprefix(b"BOCA_CURRENT_PAIR_V2 "))
    forged = dict(valid)
    forged["previous_pair_source_sha"] = "f" * 40
    # An attacker able to replace public JSON can recompute an unkeyed hash.
    # Parser deliberately cannot authenticate that new source or make it GO.
    untrusted = current.verify_current_pair_v2(_v2_bytes(forged, recompute_checksum=True))
    assert untrusted["previous_pair_source_sha"] == "f" * 40
    assert untrusted["apply_authorized"] is False
    assert untrusted["requires_fresh_same_lease_reproof"] is True


def test_v2_rejects_dangerous_fields_even_after_unkeyed_checksum_is_recomputed() -> None:
    raw = _authenticate()
    assert raw.startswith(b"BOCA_CURRENT_PAIR_V2 ")
    assert current.verify_current_pair_v2(raw)["apply_authorized"] is False
    value = json.loads(raw.removeprefix(b"BOCA_CURRENT_PAIR_V2 "))
    for change in ("authorization", "missing", "extra", "duplicate", "trailing"):
        bad = dict(value)
        if change == "authorization":
            bad["apply_authorized"] = True
        if change == "missing":
            bad.pop("previous_release_manifest_sha256")
        if change == "extra":
            bad["untrusted_field"] = "PROVENANCE_CONFIRMED"
        candidate = _v2_bytes(bad, recompute_checksum=True)
        if change == "duplicate":
            candidate = candidate[:-2] + b',"schema":2}\n'
        elif change == "trailing":
            candidate += b"{}"
        with pytest.raises(current.CurrentPairV2NoGo):
            current.verify_current_pair_v2(candidate)


def test_old_release_may_be_no_longer_main_but_target_main_must_be_authenticated() -> None:
    plan, release, raw, gh = _inputs(step=2)
    assert plan.old_source_sha != plan.new_source_sha
    assert gh.main_reads == 0
    output = _authenticate(step=2, github=gh)
    assert current.verify_current_pair_v2(output)["previous_release_run"] == release
    # The old ZIPs are read *after* the new-main observation authentication;
    # recheck main at the end of both independent provenance reads.
    assert gh.main_reads == 3

    class WrongMain(FakeGitHub):
        def get_json(self, path: str) -> object:
            value = super().get_json(path)
            if path == "git/ref/heads/main" and isinstance(value, dict):
                value["object"]["sha"] = "f" * 40
            return value

    with pytest.raises(current.CurrentPairV2NoGo):
        _authenticate(step=2, github=WrongMain(plan, release, raw))


def test_target_main_cannot_advance_during_previous_release_authentication() -> None:
    plan, release, raw, _gh = _inputs(step=2)

    class MainChangesAfterObservation(FakeGitHub):
        def get_json(self, path: str) -> object:
            value = super().get_json(path)
            if path == "git/ref/heads/main" and self.main_reads == 3:
                value["object"]["sha"] = "f" * 40  # type: ignore[index]
            return value

    with pytest.raises(current.CurrentPairV2NoGo):
        _authenticate(step=2, github=MainChangesAfterObservation(plan, release, raw))


def test_v2_never_calls_host_ops_and_never_changes_r188() -> None:
    raw = _authenticate()
    v2 = current.verify_current_pair_v2(raw)
    assert v2["observer_writes"] == 0
    assert v2["foreign_resources_touched"] == 0
    assert v2["read_only"] is True
    assert v2["requires_fresh_same_lease_reproof"] is True
    assert v2["historical_resource_custody"]["original_observation_run"] == WITNESS_RUN
    assert v2["historical_resource_custody"]["creator_ipc_attempt"] == "42806447101"
    assert v2["historical_resource_custody"]["creator_site_attempt"] == "43217075287"
    assert v2["historical_resource_custody"]["creator_egress_attempt"] == "43217075287"
    assert "historical_resource_custody" in v2
    assert adapters.parse_custody_integrity(HISTORICAL_SEED, observation_run_id=WITNESS_RUN)
