"""R84 one-first-dispatch gate; synthetic GitHub REST only, never host or network."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_release_dispatch import MAX_RESPONSE_BYTES  # noqa: E402

SCRIPT = ROOT / "scripts/check_worker_preflight_dispatch.py"
WORKFLOW = ROOT / ".github/workflows/boca-first-deploy.yml"
SHA = "f" * 40
OTHER_SHA = "e" * 40
RUN = "42350000001"
TITLE = "BOCA-R84-WORKER-PREFLIGHT-ONCE"


def _checker():
    assert SCRIPT.is_file(), "R84 cross-run preflight admission checker is missing"
    spec = importlib.util.spec_from_file_location("check_worker_preflight_dispatch", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(*, run_id: int = int(RUN), title: str = TITLE, source: str = SHA, **overrides):
    record = {
        "id": run_id,
        "display_title": title,
        "event": "workflow_dispatch",
        "head_sha": source,
        "head_branch": "main",
        "run_attempt": 1,
        "actor": {"login": "mbalbo2023"},
        "repository": {"full_name": "mbalbo2023/boca-socios-assistant"},
        "path": ".github/workflows/boca-first-deploy.yml",
    }
    return {**record, **overrides}


def _history(*records, total: int | None = None):
    return {"total_count": len(records) if total is None else total, "workflow_runs": list(records)}


def test_worker_preflight_run_name_is_unique_and_protected_before_ssh() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert workflow.count(f"'{TITLE}'") == 1
    assert "inputs.operation == 'cutover-a-worker-preflight' && '" + TITLE + "'" in workflow
    one_shot = workflow.index("- name: Require one unique R84 worker preflight dispatch before SSH")
    ssh = workflow.index("- name: Preflight exact dual GHCR image and rootless worker boundary")
    assert one_shot < ssh
    segment = workflow[one_shot:ssh]
    assert "if: inputs.operation == 'cutover-a-worker-preflight'" in segment
    assert "github.sha" not in segment.lower() or "GITHUB_SHA" in segment
    assert "python -m scripts.check_worker_preflight_dispatch" in segment
    assert "pulls?state=open&per_page=1" in segment
    assert "head_sha=$GITHUB_SHA&per_page=100" in segment
    assert "id: cutover_worker_preflight_dispatch_gate" in segment


def test_receipt_verifier_does_not_claim_host_failure_if_ssh_never_started(
    tmp_path: Path,
) -> None:
    """A pre-SSH denial is not a host failure; exercise actual runner Bash."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    marker = (
        "      - name: Require exact Boca rootless worker preflight receipt and bounded cleanup\n"
    )
    assert workflow.count(marker) == 1
    step = workflow.split(marker, 1)[1].split("\n      - name:", 1)[0]
    assert "steps.cutover_worker_preflight_dispatch_gate.outcome" in step
    body = textwrap.dedent(step.split("        run: |\n", 1)[1])
    environment = dict(os.environ)
    environment.update(
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"),
        RUNNER_TEMP=str(tmp_path),
        BOCA_PREFLIGHT_HOST_OUTCOME="skipped",
        BOCA_PREFLIGHT_DISPATCH_OUTCOME="failure",
    )
    result = subprocess.run(  # noqa: S603 - local runner Bash only, no SSH
        ("bash", "-c", body),  # noqa: S607
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=12,
        check=False,
    )
    assert result.returncode != 0
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert summary == (
        "BOCA_CUTOVER_WORKER_PREFLIGHT state=NO_GO dispatch_gate=NOT_PASSED "
        "ssh=NOT_ATTEMPTED_BY_RUN no_retry=1\n"
    )


def test_first_run_with_other_boca_dispatches_on_same_sha_is_accepted() -> None:
    checker = _checker()
    history = _history(
        _run(title="Boca first deploy", run_id=42349999999),
        _run(),
    )
    checker.validate_dispatch_history(history, [], SHA, RUN)


@pytest.mark.parametrize(
    "history,open_prs",
    [
        (_history(_run(), _run(run_id=42350000002)), []),
        (_history(_run(run_id=42350000002)), []),
        (_history(_run(), total=2), []),
        (_history(_run(), total=101), []),
        (_history(_run(), _run()), []),
        (_history(_run(run_attempt=2)), []),
        (_history(_run(actor={"login": "foreign"})), []),
        (_history(_run(repository={"full_name": "other/app"})), []),
        (_history(_run(head_branch="feature/other")), []),
        (_history(_run(event="push")), []),
        (_history(_run(path=".github/workflows/foreign.yml")), []),
        (_history(_run(head_sha=OTHER_SHA)), []),
        (_history(_run()), [{"number": 123}]),
        (_history(_run()), {}),
    ],
)
def test_replay_missing_self_truncated_foreign_or_open_pr_is_no_go(history, open_prs) -> None:
    checker = _checker()
    with pytest.raises(checker.DispatchError):
        checker.validate_dispatch_history(history, open_prs, SHA, RUN)


def test_preflight_future_fix_forward_sha_is_not_blocked_by_historical_sha() -> None:
    checker = _checker()
    # GH REST head_sha filter returns only records for the requested new SHA.
    checker.validate_dispatch_history(_history(_run(source=OTHER_SHA)), [], OTHER_SHA, RUN)


def test_fails_closed_if_gh_rest_ignores_head_sha_filter() -> None:
    checker = _checker()
    with pytest.raises(checker.DispatchError):
        checker.validate_dispatch_history(
            _history(_run(), _run(title="Boca first deploy", source=OTHER_SHA, run_id=3)),
            [],
            SHA,
            RUN,
        )


def test_bounded_json_reader_rejects_duplicate_fields_symlinks_and_oversize(
    tmp_path: Path,
) -> None:
    checker = _checker()
    file = tmp_path / "history.json"
    file.write_text('{"total_count":1,"total_count":1,"workflow_runs":[]}', encoding="utf-8")
    with pytest.raises(checker.DispatchError):
        checker.load_history(file)
    file.write_bytes(b"x" * (MAX_RESPONSE_BYTES + 1))
    with pytest.raises(checker.DispatchError):
        checker.load_history(file)
    file.write_text(json.dumps(_history(_run())), encoding="utf-8")
    symlink = tmp_path / "redirect.json"
    symlink.symlink_to(file)
    with pytest.raises(checker.DispatchError):
        checker.load_history(symlink)


def test_cli_never_claims_pass_when_history_missing(tmp_path: Path, capsys) -> None:
    checker = _checker()
    missing = tmp_path / "missing.json"
    prs = tmp_path / "prs.json"
    prs.write_text("[]", encoding="utf-8")
    assert checker.main([str(missing), str(prs), SHA, RUN]) == 1
    out, _err = capsys.readouterr()
    assert "PASS" not in out


def _protected_step_body() -> str:
    """Extract the actual reviewed runner Bash, never the subsequent SSH step."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    marker = "      - name: Require one unique R84 worker preflight dispatch before SSH\n"
    assert workflow.count(marker) == 1
    step = workflow.split(marker, 1)[1].split("\n      - name:", 1)[0]
    body = textwrap.dedent(step.split("        run: |\n", 1)[1])
    assert "ssh " not in body and "docker " not in body
    return body


def _protected_step_offline(
    tmp_path: Path, *, additional: tuple[dict[str, object], ...] = (), prs: list | None = None
) -> subprocess.CompletedProcess[str]:
    """Execute real workflow Bash with an allowlisted fake GitHub CLI."""
    reply = {
        "history": _history(_run(), *additional),
        "prs": [] if prs is None else prs,
    }
    response_file = tmp_path / "gh-rest-fixture.json"
    response_file.write_text(json.dumps(reply), encoding="utf-8")
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "args=sys.argv[1:]\n"
        "assert args[0]=='api'\n"
        "url=args[1]\n"
        "repo='repos/mbalbo2023/boca-socios-assistant'\n"
        "with open(os.environ['BOCA_TEST_R84_GH_FIXTURE'],encoding='utf-8') as f: data=json.load(f)\n"
        "if url == repo+'/pulls?state=open&per_page=1':\n"
        "    assert len(args)==2\n"
        "    print(json.dumps(data['prs']))\n"
        "elif url == repo+'/actions/workflows/boca-first-deploy.yml/runs?event=workflow_dispatch&head_sha='+os.environ['GITHUB_SHA']+'&per_page=100':\n"
        "    assert len(args)==4 and args[2]=='--jq'\n"
        "    assert 'total_count' in args[3] and 'display_title' in args[3]\n"
        "    assert 'repository:{full_name:.repository.full_name}' in args[3]\n"
        "    print(json.dumps(data['history']))\n"
        "else:\n"
        "    raise SystemExit('unauthorized gh request')\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o700)
    environment = dict(os.environ)
    environment.update(
        GITHUB_REPOSITORY="mbalbo2023/boca-socios-assistant",
        GITHUB_SHA=SHA,
        GITHUB_RUN_ID=RUN,
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"),
        RUNNER_TEMP=str(tmp_path),
        GH_TOKEN="local-synthetic-no-permissions",
        BOCA_TEST_R84_GH_FIXTURE=str(response_file),
        PATH=f"{tmp_path}:{os.environ['PATH']}",
    )
    return subprocess.run(  # noqa: S603 - local Bash, fake gh, no SSH/Docker/network
        ("bash", "-c", _protected_step_body()),  # noqa: S607
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=12,
        check=False,
    )


def test_actual_runner_bash_accepts_only_first_preflight_without_host_calls(
    tmp_path: Path,
) -> None:
    result = _protected_step_offline(tmp_path)
    assert result.returncode == 0, (result.stdout, result.stderr)
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert (
        summary
        == "BOCA_WORKER_PREFLIGHT_DISPATCH_PASS same_sha_dispatches=1 open_prs=0 no_retry=1\n"
    )


def test_actual_runner_bash_denies_second_same_sha_before_host_calls(tmp_path: Path) -> None:
    repeated = _run(run_id=int(RUN) + 1, status="completed", conclusion="failure")
    result = _protected_step_offline(tmp_path, additional=(repeated,))
    assert result.returncode != 0
    summary = tmp_path / "summary.md"
    assert not summary.exists() or "PASS" not in summary.read_text(encoding="utf-8")


def test_actual_runner_bash_denies_open_pull_request_before_host_calls(tmp_path: Path) -> None:
    result = _protected_step_offline(tmp_path, prs=[{"number": 426}])
    assert result.returncode != 0
    summary = tmp_path / "summary.md"
    assert not summary.exists() or "PASS" not in summary.read_text(encoding="utf-8")
