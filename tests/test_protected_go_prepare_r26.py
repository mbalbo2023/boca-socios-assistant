"""R26 synthetic proof of two separately dispatched, independently reviewed GO phases.

No GitHub API writes, SSH, Docker, Telegram, BLACKBOX, live browser, or host.
The real physical replay marker is owned by #351.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_protected_go_prepare as go  # noqa: E402


def _static() -> dict[str, str]:
    return {
        "version": "boca-protected-action-v1",
        "kind": "lifecycle",
        "source_sha": "a" * 40,
        "controller_id": "c" * 64,
        "controller_image": "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "d" * 64,
        "worker_id": "e" * 64,
        "worker_image": (
            "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "f" * 64
        ),
        "browser_attempt": "41990000000",
        "controller_config_hash": "1" * 64,
        "worker_config_hash": "2" * 64,
        "data_mountpoint": "/srv/boca-rootless/data",
        "expected_component": "bot",
        "expected_target": "stop",
    }


def _token(data: dict[str, str]) -> str:
    body = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return base64.urlsafe_b64encode(body.encode("ascii")).rstrip(b"=").decode("ascii")


def _env(tmp_path: Path, run_id: str) -> dict[str, str]:
    files = {
        go._ARTIFACT_MANIFEST: b"reviewed controller manifest bytes",  # noqa: SLF001
        go._ARTIFACT_BROWSER: b"reviewed browser manifest bytes",  # noqa: SLF001
        go._ARTIFACT_BUNDLE: b"reviewed exact Option B ZIP bytes",  # noqa: SLF001
    }
    for relative, blob in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    return {
        "GITHUB_REPOSITORY": "mbalbo2023/boca-socios-assistant",
        "GITHUB_ACTOR": "mbalbo2023",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": "a" * 40,
        "GITHUB_RUN_ID": run_id,
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "BOCA_SOURCE_SHA": "a" * 40,
        "BOCA_IMAGE_REF": _static()["controller_image"],
        "BOCA_BROWSER_IMAGE_REF": _static()["worker_image"],
        "BOCA_RELEASE_RUN_ID": "41800000000",
        "BOCA_SERVICE": "controller",
        "BOCA_BETA_OWNER_SUBJECT": "synthetic-owner-for-test-only",
        "RUNNER_TEMP": str(tmp_path),
    }


def _source_run(source_id: str) -> dict[str, object]:
    return {
        "id": int(source_id),
        "event": "workflow_dispatch",
        "run_attempt": 1,
        "status": "completed",
        "conclusion": "success",
        "head_sha": "a" * 40,
        "head_branch": "main",
        "path": ".github/workflows/boca-first-deploy.yml",
        "actor": {"login": "mbalbo2023"},
        "repository": {"full_name": "mbalbo2023/boca-socios-assistant"},
    }


def _prepared(
    tmp_path: Path,
) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str], str]:
    prepare_env = _env(tmp_path, "41999999999")
    static = go.decode_prepare_input(_token(_static()), environ=prepare_env)
    start = datetime(2026, 11, 5, 14, 30, tzinfo=UTC)
    prepared = go.build_prepare_receipt(static, environ=prepare_env, now=start)
    approved = go.expected_go_for_receipt(prepared)
    apply_env = _env(tmp_path, "42000000000")
    input_public, hosted = go.decode_apply_input(
        _token(static | {"prepare_run_id": prepare_env["GITHUB_RUN_ID"]}),
        environ=apply_env,
    )
    return input_public, hosted, prepared, apply_env, approved


def test_prepare_and_apply_use_distinct_known_and_runtime_generated_ids(tmp_path: Path) -> None:
    public, hosted, receipt, env, approved = _prepared(tmp_path)
    assert "attempt_id" not in public
    assert "attempt_id" not in _static()
    assert hosted["attempt_id"] == env["GITHUB_RUN_ID"]
    assert hosted["prepare_run_id"] == receipt["prepare_run_id"]
    assert hosted["prepare_run_id"] != hosted["attempt_id"]
    assert receipt["prepare_attempt"] == "1"
    assert receipt["operation"] == "lifecycle-apply"
    assert len(approved) == 64 and approved.isascii()
    assert env["BOCA_BETA_OWNER_SUBJECT"] not in json.dumps(receipt)
    assert go.verify_apply_go(
        public,
        hosted,
        receipt,
        environ=env,
        approved=approved,
        now=datetime(2026, 11, 5, 15, 30, tzinfo=UTC),
        source_run=_source_run(receipt["prepare_run_id"]),
    ) == approved


def test_future_run_id_cannot_be_in_prepare_dispatch_token(tmp_path: Path) -> None:
    env = _env(tmp_path, "41999999999")
    with pytest.raises(go.PreparedGoError):
        go.decode_prepare_input(
            _token(_static() | {"attempt_id": "42000000000"}), environ=env
        )
    with pytest.raises(go.PreparedGoError):
        go.decode_apply_input(_token(_static()), environ=_env(tmp_path, "42000000000"))


def test_second_phase_requires_exact_external_go_and_same_artifacts(tmp_path: Path) -> None:
    public, hosted, receipt, env, approved = _prepared(tmp_path)
    now = datetime(2026, 11, 5, 15, 0, tzinfo=UTC)
    run = _source_run(receipt["prepare_run_id"])
    with pytest.raises(go.PreparedGoError, match="GO"):
        go.verify_apply_go(
            public, hosted, receipt, environ=env, approved="0" * 64,
            now=now, source_run=run
        )
    with pytest.raises(go.PreparedGoError, match="GO"):
        go.verify_apply_go(
            public, hosted, receipt, environ=env, approved="",
            now=now, source_run=run
        )
    (tmp_path / go._ARTIFACT_BROWSER).write_bytes(b"tampered after PREPARE")  # noqa: SLF001
    with pytest.raises(go.PreparedGoError, match="drifted"):
        go.verify_apply_go(
            public, hosted, receipt, environ=env, approved=approved,
            now=now, source_run=run
        )


def test_prepared_digest_binds_owner_operation_and_prepared_run(tmp_path: Path) -> None:
    public, hosted, receipt, env, approved = _prepared(tmp_path)
    for mutation in (
        {"operation": "telegram-activate"},
        {"prepare_run_id": "41999999998"},
        {"owner_subject_sha256": "0" * 64},
        {"source_sha": "0" * 40},
    ):
        altered = receipt | mutation
        assert go.expected_go_for_receipt(altered) != approved
        with pytest.raises(go.PreparedGoError):
            go.verify_apply_go(
                public, hosted, altered, environ=env, approved=approved,
                now=datetime(2026, 11, 5, 15, tzinfo=UTC),
                source_run=_source_run(receipt["prepare_run_id"])
            )


def test_prepared_go_expires_and_requires_real_successful_original_dispatch(tmp_path: Path) -> None:
    public, hosted, receipt, env, approved = _prepared(tmp_path)
    for now in (
        datetime(2026, 11, 6, 14, 30, 1, tzinfo=UTC),
        datetime(2026, 11, 5, 14, 20, tzinfo=UTC),
    ):
        with pytest.raises(go.PreparedGoError, match="expired"):
            go.verify_apply_go(
                public, hosted, receipt, environ=env, approved=approved,
                now=now, source_run=_source_run(receipt["prepare_run_id"])
            )
    for mutation in (
        {"event": "pull_request"},
        {"conclusion": "skipped"},
        {"run_attempt": 2},
        {"head_branch": "feature"},
        {"id": int(receipt["prepare_run_id"]) + 1},
    ):
        with pytest.raises(go.PreparedGoError, match="not independently attested"):
            go.verify_apply_go(
                public, hosted, receipt, environ=env, approved=approved,
                now=datetime(2026, 11, 5, 15, tzinfo=UTC),
                source_run=_source_run(receipt["prepare_run_id"]) | mutation
            )


def test_public_approved_digest_not_equivalent_to_host_authorization(tmp_path: Path) -> None:
    public, hosted, receipt, env, approved = _prepared(tmp_path)
    other_attempt = dict(hosted)
    other_attempt["attempt_id"] = "42000000001"
    assert hashlib.sha256(go._canonical(other_attempt)).hexdigest() != hashlib.sha256(  # noqa: SLF001
        go._canonical(hosted)  # noqa: SLF001
    ).hexdigest()
    # Forged attempt under one runner identity must fail in the runner.
    with pytest.raises(go.PreparedGoError):
        go.verify_apply_go(
            public, other_attempt, receipt, environ=env, approved=approved,
            now=datetime(2026, 11, 5, 15, tzinfo=UTC),
            source_run=_source_run(receipt["prepare_run_id"])
        )
    # A DIFFERENT genuine APPLY run could still pass a 24h prepared GO;
    # the host #351 O_EXCL marker on PREPARE ID must reject reuse.
    second_env = env | {"GITHUB_RUN_ID": "42000000001"}
    encoded = _token(public | {"prepare_run_id": receipt["prepare_run_id"]})
    _, newly_hosted = go.decode_apply_input(encoded, environ=second_env)
    assert go.verify_apply_go(
        public, newly_hosted, receipt, environ=second_env, approved=approved,
        now=datetime(2026, 11, 5, 15, tzinfo=UTC),
        source_run=_source_run(receipt["prepare_run_id"])
    ) == approved


def test_physical_lifecycle_receipt_must_be_single_exact_applied_json(
    tmp_path: Path,
) -> None:
    _, hosted, _, env, _ = _prepared(tmp_path)
    env.update({
        "BOCA_LIFECYCLE_GO_PREFLIGHT": "success",
        "BOCA_LIFECYCLE_HOST_APPLY": "success",
    })
    (tmp_path / go.RUNNER_HOST_CONTEXT).write_text(_token(hosted) + "\\n")
    path = tmp_path / "boca-lifecycle-host.receipt"
    accepted = {
        "version": 1,
        "scope": "boca-lifecycle",
        "attempt": hosted["attempt_id"],
        "prepare_run_id": hosted["prepare_run_id"],
        "request_id": "aaaaaaa1-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        "source_sha": hosted["source_sha"],
        "component": hosted["expected_component"],
        "target": hosted["expected_target"],
        "status": "APPLIED",
        "physical_ack": True,
    }
    path.write_text(json.dumps(accepted, sort_keys=True, separators=(",", ":")) + "\\n")
    go.assert_physical_host_receipt(env)
    for changed in (
        {"status": "REFUSED"},
        {"physical_ack": False},
        {"prepare_run_id": "111"},
        {"attempt": "111"},
        {"request_id": "123"},
        {"extra": "unexpected"},
    ):
        path.write_text(json.dumps(accepted | changed, sort_keys=True, separators=(",", ":")) + "\\n")
        with pytest.raises(go.PreparedGoError):
            go.assert_physical_host_receipt(env)
    path.write_text(json.dumps(accepted, sort_keys=True, separators=(",", ":")) + "\\n\\n")
    with pytest.raises(go.PreparedGoError):
        go.assert_physical_host_receipt(env)
    env["BOCA_LIFECYCLE_HOST_APPLY"] = "failure"
    with pytest.raises(go.PreparedGoError):
        go.assert_physical_host_receipt(env)
