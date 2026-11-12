"""Authenticate Boca dual-image release artifacts against genuine GitHub Actions.

This module is a *read-only provenance boundary*, not an upgrade authorization
or host transport.  Historical R189 retained-resource observations currently
exist only as GitHub step summaries: they cannot be authenticated as an
artifact payload and therefore fail closed here.  A fresh same-lease host
observation needs its own independently reviewed journal/transport.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Protocol, cast

from boca_socios.release_run import validate_release_run

_REPOSITORY = "mbalbo2023/boca-socios-assistant"
_API_BASE = f"https://api.github.com/repos/{_REPOSITORY}/"
_WORKFLOW = ".github/workflows/release-image.yml"
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_ARTIFACTS = {
    "controller-release": ("boca-release-manifest", "boca-release-manifest.json"),
    "paired-release": (
        "boca-browser-release-manifest",
        "boca-browser-release-manifest.json",
    ),
}
_REQUIRED_RELEASE_STEPS = frozenset(
    {
        "Require verified protected release environment",
        "Scan the image that will be published",
        "Scan browser image before any publication",
        "Publish both scanned images and record immutable digests",
        "Preserve exact published digest for the guarded install",
        "Preserve paired browser release evidence for a future guarded install",
    }
)


class ReleaseAuthenticationNoGo(ValueError):
    """Fixed fail-closed answer; never reveal tokens, URLs or response bodies."""


def _fail() -> ReleaseAuthenticationNoGo:
    return ReleaseAuthenticationNoGo("Boca protected release evidence is unverified")


def _json_exact(raw: bytes) -> object:
    def _unique(items: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in items:
            if key in value:
                raise _fail()
            value[key] = item
        return value

    return json.loads(raw, object_pairs_hook=_unique)


class GitHubEvidenceTransport(Protocol):
    """Authenticated GitHub GETs; production uses only the GitHub API origin."""

    def get_json(self, path: str) -> object: ...

    def get_artifact_zip(self, ident: int) -> bytes: ...


class _RequestView(Protocol):
    @property
    def kind(self) -> str: ...

    @property
    def run_id(self) -> str: ...

    @property
    def source_sha(self) -> str: ...

    @property
    def workflow_path(self) -> str: ...

    @property
    def payload_sha256(self) -> str: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


class GitHubRestTransport:
    """Read-only authenticated REST + signed artifact redirect without token relay.

    GitHub's artifact endpoint may redirect to temporary Azure/GitHub CDN
    storage.  The bearer token is sent **only** to api.github.com; a single
    HTTPS signed CDN redirect is downloaded without an Authorization header.
    """

    def __init__(self, token: str) -> None:
        if (
            type(token) is not str
            or not token
            or len(token) > 4096
            or any(char in token for char in ("\n", "\r", "\x00"))
        ):
            raise _fail()
        self._token = token
        self._opener = urllib.request.build_opener(_NoRedirect)

    def _read(self, url: str, *, authenticated: bool, bound: int) -> bytes:
        if urllib.parse.urlsplit(url).scheme != "https":
            raise _fail()
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "boca-protected-release-evidence",
        }
        if authenticated:
            headers["Authorization"] = f"Bearer {self._token}"
        request = urllib.request.Request(url, headers=headers, method="GET")  # noqa: S310
        with self._opener.open(request, timeout=15) as response:
            if response.status != 200:
                raise _fail()
            raw = response.read(bound + 1)
        if not 0 < len(raw) <= bound:
            raise _fail()
        return cast(bytes, raw)

    def get_json(self, path: str) -> object:
        if not (
            path == "git/ref/heads/main"
            or re.fullmatch(
                r"actions/runs/[1-9][0-9]{0,19}(?:/(?:jobs|artifacts)\?per_page=100)?", path
            )
        ):
            raise _fail()
        try:
            value = _json_exact(self._read(_API_BASE + path, authenticated=True, bound=1_000_000))
            if not isinstance(value, dict):
                raise _fail()
            return value
        except Exception:
            raise _fail() from None

    def get_artifact_zip(self, ident: int) -> bytes:
        if type(ident) is not int or ident <= 0 or ident > 10**20:
            raise _fail()
        url = _API_BASE + f"actions/artifacts/{ident}/zip"
        try:
            # R244 retains a verified public receipt up to 48 KiB. Per-kind
            # ZIP limits remain narrower inside the authenticated consumer.
            return self._read(url, authenticated=True, bound=65_536)
        except urllib.error.HTTPError as redirect:
            if redirect.code not in (302, 303, 307, 308):
                raise _fail() from None
            signed = redirect.headers.get("Location", "")
            parsed = urllib.parse.urlsplit(signed)
            host = parsed.hostname or ""
            if (
                parsed.scheme != "https"
                or parsed.username is not None
                or parsed.password is not None
                or parsed.fragment
                or len(signed) > 8192
                or parsed.port not in (None, 443)
                or not host.endswith(
                    (
                        ".blob.core.windows.net",
                        ".githubusercontent.com",
                        ".actions.githubusercontent.com",
                    )
                )
            ):
                raise _fail() from None
            try:
                # The signed URL is not a GitHub API endpoint: no bearer header.
                return self._read(signed, authenticated=False, bound=65_536)
            except Exception:
                raise _fail() from None
        except Exception:
            raise _fail() from None


def _main_is_exact(client: GitHubEvidenceTransport, source_sha: str) -> None:
    main = client.get_json("git/ref/heads/main")
    if not isinstance(main, dict) or main.get("ref") != "refs/heads/main":
        raise _fail()
    target = main.get("object")
    if (
        not isinstance(target, dict)
        or target.get("type") != "commit"
        or target.get("sha") != source_sha
        or target.get("url") != _API_BASE + "git/commits/" + source_sha
    ):
        raise _fail()


def _verify_release_job(client: GitHubEvidenceTransport, run_id: str, sha: str) -> None:
    record = client.get_json(f"actions/runs/{run_id}/jobs?per_page=100")
    if not isinstance(record, dict) or record.get("total_count") != 1:
        raise _fail()
    jobs = record.get("jobs")
    if not isinstance(jobs, list) or len(jobs) != 1:
        raise _fail()
    job = jobs[0]
    if (
        not isinstance(job, dict)
        or job.get("run_id") != int(run_id)
        or job.get("name") != "publish-reviewed-image"
        or job.get("head_sha") != sha
        or job.get("status") != "completed"
        or job.get("conclusion") != "success"
    ):
        raise _fail()
    steps = job.get("steps")
    if not isinstance(steps, list) or len(steps) < len(_REQUIRED_RELEASE_STEPS):
        raise _fail()
    names: set[str] = set()
    for step in steps:
        if not isinstance(step, dict) or type(step.get("name")) is not str:
            raise _fail()
        name = step["name"]
        if name in names:
            raise _fail()
        names.add(name)
        if name in _REQUIRED_RELEASE_STEPS and (
            step.get("status") != "completed" or step.get("conclusion") != "success"
        ):
            raise _fail()
    if not _REQUIRED_RELEASE_STEPS <= names:
        raise _fail()


def _verified_zip_member(raw: bytes, filename: str) -> bytes:
    if type(raw) is not bytes or not 0 < len(raw) <= 32_768:
        raise _fail()
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) != 1:
                raise _fail()
            member = members[0]
            if (
                member.filename != filename
                or member.is_dir()
                or not 0 < member.file_size <= 1024
                or member.flag_bits & 1
                or member.compress_type not in (zipfile.ZIP_DEFLATED, zipfile.ZIP_STORED)
                or (member.external_attr >> 16) & 0o170000 == 0o120000
            ):
                raise _fail()
            with archive.open(member) as stream:
                payload = stream.read(1025)
        if len(payload) != member.file_size:
            raise _fail()
        return payload
    except Exception:
        raise _fail() from None


def _release_artifact(client: GitHubEvidenceTransport, run_id: str, sha: str, kind: str) -> bytes:
    record = client.get_json(f"actions/runs/{run_id}/artifacts?per_page=100")
    if not isinstance(record, dict) or record.get("total_count") != 2:
        raise _fail()
    artifacts = record.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 2:
        raise _fail()
    expected_names = {name for name, _ in _ARTIFACTS.values()}
    by_name: dict[str, dict[str, object]] = {}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise _fail()
        name = artifact.get("name")
        if not isinstance(name, str) or name not in expected_names or name in by_name:
            raise _fail()
        by_name[name] = artifact
    if set(by_name) != expected_names:
        raise _fail()
    name, filename = _ARTIFACTS[kind]
    artifact = by_name[name]
    ident, size, digest = (
        artifact.get("id"),
        artifact.get("size_in_bytes"),
        artifact.get("digest"),
    )
    url = artifact.get("archive_download_url")
    if (
        type(ident) is not int
        or ident <= 0
        or type(size) is not int
        or not 0 < size <= 32_768
        or type(digest) is not str
        or not digest.startswith("sha256:")
        or not _DIGEST.fullmatch(digest.removeprefix("sha256:"))
        or artifact.get("expired") is not False
        or url != _API_BASE + f"actions/artifacts/{ident}/zip"
    ):
        raise _fail()
    parent = artifact.get("workflow_run")
    if not isinstance(parent, dict) or any(
        parent.get(field) != value
        for field, value in (("id", int(run_id)), ("head_branch", "main"), ("head_sha", sha))
    ):
        raise _fail()
    raw = client.get_artifact_zip(ident)
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest.removeprefix("sha256:"):
        raise _fail()
    return _verified_zip_member(raw, filename)


def download_authenticated_release(
    client: GitHubEvidenceTransport, run_id: str, source_sha: str, kind: str
) -> bytes:
    """Authenticate a genuine release ZIP in memory; return only its checked member.

    No local extraction occurs here. The caller must validate BOTH manifest
    payloads and issue the bound proof before materializing either one.
    """
    try:
        if (
            client is None
            or type(kind) is not str
            or kind not in _ARTIFACTS
            or type(run_id) is not str
            or _RUN.fullmatch(run_id) is None
            or type(source_sha) is not str
            or _SHA.fullmatch(source_sha) is None
        ):
            raise _fail()
        _main_is_exact(client, source_sha)
        run = client.get_json(f"actions/runs/{run_id}")
        validate_release_run(run, source_sha, run_id)
        _verify_release_job(client, run_id, source_sha)
        member = _release_artifact(client, run_id, source_sha, kind)
        # The artifact listing belongs to a run ID, not an attempt. Catch
        # an in-flight rerun after the ZIP GET before accepting its member.
        validate_release_run(client.get_json(f"actions/runs/{run_id}"), source_sha, run_id)
        _main_is_exact(client, source_sha)
        return member
    except Exception:
        raise _fail() from None


@dataclass(frozen=True, slots=True)
class GitHubActionsEvidenceAuthenticator:
    """Satisfies ``EvidenceAuthenticator`` only for genuine dual release ZIPs.

    No default client and no witness fallback: simply knowing the run number,
    manifest JSON or an R189 step summary never authorizes upgrade.
    """

    client: GitHubEvidenceTransport

    def authenticate(self, request: object) -> object:
        try:
            typed = cast(_RequestView, request)
            kind = typed.kind
            run_id = typed.run_id
            source_sha = typed.source_sha
            workflow_path = typed.workflow_path
            payload_sha256 = typed.payload_sha256
            if (
                kind not in _ARTIFACTS
                or type(run_id) is not str
                or not _RUN.fullmatch(run_id)
                or type(source_sha) is not str
                or not _SHA.fullmatch(source_sha)
                or workflow_path != _WORKFLOW
                or type(payload_sha256) is not str
                or not _DIGEST.fullmatch(payload_sha256)
            ):
                raise _fail()
            member = download_authenticated_release(self.client, run_id, source_sha, kind)
            if hashlib.sha256(member).hexdigest() != payload_sha256:
                raise _fail()
            run = self.client.get_json(f"actions/runs/{run_id}")
            validate_release_run(run, source_sha, run_id)
            return run
        except Exception:
            raise _fail() from None
