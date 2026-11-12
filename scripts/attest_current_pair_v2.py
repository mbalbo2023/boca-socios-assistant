"""R247 protected runner: authenticated live Boca pair and historical R188 custody.

This script is intentionally NOT shipped to the host.  The only network client
speaks to GitHub REST through the existing strict, bearer-isolated transport.
An unkeyed V2 digest grants no authority, and every output remains NO_GO for
host effects until a separately reviewed same-lease durable journal exists.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from boca_socios import host_boca_current_pair_v2 as current
from boca_socios import host_boca_upgrade_adapters as adapters
from boca_socios import host_boca_upgrade_observation_bridge as observed
from boca_socios import host_boca_upgrade_release_bridge as release_bridge
from boca_socios import host_boca_upgrade_retained_bridge as retained_bridge
from boca_socios.host_boca_pair_upgrade import PairCoordinates
from boca_socios.host_boca_pair_upgrade_plan import CandidateRelease
from boca_socios.host_boca_upgrade_release_auth import (
    GitHubEvidenceTransport,
    GitHubRestTransport,
    _json_exact,
    _main_is_exact,
)
from boca_socios.release_run import validate_release_run

_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_API = "https://api.github.com/repos/mbalbo2023/boca-socios-assistant/"
_SENTINEL = b'{"state":"NO_GO"}\n'


class RunnerCurrentPairNoGo(ValueError):
    """One redacted refusal for all untrusted REST and runner inputs."""


def _fail() -> RunnerCurrentPairNoGo:
    return RunnerCurrentPairNoGo("Boca current-pair release provenance unverified")


class ReleaseCatalog(Protocol):
    """The one GitHub source-index query used exclusively on the runner."""

    def unique_previous_release(self, source: str) -> str: ...


class GitHubRestReleaseCatalog(GitHubRestTransport):
    """Strict source-to-run lookup; never select from two apparent releases."""

    def unique_previous_release(self, source: str) -> str:
        try:
            if type(source) is not str or _SHA.fullmatch(source) is None:
                raise _fail()
            # This URL is constructed solely from a validated SHA and fixed
            # repository/workflow/query. GitHubToken is never sent to a CDN.
            url = (
                _API
                + "actions/workflows/release-image.yml/runs?head_sha="
                + source
                + "&event=workflow_dispatch&per_page=100"
            )
            obj = _json_exact(self._read(url, authenticated=True, bound=200_000))
            if type(obj) is not dict or obj.keys() < {"total_count", "workflow_runs"}:
                raise _fail()
            runs = obj["workflow_runs"]
            if type(obj["total_count"]) is not int or obj["total_count"] != 1:
                raise _fail()
            if type(runs) is not list or len(runs) != 1 or type(runs[0]) is not dict:
                raise _fail()
            candidate = runs[0]
            ident = candidate.get("id")
            if type(ident) is not int or _RUN.fullmatch(str(ident)) is None:
                raise _fail()
            validate_release_run(candidate, source, str(ident))
            return str(ident)
        except Exception:
            raise _fail() from None


def _historical_seed(
    client: GitHubEvidenceTransport, historical_run: str, stamp: datetime
) -> tuple[bytes, str]:
    """Authenticate independently, without forcing original R186 SHA=current main."""
    if type(historical_run) is not str or _RUN.fullmatch(historical_run) is None:
        raise _fail()
    record = client.get_json(f"actions/runs/{historical_run}")
    if type(record) is not dict:
        raise _fail()
    historical_sha = record.get("head_sha")
    if type(historical_sha) is not str or _SHA.fullmatch(historical_sha) is None:
        raise _fail()
    observed._verify_run(client, historical_sha, historical_run, stamp)
    observed._verify_job(client, historical_sha, historical_run, retained_bridge._STEPS)
    raw = observed._download_artifact(
        client,
        historical_sha,
        historical_run,
        artifact_name=retained_bridge._ARTIFACT,
        member_name=retained_bridge._MEMBER,
        member_limit=48_000,
        archive_limit=65_536,
    )
    authenticator = retained_bridge._LiveGitHubCustodyAuthenticator(
        client, historical_sha, historical_run, raw
    )
    adapters.verify_custody_seed(
        raw,
        observation_run_id=historical_run,
        observer_source_sha=historical_sha,
        authenticator=authenticator,
    )
    observed._verify_run(client, historical_sha, historical_run, stamp)
    observed._verify_job(client, historical_sha, historical_run, retained_bridge._STEPS)
    return raw, historical_sha


def attest_runner(
    main_sha: str,
    pair_run: str,
    apply_run: str,
    target_release_run: str,
    historical_run: str,
    controller_ref: str,
    worker_ref: str,
    folder_arg: str,
    *,
    github: GitHubEvidenceTransport,
    release_catalog: ReleaseCatalog,
    now: datetime | None = None,
) -> None:
    """Materialize three files only after complete authenticated provenance."""
    try:
        folder = Path(folder_arg)
        stamp = datetime.now(timezone.utc) if now is None else now  # noqa: UP017
        if (
            github is None
            or release_catalog is None
            or stamp.tzinfo is None
            or not folder.is_absolute()
            or not all(
                type(value) is str and _RUN.fullmatch(value) is not None
                for value in (pair_run, apply_run, target_release_run, historical_run)
            )
            or type(main_sha) is not str
            or _SHA.fullmatch(main_sha) is None
            or not int(historical_run) < int(pair_run) < int(apply_run)
        ):
            raise _fail()
        # Before any materialization, reject an interrupted predecessor or
        # injected/symlinked output. The later O_EXCL write remains mandatory
        # for TOCTOU resistance; no preexisting V2 can mix with fresh R188.
        if any(
            os.path.lexists(folder / name)
            for name in (
                "boca-retained-observation.receipt",
                "retained-proof.json",
                "current-pair-v2.receipt",
            )
        ):
            raise _fail()
        # R244 target manifests and pair observation already authenticated by
        # distinct protected steps. Re-verify exact bytes before reading old
        # provenance; never derive an identity from a raw form field.
        candidate = CandidateRelease(main_sha, target_release_run, controller_ref, worker_ref)
        candidate.validate()
        target_ctrl = release_bridge._runner_input(str(folder / "boca-release-manifest.json"))
        target_worker = release_bridge._runner_input(
            str(folder / "boca-browser-release-manifest.json")
        )
        target_proof = release_bridge._runner_input(str(folder / "runner-proof.json"))
        release_bridge.verify_bundled_release(target_proof, target_ctrl, target_worker, candidate)
        pair_raw = observed._runner_input(str(folder / "boca-pair-observation.receipt"))
        pair_proof = observed._runner_input(str(folder / "observation-proof.json"))
        past = observed.verify_bundled_observation(
            pair_proof, pair_raw, main_sha, pair_run, apply_run, target_release_run
        )
        coordinates = PairCoordinates(
            attempt_id=apply_run,
            observation_run_id=pair_run,
            old_attempt_id=str(past["old_attempt_id"]),
            old_source_sha=str(past["old_source_sha"]),
            old_controller_id=str(past["controller_id"]),
            old_worker_id=str(past["worker_id"]),
            old_controller_image_id=str(past["controller_image_id"]),
            old_worker_image_id=str(past["worker_image_id"]),
            new_source_sha=main_sha,
            release_run_id=target_release_run,
            controller_ref=controller_ref,
            worker_ref=worker_ref,
        )
        coordinates.validate()
        previous_release = release_catalog.unique_previous_release(coordinates.old_source_sha)
        if previous_release in (historical_run, pair_run, apply_run, target_release_run):
            raise _fail()
        historical_raw, historical_source = _historical_seed(github, historical_run, stamp)
        historical_authenticator = retained_bridge._LiveGitHubCustodyAuthenticator(
            github, historical_source, historical_run, historical_raw
        )
        proof_v2 = current.authenticate_current_pair_v2(
            coordinates,
            previous_release_run_id=previous_release,
            pair_receipt=pair_raw,
            current_main_sha=main_sha,
            historical_receipt=historical_raw,
            historical_observation_run_id=historical_run,
            historical_observer_source_sha=historical_source,
            historical_authenticator=historical_authenticator,
            github=github,
            now=now,
        )
        if release_catalog.unique_previous_release(coordinates.old_source_sha) != previous_release:
            raise _fail()
        observed._verify_run(github, historical_source, historical_run, stamp)
        _main_is_exact(github, main_sha)
        current.verify_current_pair_v2(proof_v2)
        # No output files exist before all GH provenance is authenticated.
        # O_EXCL/0600/fsync protects against path/symlink race or replacement.
        release_bridge._runner_write_proof(
            str(folder / "boca-retained-observation.receipt"), historical_raw
        )
        release_bridge._runner_write_proof(str(folder / "retained-proof.json"), _SENTINEL)
        release_bridge._runner_write_proof(str(folder / "current-pair-v2.receipt"), proof_v2)
    except Exception:
        raise _fail() from None


def runner_main(args: Sequence[str], *, now: datetime | None = None) -> int:
    try:
        if len(args) != 8 or not os.environ.get("GH_TOKEN"):
            raise _fail()
        github = GitHubRestReleaseCatalog(os.environ["GH_TOKEN"])
        attest_runner(*args, github=github, release_catalog=github, now=now)
    except Exception:
        print("BOCA_CURRENT_PAIR_V2_AUTH state=NO_GO host_authorized=false")
        return 3
    print("BOCA_CURRENT_PAIR_V2_AUTH state=VERIFIED host_authorized=false")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(runner_main(sys.argv[1:]))
