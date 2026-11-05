"""Reviewable PREPARE GO_B runner artifacts; offline only, no GitHub API/host."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from boca_socios import prepared_go_runner as prepared


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def _record(
    tmp_path: Path, operation: str = "cutover-a-apply"
) -> tuple[dict[str, str], dict[str, str]]:
    prep_id = "42053482614"
    now = datetime.now(UTC).replace(microsecond=0)
    env = {
        "GITHUB_REPOSITORY": "mbalbo2023/boca-socios-assistant",
        "GITHUB_ACTOR": "mbalbo2023",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": "a" * 40,
        "BOCA_SOURCE_SHA": "a" * 40,
        "GITHUB_RUN_ID": "42055559999",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "BOCA_OPERATION": operation,
        "RUNNER_TEMP": str(tmp_path),
    }
    receipt = {
        "version": "boca-protected-prepared-go-v1",
        "operation": operation,
        "repository": env["GITHUB_REPOSITORY"],
        "actor": env["GITHUB_ACTOR"],
        "ref": env["GITHUB_REF"],
        "source_sha": env["GITHUB_SHA"],
        "release_run_id": "42031822994",
        "prepare_run_id": prep_id,
        "prepare_attempt": "1",
        "prepared_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "valid_until_utc": (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "public_context_sha256": "f" * 64,
        "release_manifest_sha256": "c" * 64,
        "browser_manifest_sha256": "d" * 64,
        "bundle_sha256": "e" * 64,
        "owner_subject_sha256": hashlib.sha256(b"owner").hexdigest(),
    }
    domain = {
        "cutover-a-apply": b"boca-cutover-a-prepared-go-v1:\x00",
        "official-notice-import": b"boca-official-notice-import-prepared-go-v1:\x00",
    }[operation]
    approval = hashlib.sha256(domain + _canonical(receipt)).hexdigest()
    go_var = {
        "cutover-a-apply": "BOCA_CUTOVER_A_GO_BINDING_SHA256",
        "official-notice-import": "BOCA_OFFICIAL_IMPORT_GO_BINDING_SHA256",
    }[operation]
    env[go_var] = approval
    for name, content in {
        "boca-protected-legacy-go.prepare-id": prep_id + "\n",
        "boca-protected-legacy-go.approved": approval + "\n",
        "boca-protected-legacy-go.receipt.json": _canonical(receipt).decode("ascii"),
    }.items():
        target = tmp_path / name
        target.write_text(content, encoding="ascii")
        target.chmod(0o600)
    return env, receipt


def _verify(env: dict[str, str], operation: str = "cutover-a-apply") -> prepared.PreparedGoProof:
    return prepared.verify_legacy_prepared_go(
        operation=operation,
        expected_public_context_sha256=lambda _prepare_id: "f" * 64,
        source_sha="a" * 40,
        release_run_id="42031822994",
        release_manifest_sha256="c" * 64,
        browser_manifest_sha256="d" * 64,
        bundle_sha256="e" * 64,
        owner_subject="owner",
        environ=env,
    )


@pytest.mark.parametrize("operation", ("cutover-a-apply", "official-notice-import"))
def test_canonical_go_b_from_independent_environment_receipt(
    tmp_path: Path, operation: str
) -> None:
    env, receipt = _record(tmp_path, operation)
    proof = _verify(env, operation)
    assert proof.prepare_run_id == receipt["prepare_run_id"]
    assert (
        proof.approved_sha256
        == env[
            "BOCA_CUTOVER_A_GO_BINDING_SHA256"
            if operation == "cutover-a-apply"
            else "BOCA_OFFICIAL_IMPORT_GO_BINDING_SHA256"
        ]
    )
    assert len(proof.receipt_sha256) == 64


@pytest.mark.parametrize(
    "change", ("missing_go", "wrong_context", "replay", "wrong_owner", "tamper")
)
def test_prepared_fail_closed_without_affecting_host(tmp_path: Path, change: str) -> None:
    env, receipt = _record(tmp_path)
    if change == "missing_go":
        env.pop("BOCA_CUTOVER_A_GO_BINDING_SHA256")
    elif change == "wrong_context":
        receipt["public_context_sha256"] = "0" * 64
    elif change == "replay":
        env["GITHUB_RUN_ID"] = receipt["prepare_run_id"]
    elif change == "wrong_owner":
        receipt["owner_subject_sha256"] = "1" * 64
    else:
        marker = tmp_path / "boca-protected-legacy-go.receipt.json"
        marker.write_bytes(marker.read_bytes() + b" ")
    if change in ("wrong_context", "wrong_owner"):
        (tmp_path / "boca-protected-legacy-go.receipt.json").write_bytes(_canonical(receipt))
    with pytest.raises(prepared.PreparedGoError):
        _verify(env)


def test_prepared_rejects_reused_domain_and_symlink(tmp_path: Path) -> None:
    env, _receipt = _record(tmp_path)
    with pytest.raises(prepared.PreparedGoError):
        _verify(env, "official-notice-import")
    target = tmp_path / "boca-protected-legacy-go.approved"
    moved = tmp_path / "reviewed-approved"
    target.rename(moved)
    target.symlink_to(moved)
    with pytest.raises(prepared.PreparedGoError):
        _verify(env)
