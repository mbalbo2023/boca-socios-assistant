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

from boca_socios.browser_release_manifest import make_browser_manifest
from boca_socios.host_boca_cutover import CutoverPlan
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


def test_no_effectful_dispatch_is_exposed_even_if_go_source_exists() -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    assert "cutover-a-observe" in workflow
    assert "cutover-a-apply" not in workflow
    assert "BOCA_CUTOVER_A_GO_BINDING_SHA256" not in workflow
    assert (
        "transaction_not_wired" in (ROOT / "src/boca_socios/host_boca_transaction.py").read_text()
    )
