"""Authenticate a second, read-only retained Boca resource observation.

GitHub run/job/step/ZIP origin is verified only by the protected runner.
The host checks the byte-for-byte data in the SHA-pinned memfd ZIP, including
the historical resource custody parser. This is not upgrade permission.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from boca_socios import host_boca_upgrade_adapters as adapters
from boca_socios import host_boca_upgrade_observation_bridge as observed
from boca_socios.host_boca_upgrade_release_auth import (
    GitHubEvidenceTransport,
    GitHubRestTransport,
    _main_is_exact,
)
from boca_socios.host_boca_upgrade_release_bridge import _runner_write_proof

_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_ARTIFACT = "boca-retained-resources-observation"
_MEMBER = "boca-retained-observation.receipt"
_STEPS = frozenset(
    {
        "Require verified protected environment and matching main commit",
        "Observe retained Boca resource provenance READ_ONLY",
        "Upload authenticated candidate for retained Boca resources READ_ONLY",
    }
)
_FIELDS = frozenset(
    {
        "schema",
        "observer_run_id",
        "observer_source_sha",
        "pair_observation_run_id",
        "apply_attempt_id",
        "release_run_id",
        "custody",
    }
)


class UpgradeRetainedNoGo(ValueError):
    """No raw Docker, GitHub, path, user or member data in a refusal."""


def _fail() -> UpgradeRetainedNoGo:
    return UpgradeRetainedNoGo("Boca retained resource provenance unverified")


def _canonical(value: dict[str, object]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("ascii")


class _LiveGitHubCustodyAuthenticator:
    """Runner-only: actual authenticated run metadata, never a host source."""

    def __init__(
        self, client: GitHubEvidenceTransport, main_sha: str, run_id: str, receipt: bytes
    ) -> None:
        self.client = client
        self.expected = adapters.AuthenticationRequest(
            "retained-resource-observe",
            run_id,
            main_sha,
            ".github/workflows/boca-first-deploy.yml",
            hashlib.sha256(receipt).hexdigest(),
        )

    def authenticate(self, request: adapters.AuthenticationRequest) -> object:
        if request != self.expected:
            raise _fail()
        return self.client.get_json(f"actions/runs/{request.run_id}")


class _BundledCustodyAuthenticator:
    """Transport-only integrity, conditional on caller's verified host memfd."""

    def __init__(self, main_sha: str, run_id: str, receipt: bytes) -> None:
        self.expected = adapters.AuthenticationRequest(
            "retained-resource-observe",
            run_id,
            main_sha,
            ".github/workflows/boca-first-deploy.yml",
            hashlib.sha256(receipt).hexdigest(),
        )

    def authenticate(self, request: adapters.AuthenticationRequest) -> object:
        if request != self.expected:
            raise _fail()
        return {
            "id": int(self.expected.run_id),
            "run_attempt": 1,
            "name": "Boca first deploy",
            "event": "workflow_dispatch",
            "head_sha": self.expected.source_sha,
            "head_branch": "main",
            "status": "completed",
            "conclusion": "success",
            "path": self.expected.workflow_path,
            "actor": {"login": "mbalbo2023"},
            "repository": {"full_name": "mbalbo2023/boca-socios-assistant"},
        }


def _coordinates(
    custody: adapters.CustodyEvidence,
    pair_proof: bytes,
    pair_raw: bytes,
    main_sha: str,
    retained_run: str,
    paired_run: str,
    apply_run: str,
    release_run: str,
) -> None:
    if not _SHA.fullmatch(main_sha) or any(
        type(value) is not str or _RUN.fullmatch(value) is None
        for value in (retained_run, paired_run, apply_run, release_run)
    ):
        raise _fail()
    pair_value = observed.verify_bundled_observation(
        pair_proof, pair_raw, main_sha, paired_run, apply_run, release_run
    )
    if (
        len(
            {
                retained_run,
                paired_run,
                apply_run,
                release_run,
                custody.installation_attempt,
            }
        )
        != 5
        or not int(custody.installation_attempt)
        < int(paired_run)
        < int(retained_run)
        < int(apply_run)
        or custody.installation_attempt != pair_value["old_attempt_id"]
        or custody.installed_source_sha != pair_value["old_source_sha"]
        or custody.observation_run_id != retained_run
    ):
        raise _fail()


def verify_bundled_retained(
    proof: bytes,
    raw: bytes,
    pair_proof: bytes,
    pair_raw: bytes,
    main_sha: str,
    retained_run: str,
    paired_run: str,
    apply_run: str,
    release_run: str,
) -> adapters.CustodyEvidence:
    """Re-parse custody on host; this is not an independent GitHub trust root.

    The trusted runner already authenticated the actual ZIP. The protected
    bootstrap hashes every bundled byte before this verifier may be called.
    Never call this on unauthenticated host/form data and treat it as APPLY GO.
    """
    try:
        if type(proof) is not bytes or not 0 < len(proof) <= 4096:
            raise _fail()
        custody = adapters.verify_custody_seed(
            raw,
            observation_run_id=retained_run,
            observer_source_sha=main_sha,
            authenticator=_BundledCustodyAuthenticator(main_sha, retained_run, raw),
        )
        _coordinates(
            custody,
            pair_proof,
            pair_raw,
            main_sha,
            retained_run,
            paired_run,
            apply_run,
            release_run,
        )
        value = {
            "schema": 1,
            "observer_run_id": retained_run,
            "observer_source_sha": main_sha,
            "pair_observation_run_id": paired_run,
            "apply_attempt_id": apply_run,
            "release_run_id": release_run,
            "custody": asdict(custody),
        }
        parsed = json.loads(proof, object_pairs_hook=observed._unique)
        if (
            not isinstance(parsed, dict)
            or parsed.keys() != _FIELDS
            or parsed != value
            or _canonical(value) != proof
        ):
            raise _fail()
        return custody
    except Exception:
        raise _fail() from None


def _authenticate_and_download(
    main_sha: str,
    retained_run: str,
    paired_run: str,
    apply_run: str,
    release_run: str,
    supplied: bytes | None,
    pair_proof: bytes,
    pair_raw: bytes,
    client: GitHubEvidenceTransport,
    *,
    now: datetime | None = None,
) -> tuple[bytes, bytes]:
    timestamp = datetime.now(timezone.utc) if now is None else now  # noqa: UP017 - host py3.10
    if timestamp.tzinfo is None or client is None:
        raise _fail()
    _main_is_exact(client, main_sha)
    observed._verify_run(client, main_sha, retained_run, timestamp)
    observed._verify_job(client, main_sha, retained_run, _STEPS)
    raw = observed._download_artifact(
        client,
        main_sha,
        retained_run,
        artifact_name=_ARTIFACT,
        member_name=_MEMBER,
        member_limit=48_000,
        archive_limit=65_536,
    )
    if supplied is not None and supplied != raw:
        raise _fail()
    custody = adapters.verify_custody_seed(
        raw,
        observation_run_id=retained_run,
        observer_source_sha=main_sha,
        authenticator=_LiveGitHubCustodyAuthenticator(client, main_sha, retained_run, raw),
    )
    _coordinates(
        custody, pair_proof, pair_raw, main_sha, retained_run, paired_run, apply_run, release_run
    )
    # Catch a new attempt/branch/result while its artifact was being read.
    observed._verify_run(client, main_sha, retained_run, timestamp)
    _main_is_exact(client, main_sha)
    proof = _canonical(
        {
            "schema": 1,
            "observer_run_id": retained_run,
            "observer_source_sha": main_sha,
            "pair_observation_run_id": paired_run,
            "apply_attempt_id": apply_run,
            "release_run_id": release_run,
            "custody": asdict(custody),
        }
    )
    verify_bundled_retained(
        proof, raw, pair_proof, pair_raw, main_sha, retained_run, paired_run, apply_run, release_run
    )
    return proof, raw


def authenticate_runner_retained(
    main_sha: str,
    retained_run: str,
    paired_run: str,
    apply_run: str,
    release_run: str,
    raw: bytes,
    pair_proof: bytes,
    pair_raw: bytes,
    client: GitHubEvidenceTransport,
    *,
    now: datetime | None = None,
) -> bytes:
    """Runner attests both exact observation archives, never a host effect."""
    try:
        return _authenticate_and_download(
            main_sha,
            retained_run,
            paired_run,
            apply_run,
            release_run,
            raw,
            pair_proof,
            pair_raw,
            client,
            now=now,
        )[0]
    except Exception:
        raise _fail() from None


def runner_main(args: Sequence[str], *, now: datetime | None = None) -> int:
    try:
        if len(args) != 9 or not os.environ.get("GH_TOKEN"):
            raise _fail()
        (
            main,
            retained_run,
            paired_run,
            apply_run,
            release_run,
            pair_file,
            pair_proof_file,
            raw_path,
            proof_path,
        ) = args
        parent = Path(pair_file).parent
        if any(Path(path).parent != parent for path in (pair_proof_file, raw_path, proof_path)):
            raise _fail()
        pair_raw = observed._runner_input(pair_file)
        pair_proof = observed._runner_input(pair_proof_file)
        proof, raw = _authenticate_and_download(
            main,
            retained_run,
            paired_run,
            apply_run,
            release_run,
            None,
            pair_proof,
            pair_raw,
            GitHubRestTransport(os.environ["GH_TOKEN"]),
            now=now,
        )
        _runner_write_proof(raw_path, raw)
        _runner_write_proof(proof_path, proof)
    except Exception:
        print("BOCA_RETAINED_AUTH state=NO_GO host_authorized=false")
        return 3
    print("BOCA_RETAINED_AUTH state=VERIFIED host_authorized=false")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(runner_main(sys.argv[1:]))
