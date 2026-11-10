"""The runner may project a category from its own reviewed attempt only."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_cutover_a_go as runner  # noqa: E402

RUN = "42800000123"
SHA = "a" * 40
SIGNATURE = "EMPTY.EXITED.EARLY_LT_5S.NOT_RUN"


@pytest.mark.parametrize(
    ("observed", "run", "sha", "source", "rc", "signature", "visible"),
    [
        ("PERMISSION_ERROR", RUN, SHA, SHA, "3", SIGNATURE, True),
        ("EMPTY", RUN, SHA, SHA, "3", SIGNATURE, True),
        ("PRIVATE_CANARY", RUN, SHA, SHA, "3", SIGNATURE, False),
        ("PERMISSION_ERROR", "42800000124", SHA, SHA, "3", SIGNATURE, False),
        ("PERMISSION_ERROR", RUN, "b" * 40, SHA, "3", SIGNATURE, False),
        ("PERMISSION_ERROR", RUN, SHA, "b" * 40, "3", SIGNATURE, False),
        ("PERMISSION_ERROR", RUN, SHA, SHA, "255", SIGNATURE, False),
        ("PERMISSION_ERROR", RUN, SHA, SHA, "3", "", False),
    ],
)
def test_runner_capture_is_closed_and_bound_to_the_failed_ssh(
    tmp_path: Path,
    observed: str,
    run: str,
    sha: str,
    source: str,
    rc: str,
    signature: str,
    visible: bool,
) -> None:
    environment = {
        "BOCA_OPERATION": "cutover-a-apply",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "BOCA_CUTOVER_A_SSH_RC": rc,
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_RUN_ID": RUN,
        "GITHUB_SHA": SHA,
        "BOCA_SOURCE_SHA": source,
    }
    signature_field = f" signature={signature}" if signature else ""
    (tmp_path / runner.HOST_RECEIPT_NAME).write_text(
        "BOCA_CUTOVER_A_WORKER_FAILURE primary=HEALTH_EXITED compensation=VERIFIED "
        f"exit_code=1 oom=NO{signature_field} stderr_observation={observed} run={run} sha={sha}\n"
        "BOCA_CUTOVER_A_FAILURE_PHASE phase=PREPARE_WORKER\n"
        "BOCA_CUTOVER_A_HOST state=NO_GO receipt=RECORDED runtime=UNVERIFIED\n",
        encoding="ascii",
    )
    result = runner.classify_cutover_ssh_failure(environment)
    if visible:
        assert f"worker_stderr_observation_claim={observed}" in result
    else:
        assert "worker_stderr_observation_claim=" not in result
        assert "worker_primary_claim=UNVERIFIED" in result
    assert "PRIVATE_CANARY" not in result
    assert "worker_internal_cause=UNKNOWN" in result
    assert "terminal=UNVERIFIED no_retry=true" in result
