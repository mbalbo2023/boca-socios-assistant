"""Read the current dispatch's terminal or early worker capture without Docker effects."""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from boca_socios import host_boca_cutover_cli as cli
from boca_socios import host_boca_cutover_receipt as terminal
from boca_socios import worker_start_receipt as custody
from boca_socios.host_boca_cutover import CandidateEvidence
from boca_socios.worker_start_capture import is_capture_result

_READ_MODE = "cutover-a-capture-readback-v3"
_APPLY_MODE = "cutover-a-dispatch-v3"
_BINDING = "BOCA_CUTOVER_A_DISPATCH_BINDING_SHA256"
_MAX_LINE = 320
_REPO = "https://github.com/mbalbo2023/boca-socios-assistant"


def _bound(token: str, approved: str, bundle: str) -> cli.CutoverInvocation:
    invocation = cli.CutoverInvocation.decode(token)
    if (
        not invocation.dispatch_v3
        or invocation.go_binding_sha256 != approved
        or invocation.bundle_sha256 != bundle
    ):
        raise ValueError("unverified V3 binding")
    return invocation


def _prefix(run: str, sha: str) -> str:
    if not re.fullmatch(r"[1-9][0-9]{0,19}", run) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("invalid dispatch coordinates")
    return f"BOCA_WORKER_CAPTURE_V1 run={run} sha={sha} observation="


def run_host(encoded: str, *, approved_go_binding_sha256: str) -> int:
    """Read only existing same-attempt markers, without consulting Docker or executing work."""
    try:
        plan = _bound(encoded, approved_go_binding_sha256, cli._bundle_digest()).plan
        # Read the same immutable terminal first, even if APPLY's stdout was lost.
        record = terminal.read_persisted_record(plan)
        if record is not None:
            candidate = record.candidate_evidence()
            if candidate is not None:
                print(
                    f"BOCA_CANDIDATE_FAILURE_V1 run={plan.attempt_id} sha={plan.target_sha} "
                    + candidate.wire()
                )
                return 0
            if record.worker_stderr_observation is not None:
                # The canonical reader already checked the pre-compensation worker marker.
                print(_prefix(plan.attempt_id, plan.target_sha) + record.worker_stderr_observation)
                return 0
            if record.candidate_id is not None or record.state == "ACCEPTED":
                return 3  # No worker-start capture belongs to a later candidate acceptance.
        # A worker exit can leave a valid capture before its final typed receipt exists.
        cid, observation = custody.read_before_cleanup(plan)
        if (
            type(cid) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", cid)
            or cid == plan.legacy_id
            or type(observation) is not str
            or not is_capture_result(observation)
        ):
            return 3
        print(_prefix(plan.attempt_id, plan.target_sha) + observation)
        return 0
    except Exception:
        # Private receipt errors, partial writes and SSH failures never become output.
        return 3


def verify(raw: bytes, run: str, sha: str) -> str:
    """Rebuild the public line only from a closed category and the runner's coordinates."""
    prefix = _prefix(run, sha).encode("ascii")
    if not 0 < len(raw) <= _MAX_LINE or not raw.endswith(b"\n"):
        raise ValueError("invalid observation envelope")
    candidate_prefix = f"BOCA_CANDIDATE_FAILURE_V1 run={run} sha={sha} ".encode("ascii")
    if raw.startswith(candidate_prefix):
        candidate = CandidateEvidence.parse(raw[len(candidate_prefix) : -1].decode("ascii"))
        return (
            f"BOCA_CUTOVER_CANDIDATE_READBACK state=NO_GO receipt=VERIFIED "
            f"phase=ACCEPT_CANDIDATE {candidate.wire()} runtime=UNVERIFIED retry=NO_GO "
            f"[run {run}]({_REPO}/actions/runs/{run}) [commit {sha}]({_REPO}/commit/{sha})"
        )
    if not raw.startswith(prefix):
        raise ValueError("invalid observation envelope")
    try:
        observation = raw[len(prefix) : -1].decode("ascii")
    except UnicodeError:
        raise ValueError("invalid observation category") from None
    if not is_capture_result(observation):
        raise ValueError("invalid observation category")
    return (
        f"BOCA_WORKER_CAPTURE_READBACK state=NO_GO receipt=VERIFIED worker_stderr_observation={observation} "
        "worker_internal_cause=UNKNOWN cleanup=UNVERIFIED retry=NO_GO "
        f"[run {run}]({_REPO}/actions/runs/{run}) [commit {sha}]({_REPO}/commit/{sha})"
    )


def command(
    mode: str, environment: Mapping[str, str], *, read_bounded: Callable[[Path, int], bytes]
) -> str:
    """Runner-only builder shared with the original apply. Never log the resulting command."""
    if mode not in (_APPLY_MODE, _READ_MODE):
        raise ValueError("invalid dispatch operation")
    directory = Path(environment["RUNNER_TEMP"])
    token = read_bounded(directory / "boca-cutover-a-invocation.token", 5463)
    approval = read_bounded(directory / "boca-cutover-a-approved.digest", 65)
    if not token.endswith(b"\n") or not approval.endswith(b"\n"):
        raise ValueError("incomplete dispatch binding")
    encoded = token[:-1].decode("ascii")
    approved = approval[:-1].decode("ascii")
    archive = read_bounded(directory / "boca-cutover-a-review.pyz", cli.MAX_BUNDLE_BYTES)
    digest = hashlib.sha256(archive).hexdigest()
    plan = _bound(encoded, approved, digest).plan
    if (
        plan.attempt_id != environment["GITHUB_RUN_ID"]
        or plan.target_sha != environment["GITHUB_SHA"]
        or plan.target_sha != environment["BOCA_SOURCE_SHA"]
    ):
        raise ValueError("dispatch belongs to a different run or source")
    bootstrap = Path("scripts/boca_protected_memfd_bootstrap.py").read_text(encoding="utf-8")
    argv = ["python3", "-c", bootstrap, digest, mode, encoded]
    return _BINDING + "=" + shlex.quote(approved) + " " + shlex.join(argv)


def main() -> int:
    try:
        if sys.argv[1:] != ["verify"]:
            return 1
        raw = sys.stdin.buffer.read(_MAX_LINE + 1)
        print(verify(raw, os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_SHA"]))
        return 0
    except Exception:
        # The caller emits a fixed NO_GO after checking the entire SSH + reader pipeline.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
