"""A45-R28 mobile lifecycle GO: one attested Boca host read, short APPLY run ID.

Synthetic runner fixtures only. NO SSH, Docker, GitHub API, BLACKBOX or host writes.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_protected_go_prepare as go  # noqa: E402


def _public() -> dict[str, str]:
    return {
        "version": "boca-protected-action-v1",
        "kind": "lifecycle",
        "source_sha": "a" * 40,
        "controller_id": "c" * 64,
        "controller_image": "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "d" * 64,
        "worker_id": "e" * 64,
        "worker_image": "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "f" * 64,
        "browser_attempt": "41800000000",
        "controller_config_hash": "1" * 64,
        "worker_config_hash": "2" * 64,
        "data_mountpoint": "/srv/boca-rootless/data",
        "expected_request_id": "12345678-1234-4123-8123-123456789abc",
        "expected_component": "bot",
        "expected_target": "stop",
    }


def _env(
    tmp: Path,
    *,
    attempt: str = "42000000000",
    operation: str = "protected-go-prepare",
) -> dict[str, str]:
    for name in (go._ARTIFACT_MANIFEST, go._ARTIFACT_BROWSER, go._ARTIFACT_BUNDLE):  # noqa: SLF001
        file = tmp / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("synthetic reviewed content " + name, encoding="utf-8")
    return {
        "GITHUB_REPOSITORY": "mbalbo2023/boca-socios-assistant",
        "GITHUB_ACTOR": "mbalbo2023",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": "a" * 40,
        "GITHUB_RUN_ID": attempt,
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "BOCA_SOURCE_SHA": "a" * 40,
        "BOCA_IMAGE_REF": _public()["controller_image"],
        "BOCA_BROWSER_IMAGE_REF": _public()["worker_image"],
        "BOCA_RELEASE_RUN_ID": "41800000000",
        "BOCA_SERVICE": "controller",
        "BOCA_OPERATION": operation,
        "BOCA_PROTECTED_ACTION_CONTEXT": "",
        "BOCA_BETA_OWNER_SUBJECT": "synthetic-test-owner",
        "RUNNER_TEMP": str(tmp),
    }


def _decode(encoded: str) -> dict[str, str]:
    return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))


def _token(body: dict[str, str]) -> str:
    return (
        base64.urlsafe_b64encode(go._canonical(body))  # noqa: SLF001
        .rstrip(b"=")
        .decode("ascii")
    )


def test_observer_input_is_runner_pinned_six_fields_without_user_host_ids(tmp_path: Path) -> None:
    env = _env(tmp_path)
    token = go.observer_request(env)
    assert not token.endswith("=")
    assert _decode(token) == {
        "version": "boca-lifecycle-observe-v1",
        "source_sha": env["BOCA_SOURCE_SHA"],
        "controller_image": env["BOCA_IMAGE_REF"],
        "worker_image": env["BOCA_BROWSER_IMAGE_REF"],
        "release_run_id": env["BOCA_RELEASE_RUN_ID"],
        "observe_run_id": env["GITHUB_RUN_ID"],
    }


@pytest.mark.parametrize(
    "edit",
    (
        {"BOCA_PROTECTED_ACTION_CONTEXT": "manually-crafted-json"},
        {"BOCA_OPERATION": "lifecycle-apply"},
        {"GITHUB_RUN_ID": "41800000000"},
        {"GITHUB_SHA": "b" * 40},
        {"GITHUB_ACTOR": "attacker"},
        {"BOCA_BROWSER_IMAGE_REF": "ghcr.io/other/worker@sha256:" + "f" * 64},
    ),
)
def test_observer_request_refuses_unreviewed_source_or_manual_pins(
    tmp_path: Path, edit: dict[str, str]
) -> None:
    with pytest.raises((go.PreparedGoError, go.context.ProtectedActionError)):
        go.observer_request(_env(tmp_path) | edit)


def test_observed_receipt_must_be_one_canonical_host_line_no_user_input(tmp_path: Path) -> None:
    env = _env(tmp_path)
    file = tmp_path / go.RUNNER_OBSERVE_CONTEXT
    file.write_bytes(go._canonical(_public()) + b"\n")  # noqa: SLF001
    assert go.observed_prepare_context(file, environ=env) == _public()
    for bad in (
        go._canonical(_public()),  # noqa: SLF001
        go._canonical(_public()) + b"\n\n",  # noqa: SLF001
        b'{"kind":"lifecycle","kind":"lifecycle"}\n',
        json.dumps(_public(), indent=2).encode("ascii") + b"\n",
        go._canonical(_public() | {"extra": "pin"}) + b"\n",  # noqa: SLF001
        go._canonical(_public() | {"controller_id": "e" * 64}) + b"\n",  # noqa: SLF001
        go._canonical(_public() | {"source_sha": "b" * 40}) + b"\n",  # noqa: SLF001
        go._canonical(_public() | {"expected_target": "erase"}) + b"\n",  # noqa: SLF001
    ):
        file.write_bytes(bad)
        with pytest.raises((go.PreparedGoError, go.context.ProtectedActionError)):
            go.observed_prepare_context(file, environ=env)
    file.write_bytes(go._canonical(_public()) + b"\n")  # noqa: SLF001
    with pytest.raises(go.PreparedGoError):
        go.observed_prepare_context(
            file, environ=env | {"BOCA_PROTECTED_ACTION_CONTEXT": _token(_public())}
        )


def test_observed_receipt_refuses_symlink_and_bogus_sender_partial(tmp_path: Path) -> None:
    env = _env(tmp_path)
    path = tmp_path / "observed.json"
    path.write_bytes(go._canonical(_public() | {"sender_id": "f" * 64}) + b"\n")  # noqa: SLF001
    with pytest.raises((go.PreparedGoError, go.context.ProtectedActionError)):
        go.observed_prepare_context(path, environ=env)
    shortcut = tmp_path / go.RUNNER_OBSERVE_CONTEXT
    shortcut.symlink_to(path)
    with pytest.raises(go.PreparedGoError):
        go.observed_prepare_context(shortcut, environ=env)


@pytest.mark.parametrize(
    "run_id",
    ("", "0", "01", "-1", "41800000000\n", " 41800000000", "abc", "9" * 21, _token(_public())),
)
def test_apply_rejects_any_non_short_canonical_run_id(tmp_path: Path, run_id: str) -> None:
    with pytest.raises(go.PreparedGoError):
        go.parse_prepared_run_id(run_id, environ=_env(tmp_path, operation="lifecycle-apply"))


def test_apply_run_id_ref_is_not_future_run_and_never_context_capability(tmp_path: Path) -> None:
    env = _env(tmp_path, operation="lifecycle-apply")
    assert go.parse_prepared_run_id("41999999999", environ=env) == "41999999999"
    with pytest.raises(go.PreparedGoError):
        go.parse_prepared_run_id(env["GITHUB_RUN_ID"], environ=env)


def test_apply_uses_only_artifact_token_matching_short_reviewed_prepare_id(tmp_path: Path) -> None:
    env = _env(tmp_path, operation="lifecycle-apply")
    ref = "41999999999"
    path = tmp_path / go.RUNNER_APPLY_CONTEXT
    path.write_text(_token(_public() | {"prepare_run_id": ref}) + "\n", encoding="ascii")
    public, hosted = go.public_from_prepared_artifact(path, prepare_run_id=ref, environ=env)
    assert public == _public()
    assert hosted["prepare_run_id"] == ref
    assert hosted["attempt_id"] == env["GITHUB_RUN_ID"]
    for changed in (
        _token(_public() | {"prepare_run_id": "41999999998"}) + "\n",
        _token(_public() | {"prepare_run_id": ref}) + "\n\n",
        _token(_public() | {"prepare_run_id": ref}),
        _token(_public() | {"prepare_run_id": ref, "unexpected": "field"}) + "\n",
        _token(_public() | {"prepare_run_id": ref, "source_sha": "b" * 40}) + "\n",
    ):
        path.write_text(changed, encoding="ascii")
        with pytest.raises((go.PreparedGoError, go.context.ProtectedActionError)):
            go.public_from_prepared_artifact(path, prepare_run_id=ref, environ=env)
    path.write_text(_token(_public() | {"prepare_run_id": ref}) + "\n", encoding="ascii")
    with pytest.raises(go.PreparedGoError):
        go.public_from_prepared_artifact(path, prepare_run_id=env["GITHUB_RUN_ID"], environ=env)


def test_observation_artifact_is_public_context_and_go_receipt_hash_only(tmp_path: Path) -> None:
    env = _env(tmp_path)
    path = tmp_path / go.RUNNER_OBSERVE_CONTEXT
    path.write_bytes(go._canonical(_public()) + b"\n")  # noqa: SLF001
    public = go.observed_prepare_context(path, environ=env)
    receipt = go.build_prepare_receipt(
        public, environ=env, now=go.datetime(2026, 11, 5, 14, 0, tzinfo=go.UTC)
    )
    expected_sha256 = go.hashlib.sha256(go._canonical(public)).hexdigest()  # noqa: SLF001
    assert receipt["public_context_sha256"] == expected_sha256
    assert receipt["operation"] == "lifecycle-apply"
    assert receipt["prepare_run_id"] == env["GITHUB_RUN_ID"]
    assert env["BOCA_BETA_OWNER_SUBJECT"] not in json.dumps(receipt)
    assert len(go.expected_go_for_receipt(receipt)) == 64


def test_go_receipt_is_specific_to_actual_observed_request_uuid(tmp_path: Path) -> None:
    env = _env(tmp_path)
    path = tmp_path / go.RUNNER_OBSERVE_CONTEXT
    first = _public()
    second = first | {"expected_request_id": "87654321-4321-4321-8123-abcdefabcdef"}
    path.write_bytes(go._canonical(first) + b"\n")  # noqa: SLF001
    first_receipt = go.build_prepare_receipt(
        go.observed_prepare_context(path, environ=env),
        environ=env,
        now=go.datetime(2026, 11, 5, 14, 0, tzinfo=go.UTC),
    )
    path.write_bytes(go._canonical(second) + b"\n")  # noqa: SLF001
    second_receipt = go.build_prepare_receipt(
        go.observed_prepare_context(path, environ=env),
        environ=env,
        now=go.datetime(2026, 11, 5, 14, 0, tzinfo=go.UTC),
    )
    assert first_receipt["public_context_sha256"] != second_receipt["public_context_sha256"]
    assert go.expected_go_for_receipt(first_receipt) != go.expected_go_for_receipt(second_receipt)
