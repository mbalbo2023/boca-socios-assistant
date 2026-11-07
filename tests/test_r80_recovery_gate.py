"""R80 one-time pre-SSH gate: offline GitHub API evidence and replay attacks."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts" / "check_worker_recovery_dispatch.py"
WORKFLOW = ROOT / ".github" / "workflows" / "boca-first-deploy.yml"
REPO = "mbalbo2023/boca-socios-assistant"
WORKFLOW_PATH = ".github/workflows/boca-first-deploy.yml"
RELEASE_PATH = ".github/workflows/release-image.yml"
FAILED_ID = 42329475083
FAILED_SOURCE = "92624ed6b7e75c6010f59670c866df00a29766dd"
WITNESS_ID = 42337103473
WITNESS_SOURCE = "7dc0b477479aec118ed4e46edd1ffb4541558dbc"
PRIOR_ID = 42339451485  # Physical #804: no host recovery step executed.
PRIOR_SOURCE = "d9100c6c4666c61ba66fbbefa48e61102a20ce5d"
PRIOR_JOB_ID = 128303677116
CURRENT_ID = 99999999999
CURRENT_SOURCE = "a" * 40
R79_TITLE = "BOCA-R79-WORKER-RECOVER-ONCE"
R80_TITLE = "BOCA-R80-WORKER-RECOVER-ONCE"


def _run_record(
    run_id: int,
    source: str,
    result: str,
    *,
    path: str = WORKFLOW_PATH,
    title: str = "Boca first deploy",
) -> dict[str, Any]:
    return {
        "id": run_id,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": result,
        "run_attempt": 1,
        "head_branch": "main",
        "head_sha": source,
        "path": path,
        "display_title": title,
        "actor": {"login": "mbalbo2023"},
        "repository": {"full_name": REPO},
    }


def _history_item(run_id: int, title: str, sha: str) -> dict[str, Any]:
    return {
        "id": run_id,
        "display_title": title,
        "event": "workflow_dispatch",
        "head_sha": sha,
        "head_branch": "main",
        "run_attempt": 1,
        "actor": {"login": "mbalbo2023"},
    }


def _step(number: int, name: str, conclusion: str) -> dict[str, Any]:
    return {"number": number, "name": name, "status": "completed", "conclusion": conclusion}


def _physical_804_steps() -> list[dict[str, Any]]:
    """Actual 154 REST steps: 1..152,304,305; GitHub omits 153..303."""
    permitted_successes = {
        1: "Set up job",
        5: "Require verified protected environment and matching main commit",
        6: "Reject legacy install routes without same-lease Boca-only postflight",
        7: "Checkout exact main commit without persisted credentials",
        8: "Confirm current main HEAD before host access",
        19: "Hash reviewed Boca Compose file",
        36: "Configure pinned SSH host key and dedicated identity",
        304: "Post Checkout exact main commit without persisted credentials",
        305: "Complete job",
    }
    numbers = [*range(1, 153), 304, 305]
    steps = [
        _step(
            number,
            permitted_successes.get(number, f"Skipped phase {number}"),
            "success" if number in permitted_successes else "skipped",
        )
        for number in numbers
    ]
    for number, name, result in (
        (37, "Require exact 795/802 evidence and zero open PRs before recovery SSH", "failure"),
        (38, "Recover only the stopped exact 795 worker probe under Boca lease", "skipped"),
        (39, "Require exact terminal worker recovery receipt on every outcome", "failure"),
    ):
        steps[number - 1] = _step(number, name, result)
    return steps


def _evidence() -> dict[str, Any]:
    return {
        "prs": [],
        "failed": _run_record(FAILED_ID, FAILED_SOURCE, "failure"),
        "witness": _run_record(WITNESS_ID, WITNESS_SOURCE, "success"),
        "release": _run_record(42329201039, FAILED_SOURCE, "success", path=RELEASE_PATH),
        "history": {
            "total_count": 3,
            "workflow_runs": [
                _history_item(WITNESS_ID, "Boca first deploy", WITNESS_SOURCE),
                _history_item(PRIOR_ID, R79_TITLE, PRIOR_SOURCE),
                _history_item(CURRENT_ID, R80_TITLE, CURRENT_SOURCE),
            ],
        },
        "prior": _run_record(PRIOR_ID, PRIOR_SOURCE, "failure", title=R79_TITLE),
        "jobs": {
            "total_count": 3,
            "jobs": [
                {
                    "id": PRIOR_JOB_ID,
                    "name": "approved-boca-manual-operation",
                    "run_id": PRIOR_ID,
                    "status": "completed",
                    "conclusion": "failure",
                    "steps": _physical_804_steps(),
                },
                {
                    "id": PRIOR_JOB_ID + 1,
                    "name": "first-deploy-runtime-smoke",
                    "run_id": PRIOR_ID,
                    "status": "completed",
                    "conclusion": "skipped",
                    "steps": [],
                },
                {
                    "id": PRIOR_JOB_ID + 2,
                    "name": "first-deploy-pr-validation",
                    "run_id": PRIOR_ID,
                    "status": "completed",
                    "conclusion": "skipped",
                    "steps": [],
                },
            ],
        },
    }


def _check(
    tmp_path: Path,
    evidence: dict[str, Any],
    *,
    current_id: int = CURRENT_ID,
    current_sha: str = CURRENT_SOURCE,
    raw_overrides: dict[str, bytes] | None = None,
) -> subprocess.CompletedProcess[str]:
    paths: list[str] = []
    for key in ("prs", "failed", "witness", "release", "history", "prior", "jobs"):
        path = tmp_path / f"{key}.json"
        if raw_overrides is not None and key in raw_overrides:
            path.write_bytes(raw_overrides[key])
        else:
            path.write_text(json.dumps(evidence[key]), encoding="utf-8")
        paths.append(str(path))
    env = dict(os.environ)
    env.update(GITHUB_RUN_ID=str(current_id), GITHUB_SHA=current_sha)
    return subprocess.run(  # noqa: S603 - local Python gate, no GitHub/host I/O
        (sys.executable, str(GATE), *paths),  # noqa: S607
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


@pytest.mark.parametrize("reference", ["", "@main", "@refs/heads/main"])
def test_exact_r80_followup_accepts_authentic_pre_ssh_failure_with_rest_bare_paths(
    tmp_path: Path, reference: str
) -> None:
    evidence = _evidence()
    for key in ("failed", "witness", "prior"):
        evidence[key]["path"] = WORKFLOW_PATH + reference
    evidence["release"]["path"] = RELEASE_PATH + reference
    result = _check(tmp_path, evidence)
    assert result.returncode == 0, (result.stdout, result.stderr)


def _change(evidence: dict[str, Any], path: tuple[str | int, ...], value: Any) -> None:
    node: Any = evidence
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("failed", "id"), 1),
        (("failed", "head_sha"), WITNESS_SOURCE),
        (("failed", "conclusion"), "success"),
        (("failed", "status"), "in_progress"),
        (("failed", "event"), "push"),
        (("failed", "run_attempt"), 2),
        (("failed", "head_branch"), "feature/unsafe"),
        (("failed", "actor", "login"), "other"),
        (("failed", "repository", "full_name"), "other/repo"),
        (("witness", "id"), 1),
        (("witness", "head_sha"), FAILED_SOURCE),
        (("witness", "conclusion"), "failure"),
        (("witness", "status"), "in_progress"),
        (("witness", "run_attempt"), 2),
        (("release", "id"), 1),
        (("release", "head_sha"), WITNESS_SOURCE),
        (("release", "conclusion"), "failure"),
        (("prior", "id"), PRIOR_ID + 1),
        (("prior", "head_sha"), FAILED_SOURCE),
        (("prior", "conclusion"), "success"),
        (("prior", "conclusion"), "cancelled"),
        (("prior", "status"), "in_progress"),
        (("prior", "event"), "push"),
        (("prior", "run_attempt"), 2),
        (("prior", "head_branch"), "feature/unsafe"),
        (("prior", "display_title"), "Boca first deploy"),
        (("prior", "actor", "login"), "other"),
        (("prior", "repository", "full_name"), "other/repo"),
    ],
)
def test_changed_historical_provenance_fails_closed(
    tmp_path: Path, path: tuple[str | int, ...], value: Any
) -> None:
    evidence = _evidence()
    _change(evidence, path, value)
    result = _check(tmp_path, evidence)
    assert result.returncode != 0, f"accepted forged provenance: {path}={value!r}"


@pytest.mark.parametrize(
    ("target", "path"),
    [
        ("failed", WORKFLOW_PATH + "@feature/r80"),
        ("witness", WORKFLOW_PATH + "@refs/tags/v1"),
        ("prior", WORKFLOW_PATH + "@refs/heads/feature"),
        ("release", RELEASE_PATH + "@other"),
        ("failed", "../boca-first-deploy.yml"),
        ("prior", ".github/workflows/other.yml"),
        ("witness", WORKFLOW_PATH + "/injected"),
    ],
)
def test_wrong_workflow_path_or_untrusted_ref_is_never_authority(
    tmp_path: Path, target: str, path: str
) -> None:
    evidence = _evidence()
    evidence[target]["path"] = path
    result = _check(tmp_path, evidence)
    assert result.returncode != 0, f"accepted workflow path {path}"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("history", "total_count"), 101),
        (("history", "total_count"), 2),
        (("history", "total_count"), True),
        (("history", "workflow_runs", 1, "id"), PRIOR_ID + 1),
        (("history", "workflow_runs", 1, "display_title"), "Boca first deploy"),
        (("history", "workflow_runs", 1, "head_sha"), FAILED_SOURCE),
        (("history", "workflow_runs", 1, "run_attempt"), 2),
        (("history", "workflow_runs", 1, "actor", "login"), "other"),
        (("history", "workflow_runs", 2, "id"), CURRENT_ID + 1),
        (("history", "workflow_runs", 2, "display_title"), "Boca first deploy"),
        (("history", "workflow_runs", 2, "head_sha"), PRIOR_SOURCE),
        (("history", "workflow_runs", 2, "run_attempt"), 2),
        (("history", "workflow_runs", 2, "event"), "push"),
        (("history", "workflow_runs", 2, "head_branch"), "feature/unsafe"),
        (("history", "workflow_runs", 2, "actor", "login"), "other"),
    ],
)
def test_replay_history_and_current_identity_mismatch_block_r80(
    tmp_path: Path, path: tuple[str | int, ...], value: Any
) -> None:
    evidence = _evidence()
    _change(evidence, path, value)
    result = _check(tmp_path, evidence)
    assert result.returncode != 0, f"accepted replay/history mismatch: {path}"


@pytest.mark.parametrize("prior", [True, False])
def test_second_r79_or_r80_marker_blocks_new_recovery(tmp_path: Path, prior: bool) -> None:
    evidence = _evidence()
    item = _history_item(
        CURRENT_ID + 1,
        R79_TITLE if prior else R80_TITLE,
        PRIOR_SOURCE if prior else CURRENT_SOURCE,
    )
    evidence["history"]["workflow_runs"].append(item)
    evidence["history"]["total_count"] += 1
    result = _check(tmp_path, evidence)
    assert result.returncode != 0


def test_unrelated_dispatch_does_not_consume_the_one_r80_allowance(tmp_path: Path) -> None:
    evidence = _evidence()
    evidence["history"]["workflow_runs"].append(
        _history_item(CURRENT_ID + 1, "Boca first deploy", CURRENT_SOURCE)
    )
    evidence["history"]["total_count"] += 1
    result = _check(tmp_path, evidence)
    assert result.returncode == 0, (result.stdout, result.stderr)


@pytest.mark.parametrize("bad_prs", [[{"number": 421, "draft": True}], {}, None])
def test_open_pr_or_invalid_pr_inventory_prevents_host_access(tmp_path: Path, bad_prs: Any) -> None:
    evidence = _evidence()
    evidence["prs"] = bad_prs
    result = _check(tmp_path, evidence)
    assert result.returncode != 0


def test_current_run_id_or_exact_main_sha_mismatch_blocks(tmp_path: Path) -> None:
    evidence = _evidence()
    assert _check(tmp_path, evidence, current_id=CURRENT_ID + 1).returncode != 0
    assert _check(tmp_path, evidence, current_sha=PRIOR_SOURCE).returncode != 0


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("jobs", "total_count"), 1),
        (("jobs", "total_count"), 4),
        (("jobs", "total_count"), True),
        (("jobs", "jobs", 0, "id"), PRIOR_JOB_ID + 5),
        (("jobs", "jobs", 0, "run_id"), PRIOR_ID + 1),
        (("jobs", "jobs", 0, "name"), "another deployment"),
        (("jobs", "jobs", 0, "status"), "in_progress"),
        (("jobs", "jobs", 0, "conclusion"), "success"),
        (("jobs", "jobs", 1, "conclusion"), "success"),
        (("jobs", "jobs", 2, "conclusion"), "failure"),
        (("jobs", "jobs", 0, "steps", 36, "conclusion"), "success"),
        (("jobs", "jobs", 0, "steps", 36, "conclusion"), "skipped"),
        (("jobs", "jobs", 0, "steps", 37, "conclusion"), "success"),
        (("jobs", "jobs", 0, "steps", 37, "conclusion"), "failure"),
        (("jobs", "jobs", 0, "steps", 37, "conclusion"), None),
        (("jobs", "jobs", 0, "steps", 38, "conclusion"), "success"),
        (("jobs", "jobs", 0, "steps", 38, "conclusion"), "skipped"),
        (("jobs", "jobs", 0, "steps", 36, "name"), "different gate"),
        (("jobs", "jobs", 0, "steps", 37, "name"), "another host command"),
        (("jobs", "jobs", 0, "steps", 38, "name"), "unknown terminal"),
        (("jobs", "jobs", 0, "steps", 36, "number"), 38),
        (("jobs", "jobs", 0, "steps", 37, "number"), 37),
        (("jobs", "jobs", 0, "steps", 39, "conclusion"), "success"),
        (("jobs", "jobs", 0, "steps", 0, "conclusion"), "failure"),
        (("jobs", "jobs", 0, "steps", 152, "conclusion"), "skipped"),
        (("jobs", "jobs", 0, "steps", 153, "conclusion"), "skipped"),
    ],
)
def test_prior_job_or_any_unexpected_execution_never_certifies_pre_ssh(
    tmp_path: Path, path: tuple[str | int, ...], value: Any
) -> None:
    evidence = _evidence()
    _change(evidence, path, value)
    result = _check(tmp_path, evidence)
    assert result.returncode != 0, f"accepted impossible #804 job evidence: {path}"


@pytest.mark.parametrize("change", ["remove_host_step", "duplicate_host_step", "late_phase"])
def test_job_step_omission_duplication_or_late_host_phase_blocks(
    tmp_path: Path, change: str
) -> None:
    evidence = _evidence()
    steps = evidence["jobs"]["jobs"][0]["steps"]
    if change == "remove_host_step":
        steps.pop(37)
    elif change == "duplicate_host_step":
        steps.insert(38, copy.deepcopy(steps[37]))
    else:
        steps.insert(-2, _step(200, "Unexpected remote effect after pre-SSH failure", "success"))
    result = _check(tmp_path, evidence)
    assert result.returncode != 0


def test_second_host_job_cannot_hide_behind_one_skipped_job(tmp_path: Path) -> None:
    evidence = _evidence()
    evidence["jobs"]["jobs"].append(
        {
            "id": PRIOR_JOB_ID + 3,
            "name": "approved-boca-manual-operation",
            "run_id": PRIOR_ID,
            "status": "completed",
            "conclusion": "success",
            "steps": [
                _step(
                    38,
                    "Recover only the stopped exact 795 worker probe under Boca lease",
                    "success",
                )
            ],
        }
    )
    evidence["jobs"]["total_count"] += 1
    result = _check(tmp_path, evidence)
    assert result.returncode != 0


@pytest.mark.parametrize(
    ("field", "raw"),
    [
        ("prs", b"not-json"),
        ("prior", b"{}{}"),
        ("jobs", b"x" * 32769),
        ("history", b"\xff"),
        ("failed", b""),
    ],
)
def test_untrusted_malformed_truncated_or_oversized_api_data_is_no_go(
    tmp_path: Path, field: str, raw: bytes
) -> None:
    result = _check(tmp_path, _evidence(), raw_overrides={field: raw})
    assert result.returncode != 0


def test_duplicate_json_fields_cannot_forge_authoritative_run_id(tmp_path: Path) -> None:
    evidence = _evidence()
    raw = json.dumps(evidence["prior"], separators=(",", ":")).encode("ascii")
    # The last duplicate happens to be the expected ID; permissive json.loads
    # must not turn this malicious API payload into trusted provenance.
    raw = raw.replace(b'"id":42339451485', b'"id":1,"id":42339451485', 1)
    assert b'"id":1,"id":42339451485' in raw
    result = _check(tmp_path, evidence, raw_overrides={"prior": raw})
    assert result.returncode != 0


def _workflow_presh_script() -> str:
    """Execute the real protected pre-SSH Bash body, never its host step."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    header = "      - name: Require exact 795/802 evidence and zero open PRs before recovery SSH\n"
    assert workflow.count(header) == 1
    block = workflow.split(header, 1)[1].split("\n      - name:", 1)[0]
    return textwrap.dedent(block.split("        run: |\n", 1)[1])


def _shell_gate(tmp_path: Path, evidence: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    """Local fake gh yields projected API JSON, while production Bash/Python run."""
    prefix = f"repos/{REPO}"
    responses = {
        f"{prefix}/pulls?state=open&per_page=1": evidence["prs"],
        (
            f"{prefix}/actions/workflows/boca-first-deploy.yml/runs?"
            "event=workflow_dispatch&created=%3E%3D2026-11-07&per_page=100"
        ): evidence["history"],
        f"{prefix}/actions/runs/{FAILED_ID}": evidence["failed"],
        f"{prefix}/actions/runs/{WITNESS_ID}": evidence["witness"],
        f"{prefix}/actions/runs/42329201039": evidence["release"],
        f"{prefix}/actions/runs/{PRIOR_ID}": evidence["prior"],
        f"{prefix}/actions/runs/{PRIOR_ID}/attempts/1/jobs?per_page=100": evidence["jobs"],
        f"{prefix}/git/ref/heads/main": {
            "ref": "refs/heads/main",
            "object": {"type": "commit", "sha": CURRENT_SOURCE},
        },
    }
    responses_path = tmp_path / "fake-rest-responses.json"
    responses_path.write_text(json.dumps(responses), encoding="utf-8")
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "with open(os.environ['BOCA_TEST_GH_DATA'], encoding='utf-8') as file:\n"
        "    replies=json.load(file)\n"
        "print(json.dumps(replies[sys.argv[2]]))\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o700)
    env = dict(os.environ)
    env.update(
        GITHUB_RUN_ID=str(CURRENT_ID),
        GITHUB_SHA=CURRENT_SOURCE,
        GITHUB_REPOSITORY=REPO,
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"),
        RUNNER_TEMP=str(tmp_path),
        GH_TOKEN="local-offline-fixture",
        BOCA_TEST_GH_DATA=str(responses_path),
        PYTHONPATH="src",
        PATH=f"{tmp_path}:{os.environ['PATH']}",
    )
    return subprocess.run(  # noqa: S603 - local fake gh and production pre-SSH script
        ("bash", "-c", "set -euo pipefail\n" + _workflow_presh_script()),  # noqa: S607
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=12,
        check=False,
    )


def test_protected_workflow_pre_ssh_gate_accepts_real_bare_rest_paths_offline(
    tmp_path: Path,
) -> None:
    result = _shell_gate(tmp_path, _evidence())
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "prior=PRE_SSH_NO_EFFECT" in result.stdout
    assert "host_writes=0" in (tmp_path / "summary.md").read_text(encoding="utf-8")


def test_protected_workflow_pre_ssh_gate_rejects_false_host_skipped_evidence(
    tmp_path: Path,
) -> None:
    evidence = _evidence()
    evidence["jobs"]["jobs"][0]["steps"][37]["conclusion"] = "success"
    result = _shell_gate(tmp_path, evidence)
    assert result.returncode != 0
    assert "state=PASS" not in result.stdout
    summary = tmp_path / "summary.md"
    assert not summary.exists() or "state=PASS" not in summary.read_text(encoding="utf-8")
