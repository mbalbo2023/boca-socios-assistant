"""Fail-closed public-coordinate decoder for one shared protected Actions input.

No network, SSH, Docker, real Telegram payload or browser source is imported.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_protected_action_context as gate  # noqa: E402


def _context(kind: str = "lifecycle") -> dict[str, str]:
    common = {
        "version": "boca-protected-action-v1",
        "kind": kind,
        "attempt_id": "42000000000",
        "prepare_run_id": "41999999990",
        "source_sha": "a" * 40,
        "controller_id": "c" * 64,
        "controller_image": "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "d" * 64,
        "worker_id": "e" * 64,
        "worker_image": ("ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "f" * 64),
        "browser_attempt": "41900000000",
        "controller_config_hash": "1" * 64,
        "worker_config_hash": "2" * 64,
        "data_mountpoint": "/srv/boca-rootless/data",
    }
    if kind == "lifecycle":
        return common | {
            "expected_component": "bot",
            "expected_target": "stop",
            "expected_request_id": "12345678-1234-4123-8123-123456789abc",
        }
    common["data_mountpoint"] = "/data"
    return common | {
        "cutover_attempt": "41999999999",
        "cutover_receipt_sha256": "3" * 64,
        "owner_digest": "4" * 64,
        "recipient_fingerprint": "5" * 64,
        "sender_expected_state": "absent",
    }


def _encode(obj: object) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _env() -> dict[str, str]:
    return {
        "GITHUB_REPOSITORY": "mbalbo2023/boca-socios-assistant",
        "GITHUB_ACTOR": "mbalbo2023",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": "a" * 40,
        "GITHUB_RUN_ID": "42000000000",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "BOCA_SOURCE_SHA": "a" * 40,
        "BOCA_IMAGE_REF": _context()["controller_image"],
        "BOCA_BROWSER_IMAGE_REF": _context()["worker_image"],
        "BOCA_RELEASE_RUN_ID": "41999998888",
        "BOCA_SERVICE": "controller",
    }


@pytest.mark.parametrize(
    ("kind", "operation"), (("lifecycle", "lifecycle-apply"), ("telegram", "telegram-activate"))
)
def test_exact_context_binds_to_current_protected_actions(kind: str, operation: str) -> None:
    obj = _context(kind)
    decoded = gate.decode_context(_encode(obj), operation=operation, environ=_env())
    assert decoded == obj


@pytest.mark.parametrize(
    "bad",
    (
        {"kind": "telegram"},
        {"version": "future-unknown"},
        {"attempt_id": "42000000001"},
        {"source_sha": "0" * 40},
        {"worker_id": "c" * 64},
        {"controller_id": "d" * 63},
        {"expected_target": "restart"},
        {"expected_component": "porota"},
        {"expected_request_id": "12345678-1234-4123-8123-123456789abC"},
        {"additional_shell_command": "docker system prune"},
        {"telegram_token": "123:synthetic"},
        {"data_mountpoint": "../tmp"},
        {"browser_attempt": "0"},
    ),
)
def test_reject_changed_or_extra_lifecycle_coordinate(bad: dict[str, str]) -> None:
    obj = _context()
    obj.update(bad)
    with pytest.raises(gate.ProtectedActionError):
        gate.decode_context(_encode(obj), operation="lifecycle-apply", environ=_env())


def test_reject_duplicate_json_keys_noncanonical_base64_padding_and_oversize() -> None:
    raw = b'{"kind":"lifecycle","kind":"lifecycle"}'
    duplicate = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    for token in (duplicate, _encode(_context()) + "=", "A" * 4000, ""):
        with pytest.raises(gate.ProtectedActionError):
            gate.decode_context(token, operation="lifecycle-apply", environ=_env())


@pytest.mark.parametrize(
    "changed",
    (
        {"GITHUB_EVENT_NAME": "pull_request"},
        {"GITHUB_ACTOR": "foreign"},
        {"GITHUB_REF": "refs/heads/foreign"},
        {"GITHUB_RUN_ATTEMPT": "2"},
        {"BOCA_RELEASE_RUN_ID": ""},
        {"BOCA_SERVICE": "browser-worker"},
        {"BOCA_BROWSER_IMAGE_REF": ""},
    ),
)
def test_runner_authority_and_reviewed_release_are_mandatory(changed: dict[str, str]) -> None:
    env = _env()
    env.update(changed)
    with pytest.raises(gate.ProtectedActionError):
        gate.decode_context(_encode(_context()), operation="lifecycle-apply", environ=env)


def test_telegram_context_cannot_be_forged_with_human_start_time_or_secrets() -> None:
    obj = _context("telegram")
    for key, value in (
        ("staged_at", "2026-11-05T11:00:00Z"),
        ("nonce", "synthetic-nonce"),
        ("token", "synthetic-secret"),
        ("sender_state", "on"),
    ):
        changed = obj | {key: value}
        with pytest.raises(gate.ProtectedActionError):
            gate.decode_context(_encode(changed), operation="telegram-activate", environ=_env())


def test_obsolete_single_dispatch_go_entrypoint_is_permanently_no_go(
    capsys: pytest.CaptureFixture[str],
) -> None:
    obj = _context()
    env = _env()
    decoded = gate.decode_context(_encode(obj), operation="lifecycle-apply", environ=env)
    assert decoded == obj
    assert not hasattr(gate, "expected_go_binding")
    assert not hasattr(gate, "require_go_binding")
    changed = env | {"GITHUB_RUN_ID": "42000000001"}
    with pytest.raises(gate.ProtectedActionError):
        gate.decode_context(_encode(obj), operation="lifecycle-apply", environ=changed)
    assert gate.main() == 2
    assert "state=NO_GO host=untouched" in capsys.readouterr().err


@pytest.mark.parametrize(
    "bad_sender",
    (
        {"sender_id": "7" * 64},
        {
            "sender_id": "7" * 64,
            "sender_config_hash": "8" * 64,
            "sender_attempt_id": "1",
            "sender_state": "enabled",
        },
        {
            "sender_id": "c" * 64,
            "sender_config_hash": "8" * 64,
            "sender_attempt_id": "1",
            "sender_state": "off",
        },
    ),
)
def test_lifecycle_sender_pin_quartet_is_exact_or_absent(
    bad_sender: dict[str, str],
) -> None:
    obj = _context() | bad_sender
    with pytest.raises(gate.ProtectedActionError):
        gate.decode_context(_encode(obj), operation="lifecycle-apply", environ=_env())
    valid = _context() | {
        "sender_id": "7" * 64,
        "sender_config_hash": "8" * 64,
        "sender_attempt_id": "123",
        "sender_state": "off",
    }
    assert gate.decode_context(_encode(valid), operation="lifecycle-apply", environ=_env()) == valid


def test_telegram_absent_vs_stopped_sender_state_requires_exact_pins() -> None:
    absent = _context("telegram")
    assert (
        gate.decode_context(_encode(absent), operation="telegram-activate", environ=_env())
        == absent
    )
    stopped = absent | {
        "sender_expected_state": "stopped",
        "sender_id": "7" * 64,
        "sender_image": absent["controller_image"],
        "sender_config_hash": "8" * 64,
        "sender_attempt": "123456789",
    }
    assert (
        gate.decode_context(_encode(stopped), operation="telegram-activate", environ=_env())
        == stopped
    )
    # Each mutation must actually change or REMOVE a validated field.
    malformed = (
        absent | {"sender_expected_state": "stopped"},
        stopped | {"sender_expected_state": "absent"},
        {key: value for key, value in stopped.items() if key != "sender_image"},
        stopped | {"sender_image": absent["worker_image"]},
        stopped | {"sender_attempt": "0"},
    )
    for changed in malformed:
        with pytest.raises(gate.ProtectedActionError):
            gate.decode_context(_encode(changed), operation="telegram-activate", environ=_env())


@pytest.mark.parametrize(
    "bad_request_id",
    (
        "",
        "12345678-1234-4123-8123-123456789abC",
        "12345678-1234-5123-8123-123456789abc",
        "12345678-1234-4123-7123-123456789abc",
        "12345678123441238123123456789abc",
        "00000000-0000-0000-0000-000000000000",
    ),
)
def test_lifecycle_go_requires_one_canonical_v4_request_uuid(bad_request_id: str) -> None:
    obj = _context()
    obj["expected_request_id"] = bad_request_id
    with pytest.raises(gate.ProtectedActionError):
        gate.decode_context(_encode(obj), operation="lifecycle-apply", environ=_env())


def test_missing_expected_request_id_does_not_fall_back_to_component_and_target() -> None:
    obj = _context()
    del obj["expected_request_id"]
    with pytest.raises(gate.ProtectedActionError):
        gate.decode_context(_encode(obj), operation="lifecycle-apply", environ=_env())
