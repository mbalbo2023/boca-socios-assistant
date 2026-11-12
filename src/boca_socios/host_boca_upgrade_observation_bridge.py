"""Runner-authenticated earlier READ_ONLY pair observation for a successor.

The observation is a *separate* completed protected Actions run that uploaded
one exact canonical host receipt. GitHub REST run/job/step/artifact/ZIP are
authenticated on the runner; GH_TOKEN never reaches the Boca host. The
transport digest projected into a memfd bundle is NOT an effect permission.
The host must still recapture both identities under the same mutation lease.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import zipfile
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

from boca_socios import host_boca_pair_observe as pair
from boca_socios.host_boca_upgrade_release_auth import (
    GitHubEvidenceTransport,
    GitHubRestTransport,
    _main_is_exact,
)
from boca_socios.host_boca_upgrade_release_bridge import _runner_write_proof

_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_PAIR_PREFIX = b"BOCA_INSTALLED_PAIR "
_API = "https://api.github.com/repos/mbalbo2023/boca-socios-assistant/"
_ARTIFACT = "boca-installed-pair-observation"
_MEMBER = "boca-pair-observation.receipt"
_STEPS = frozenset(
    {
        "Require verified protected environment and matching main commit",
        "Observe installed Boca controller and worker pair READ_ONLY",
        "Upload authenticated candidate for installed pair observation READ_ONLY",
    }
)
_FIELDS = frozenset(
    {
        "schema",
        "observer_run_id",
        "observer_source_sha",
        "apply_attempt_id",
        "release_run_id",
        "old_attempt_id",
        "old_source_sha",
        "controller_id",
        "worker_id",
        "controller_image_id",
        "worker_image_id",
        "controller_ref",
        "worker_ref",
        "observation_receipt_sha256",
    }
)


class UpgradeObservationNoGo(ValueError):
    """Fixed public refusal; never include a private run/host/HTTP response."""


def _fail() -> UpgradeObservationNoGo:
    return UpgradeObservationNoGo("Boca prior observation provenance unverified")


def _unique(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in items:
        if name in result:
            raise _fail()
        result[name] = value
    return result


def _canonical(value: dict[str, object]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("ascii")


def _pair_projection(raw: bytes, observation_run: str, main_sha: str) -> dict[str, object]:
    if not _RUN.fullmatch(observation_run) or not _SHA.fullmatch(main_sha):
        raise _fail()
    pair.verify(raw, observation_run)
    parsed = json.loads(raw.removeprefix(_PAIR_PREFIX), object_pairs_hook=_unique)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("services"), list):
        raise _fail()
    controller, worker = parsed["services"]
    if (
        controller["running"] is not True
        or controller["status"] != "running"
        or controller["health"] != "healthy"
        or worker["running"] is not False
        or worker["status"] != "created"
        or worker["pid"] != 0
        or worker["exit_code"] != 0
        or parsed["source_sha"] == main_sha
    ):
        raise _fail()
    return {
        "schema": 1,
        "observer_run_id": observation_run,
        "observer_source_sha": main_sha,
        "old_attempt_id": parsed["attempt_id"],
        "old_source_sha": parsed["source_sha"],
        "controller_id": controller["container_id"],
        "worker_id": worker["container_id"],
        "controller_image_id": controller["image_id"],
        "worker_image_id": worker["image_id"],
        "controller_ref": controller["image_ref"],
        "worker_ref": worker["image_ref"],
        "observation_receipt_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _runs_are_distinct(projection: dict[str, object], apply_run: str, release_run: str) -> None:
    obs = projection["observer_run_id"]
    old = projection["old_attempt_id"]
    if (
        not isinstance(obs, str)
        or not isinstance(old, str)
        or not all(type(run) is str and _RUN.fullmatch(run) for run in (apply_run, release_run))
        or len({obs, old, apply_run, release_run}) != 4
        or int(obs) >= int(apply_run)
        or int(obs) <= int(old)
    ):
        raise _fail()


def verify_bundled_observation(
    proof: bytes,
    raw: bytes,
    main_sha: str,
    observation_run: str,
    apply_run: str,
    release_run: str,
) -> dict[str, object]:
    """Host checks *integrity*, never independently authorizes GitHub origin."""
    try:
        if type(proof) is not bytes or not 0 < len(proof) <= 2048:
            raise _fail()
        expected = _pair_projection(raw, observation_run, main_sha)
        _runs_are_distinct(expected, apply_run, release_run)
        expected.update({"apply_attempt_id": apply_run, "release_run_id": release_run})
        parsed = json.loads(proof, object_pairs_hook=_unique)
        if (
            not isinstance(parsed, dict)
            or parsed.keys() != _FIELDS
            or type(parsed.get("schema")) is not int
            or parsed != expected
            or _canonical(parsed) != proof
        ):
            raise _fail()
        return expected
    except Exception:
        raise _fail() from None


def _verify_run(client: GitHubEvidenceTransport, main_sha: str, run_id: str, now: datetime) -> None:
    run = client.get_json(f"actions/runs/{run_id}")
    if not isinstance(run, dict):
        raise _fail()
    exact = {
        "id": int(run_id),
        "run_attempt": 1,
        "name": "Boca first deploy",
        "event": "workflow_dispatch",
        "head_sha": main_sha,
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
    }
    if any(
        type(run.get(key)) is not type(value) or run.get(key) != value
        for key, value in exact.items()
    ):
        raise _fail()
    if run.get("path") not in (
        ".github/workflows/boca-first-deploy.yml",
        ".github/workflows/boca-first-deploy.yml@main",
    ):
        raise _fail()
    actor, repo = run.get("actor"), run.get("repository")
    if (
        not isinstance(actor, dict)
        or actor.get("login") != "mbalbo2023"
        or not isinstance(repo, dict)
        or repo.get("full_name") != "mbalbo2023/boca-socios-assistant"
    ):
        raise _fail()
    created = run.get("created_at")
    if type(created) is not str or not created.endswith("Z") or len(created) > 40:
        raise _fail()
    stamp = datetime.fromisoformat(created.removesuffix("Z") + "+00:00")
    if stamp.tzinfo is None or not timedelta(0) <= now - stamp <= timedelta(hours=48):
        raise _fail()


def _verify_job(client: GitHubEvidenceTransport, main_sha: str, run_id: str) -> None:
    record = client.get_json(f"actions/runs/{run_id}/jobs?per_page=100")
    if not isinstance(record, dict):
        raise _fail()
    jobs, count = record.get("jobs"), record.get("total_count")
    if (
        not isinstance(jobs, list)
        or type(count) is not int
        or count != len(jobs)
        or not 1 <= len(jobs) <= 2
    ):
        raise _fail()
    selected = [
        job
        for job in jobs
        if isinstance(job, dict) and job.get("name") == "approved-boca-manual-operation"
    ]
    if len(selected) != 1:
        raise _fail()
    if any(
        job.get("name") != "first-deploy-pr-validation" or job.get("conclusion") != "skipped"
        for job in jobs
        if job is not selected[0]
    ):
        raise _fail()
    job = selected[0]
    if (
        job.get("run_id") != int(run_id)
        or job.get("head_sha") != main_sha
        or job.get("status") != "completed"
        or job.get("conclusion") != "success"
    ):
        raise _fail()
    steps = job.get("steps")
    if not isinstance(steps, list) or len(steps) < len(_STEPS):
        raise _fail()
    names: set[str] = set()
    for step in steps:
        if not isinstance(step, dict) or type(step.get("name")) is not str:
            raise _fail()
        name = step["name"]
        if name in names:
            raise _fail()
        names.add(name)
        if name in _STEPS and (
            step.get("status") != "completed" or step.get("conclusion") != "success"
        ):
            raise _fail()
    if not _STEPS <= names:
        raise _fail()


def _verify_artifact(
    client: GitHubEvidenceTransport, main_sha: str, run_id: str, raw: bytes
) -> None:
    listing = client.get_json(f"actions/runs/{run_id}/artifacts?per_page=100")
    if not isinstance(listing, dict) or listing.get("total_count") != 1:
        raise _fail()
    entries = listing.get("artifacts")
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
        raise _fail()
    artifact = entries[0]
    ident, size, digest = artifact.get("id"), artifact.get("size_in_bytes"), artifact.get("digest")
    if (
        type(ident) is not int
        or ident <= 0
        or type(size) is not int
        or not 0 < size <= 16_384
        or type(digest) is not str
        or not digest.startswith("sha256:")
        or _HASH.fullmatch(digest.removeprefix("sha256:")) is None
        or artifact.get("name") != _ARTIFACT
        or artifact.get("expired") is not False
        or artifact.get("archive_download_url") != _API + f"actions/artifacts/{ident}/zip"
    ):
        raise _fail()
    parent = artifact.get("workflow_run")
    if not isinstance(parent, dict) or any(
        parent.get(field) != value
        for field, value in (("id", int(run_id)), ("head_branch", "main"), ("head_sha", main_sha))
    ):
        raise _fail()
    zip_bytes = client.get_artifact_zip(ident)
    if (
        type(zip_bytes) is not bytes
        or len(zip_bytes) != size
        or hashlib.sha256(zip_bytes).hexdigest() != digest.removeprefix("sha256:")
    ):
        raise _fail()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        members = archive.infolist()
        if len(members) != 1:
            raise _fail()
        member = members[0]
        if (
            member.filename != _MEMBER
            or member.is_dir()
            or not 0 < member.file_size <= 4096
            or member.flag_bits & 1
            or member.compress_type not in (zipfile.ZIP_DEFLATED, zipfile.ZIP_STORED)
            or (member.external_attr >> 16) & 0o170000 == 0o120000
        ):
            raise _fail()
        with archive.open(member) as stream:
            contents = stream.read(4097)
    if contents != raw or len(contents) != member.file_size:
        raise _fail()


def authenticate_runner_observation(
    main_sha: str,
    observation_run: str,
    apply_run: str,
    release_run: str,
    raw: bytes,
    client: GitHubEvidenceTransport,
    *,
    now: datetime | None = None,
) -> bytes:
    """Runner-only real Actions artifact authentication; never host capability."""
    try:
        observed_now = datetime.now(timezone.utc) if now is None else now  # noqa: UP017 - host py3.10
        if observed_now.tzinfo is None or client is None:
            raise _fail()
        expected = _pair_projection(raw, observation_run, main_sha)
        _runs_are_distinct(expected, apply_run, release_run)
        expected.update({"apply_attempt_id": apply_run, "release_run_id": release_run})
        _main_is_exact(client, main_sha)
        _verify_run(client, main_sha, observation_run, observed_now)
        _verify_job(client, main_sha, observation_run)
        _verify_artifact(client, main_sha, observation_run, raw)
        _main_is_exact(client, main_sha)
        proof = _canonical(expected)
        verify_bundled_observation(proof, raw, main_sha, observation_run, apply_run, release_run)
        return proof
    except Exception:
        raise _fail() from None


def _runner_input(path: str) -> bytes:
    folder = Path(path).parent
    metadata = folder.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise _fail()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        item = os.fstat(fd)
        if (
            not stat.S_ISREG(item.st_mode)
            or item.st_uid != os.geteuid()
            or item.st_nlink != 1
            or not 0 < item.st_size <= 4096
        ):
            raise _fail()
        raw = os.read(fd, 4097)
        if len(raw) != item.st_size:
            raise _fail()
        return raw
    finally:
        os.close(fd)


def runner_main(args: Sequence[str], *, now: datetime | None = None) -> int:
    try:
        if len(args) != 6 or not os.environ.get("GH_TOKEN"):
            raise _fail()
        main, observation, apply, release, source, destination = args
        if Path(source).parent != Path(destination).parent:
            raise _fail()
        raw = _runner_input(source)
        proof = authenticate_runner_observation(
            main,
            observation,
            apply,
            release,
            raw,
            GitHubRestTransport(os.environ["GH_TOKEN"]),
            now=now,
        )
        _runner_write_proof(destination, proof)
    except Exception:
        print("BOCA_OBSERVATION_AUTH state=NO_GO host_authorized=false")
        return 3
    print("BOCA_OBSERVATION_AUTH state=VERIFIED host_authorized=false")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(runner_main(sys.argv[1:]))
