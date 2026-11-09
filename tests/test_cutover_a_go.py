"""Offline GO preflight: wrong run/manifests/ZIP never reaches Boca host."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios.browser_release_manifest import make_browser_manifest
from boca_socios.host_boca_cutover import CutoverPlan
from boca_socios.host_boca_cutover_cli import CutoverInvocation
from boca_socios.release_manifest import make_manifest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_protected_boca_bundle as builder  # noqa: E402
import check_cutover_a_go as go  # noqa: E402


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file(path: Path, raw: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(0o600)
    return path


def _fixture(tmp_path: Path, *, complete_b: bool = True) -> go.GoRequest:
    target_source = "d" * 40
    legacy_source = "a" * 40
    target_image = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "e" * 64
    browser_image = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "f" * 64
    legacy_image = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64
    files = {
        "historical": _file(tmp_path / "legacy-compose.yaml", b"old Boca-only Compose evidence"),
        "base": _file(tmp_path / "target-compose.yaml", b"new Boca-only Compose reviewed"),
        "overlay": _file(tmp_path / "overlay.yaml", b"new Boca-only overlay reviewed"),
        "seccomp": _file(tmp_path / "seccomp.json", b"new Boca-only seccomp reviewed"),
    }
    plan = CutoverPlan(
        attempt_id="41949228860",
        legacy_id="1" * 64,
        legacy_sha=legacy_source,
        legacy_image=legacy_image,
        legacy_compose_sha=_sha(files["historical"].read_bytes()),
        target_sha=target_source,
        target_image=target_image,
        browser_image=browser_image,
        target_compose_sha=_sha(files["base"].read_bytes()),
        overlay_sha=_sha(files["overlay"].read_bytes()),
        seccomp_sha=_sha(files["seccomp"].read_bytes()),
        owner_subject="owner",
    )
    target_run, legacy_run = "41949228846", "41573026189"
    target = make_manifest(target_image, target_source, target_run)
    browser = make_browser_manifest(target_image, browser_image, target_source, target_run)
    legacy = make_manifest(legacy_image, legacy_source, legacy_run)
    manifests = {
        name: _file(tmp_path / (name + ".json"), json.dumps(value).encode("utf-8"))
        for name, value in (("target", target), ("browser", browser), ("legacy", legacy))
    }
    repo_fixture = tmp_path / "reviewed-source"
    for relative in builder.SOURCES + (builder.OPTION_B_SOURCES if complete_b else ()):
        _file(repo_fixture / relative, b"bounded test fixture file: " + relative.encode())
    zip_path = tmp_path / "reviewed-zip.pyz"
    builder.build(repo_fixture, zip_path)
    return go.GoRequest(
        plan=plan,
        github_repository=go.REPOSITORY,
        github_actor=go.OWNER,
        github_ref=go.MAIN,
        github_sha=target_source,
        github_run_id=plan.attempt_id,
        github_run_attempt="1",
        target_release_run_id=target_run,
        legacy_release_run_id=legacy_run,
        target_manifest_path=manifests["target"],
        browser_manifest_path=manifests["browser"],
        legacy_manifest_path=manifests["legacy"],
        historical_compose_path=files["historical"],
        target_compose_path=files["base"],
        overlay_path=files["overlay"],
        seccomp_path=files["seccomp"],
        bundle_path=zip_path,
    )


def _actions_fixture(tmp_path: Path) -> tuple[go.GoRequest, dict[str, str]]:
    source = _fixture(tmp_path / "source")
    workspace = tmp_path / "workspace"
    runner = tmp_path / "runner"
    reviewed_paths = {
        workspace / "compose.beta.yaml": source.target_compose_path,
        workspace / "compose.beta.browser.yaml": source.overlay_path,
        workspace / "docker/seccomp_profile.json": source.seccomp_path,
        runner / "boca-cutover-legacy-compose.yaml": source.historical_compose_path,
        runner / "boca-release-manifest/boca-release-manifest.json": source.target_manifest_path,
        runner
        / "boca-browser-release-manifest/boca-browser-release-manifest.json": source.browser_manifest_path,
        runner
        / "boca-cutover-legacy-manifest/boca-release-manifest.json": source.legacy_manifest_path,
        runner / "boca-cutover-a-review.pyz": source.bundle_path,
    }
    for destination, original in reviewed_paths.items():
        _file(destination, original.read_bytes())
    env = {
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "BOCA_OPERATION": "cutover-a-apply",
        "BOCA_SERVICE": "controller",
        "BOCA_BUDGET": "1.5cpu-1024m-192pids",
        "GITHUB_REPOSITORY": source.github_repository,
        "GITHUB_ACTOR": source.github_actor,
        "GITHUB_REF": source.github_ref,
        "GITHUB_SHA": source.github_sha,
        "GITHUB_RUN_ID": source.github_run_id,
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKSPACE": str(workspace),
        "RUNNER_TEMP": str(runner),
        "BOCA_SOURCE_SHA": source.plan.target_sha,
        "BOCA_LEGACY_CONTROLLER_ID": source.plan.legacy_id,
        "BOCA_LEGACY_SOURCE_SHA": source.plan.legacy_sha,
        "BOCA_LEGACY_IMAGE_REF": source.plan.legacy_image,
        "BOCA_IMAGE_REF": source.plan.target_image,
        "BOCA_BROWSER_IMAGE_REF": source.plan.browser_image,
        "BOCA_BETA_OWNER_SUBJECT": source.plan.owner_subject,
        "BOCA_RELEASE_RUN_ID": source.target_release_run_id,
        "BOCA_LEGACY_RELEASE_RUN_ID": source.legacy_release_run_id,
    }
    request = go.actions_request(env)
    assert go.authorization_digest(request) == go.authorization_digest(source)
    return request, env


def test_actions_go_binds_exact_run_manifest_and_memfd_zip_without_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    request, env = _actions_fixture(tmp_path)
    assert not (Path(env["RUNNER_TEMP"]) / go.HOST_INVOCATION_NAME).exists()
    monkeypatch.setattr(os, "environ", {**env})
    assert go.main(["--from-actions"]) == 1
    assert "host=untouched" in capsys.readouterr().err
    assert not (Path(env["RUNNER_TEMP"]) / go.HOST_INVOCATION_NAME).exists()

    approved = go.authorization_digest(request)
    monkeypatch.setattr(os, "environ", {**env, "BOCA_CUTOVER_A_GO_BINDING_SHA256": approved})
    assert go.main(["--from-actions"]) == 0
    assert "state=PASS" in capsys.readouterr().out
    token = (Path(env["RUNNER_TEMP"]) / go.HOST_INVOCATION_NAME).read_text().strip()
    host = CutoverInvocation.decode(token)
    assert host.plan == request.plan
    assert host.go_binding_sha256 == approved
    assert host.bundle_sha256 == _sha(request.bundle_path.read_bytes())
    assert (Path(env["RUNNER_TEMP"]) / go.HOST_APPROVAL_NAME).read_text() == approved + "\n"
    assert not (Path(env["RUNNER_TEMP"]) / go.HOST_RECEIPT_NAME).exists()
    # A duplicate use of the same GH run may not replace its approved token.
    assert go.main(["--from-actions"]) == 1
    assert "NO_GO" in capsys.readouterr().err


@pytest.mark.parametrize(
    "mutation",
    [
        {"GITHUB_EVENT_NAME": "pull_request"},
        {"BOCA_OPERATION": "cutover-a-observe"},
        {"GITHUB_REF": "refs/heads/feature"},
        {"GITHUB_ACTOR": "other"},
        {"GITHUB_SHA": "0" * 40},
        {"GITHUB_RUN_ATTEMPT": "2"},
        {"BOCA_RELEASE_RUN_ID": "41573026189"},
        {"BOCA_LEGACY_CONTROLLER_ID": ""},
        {"BOCA_BUDGET": "0.5cpu-256m-64pids"},
    ],
)
def test_actions_go_refuses_unapproved_context_before_creating_host_token(
    tmp_path: Path, mutation: dict[str, str]
) -> None:
    request, env = _actions_fixture(tmp_path)
    env.update(mutation)
    with pytest.raises((go.CutoverGoError, ValueError)):
        actual = go.actions_request(env)
        go.write_actions_invocation(actual, protected_go_digest=go.authorization_digest(request))
    assert not (Path(env["RUNNER_TEMP"]) / go.HOST_INVOCATION_NAME).exists()


def _host_approval_files(
    request: go.GoRequest, env: dict[str, str], *, prepare_id: str | None = None
) -> None:
    runner = Path(env["RUNNER_TEMP"])
    token = go.encode_invocation(
        request.plan,
        bundle_sha256="a" * 64,
        go_binding_sha256="b" * 64,
        prepare_run_id=prepare_id,
    )
    _file(runner / go.HOST_INVOCATION_NAME, (token + "\n").encode("ascii"))
    _file(runner / go.HOST_APPROVAL_NAME, ("b" * 64 + "\n").encode("ascii"))


def test_assert_host_receipt_requires_matching_attempt_sha_and_green_steps(
    tmp_path: Path,
) -> None:
    request, env = _actions_fixture(tmp_path)
    env.update({"BOCA_CUTOVER_A_GO_PREFLIGHT": "success", "BOCA_CUTOVER_A_HOST_APPLY": "success"})
    _host_approval_files(request, env)
    path = Path(env["RUNNER_TEMP"]) / go.HOST_RECEIPT_NAME
    with pytest.raises(go.CutoverGoError):
        go.assert_actions_host_receipt(env)
    exact = (
        f"BOCA_CUTOVER_A_HOST state=ACCEPTED attempt={request.plan.attempt_id} "
        f"target_sha={request.plan.target_sha} cleanup=ACCEPT "
        "receipt=RECORDED runtime=UNVERIFIED\n"
    ).encode()
    _file(path, exact)
    go.assert_actions_host_receipt(env)
    for fake in (
        exact.replace(b"cleanup=ACCEPT", b"cleanup=NO_GO"),
        exact.replace(request.plan.target_sha.encode(), b"0" * 40),
        exact + b"BOCA_CUTOVER_A_HOST state=ACCEPTED\n",
    ):
        path.write_bytes(fake)
        with pytest.raises(go.CutoverGoError, match="terminal receipt"):
            go.assert_actions_host_receipt(env)
    path.write_bytes(exact)
    for field, bad in (
        ("BOCA_CUTOVER_A_GO_PREFLIGHT", "failure"),
        ("BOCA_CUTOVER_A_HOST_APPLY", "skipped"),
        ("GITHUB_SHA", "0" * 40),
    ):
        with pytest.raises(go.CutoverGoError):
            go.assert_actions_host_receipt({**env, field: bad})


def test_go_b_host_receipt_requires_canonical_redacted_postflight_with_exact_ids(
    tmp_path: Path,
) -> None:
    request, env = _actions_fixture(tmp_path)
    env.update({"BOCA_CUTOVER_A_GO_PREFLIGHT": "success", "BOCA_CUTOVER_A_HOST_APPLY": "success"})
    _host_approval_files(request, env, prepare_id="50000000001")
    path = Path(env["RUNNER_TEMP"]) / go.HOST_RECEIPT_NAME
    exact_ack = (
        f"BOCA_CUTOVER_A_HOST state=ACCEPTED attempt={request.plan.attempt_id} "
        f"target_sha={request.plan.target_sha} cleanup=ACCEPT "
        "receipt=RECORDED runtime=UNVERIFIED\n"
    ).encode("ascii")
    disk_before = cleanup.DiskInodes(2000, 200, 4000, 400, 8, 10, 16, 18)
    disk_after = cleanup.DiskInodes(3000, 208, 5000, 406, 8, 10, 16, 18)
    report = cleanup.CleanupReceipt(
        "SUCCESS",
        request.plan.attempt_id,
        "ACCEPT",
        disk_before,
        disk_after,
        (cleanup.Target("image", "sha256:" + "f" * 64),),
        (),
        (),
    ).redacted_json()
    _file(path, exact_ack + b"BOCA_CUTOVER_A_POSTFLIGHT " + report.encode("ascii") + b"\n")
    assert go.assert_actions_host_receipt(env) == report
    # The exact historical image exception must survive the whole protected
    # host transcript parser, not only the standalone JSON grammar.
    retained = cleanup.CleanupReceipt(
        "SUCCESS",
        request.plan.attempt_id,
        "ACCEPT",
        disk_before,
        disk_after,
        (),
        (),
        (),
        (
            cleanup.HistoricalRetainedImageProof(
                cleanup.HISTORICAL_RETIRE_TARGET,
                cleanup.HISTORICAL_RETIRE_DIGEST,
                cleanup.HISTORICAL_RETIRE_REVISION,
            ),
        ),
    ).redacted_json()
    _file(path, exact_ack + b"BOCA_CUTOVER_A_POSTFLIGHT " + retained.encode("ascii") + b"\n")
    assert go.assert_actions_host_receipt(env) == retained
    for malformed in (
        exact_ack,
        exact_ack + b"BOCA_CUTOVER_A_POSTFLIGHT {}\n",
        exact_ack + b"BOCA_CUTOVER_A_POSTFLIGHT " + report.encode("ascii") + b"\nEXTRA\n",
        exact_ack.replace(b"cleanup=ACCEPT", b"cleanup=NO_GO")
        + b"BOCA_CUTOVER_A_POSTFLIGHT "
        + report.encode("ascii")
        + b"\n",
    ):
        _file(path, malformed)
        with pytest.raises(go.CutoverGoError):
            go.assert_actions_host_receipt(env)
    bad = json.loads(report)
    for changed in (
        {"status": "NO_GO"},
        {"outcome": "FAILURE"},
        {"attempt_id": "50000000002"},
        {"retained_uncertain": ["unknown-external"]},
        {"removed": [{"kind": "volume", "id": "porota_data"}]},
        {"removed": [{"kind": "volume", "id": "boca-socios_boca_data"}]},
        {"removed": [{"kind": "container", "id": "short"}]},
    ):
        payload = dict(bad, **changed)
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
        _file(path, exact_ack + b"BOCA_CUTOVER_A_POSTFLIGHT " + serialized + b"\n")
        with pytest.raises(go.CutoverGoError):
            go.assert_actions_host_receipt(env)


def test_runner_accepts_only_exact_historical_quarantine_receipt_v2() -> None:
    disk = cleanup.DiskInodes(2000, 200, 4000, 400, 8, 10, 16, 18)
    proof = cleanup.HistoricalRetainedImageProof(
        cleanup.HISTORICAL_RETIRE_TARGET,
        cleanup.HISTORICAL_RETIRE_DIGEST,
        cleanup.HISTORICAL_RETIRE_REVISION,
    )
    receipt = cleanup.CleanupReceipt(
        "SUCCESS", "50000000001", "ACCEPT", disk, disk, (), (), (), (proof,)
    )
    raw = receipt.redacted_json().encode("ascii")
    assert go.verify_postflight_json(raw, "50000000001") == raw.decode("ascii")
    body = json.loads(raw)
    for changed in (
        {"version": 1},
        {"retained_attested": []},
        {"retained_attested": [dict(body["retained_attested"][0], digest="sha256:foreign")]},
        {"retained_attested": [dict(body["retained_attested"][0], id="sha256:" + "1" * 64)]},
        {"retained_attested": [dict(body["retained_attested"][0], unknown=True)]},
    ):
        mutated = dict(body, **changed)
        payload = json.dumps(mutated, sort_keys=True, separators=(",", ":")).encode("ascii")
        with pytest.raises(go.CutoverGoError):
            go.verify_postflight_json(payload, "50000000001")


def test_bound_go_requires_distinct_protected_variable_which_is_absent_by_default(
    tmp_path: Path,
) -> None:
    request = _fixture(tmp_path)
    with pytest.raises(go.CutoverGoError, match="absent"):
        go.require_protected_go(request, protected_go_digest="")
    with pytest.raises(go.CutoverGoError, match="not bound"):
        go.require_protected_go(request, protected_go_digest="f" * 64)
    expected = go.authorization_digest(request)
    assert go.require_protected_go(request, protected_go_digest=expected) == expected


@pytest.mark.parametrize(
    "change",
    [
        {"github_repository": "untrusted/fork"},
        {"github_actor": "different-maintainer"},
        {"github_ref": "refs/pull/320/merge"},
        {"github_ref": "refs/heads/feature-320"},
        {"github_run_attempt": "2"},
        {"github_run_id": "41949228861"},
        {"github_sha": "1" * 40},
        {"target_release_run_id": "41573026189"},
        {"legacy_release_run_id": "41949228846"},
    ],
)
def test_fork_pr_nonmain_rerun_and_wrong_release_are_never_authorized(
    tmp_path: Path, change: dict[str, str]
) -> None:
    request = replace(_fixture(tmp_path), **change)
    with pytest.raises(go.CutoverGoError, match="main/owner/one-shot/releases"):
        go.authorization_digest(request)


def test_historical_and_companion_manifests_are_independent_trusted_evidence(
    tmp_path: Path,
) -> None:
    request = _fixture(tmp_path)
    original_go = go.authorization_digest(request)
    request.browser_manifest_path.write_text(json.dumps({"source_sha": "0" * 40}))
    with pytest.raises(go.CutoverGoError, match="manifests conflict"):
        go.require_protected_go(request, protected_go_digest=original_go)


def test_historical_compose_or_reviewed_stage_drift_refuses_go(tmp_path: Path) -> None:
    request = _fixture(tmp_path)
    original_go = go.authorization_digest(request)
    request.historical_compose_path.write_bytes(b"drifted old compose evidence")
    with pytest.raises(go.CutoverGoError, match="digest mismatch"):
        go.require_protected_go(request, protected_go_digest=original_go)
    request = _fixture(tmp_path / "again")
    request.seccomp_path.write_bytes(b"tampered seccomp")
    with pytest.raises(go.CutoverGoError, match="digest mismatch"):
        go.authorization_digest(request)


def test_unpaired_or_missing_option_b_zip_cannot_authorize_legacy_migration(tmp_path: Path) -> None:
    request = _fixture(tmp_path, complete_b=False)
    with pytest.raises(go.CutoverGoError, match="Option B"):
        go.authorization_digest(request)


def test_duplicate_manifest_field_or_symlink_or_swapped_bundle_is_no_go(tmp_path: Path) -> None:
    request = _fixture(tmp_path)
    original_go = go.authorization_digest(request)
    request.target_manifest_path.write_text('{"source_sha":"d","source_sha":"e"}')
    with pytest.raises(go.CutoverGoError, match="duplicate"):
        go.require_protected_go(request, protected_go_digest=original_go)

    request = _fixture(tmp_path / "symlink")
    target = request.browser_manifest_path
    alias = target.parent / "untrusted-browser-alias.json"
    alias.symlink_to(target)
    with pytest.raises(go.CutoverGoError, match="symlink"):
        go.authorization_digest(replace(request, browser_manifest_path=alias))

    parent_alias = target.parent.parent / "browser-artifact-parent-link"
    parent_alias.symlink_to(target.parent, target_is_directory=True)
    with pytest.raises(go.CutoverGoError, match="parent symlink"):
        go.authorization_digest(replace(request, browser_manifest_path=parent_alias / target.name))
    with pytest.raises(go.CutoverGoError, match="absolute"):
        go.authorization_digest(replace(request, browser_manifest_path=Path("browser.json")))

    request = _fixture(tmp_path / "bundle")
    original_go = go.authorization_digest(request)
    with request.bundle_path.open("ab") as bundle:
        bundle.write(b"unexpected trailing bytes")
    with pytest.raises(go.CutoverGoError, match="not bound"):
        go.require_protected_go(request, protected_go_digest=original_go)


def test_cli_missing_protected_go_and_untrusted_request_is_inert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    request = _fixture(tmp_path)
    request_file = _file(
        tmp_path / "go-request.json",
        json.dumps(
            {
                "plan": asdict(request.plan),
                **{
                    key: str(value) if isinstance(value, Path) else value
                    for key, value in asdict(request).items()
                    if key != "plan"
                },
            }
        ).encode("utf-8"),
    )
    monkeypatch.delenv("BOCA_CUTOVER_A_GO_BINDING_SHA256", raising=False)
    assert go.main([str(request_file)]) == 1
    assert "NO_GO host=untouched" in capsys.readouterr().err
    assert go.GoRequest.from_json(json.loads(request_file.read_text())) == request

    request_file.write_text('{"plan":{},"plan":{}}')
    monkeypatch.setenv("BOCA_CUTOVER_A_GO_BINDING_SHA256", "a" * 64)
    assert go.main([str(request_file)]) == 1
    assert "NO_GO host=untouched" in capsys.readouterr().err
    assert os.path.exists(request.historical_compose_path)


def test_fifo_0600_cannot_block_go_preflight_before_regular_file_attestation(
    tmp_path: Path,
) -> None:
    """Adversarial real FIFO: a protected runner must fail instead of hanging."""
    fifo = tmp_path / "malicious-go-request.json"
    os.mkfifo(fifo, 0o600)
    result = subprocess.run(  # noqa: S603 - fixed Python script, no shell or untrusted executable
        [sys.executable, str(ROOT / "scripts/check_cutover_a_go.py"), str(fifo)],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        check=False,
        timeout=2.5,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "BOCA_CUTOVER_A_GO state=NO_GO host=untouched" in result.stderr


def test_effectful_dispatch_v3_requires_authenticated_exact_run_binding() -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    assert "cutover-a-observe" in workflow
    assert "cutover-a-apply" in workflow
    assert (
        "BOCA_CUTOVER_A_GO_BINDING_SHA256: ${{ vars.BOCA_CUTOVER_A_GO_BINDING_SHA256 }}"
        not in workflow
    )
    assert (
        'check_boca_deploy_dispatch.py "$RUNNER_TEMP/boca-dispatch-v3" --write-invocation'
        in workflow
    )
    assert "python scripts/check_cutover_a_go.py --from-actions" not in workflow
    assert "check_legacy_go_dispatch.py apply" in workflow
    assert "python scripts/check_cutover_a_go.py --assert-host-receipt" in workflow
    assert "always() && inputs.operation == 'cutover-a-apply'" in workflow
    assert "timeout --signal=TERM --kill-after=5s 900s ssh" in workflow
    effect = workflow.split("      - name: Apply exactly one reviewed Cutover A", 1)[1].split(
        "      - name:", 1
    )[0]
    assert effect.index("boca-main-ref-cutover-effect.json") < effect.index(
        'boca-target "$remote_command"'
    )
    assert "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in effect
    assert "|| host_ssh_rc=$?" in effect
    assert "--report-host-failure" in effect
    assert 'exit "$host_ssh_rc"' in effect
    assert "2>/dev/null" in effect
    assert "docker image prune" not in workflow
    assert "docker system prune" not in workflow


def test_post_ssh_missing_ack_never_claims_original_host_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _request, env = _actions_fixture(tmp_path)
    env.update({"BOCA_CUTOVER_A_GO_PREFLIGHT": "success", "BOCA_CUTOVER_A_HOST_APPLY": "failure"})
    monkeypatch.setattr(os, "environ", env)
    assert go.main(["--assert-host-receipt"]) == 1
    stderr = capsys.readouterr().err
    assert stderr == "BOCA_CUTOVER_A_HOST_VERIFY state=NO_GO host=UNVERIFIED\n"
    assert "untouched" not in stderr


@pytest.mark.parametrize(
    ("ssh_rc", "remote_stdout", "claim", "transport"),
    [
        (
            3,
            b"BOCA_CUTOVER_A_HOST state=NO_GO receipt=UNVERIFIED runtime=UNVERIFIED\n",
            "NO_GO_UNVERIFIED",
            "EXIT_NONZERO",
        ),
        (
            3,
            b"BOCA_CUTOVER_A_HOST state=NO_GO receipt=RECORDED runtime=UNVERIFIED\n",
            "NO_GO_RECORDED_UNVERIFIED",
            "EXIT_NONZERO",
        ),
        (124, b"SECRET=must-never-show\n", "NONE", "TIMEOUT"),
        (255, b"BOCA_CUTOVER_A_HOST state=ACCEPTED\n", "NONE", "SSH_255"),
        (
            3,
            b"bogus\nBOCA_CUTOVER_A_HOST state=NO_GO receipt=RECORDED runtime=UNVERIFIED\n",
            "NONE",
            "EXIT_NONZERO",
        ),
    ],
)
def test_failed_ssh_diagnostic_is_redacted_and_never_accepts_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    ssh_rc: int,
    remote_stdout: bytes,
    claim: str,
    transport: str,
) -> None:
    _request, env = _actions_fixture(tmp_path)
    env["BOCA_CUTOVER_A_SSH_RC"] = str(ssh_rc)
    _file(Path(env["RUNNER_TEMP"]) / go.HOST_RECEIPT_NAME, remote_stdout)
    monkeypatch.setattr(os, "environ", env)
    assert go.main(["--report-host-failure"]) == 0
    receipt = capsys.readouterr().out
    assert f"host_claim={claim}" in receipt
    assert f"transport={transport}" in receipt
    assert "host=UNVERIFIED" in receipt and "terminal=UNVERIFIED" in receipt
    assert "state=ACCEPTED" not in receipt and "SECRET" not in receipt


@pytest.mark.parametrize(
    ("phase_line", "expected_phase", "expected_claim"),
    [
        (
            "BOCA_CUTOVER_A_FAILURE_PHASE phase=STAGE\n",
            "STAGE",
            "NO_GO_RECORDED_UNVERIFIED",
        ),
        (
            "BOCA_CUTOVER_A_FAILURE_PHASE phase=PREPARE_WORKER\n",
            "PREPARE_WORKER",
            "NO_GO_RECORDED_UNVERIFIED",
        ),
        ("BOCA_CUTOVER_A_FAILURE_PHASE phase=STAGE;PRIVATE\n", "UNVERIFIED", "NONE"),
        ("BOCA_CUTOVER_A_FAILURE_PHASE phase=FAKE\n", "UNVERIFIED", "NONE"),
    ],
)
def test_failed_ssh_allows_exact_phase_claim_without_promoting_host_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    phase_line: str,
    expected_phase: str,
    expected_claim: str,
) -> None:
    _request, env = _actions_fixture(tmp_path)
    env["BOCA_CUTOVER_A_SSH_RC"] = "3"
    remote = (
        phase_line + "BOCA_CUTOVER_A_HOST state=NO_GO receipt=RECORDED runtime=UNVERIFIED\n"
    ).encode("ascii")
    _file(Path(env["RUNNER_TEMP"]) / go.HOST_RECEIPT_NAME, remote)
    monkeypatch.setattr(os, "environ", env)
    assert go.main(["--report-host-failure"]) == 0
    output = capsys.readouterr().out
    assert f"phase_claim={expected_phase}" in output
    assert f"host_claim={expected_claim}" in output
    assert "phase=UNVERIFIED host=UNVERIFIED terminal=UNVERIFIED" in output
    assert "ACCEPTED" not in output and "PRIVATE" not in output


def _cutover_observe_ready(plan: CutoverPlan) -> bytes:
    """The exact bounded line emitted before the host Cutover transaction."""
    return (
        f"BOCA_CUTOVER_A_OBSERVE state=READY legacy_sha={plan.legacy_sha} "
        f"legacy_id={plan.legacy_id} legacy_image={plan.legacy_image} "
        f"target_sha={plan.target_sha} target_image={plan.target_image} "
        f"browser_image={plan.browser_image} original=RUNNING "
        "port=127.0.0.1:8443 worker=absent owner=preserved key=preserved "
        "data=preserved effects=none\n"
    ).encode("ascii")


@pytest.mark.parametrize("failed_phase", ["STAGE", "PREPARE_WORKER"])
@pytest.mark.parametrize("postflight", [b"", b'BOCA_CUTOVER_A_POSTFLIGHT {"status":"NO_GO"}\n'])
def test_failed_ssh_phase_survives_real_prior_observation_without_host_acceptance(
    tmp_path: Path,
    failed_phase: str,
    postflight: bytes,
) -> None:
    request, env = _actions_fixture(tmp_path)
    env["BOCA_CUTOVER_A_SSH_RC"] = "3"
    stdout = (
        _cutover_observe_ready(request.plan)
        + postflight
        + f"BOCA_CUTOVER_A_FAILURE_PHASE phase={failed_phase}\n".encode("ascii")
        + b"BOCA_CUTOVER_A_HOST state=NO_GO receipt=RECORDED runtime=UNVERIFIED\n"
    )
    _file(Path(env["RUNNER_TEMP"]) / go.HOST_RECEIPT_NAME, stdout)
    report = go.classify_cutover_ssh_failure(env)
    assert "host_claim=NO_GO_RECORDED_UNVERIFIED" in report
    assert f"phase_claim={failed_phase}" in report
    assert "phase=UNVERIFIED host=UNVERIFIED terminal=UNVERIFIED no_retry=true" in report
    assert "ACCEPTED" not in report


@pytest.mark.parametrize(
    "bad_line",
    [
        b"",
        b"BOCA_CUTOVER_A_WORKER_FAILURE primary=CREATE compensation=INDETERMINATE\n",
        b"BOCA_CUTOVER_A_WORKER_FAILURE primary=CREATE compensation=INDETERMINATE PRIVATE=secret\n",
        b"BOCA_CUTOVER_A_WORKER_FAILURE primary=FAKE compensation=VERIFIED\n",
    ],
)
@pytest.mark.parametrize("primary", ["CREATE", "HEALTH_UNHEALTHY"])
def test_failed_ssh_typed_worker_phase_is_bounded_diagnostic_only(
    tmp_path: Path, bad_line: bytes, primary: str
) -> None:
    _request, env = _actions_fixture(tmp_path)
    env["BOCA_CUTOVER_A_SSH_RC"] = "3"
    typed = f"BOCA_CUTOVER_A_WORKER_FAILURE primary={primary} compensation=VERIFIED\n".encode()
    prefix = (
        typed
        if not bad_line
        else (bad_line if b"PRIVATE" in bad_line or b"FAKE" in bad_line else typed + bad_line)
    )
    stdout = (
        prefix
        + b"BOCA_CUTOVER_A_FAILURE_PHASE phase=PREPARE_WORKER\n"
        + b"BOCA_CUTOVER_A_HOST state=NO_GO receipt=RECORDED runtime=UNVERIFIED\n"
    )
    _file(Path(env["RUNNER_TEMP"]) / go.HOST_RECEIPT_NAME, stdout)
    report = go.classify_cutover_ssh_failure(env)
    if not bad_line:
        assert f"worker_primary_claim={primary} worker_compensation_claim=VERIFIED" in report
        assert "phase_claim=PREPARE_WORKER" in report
    else:
        assert "host_claim=NONE" in report
        assert "worker_primary_claim=UNVERIFIED worker_compensation_claim=UNVERIFIED" in report
    assert "host=UNVERIFIED terminal=UNVERIFIED no_retry=true" in report
    assert "PRIVATE" not in report and "secret" not in report


@pytest.mark.parametrize(
    ("exit_code", "oom"),
    [
        ("0", "NO"),
        ("1", "YES"),
        ("137", "YES"),
        ("137", "NO"),
        ("UNKNOWN", "UNKNOWN"),
        ("UNKNOWN", "NO"),
    ],
)
def test_failed_ssh_v3_worker_exit_is_strictly_typed_and_never_go(
    tmp_path: Path, exit_code: str, oom: str
) -> None:
    request, env = _actions_fixture(tmp_path)
    env["BOCA_CUTOVER_A_SSH_RC"] = "3"
    payload = (
        _cutover_observe_ready(request.plan)
        + f"BOCA_CUTOVER_A_WORKER_FAILURE primary=HEALTH_EXITED compensation=VERIFIED "
        f"exit_code={exit_code} oom={oom}\n".encode("ascii")
        + b"BOCA_CUTOVER_A_FAILURE_PHASE phase=PREPARE_WORKER\n"
        + b"BOCA_CUTOVER_A_HOST state=NO_GO receipt=RECORDED runtime=UNVERIFIED\n"
    )
    _file(Path(env["RUNNER_TEMP"]) / go.HOST_RECEIPT_NAME, payload)
    report = go.classify_cutover_ssh_failure(env)
    assert "host_claim=NO_GO_RECORDED_UNVERIFIED" in report
    assert f"worker_exit_code_claim={exit_code} worker_oom_claim={oom}" in report
    assert "terminal=UNVERIFIED no_retry=true" in report
    assert "ACCEPTED" not in report


def test_failed_ssh_exit_one_diagnostic_distinguishes_start_ack_from_unknown_cause(
    tmp_path: Path,
) -> None:
    request, env = _actions_fixture(tmp_path)
    env["BOCA_CUTOVER_A_SSH_RC"] = "3"
    _file(
        Path(env["RUNNER_TEMP"]) / go.HOST_RECEIPT_NAME,
        _cutover_observe_ready(request.plan)
        + b"BOCA_CUTOVER_A_WORKER_FAILURE primary=HEALTH_EXITED compensation=VERIFIED "
        + b"exit_code=1 oom=NO\n"
        + b"BOCA_CUTOVER_A_FAILURE_PHASE phase=PREPARE_WORKER\n"
        + b"BOCA_CUTOVER_A_HOST state=NO_GO receipt=RECORDED runtime=UNVERIFIED\n",
    )
    report = go.classify_cutover_ssh_failure(env)

    assert "worker_start_ack_claim=EXACT_CID_IMPLIED_BY_HEALTH_PHASE" in report
    assert "worker_internal_cause=UNKNOWN" in report
    assert "worker_cause_evidence=INFERENCE_NOT_CAUSE" in report
    assert "worker_exit_code_claim=1 worker_oom_claim=NO" in report
    assert "state=NO_GO" in report
    assert "host=UNVERIFIED terminal=UNVERIFIED no_retry=true" in report


@pytest.mark.parametrize("ssh_rc", ["124", "255"])
def test_failed_ssh_exit_one_inference_rejects_transport_failure_even_with_host_claim(
    tmp_path: Path, ssh_rc: str
) -> None:
    request, env = _actions_fixture(tmp_path)
    env["BOCA_CUTOVER_A_SSH_RC"] = ssh_rc
    _file(
        Path(env["RUNNER_TEMP"]) / go.HOST_RECEIPT_NAME,
        _cutover_observe_ready(request.plan)
        + b"BOCA_CUTOVER_A_WORKER_FAILURE primary=HEALTH_EXITED compensation=VERIFIED "
        + b"exit_code=1 oom=NO\n"
        + b"BOCA_CUTOVER_A_FAILURE_PHASE phase=PREPARE_WORKER\n"
        + b"BOCA_CUTOVER_A_HOST state=NO_GO receipt=RECORDED runtime=UNVERIFIED\n",
    )
    report = go.classify_cutover_ssh_failure(env)

    assert f"ssh_rc={ssh_rc}" in report
    assert "worker_start_ack_claim=UNVERIFIED" in report
    assert "worker_internal_cause=UNKNOWN worker_cause_evidence=UNVERIFIED" in report
    assert "host=UNVERIFIED terminal=UNVERIFIED no_retry=true" in report


@pytest.mark.parametrize("receipt_state", ["absent", "truncated"])
def test_failed_ssh_exit_one_inference_rejects_missing_or_truncated_receipt(
    tmp_path: Path, receipt_state: str
) -> None:
    request, env = _actions_fixture(tmp_path)
    env["BOCA_CUTOVER_A_SSH_RC"] = "3"
    if receipt_state == "truncated":
        _file(
            Path(env["RUNNER_TEMP"]) / go.HOST_RECEIPT_NAME,
            _cutover_observe_ready(request.plan)
            + b"BOCA_CUTOVER_A_WORKER_FAILURE primary=HEALTH_EXITED "
            + b"compensation=VERIFIED exit_code=1 oom=NO\n"
            + b"BOCA_CUTOVER_A_FAILURE_PHASE phase=PREPARE_WORKER\n"
            + b"BOCA_CUTOVER_A_HOST state=NO_GO receipt=RECORDED runtime=UNVERIFIED",
        )
    report = go.classify_cutover_ssh_failure(env)

    assert "worker_start_ack_claim=UNVERIFIED" in report
    assert "worker_internal_cause=UNKNOWN worker_cause_evidence=UNVERIFIED" in report
    assert "host=UNVERIFIED terminal=UNVERIFIED no_retry=true" in report


@pytest.mark.parametrize(
    ("worker_line", "phase_line"),
    [
        (
            b"BOCA_CUTOVER_A_WORKER_FAILURE primary=HEALTH_EXITED compensation=VERIFIED exit_code=0 oom=NO\n",
            b"BOCA_CUTOVER_A_FAILURE_PHASE phase=PREPARE_WORKER\n",
        ),
        (
            b"BOCA_CUTOVER_A_WORKER_FAILURE primary=HEALTH_EXITED compensation=VERIFIED exit_code=137 oom=NO\n",
            b"BOCA_CUTOVER_A_FAILURE_PHASE phase=PREPARE_WORKER\n",
        ),
        (
            b"BOCA_CUTOVER_A_WORKER_FAILURE primary=HEALTH_EXITED compensation=VERIFIED exit_code=1 oom=YES\n",
            b"BOCA_CUTOVER_A_FAILURE_PHASE phase=PREPARE_WORKER\n",
        ),
        (
            b"BOCA_CUTOVER_A_WORKER_FAILURE primary=HEALTH_EXITED compensation=VERIFIED exit_code=UNKNOWN oom=NO\n",
            b"BOCA_CUTOVER_A_FAILURE_PHASE phase=PREPARE_WORKER\n",
        ),
        (
            b"BOCA_CUTOVER_A_WORKER_FAILURE primary=HEALTH_EXITED compensation=INDETERMINATE exit_code=1 oom=NO\n",
            b"BOCA_CUTOVER_A_FAILURE_PHASE phase=PREPARE_WORKER\n",
        ),
        (
            b"BOCA_CUTOVER_A_WORKER_FAILURE primary=HEALTH_TIMEOUT compensation=VERIFIED\n",
            b"BOCA_CUTOVER_A_FAILURE_PHASE phase=PREPARE_WORKER\n",
        ),
        (
            b"BOCA_CUTOVER_A_WORKER_FAILURE primary=HEALTH_EXITED compensation=VERIFIED exit_code=1 oom=NO\n",
            b"BOCA_CUTOVER_A_FAILURE_PHASE phase=START\n",
        ),
        (
            b"BOCA_CUTOVER_A_WORKER_FAILURE primary=HEALTH_EXITED compensation=VERIFIED exit_code=01 oom=NO\n",
            b"BOCA_CUTOVER_A_FAILURE_PHASE phase=PREPARE_WORKER\n",
        ),
        (
            b"BOCA_CUTOVER_A_WORKER_FAILURE primary=HEALTH_EXITED compensation=VERIFIED exit_code=1 oom=NO PRIVATE=not-for-report\n",
            b"BOCA_CUTOVER_A_FAILURE_PHASE phase=PREPARE_WORKER\n",
        ),
        (
            b"BOCA_CUTOVER_A_WORKER_FAILURE primary=HEALTH_EXITED compensation=VERIFIED exit_code=1 oom=NO\n"
            b"BOCA_CUTOVER_A_WORKER_FAILURE primary=HEALTH_EXITED compensation=VERIFIED exit_code=1 oom=NO\n",
            b"BOCA_CUTOVER_A_FAILURE_PHASE phase=PREPARE_WORKER\n",
        ),
    ],
)
def test_failed_ssh_exit_one_inference_requires_one_exact_verified_worker_claim(
    tmp_path: Path, worker_line: bytes, phase_line: bytes
) -> None:
    request, env = _actions_fixture(tmp_path)
    env["BOCA_CUTOVER_A_SSH_RC"] = "3"
    _file(
        Path(env["RUNNER_TEMP"]) / go.HOST_RECEIPT_NAME,
        _cutover_observe_ready(request.plan)
        + worker_line
        + phase_line
        + b"BOCA_CUTOVER_A_HOST state=NO_GO receipt=RECORDED runtime=UNVERIFIED\n",
    )
    report = go.classify_cutover_ssh_failure(env)

    assert "worker_start_ack_claim=UNVERIFIED" in report
    assert "worker_internal_cause=UNKNOWN" in report
    assert "worker_cause_evidence=UNVERIFIED" in report
    assert "host=UNVERIFIED terminal=UNVERIFIED no_retry=true" in report
    assert "PRIVATE" not in report and "not-for-report" not in report


@pytest.mark.parametrize(
    "mutation",
    [
        "exit_code=01 oom=NO",
        "exit_code=-1 oom=NO",
        "exit_code=256 oom=NO",
        "exit_code=True oom=NO",
        "exit_code=1 oom=true",
        "exit_code=137 oom=1",
        "exit_code=137 oom=YES Extra=PRIVATE",
        "exit_code=137 oom=NO\nRAW=PRIVATE",
        "exit_code=137",
        "oom=YES",
    ],
)
def test_failed_ssh_v3_rejects_invalid_worker_exit_without_leaking_data(
    tmp_path: Path, mutation: str
) -> None:
    _request, env = _actions_fixture(tmp_path)
    env["BOCA_CUTOVER_A_SSH_RC"] = "3"
    _file(
        Path(env["RUNNER_TEMP"]) / go.HOST_RECEIPT_NAME,
        f"BOCA_CUTOVER_A_WORKER_FAILURE primary=HEALTH_EXITED compensation=VERIFIED "
        f"{mutation}\n".encode()
        + b"BOCA_CUTOVER_A_FAILURE_PHASE phase=PREPARE_WORKER\n"
        + b"BOCA_CUTOVER_A_HOST state=NO_GO receipt=RECORDED runtime=UNVERIFIED\n",
    )
    report = go.classify_cutover_ssh_failure(env)
    assert "host_claim=NONE" in report
    assert "worker_exit_code_claim=UNKNOWN worker_oom_claim=UNKNOWN" in report
    assert "terminal=UNVERIFIED no_retry=true" in report
    assert "PRIVATE" not in report


@pytest.mark.parametrize(
    "mutation",
    [
        lambda ready: ready + ready,
        lambda ready: ready.replace(b"effects=none", b"effects=write"),
        lambda ready: ready.replace(b"legacy_sha=", b"legacy_sha=x"),
        lambda ready: ready.replace(b"ghcr.io/mbalbo2023/", b"ghcr.io/foreign/"),
        lambda ready: ready.replace(b"port=127.0.0.1:8443", b"port=0.0.0.0:8443"),
        lambda ready: ready[:-1] + b"\x00\n",
        lambda ready: ready + b"PRIVATE=do-not-disclose\n",
        lambda ready: b"BOCA_CUTOVER_A_OBSERVE state=READY\n",
    ],
)
def test_failed_ssh_observation_prefix_must_be_exact_and_single(
    tmp_path: Path,
    mutation: object,
) -> None:
    request, env = _actions_fixture(tmp_path)
    env["BOCA_CUTOVER_A_SSH_RC"] = "3"
    ready = _cutover_observe_ready(request.plan)
    stdout = (
        mutation(ready)
        + b"BOCA_CUTOVER_A_FAILURE_PHASE phase=STAGE\n"
        + b"BOCA_CUTOVER_A_HOST state=NO_GO receipt=RECORDED runtime=UNVERIFIED\n"
    )
    _file(Path(env["RUNNER_TEMP"]) / go.HOST_RECEIPT_NAME, stdout)
    report = go.classify_cutover_ssh_failure(env)
    assert "host_claim=NONE" in report
    assert "phase_claim=UNVERIFIED" in report
    assert "PRIVATE" not in report and "ACCEPTED" not in report


def test_failed_ssh_diagnostic_rejects_zero_rc_and_no_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _request, env = _actions_fixture(tmp_path)
    for changed in (
        {"BOCA_CUTOVER_A_SSH_RC": "0"},
        {"BOCA_OPERATION": "other", "BOCA_CUTOVER_A_SSH_RC": "3"},
    ):
        monkeypatch.setattr(os, "environ", {**env, **changed})
        assert go.main(["--report-host-failure"]) == 1
        assert "host=UNVERIFIED" in capsys.readouterr().err


def test_prepared_cutover_review_remains_exact_across_distinct_apply_runs(
    tmp_path: Path,
) -> None:
    """A known PREPARE identity can bind reviewed bytes before APPLY gets its ID."""
    request = _fixture(tmp_path)
    prepare_id = "50000000001"
    prepared = go.cutover_prepared_context_sha256(request, prepare_run_id=prepare_id)
    assert len(prepared) == 64
    assert prepared != go.authorization_digest(request)
    second_run = "50000000002"
    replay = replace(
        request,
        github_run_id=second_run,
        plan=replace(request.plan, attempt_id=second_run),
    )
    assert go.cutover_prepared_context_sha256(replay, prepare_run_id=prepare_id) == prepared
    assert go.cutover_prepared_context_sha256(request, prepare_run_id="50000000003") != prepared
    # New digest cannot satisfy the legacy GO gate.
    with pytest.raises(go.CutoverGoError, match="not bound"):
        go.require_protected_go(request, protected_go_digest=prepared)
    for invalid in ("", "0", "5" * 21):
        with pytest.raises(go.CutoverGoError):
            go.cutover_prepared_context_sha256(request, prepare_run_id=invalid)
    with pytest.raises(go.CutoverGoError):
        go.cutover_prepared_context_sha256(
            replace(request, github_actor="imposter"), prepare_run_id=prepare_id
        )
    with pytest.raises(go.CutoverGoError):
        go.cutover_prepared_context_sha256(
            replace(request, github_run_id="50000000004"), prepare_run_id=prepare_id
        )


def test_prepared_cutover_review_rejects_any_reviewed_bytes_drift(tmp_path: Path) -> None:
    request = _fixture(tmp_path)
    prepared = go.cutover_prepared_context_sha256(request, prepare_run_id="50000000001")
    request.browser_manifest_path.write_text('{"source_sha":"tampered"}')
    with pytest.raises(go.CutoverGoError, match="manifests conflict"):
        go.cutover_prepared_context_sha256(request, prepare_run_id="50000000001")
    assert len(prepared) == 64


def test_prepared_actions_go_b_creates_v2_token_after_reviewed_pins(
    tmp_path: Path,
) -> None:
    from datetime import UTC, datetime, timedelta

    request, env = _actions_fixture(tmp_path)
    runner = Path(env["RUNNER_TEMP"])
    prepare_id = "42053482614"
    instant = datetime.now(UTC).replace(microsecond=0)
    receipt = {
        "version": "boca-protected-prepared-go-v1",
        "operation": "cutover-a-apply",
        "repository": env["GITHUB_REPOSITORY"],
        "actor": env["GITHUB_ACTOR"],
        "ref": env["GITHUB_REF"],
        "source_sha": env["GITHUB_SHA"],
        "release_run_id": env["BOCA_RELEASE_RUN_ID"],
        "prepare_run_id": prepare_id,
        "prepare_attempt": "1",
        "prepared_at_utc": instant.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "valid_until_utc": (instant + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "public_context_sha256": go.cutover_prepared_context_sha256(
            request, prepare_run_id=prepare_id
        ),
        "release_manifest_sha256": _sha(request.target_manifest_path.read_bytes()),
        "browser_manifest_sha256": _sha(request.browser_manifest_path.read_bytes()),
        "bundle_sha256": _sha(request.bundle_path.read_bytes()),
        "owner_subject_sha256": _sha(request.plan.owner_subject.encode("ascii")),
    }
    raw = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )
    approved = hashlib.sha256(b"boca-cutover-a-prepared-go-v1:\x00" + raw).hexdigest()
    env["BOCA_CUTOVER_A_GO_BINDING_SHA256"] = approved
    _file(runner / "boca-protected-legacy-go.approved", (approved + "\n").encode("ascii"))
    _file(runner / "boca-protected-legacy-go.prepare-id", (prepare_id + "\n").encode("ascii"))
    _file(runner / "boca-protected-legacy-go.receipt.json", raw)
    assert go.write_actions_invocation_prepared(request, environ=env) == approved
    token = (runner / go.HOST_INVOCATION_NAME).read_text(encoding="ascii").strip()
    invocation = CutoverInvocation.decode(token)
    assert invocation.prepare_run_id == prepare_id
    assert invocation.plan.attempt_id == env["GITHUB_RUN_ID"]
    assert invocation.go_binding_sha256 == approved


def test_prepared_actions_missing_go_b_prevents_runner_token(
    tmp_path: Path,
) -> None:
    request, env = _actions_fixture(tmp_path)
    with pytest.raises(go.CutoverGoError):
        go.write_actions_invocation_prepared(request, environ=env)
    assert not (Path(env["RUNNER_TEMP"]) / go.HOST_INVOCATION_NAME).exists()
