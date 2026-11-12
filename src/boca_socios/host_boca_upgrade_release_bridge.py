"""Bridge verified runner artifacts to bounded protected-bundle evidence.

The protected GitHub Actions runner authenticates release ZIPs with R242 before
constructing this proof.  The host then checks the exact bytes transported in
the SHA-pinned memfd archive; the proof is NOT a portable authorization token,
and it cannot replace main/owner/CI/environment or same-lease host gates.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from boca_socios import host_boca_upgrade_adapters as adapters
from boca_socios.browser_release_manifest import validate_browser_manifest
from boca_socios.host_boca_pair_upgrade_plan import CandidateRelease
from boca_socios.host_boca_upgrade_release_auth import (
    GitHubActionsEvidenceAuthenticator,
    GitHubEvidenceTransport,
    GitHubRestTransport,
    download_authenticated_release,
)
from boca_socios.release_manifest import validate_manifest

_FIELDS = frozenset(
    {
        "schema",
        "source_sha",
        "release_run_id",
        "controller_ref",
        "worker_ref",
        "controller_manifest_sha256",
        "paired_manifest_sha256",
    }
)


class UpgradeReleaseBridgeNoGo(ValueError):
    """Fixed safe refusal; never expose GitHub response bytes or bearer tokens."""


def _fail() -> UpgradeReleaseBridgeNoGo:
    return UpgradeReleaseBridgeNoGo("Boca dual release bridge unverified")


def _canonical(value: dict[str, object]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("ascii")


def authenticate_runner_release(
    candidate: CandidateRelease,
    controller_manifest: bytes,
    paired_manifest: bytes,
    client: GitHubEvidenceTransport,
) -> bytes:
    """Runner-only: independently authenticate both real GH release ZIPs.

    The actual short manifest bytes came from a protected workflow download.
    Their hashes MUST match each authenticated artifact member, and GitHub's
    current main ref is checked before and after EACH role authentication.
    This proof is only meaningful when the trusted runner builds the pinned ZIP.
    """
    try:
        if type(candidate) is not CandidateRelease or client is None:
            raise _fail()
        release = adapters.verify_release(
            candidate,
            controller_manifest=controller_manifest,
            paired_manifest=paired_manifest,
            current_main_sha=candidate.source_sha,
            authenticator=GitHubActionsEvidenceAuthenticator(client),
        )
        value: dict[str, object] = {"schema": 1, **asdict(release)}
        result = _canonical(value)
        if len(result) > 1024:
            raise _fail()
        verify_bundled_release(result, controller_manifest, paired_manifest, candidate)
        return result
    except Exception:
        raise _fail() from None


def download_runner_release(
    candidate: CandidateRelease, client: GitHubEvidenceTransport
) -> tuple[bytes, bytes, bytes]:
    """Download both REST ZIPs, authenticate bytes, then prepare a local proof.

    No caller-provided manifests and no filesystem writes until both ZIP
    digests, member allowlists, attempts, main and manifest identities pass.
    """
    try:
        if type(candidate) is not CandidateRelease or client is None:
            raise _fail()
        candidate.validate()
        controller = download_authenticated_release(
            client, candidate.release_run_id, candidate.source_sha, "controller-release"
        )
        worker = download_authenticated_release(
            client, candidate.release_run_id, candidate.source_sha, "paired-release"
        )
        proof = _canonical(
            {
                "schema": 1,
                "source_sha": candidate.source_sha,
                "release_run_id": candidate.release_run_id,
                "controller_ref": candidate.controller_image_ref,
                "worker_ref": candidate.worker_image_ref,
                "controller_manifest_sha256": hashlib.sha256(controller).hexdigest(),
                "paired_manifest_sha256": hashlib.sha256(worker).hexdigest(),
            }
        )
        verify_bundled_release(proof, controller, worker, candidate)
        return controller, worker, proof
    except Exception:
        raise _fail() from None


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise _fail()
        result[name] = value
    return result


def verify_bundled_release(
    proof: bytes,
    controller_manifest: bytes,
    paired_manifest: bytes,
    candidate: CandidateRelease,
) -> tuple[str, str]:
    """Host checks transport integrity; it does NOT authenticate a GH run.

    Only the SHA-checked host bundle constructed *after* runner verification
    makes this evidence trusted. Never call this on a form/host-provided proof
    and interpret the resulting pair as an authorization for Docker effects.
    """
    try:
        if (
            type(candidate) is not CandidateRelease
            or type(proof) is not bytes
            or not 0 < len(proof) <= 1024
            or type(controller_manifest) is not bytes
            or not 0 < len(controller_manifest) <= 1024
            or type(paired_manifest) is not bytes
            or not 0 < len(paired_manifest) <= 1024
        ):
            raise _fail()
        candidate.validate()
        value = json.loads(proof, object_pairs_hook=_unique)
        if not isinstance(value, dict) or value.keys() != _FIELDS or _canonical(value) != proof:
            raise _fail()
        controller_digest = hashlib.sha256(controller_manifest).hexdigest()
        paired_digest = hashlib.sha256(paired_manifest).hexdigest()
        expected = {
            "schema": 1,
            "source_sha": candidate.source_sha,
            "release_run_id": candidate.release_run_id,
            "controller_ref": candidate.controller_image_ref,
            "worker_ref": candidate.worker_image_ref,
            "controller_manifest_sha256": controller_digest,
            "paired_manifest_sha256": paired_digest,
        }
        if value != expected:
            raise _fail()
        validate_manifest(
            json.loads(controller_manifest, object_pairs_hook=_unique),
            candidate.controller_image_ref,
            candidate.source_sha,
            candidate.release_run_id,
        )
        validate_browser_manifest(
            json.loads(paired_manifest, object_pairs_hook=_unique),
            candidate.controller_image_ref,
            candidate.worker_image_ref,
            candidate.source_sha,
            candidate.release_run_id,
        )
        return controller_digest, paired_digest
    except Exception:
        raise _fail() from None


def _runner_input(path: str) -> bytes:
    """Read a verified runner-private manifest without following links.

    The bundle builder consumes only files previously authenticated and
    written by the REST runner bridge, not untrusted CLI-extracted archives.
    """
    folder = Path(path).parent
    parent = folder.lstat()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.geteuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise _fail()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        item = os.fstat(fd)
        if (
            not stat.S_ISREG(item.st_mode)
            or item.st_uid != os.geteuid()
            or item.st_nlink != 1
            or not 0 < item.st_size <= 1024
        ):
            raise _fail()
        raw = os.read(fd, 1025)
        if len(raw) != item.st_size:
            raise _fail()
        return raw
    finally:
        os.close(fd)


def _runner_write_proof(path: str, proof: bytes) -> None:
    folder = Path(path).parent
    parent = folder.lstat()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.geteuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise _fail()
    fd = os.open(path, os.O_WRONLY | os.O_EXCL | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        if os.write(fd, proof) != len(proof):
            raise _fail()
        os.fsync(fd)
    finally:
        os.close(fd)
    directory = os.open(folder, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def runner_main(args: Sequence[str]) -> int:
    """Five runner-only coordinates, no untrusted local manifest input."""
    try:
        if len(args) != 5:
            raise _fail()
        source, run, controller_ref, worker_ref, folder_arg = args
        candidate = CandidateRelease(source, run, controller_ref, worker_ref)
        candidate.validate()
        token = os.environ.get("GH_TOKEN", "")
        folder = Path(folder_arg)
        if not token or not folder.is_absolute():
            raise _fail()
        parent = folder.lstat()
        if (
            not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid != os.geteuid()
            or stat.S_IMODE(parent.st_mode) != 0o700
        ):
            raise _fail()
        destinations = (
            folder / "boca-release-manifest.json",
            folder / "boca-browser-release-manifest.json",
            folder / "runner-proof.json",
        )
        for path in destinations:
            try:
                path.lstat()
            except FileNotFoundError:
                continue
            raise _fail()
        controller, worker, proof = download_runner_release(candidate, GitHubRestTransport(token))
        for path, raw in zip(destinations, (controller, worker, proof), strict=True):
            _runner_write_proof(str(path), raw)
    except Exception:
        print("BOCA_RELEASE_AUTH state=NO_GO host_authorized=false")
        return 3
    print("BOCA_RELEASE_AUTH state=VERIFIED host_authorized=false")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(runner_main(sys.argv[1:]))
