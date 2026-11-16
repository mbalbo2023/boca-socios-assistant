"""Offline execution tests for the paired release publisher."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
REPO = "ghcr.io/mbalbo2023/boca-socios-assistant"

FAKE = r"""#!/usr/bin/env python3
import json, os, pathlib, sys
p = pathlib.Path(os.environ["FAKE_DIR"])
cfg = json.loads((p / "config").read_text())
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
if name == "sleep": sys.exit(0)
if name == "gh":
    n = len((p / "calls").read_text().splitlines()) if (p / "calls").exists() else 0
    changed = n >= cfg.get("gh_drift_after", 0)
    if "git/ref/heads/main" in args[1]:
        print(json.dumps({"ref":"refs/heads/main", "object":{"type":"commit", "sha": cfg.get("main", "a" * 40) if changed else "a" * 40}}))
    else:
        run = {"id":123, "head_sha":"a"*40, "head_branch":"main", "event":"workflow_dispatch", "run_attempt":1}
        print(json.dumps({"total_count":cfg.get("count", 1) if changed else 1, "workflow_runs":[run]}))
    sys.exit(0)
if args[:2] == ["image", "inspect"]:
    n = len((p / "calls").read_text().splitlines()) if (p / "calls").exists() else 0
    drift = cfg.get("drift_after", 999) <= n
    role = "browser" if "-browser:" in args[-1] else "controller"
    print(json.dumps({"Id": "sha256:" + (("f" if drift and cfg.get("drift") == "id" else ("b" if role == "browser" else "c")) * 64), "Config":{"Labels":{"org.opencontainers.image.source": "bad" if drift and cfg.get("drift") == "label" else "https://github.com/mbalbo2023/boca-socios-assistant", "org.opencontainers.image.revision":"a"*40}}}))
    sys.exit(0)
if args[0] == "push":
    with (p / "calls").open("a") as f: f.write(args[1] + "\n")
    n = len((p / "calls").read_text().splitlines()) - 1
    event = cfg["events"][n]
    role = "browser" if "-browser:" in args[1] else "controller"
    repo = "ghcr.io/mbalbo2023/boca-socios-assistant" + ("-browser" if role == "browser" else "")
    header = "The push refers to repository [" + repo + "]\n"
    digest = "sha-" + "a"*40 + ": digest: sha256:" + "d"*64 + " size: 42\n"
    if event == "ok": print(header + digest, end="")
    elif event == "ok_progress": print(header + "abcdef123456: Preparing\nabcdef123456: Pushing  3.584kB/3.584kB\nabcdef123456: Pushed\n" + digest, end="")
    elif event == "unknown": print("unknown blob", file=sys.stderr)
    elif event == "mixed": print("denied: auth\nunknown blob", file=sys.stderr)
    elif event == "auth": print("unauthorized", file=sys.stderr)
    elif event == "digest_error": print(header + digest); print("unknown blob", file=sys.stderr)
    elif event == "ambiguous": print("unknown blob"); print("unknown blob", file=sys.stderr)
    elif event == "missing": print(header)
    elif event == "duplicate": print(header + digest + digest)
    elif event == "foreign": print(header.replace(repo, "other/repo") + digest)
    elif event == "success_error": print(header + digest); print("unauthorized", file=sys.stderr)
    elif event == "success_unknown": print(header + digest + "unknown blob\n", end="")
    elif event == "success_auth": print(header + digest + "unauthorized\n", end="")
    elif event == "success_junk": print(header + digest + "secret-canary\n", end="")
    elif event == "success_before_digest": print(header + "unauthorized\n" + digest, end="")
    elif event == "push_bad_progress": print("abcdef123456: Pushing unauthorized"); print("unknown blob", file=sys.stderr)
    elif event == "oversized": print("x" * 1100000)
    elif event == "timeout": sys.exit(124)
    sys.exit(0 if event in ("ok", "ok_progress", "missing", "duplicate", "foreign", "success_error", "oversized", "success_unknown", "success_auth", "success_junk", "success_before_digest") else 1)
sys.exit(2)
"""


@pytest.fixture
def rig(tmp_path):
    for name in ("docker", "gh", "sleep"):
        path = tmp_path / name
        path.write_text(FAKE)
        path.chmod(0o755)
    env = os.environ | {
        "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        "PYTHONPATH": str(ROOT / "src"),
        "FAKE_DIR": str(tmp_path),
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_SHA": SHA,
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REPOSITORY": "mbalbo2023/boca-socios-assistant",
        "BROWSER_IMAGE": REPO + "-browser:sha-" + SHA,
        "CONTROLLER_IMAGE": REPO + ":sha-" + SHA,
    }

    def run(mode, cfg, attempt="1"):
        (tmp_path / "config").write_text(json.dumps(cfg))
        return subprocess.run(  # noqa: S603
            [sys.executable, str(ROOT / "scripts/release_push_guard.py"), mode],
            env=env | {"GITHUB_RUN_ATTEMPT": attempt},
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

    return tmp_path, run


@pytest.mark.parametrize(
    "events,pushes", [(["ok", "ok"], 2), (["unknown", "ok", "ok"], 3), (["ok", "unknown", "ok"], 3)]
)
def test_success_requires_both_verified_digests(rig, events, pushes):
    path, run = rig
    assert run("snapshot", {"events": events}).returncode == 0
    result = run("publish", {"events": events})
    assert result.returncode == 0, result.stderr
    assert len((path / "calls").read_text().splitlines()) == pushes
    assert result.stdout.count("@sha256:") == 2


@pytest.mark.parametrize(
    "events",
    [
        ["unknown", "ok", "unknown"],
        ["unknown", "unknown"],
        ["mixed"],
        ["auth"],
        ["timeout"],
        ["digest_error"],
        ["ambiguous"],
        ["missing"],
        ["duplicate"],
        ["foreign"],
        ["ok", "missing"],
        ["success_error"],
        ["oversized"],
    ],
)
def test_failure_never_yields_partial_references(rig, events):
    path, run = rig
    assert run("snapshot", {"events": events}).returncode == 0
    result = run("publish", {"events": events})
    assert result.returncode != 0
    assert "@sha256:" not in result.stdout
    assert len((path / "calls").read_text().splitlines()) <= len(events)
    assert not list(path.glob("*manifest*.json"))


def test_log_io_failure_prevents_any_push(rig):
    path, run = rig
    assert run("snapshot", {"events": ["ok", "ok"]}).returncode == 0
    (path / "boca-browser-push-1.out").mkdir()
    result = run("publish", {"events": ["ok", "ok"]})
    assert result.returncode != 0
    assert not (path / "calls").exists()
    assert "@sha256:" not in result.stdout


def test_shared_retry_is_exhausted_before_controller_unknown(rig):
    path, run = rig
    events = ["unknown", "ok", "unknown"]
    assert run("snapshot", {"events": events}).returncode == 0
    result = run("publish", {"events": events})
    calls = (path / "calls").read_text().splitlines()
    assert result.returncode != 0
    assert ["-browser:" in call for call in calls] == [True, True, False]
    assert "@sha256:" not in result.stdout
    assert not list(path.glob("*manifest*.json"))


@pytest.mark.parametrize("change", [{"main": "b" * 40}, {"count": 2}])
def test_main_or_dispatch_drift_stops_first_controller_push(rig, change):
    path, run = rig
    events = ["ok", "ok"]
    assert run("snapshot", {"events": events}).returncode == 0
    result = run("publish", {"events": events, "gh_drift_after": 1, **change})
    assert result.returncode != 0
    assert len((path / "calls").read_text().splitlines()) == 1
    assert "@sha256:" not in result.stdout


def test_rerun_attempt_cannot_publish(rig):
    path, run = rig
    assert run("snapshot", {"events": ["ok", "ok"]}).returncode == 0
    result = run("publish", {"events": ["ok", "ok"]}, attempt="2")
    assert result.returncode != 0
    assert not (path / "calls").exists()


@pytest.mark.parametrize(
    "change",
    [
        {"drift": "id", "drift_after": 1},
        {"drift": "label", "drift_after": 1},
        {"main": "b" * 40},
        {"count": 2},
    ],
)
def test_retry_rechecks_provenance_before_second_push(rig, change):
    path, run = rig
    assert run("snapshot", {"events": ["unknown", "ok"]}).returncode == 0
    result = run("publish", {"events": ["unknown", "ok"], "gh_drift_after": 1, **change})
    assert result.returncode != 0
    assert len((path / "calls").read_text().splitlines()) == 1
    assert "@sha256:" not in result.stdout


@pytest.mark.parametrize(
    "event", ["success_unknown", "success_auth", "success_junk", "success_before_digest"]
)
def test_success_status_cannot_hide_extra_diagnostics(rig, event):
    path, run = rig
    assert run("snapshot", {"events": [event]}).returncode == 0
    result = run("publish", {"events": [event]})
    assert result.returncode != 0
    assert len((path / "calls").read_text().splitlines()) == 1
    assert "@sha256:" not in result.stdout
    assert "category=DIGEST" in result.stderr
    assert "secret-canary" not in result.stderr


@pytest.mark.parametrize(
    "event,category",
    [
        ("unknown", "UNKNOWN_BLOB"),
        ("auth", "AUTH"),
        ("mixed", "OTHER"),
        ("timeout", "TIMEOUT"),
        ("missing", "DIGEST"),
    ],
)
def test_push_diagnostics_are_structured_and_redacted(rig, event, category):
    _, run = rig
    events = [event, "ok", "ok"] if event == "unknown" else [event]
    assert run("snapshot", {"events": events}).returncode == 0
    result = run("publish", {"events": events})
    assert f"category={category}" in result.stderr
    import re

    assert re.search(
        r"role=browser attempt=1 rc=\d+ duration_ms=\d+ category=" + category, result.stderr
    )
    assert "unauthorized" not in result.stderr
    assert "unknown blob" not in result.stderr


def test_provenance_and_log_io_have_finite_failure_codes(rig):
    path, run = rig
    assert run("snapshot", {"events": ["ok"]}).returncode == 0
    result = run("publish", {"events": ["ok"], "main": "b" * 40})
    assert "stage=PREPUSH category=PROVENANCE" in result.stderr
    (path / "boca-browser-push-1.out").mkdir()
    result = run("publish", {"events": ["ok"]})
    assert "stage=PUSH category=LOG_IO" in result.stderr


def test_unknown_with_conflicting_progress_does_not_retry(rig):
    path, run = rig
    assert run("snapshot", {"events": ["push_bad_progress", "ok"]}).returncode == 0
    result = run("publish", {"events": ["push_bad_progress", "ok"]})
    assert result.returncode != 0
    assert len((path / "calls").read_text().splitlines()) == 1
    assert "category=OTHER" in result.stderr


def test_normal_docker_layer_progress_is_accepted(rig):
    _, run = rig
    assert run("snapshot", {"events": ["ok_progress", "ok"]}).returncode == 0
    result = run("publish", {"events": ["ok_progress", "ok"]})
    assert result.returncode == 0
    assert result.stdout.count("@sha256:") == 2
