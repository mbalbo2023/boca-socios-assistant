"""Authenticated dual-release evidence: forged metadata is never enough."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import zipfile
from dataclasses import dataclass

import pytest

from boca_socios import host_boca_upgrade_release_auth as release_auth
from boca_socios.host_boca_upgrade_release_auth import (
    GitHubActionsEvidenceAuthenticator,
    ReleaseAuthenticationNoGo,
)

SOURCE = "a" * 40
RUN = "43123456789"
CONTROLLER = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64
BROWSER = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "c" * 64
REQUIRED_STEPS = (
    "Require verified protected release environment",
    "Scan the image that will be published",
    "Scan browser image before any publication",
    "Publish both scanned images and record immutable digests",
    "Preserve exact published digest for the guarded install",
    "Preserve paired browser release evidence for a future guarded install",
)


@dataclass(frozen=True)
class Request:
    kind: str
    run_id: str = RUN
    source_sha: str = SOURCE
    workflow_path: str = ".github/workflows/release-image.yml"
    payload_sha256: str = ""


def _archive(name: str, content: bytes) -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as destination:
        destination.writestr(name, content)
    return target.getvalue()


def _payload(kind: str) -> bytes:
    if kind == "controller-release":
        obj = {"image_ref": CONTROLLER, "source_sha": SOURCE, "release_run_id": RUN}
    else:
        obj = {
            "source_sha": SOURCE,
            "run_id": RUN,
            "controller_digest": CONTROLLER,
            "browser_digest": BROWSER,
        }
    return (json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n").encode()


class FakeGitHub:
    """External API boundary with complete realistic run/job/artifact shapes."""

    def __init__(self) -> None:
        self.main_sha = SOURCE
        self.main_reads = 0
        self.run = {
            "id": int(RUN),
            "run_attempt": 1,
            "name": "Boca image release",
            "event": "workflow_dispatch",
            "head_sha": SOURCE,
            "head_branch": "main",
            "status": "completed",
            "conclusion": "success",
            "path": ".github/workflows/release-image.yml",
            "actor": {"login": "mbalbo2023", "id": 151845499},
            "repository": {
                "full_name": "mbalbo2023/boca-socios-assistant",
                "private": False,
            },
        }
        self.jobs = {
            "total_count": 1,
            "jobs": [
                {
                    "id": 511,
                    "name": "publish-reviewed-image",
                    "run_id": int(RUN),
                    "head_sha": SOURCE,
                    "status": "completed",
                    "conclusion": "success",
                    "steps": [
                        {"name": name, "status": "completed", "conclusion": "success"}
                        for name in REQUIRED_STEPS
                    ],
                }
            ],
        }
        self.payloads = {
            "controller-release": _payload("controller-release"),
            "paired-release": _payload("paired-release"),
        }
        self.archive_bytes = {
            81: _archive("boca-release-manifest.json", self.payloads["controller-release"]),
            82: _archive("boca-browser-release-manifest.json", self.payloads["paired-release"]),
        }
        self.artifacts = {
            "total_count": 2,
            "artifacts": [
                self._artifact(81, "boca-release-manifest"),
                self._artifact(82, "boca-browser-release-manifest"),
            ],
        }

    def _artifact(self, ident: int, name: str) -> dict:
        data = self.archive_bytes[ident]
        return {
            "id": ident,
            "name": name,
            "size_in_bytes": len(data),
            "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
            "expired": False,
            "archive_download_url": (
                "https://api.github.com/repos/mbalbo2023/boca-socios-assistant"
                f"/actions/artifacts/{ident}/zip"
            ),
            "workflow_run": {"id": int(RUN), "head_branch": "main", "head_sha": SOURCE},
        }

    def get_json(self, path: str) -> object:
        if path == "git/ref/heads/main":
            self.main_reads += 1
            return {
                "ref": "refs/heads/main",
                "node_id": "MDM6UmVm",
                "url": "https://api.github.com/repos/mbalbo2023/boca-socios-assistant/git/refs/heads/main",
                "object": {
                    "type": "commit",
                    "sha": self.main_sha,
                    "url": "https://api.github.com/repos/mbalbo2023/boca-socios-assistant/git/commits/"
                    + self.main_sha,
                },
            }
        if path == f"actions/runs/{RUN}":
            return self.run
        if path == f"actions/runs/{RUN}/jobs?per_page=100":
            return self.jobs
        if path == f"actions/runs/{RUN}/artifacts?per_page=100":
            return self.artifacts
        raise AssertionError(f"unexpected trusted API route: {path}")

    def get_artifact_zip(self, ident: int) -> bytes:
        return self.archive_bytes[ident]


def _request(kind: str, gh: FakeGitHub) -> Request:
    return Request(kind, payload_sha256=hashlib.sha256(gh.payloads[kind]).hexdigest())


def _historical_release_with_skipped_pr_validation() -> FakeGitHub:
    """The actual #851 release has a successful publish and a skipped PR job."""
    gh = FakeGitHub()
    gh.jobs["jobs"].append(
        {
            "id": 512,
            "name": "release-image-pr-validation",
            "run_id": int(RUN),
            "head_sha": SOURCE,
            "status": "completed",
            "conclusion": "skipped",
            "steps": [],
        }
    )
    gh.jobs["total_count"] = 2
    return gh


def test_authenticates_historical_release_with_exact_skipped_pr_validation_job() -> None:
    gh = _historical_release_with_skipped_pr_validation()
    release_auth._verify_release_job(gh, RUN, SOURCE)
    assert release_auth.download_authenticated_release(gh, RUN, SOURCE, "paired-release") == gh.payloads[
        "paired-release"
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda gh: gh.jobs["jobs"][1].update(conclusion="success"),
        lambda gh: gh.jobs["jobs"][1].update(name="unreviewed-job"),
        lambda gh: gh.jobs["jobs"][1].update(head_sha="f" * 40),
        lambda gh: gh.jobs["jobs"][1].update(run_id=1),
        lambda gh: gh.jobs["jobs"][1].update(status="queued"),
        lambda gh: gh.jobs["jobs"][1].update(steps=[{"name": "unreviewed"}]),
        lambda gh: gh.jobs.update(total_count=1),
        lambda gh: gh.jobs["jobs"].append(dict(gh.jobs["jobs"][1])),
    ],
)
def test_historical_release_rejects_unreviewed_or_active_extra_job(mutation) -> None:
    gh = _historical_release_with_skipped_pr_validation()
    mutation(gh)
    with pytest.raises(ReleaseAuthenticationNoGo):
        release_auth._verify_release_job(gh, RUN, SOURCE)


@pytest.mark.parametrize("kind", ["controller-release", "paired-release"])
def test_authenticates_exact_release_archive_and_current_main(kind: str) -> None:
    gh = FakeGitHub()
    run = GitHubActionsEvidenceAuthenticator(gh).authenticate(_request(kind, gh))
    assert run == gh.run
    assert gh.main_reads == 2


@pytest.mark.parametrize("kind", ["controller-release", "paired-release"])
def test_downloads_exact_authenticated_manifest_in_memory_without_a_prior_file(kind: str) -> None:
    gh = FakeGitHub()
    assert release_auth.download_authenticated_release(gh, RUN, SOURCE, kind) == gh.payloads[kind]
    assert gh.main_reads == 2


def test_download_rechecks_first_attempt_after_archive_fetch() -> None:
    class MutatingRun(FakeGitHub):
        def get_artifact_zip(self, ident: int) -> bytes:
            payload = super().get_artifact_zip(ident)
            self.run["run_attempt"] = 2
            return payload

    with pytest.raises(ReleaseAuthenticationNoGo):
        release_auth.download_authenticated_release(
            MutatingRun(), RUN, SOURCE, "controller-release"
        )


@pytest.mark.parametrize(
    "alteration", ["digest", "member", "size", "zip", "symlink_member", "oversized_archive"]
)
def test_download_never_returns_an_unverified_archive_member(alteration: str) -> None:
    gh = FakeGitHub()
    artifact = gh.artifacts["artifacts"][0]
    if alteration == "digest":
        artifact["digest"] = "sha256:" + "0" * 64
    elif alteration == "member":
        gh.archive_bytes[81] = _archive("unreviewed.json", gh.payloads["controller-release"])
        gh.artifacts["artifacts"][0] = gh._artifact(81, "boca-release-manifest")
    elif alteration == "size":
        artifact["size_in_bytes"] += 1
    elif alteration == "symlink_member":
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            entry = zipfile.ZipInfo("boca-release-manifest.json")
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(entry, gh.payloads["controller-release"])
        gh.archive_bytes[81] = buffer.getvalue()
        gh.artifacts["artifacts"][0] = gh._artifact(81, "boca-release-manifest")
    elif alteration == "oversized_archive":
        artifact["size_in_bytes"] = 32_769
    else:
        gh.archive_bytes[81] = b"not-a-ZIP"
        gh.artifacts["artifacts"][0] = gh._artifact(81, "boca-release-manifest")
    with pytest.raises(ReleaseAuthenticationNoGo):
        release_auth.download_authenticated_release(gh, RUN, SOURCE, "controller-release")


def test_rejects_retained_summary_without_downloadable_payload_authentication() -> None:
    gh = FakeGitHub()
    witness = Request(
        "retained-resource-observe",
        workflow_path=".github/workflows/boca-first-deploy.yml",
        payload_sha256="0" * 64,
    )
    with pytest.raises(ReleaseAuthenticationNoGo):
        GitHubActionsEvidenceAuthenticator(gh).authenticate(witness)
    assert gh.main_reads == 0


def test_rejects_same_run_metadata_but_modified_manifest_payload() -> None:
    gh = FakeGitHub()
    gh.archive_bytes[81] = _archive("boca-release-manifest.json", b"tampered")
    gh.artifacts["artifacts"][0] = gh._artifact(81, "boca-release-manifest")
    with pytest.raises(ReleaseAuthenticationNoGo):
        GitHubActionsEvidenceAuthenticator(gh).authenticate(_request("controller-release", gh))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda gh: gh.run.update(run_attempt=2),
        lambda gh: gh.run.update(conclusion="failure"),
        lambda gh: gh.run.update(head_sha="f" * 40),
        lambda gh: gh.run.update(actor={"login": "someone-else"}),
        lambda gh: gh.run.update(repository={"full_name": "other/repo"}),
        lambda gh: setattr(gh, "main_sha", "f" * 40),
        lambda gh: gh.jobs["jobs"][0].update(conclusion="failure"),
        lambda gh: gh.jobs["jobs"][0].update(steps=[]),
        lambda gh: gh.jobs["jobs"][0]["steps"][1].update(conclusion="failure"),
    ],
)
def test_rejects_untrusted_run_main_or_job(mutation) -> None:
    gh = FakeGitHub()
    mutation(gh)
    with pytest.raises(ReleaseAuthenticationNoGo):
        GitHubActionsEvidenceAuthenticator(gh).authenticate(_request("paired-release", gh))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda a: a.update(workflow_run={"id": 1, "head_branch": "main", "head_sha": SOURCE}),
        lambda a: a.update(expired=True),
        lambda a: a.update(digest=None),
        lambda a: a.update(name="other-name"),
        lambda a: a.update(archive_download_url="https://malicious.example/zip"),
    ],
)
def test_rejects_artifact_outside_exact_release(mutation) -> None:
    gh = FakeGitHub()
    mutation(gh.artifacts["artifacts"][0])
    with pytest.raises(ReleaseAuthenticationNoGo):
        GitHubActionsEvidenceAuthenticator(gh).authenticate(_request("controller-release", gh))


def test_rejects_duplicate_release_artifact() -> None:
    gh = FakeGitHub()
    gh.artifacts["artifacts"].append(dict(gh.artifacts["artifacts"][0]))
    gh.artifacts["total_count"] = 3
    with pytest.raises(ReleaseAuthenticationNoGo):
        GitHubActionsEvidenceAuthenticator(gh).authenticate(_request("controller-release", gh))


@pytest.mark.parametrize(
    "member", ["../boca-release-manifest.json", "folder/boca-release-manifest.json"]
)
def test_rejects_zip_path_traversal_or_nested_member(member: str) -> None:
    gh = FakeGitHub()
    gh.archive_bytes[81] = _archive(member, gh.payloads["controller-release"])
    gh.artifacts["artifacts"][0] = gh._artifact(81, "boca-release-manifest")
    with pytest.raises(ReleaseAuthenticationNoGo):
        GitHubActionsEvidenceAuthenticator(gh).authenticate(_request("controller-release", gh))


def test_rejects_zip_with_unreviewed_extra_file() -> None:
    gh = FakeGitHub()
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w") as destination:
        destination.writestr("boca-release-manifest.json", gh.payloads["controller-release"])
        destination.writestr("leak.env", b"secret")
    gh.archive_bytes[81] = target.getvalue()
    gh.artifacts["artifacts"][0] = gh._artifact(81, "boca-release-manifest")
    with pytest.raises(ReleaseAuthenticationNoGo):
        GitHubActionsEvidenceAuthenticator(gh).authenticate(_request("controller-release", gh))


def test_rejects_manifest_greater_than_1024_bytes_even_with_matching_metadata() -> None:
    gh = FakeGitHub()
    gh.payloads["controller-release"] = b"{" + b"x" * 1024 + b"}"
    gh.archive_bytes[81] = _archive("boca-release-manifest.json", gh.payloads["controller-release"])
    gh.artifacts["artifacts"][0] = gh._artifact(81, "boca-release-manifest")
    with pytest.raises(ReleaseAuthenticationNoGo):
        GitHubActionsEvidenceAuthenticator(gh).authenticate(_request("controller-release", gh))
