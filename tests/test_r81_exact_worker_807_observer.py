"""R81 TDD: incident #807 read-only inventory must not change #795 semantics."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts import host_cutover_worker_inspect as observer  # noqa: E402

R81_ATTEMPT = "42341290485"
R86_ATTEMPT = "42353468231"
R81_SOURCE = "1199c46fee8053e637b220ad9365ce3af15eb8e5"
R81_BROWSER = (
    "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
    "c31b41f0fd6332d9d4946d4047c7eb1e58e53ba04ad2ffdedfbb7aa54bcaaa04"
)
R78_ATTEMPT = "42329475083"
R78_SOURCE = "92624ed6b7e75c6010f59670c866df00a29766dd"
R78_BROWSER = (
    "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
    "3894cfff995858d7c0ffdb994180a0d28a8a92bb69a0526fb040db2297fd8bf9"
)
LEGACY_ID = "27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793"
LEGACY_SOURCE = "cabce9f1e452e63ded115f447559a358dc0f4d1b"
LEGACY_IMAGE = (
    "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:"
    "cf6e4266cfcfea0c07fa31301d59c7aaa3b9c2fefb9f6843baddd208cacd3b59"
)
PROBE_ID = "65" * 32


def _probe(
    *, attempt: str = R81_ATTEMPT, source: str = R81_SOURCE, image: str = R81_BROWSER
) -> dict[str, object]:
    return {
        "id": PROBE_ID,
        "name": f"/boca-socios-cutover-preflight-{attempt}",
        "image_ref": image,
        "revision": source,
        "project": "boca-socios",
        "attempt": attempt,
        "running": False,
        "health": None,
        "ports": {},
    }


def _legacy() -> dict[str, object]:
    return {
        "id": LEGACY_ID,
        "name": "/boca-socios-controller-1",
        "image_ref": LEGACY_IMAGE,
        "revision": LEGACY_SOURCE,
        "project": "boca-socios",
        "attempt": None,
        "running": True,
        "health": "healthy",
        "ports": {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]},
    }


def _rootless(monkeypatch: pytest.MonkeyPatch, *, seccomp: str = "ABSENT") -> None:
    monkeypatch.setattr(observer.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(observer.os, "getegid", lambda: 10001)
    monkeypatch.setattr(
        observer,
        "_runtime_stat",
        lambda name: "PRESENT_OWNED" if name == "docker.sock" else seccomp,
    )


def _docker_fixture(
    monkeypatch: pytest.MonkeyPatch,
    *,
    attempt: str = R81_ATTEMPT,
    probe: dict[str, object] | None = None,
    present: bool = True,
    full_size: str = "54321",
    original: dict[str, object] | None = None,
) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []
    worker = _probe(attempt=attempt) if probe is None else probe
    legacy = _legacy() if original is None else original

    def docker(*args: str) -> str:
        calls.append(args)
        if args[0] == "ps":
            assert args == (
                "ps",
                "-a",
                "-q",
                "--no-trunc",
                "--filter",
                f"name=^/boca-socios-cutover-preflight-{attempt}$",
            )
            return PROBE_ID if present else ""
        assert args[:2] == ("inspect", "--format") and len(args) == 4
        if args[3] == PROBE_ID:
            assert present
            if args[2] == observer.INSPECT_FULL_JSON_LENGTH:
                return full_size
            assert args[2] == observer.INSPECT_NO_HEALTH
            return json.dumps(worker)
        assert args[3] == LEGACY_ID and args[2] == observer.INSPECT
        return json.dumps(legacy)

    monkeypatch.setattr(observer, "_docker", docker)
    return calls


def test_r81_present_exact_pin_only_four_readonly_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A current #807 digest must attest; old #795-only map rejects it (RED)."""
    _rootless(monkeypatch)
    calls = _docker_fixture(monkeypatch)

    record = observer.observe(R81_ATTEMPT, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)

    assert record["probe"] == "PRESENT_PIN_MATCH"
    assert record["probe_id"] == PROBE_ID
    assert record["probe_running"] is False
    assert record["probe_full_json_stage"] == "BELOW_CLEANUP_LIMIT"
    assert record["original"] == "RUNNING_HEALTHY"
    assert record["original_port"] == "LOOPBACK_8443"
    assert record["observer_writes"] == 0
    assert record["foreign_resources_touched"] is False
    assert record["cutover_authorized"] is False
    assert len(calls) == 4
    assert observer.verify(observer.canonical(record) + b"\n", R81_ATTEMPT, LEGACY_ID) == record


def test_r81_absent_worker_is_not_a_cleanup_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No CID still yields only a READ_ONLY inventory, never Cutover authorization."""
    _rootless(monkeypatch, seccomp="PRESENT_OWNED")
    calls = _docker_fixture(monkeypatch, present=False)

    result = observer.observe(R81_ATTEMPT, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)

    assert result["probe"] == "ABSENT"
    assert result["probe_candidate_id"] is None
    assert result["probe_list_stage"] == "ABSENT"
    assert result["probe_inspect_stage"] == "SKIPPED"
    assert result["probe_full_json_stage"] == "SKIPPED"
    assert result["seccomp"] == "PRESENT_OWNED"
    assert result["original"] == "RUNNING_HEALTHY"
    assert result["observer_writes"] == 0
    assert result["cutover_authorized"] is False
    assert len(calls) == 2
    observer.verify(observer.canonical(result) + b"\n", R81_ATTEMPT, LEGACY_ID)


@pytest.mark.parametrize(
    ("changed", "value"),
    [
        ("revision", R78_SOURCE),
        ("revision", "f" * 40),
        ("image_ref", R78_BROWSER),
        ("image_ref", "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "e" * 64),
        ("attempt", R78_ATTEMPT),
        ("name", f"/boca-socios-cutover-preflight-{R78_ATTEMPT}"),
        ("project", "foreign-project"),
        ("id", "f" * 64),
    ],
)
def test_r81_mismatched_metadata_cannot_attest_new_probe(
    monkeypatch: pytest.MonkeyPatch, changed: str, value: str
) -> None:
    """Any one mismatching Boca immutable pin must preserve only a candidate CID."""
    _rootless(monkeypatch)
    forged = {**_probe(), changed: value}
    calls = _docker_fixture(monkeypatch, probe=forged)

    result = observer.observe(R81_ATTEMPT, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)

    assert result["probe"] == "PRESENT_UNVERIFIED"
    assert result["probe_candidate_id"] == PROBE_ID
    assert result["probe_id"] is None
    assert result["probe_inspect_stage"] in {"IDENTITY_MISMATCH", "METADATA_INVALID"}
    assert result["original"] == "RUNNING_HEALTHY"
    assert result["cutover_authorized"] is False
    assert len(calls) == 4
    observer.verify(observer.canonical(result) + b"\n", R81_ATTEMPT, LEGACY_ID)


def test_r81_above_cleanup_size_never_implies_safe_removal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _rootless(monkeypatch)
    calls = _docker_fixture(monkeypatch, full_size="65536")

    result = observer.observe(R81_ATTEMPT, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)

    assert result["probe_full_json_stage"] == "AT_OR_ABOVE_CLEANUP_LIMIT"
    assert result["probe"] == "PRESENT_PIN_MATCH"  # compact pins, not full isolation
    assert result["observer_writes"] == 0
    assert result["cutover_authorized"] is False
    assert len(calls) == 4
    observer.verify(observer.canonical(result) + b"\n", R81_ATTEMPT, LEGACY_ID)


def test_r81_running_probe_is_readonly_no_go(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _rootless(monkeypatch)
    calls = _docker_fixture(monkeypatch, probe={**_probe(), "running": True})

    result = observer.observe(R81_ATTEMPT, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)

    assert result["probe"] == "PRESENT_PIN_MATCH"
    assert result["probe_running"] is True
    assert result["observer_writes"] == 0
    assert result["cutover_authorized"] is False
    assert len(calls) == 4
    observer.verify(observer.canonical(result) + b"\n", R81_ATTEMPT, LEGACY_ID)


@pytest.mark.parametrize("duplicate", ["id", "revision", "image_ref"])
def test_r81_duplicate_compact_docker_key_must_not_attest_identity(
    monkeypatch: pytest.MonkeyPatch, duplicate: str
) -> None:
    """Last-wins JSON keys must not promote an ambiguous inspect into a pinned CID."""
    _rootless(monkeypatch)
    calls = _docker_fixture(monkeypatch)
    original_docker = observer._docker

    def forged_docker(*args: str) -> str:
        raw = original_docker(*args)
        if (
            args[:2] == ("inspect", "--format")
            and args[3] == PROBE_ID
            and args[2] == observer.INSPECT_NO_HEALTH
        ):
            replaced = raw.replace(f'"{duplicate}":', f'"{duplicate}":"ATTACKER","{duplicate}":', 1)
            assert replaced != raw
            return replaced
        return raw

    monkeypatch.setattr(observer, "_docker", forged_docker)
    result = observer.observe(R81_ATTEMPT, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)

    assert result["probe"] == "PRESENT_UNVERIFIED"
    assert result["probe_candidate_id"] == PROBE_ID
    assert result["probe_id"] is None
    assert result["probe_inspect_stage"] == "METADATA_INVALID"
    assert result["original"] == "RUNNING_HEALTHY"
    assert result["cutover_authorized"] is False
    assert len(calls) == 4
    observer.verify(observer.canonical(result) + b"\n", R81_ATTEMPT, LEGACY_ID)


def test_r81_legacy_unhealthy_does_not_hide_exact_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _rootless(monkeypatch)
    unhealthy = {**_legacy(), "health": "starting"}
    calls = _docker_fixture(monkeypatch, original=unhealthy)

    result = observer.observe(R81_ATTEMPT, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)

    assert result["probe"] == "PRESENT_PIN_MATCH"
    assert result["original"] == "RUNNING_OTHER"
    assert result["original_port"] == "LOOPBACK_8443"
    assert result["cutover_authorized"] is False
    assert len(calls) == 4
    observer.verify(observer.canonical(result) + b"\n", R81_ATTEMPT, LEGACY_ID)


def test_r81_independent_original_failure_preserves_probe_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _rootless(monkeypatch)
    calls: list[tuple[str, ...]] = []

    def docker(*args: str) -> str:
        calls.append(args)
        if args[0] == "ps":
            return PROBE_ID
        if args[3] == PROBE_ID:
            return "54321" if args[2] == observer.INSPECT_FULL_JSON_LENGTH else json.dumps(_probe())
        assert args[3] == LEGACY_ID
        raise subprocess.CalledProcessError(1, ["docker", "inspect"], stderr="SECRET_807")

    monkeypatch.setattr(observer, "_docker", docker)
    result = observer.observe(R81_ATTEMPT, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)

    assert result["probe"] == "PRESENT_PIN_MATCH"
    assert result["probe_full_json_stage"] == "BELOW_CLEANUP_LIMIT"
    assert result["original"] == "UNVERIFIED"
    assert result["original_inspect_stage"] == "COMMAND_FAILED"
    assert result["original_inspect_rc"] == 1
    assert result["docker"] == "PARTIAL"
    assert b"SECRET_807" not in observer.canonical(result)
    assert len(calls) == 4
    observer.verify(observer.canonical(result) + b"\n", R81_ATTEMPT, LEGACY_ID)


def test_r81_probe_disappears_during_inspect_without_fabricating_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One successful ps isn't proof of current probe ownership after a Docker race."""
    _rootless(monkeypatch)
    calls: list[tuple[str, ...]] = []

    def docker(*args: str) -> str:
        calls.append(args)
        if args[0] == "ps":
            return PROBE_ID
        if args[3] == PROBE_ID:
            raise subprocess.CalledProcessError(1, ["docker", "inspect"], stderr="PRIVATE_807")
        assert args[3] == LEGACY_ID
        return json.dumps(_legacy())

    monkeypatch.setattr(observer, "_docker", docker)
    result = observer.observe(R81_ATTEMPT, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)

    assert result["probe"] == "PRESENT_UNVERIFIED"
    assert result["probe_candidate_id"] == PROBE_ID
    assert result["probe_id"] is None
    assert result["probe_inspect_stage"] == "COMMAND_FAILED"
    assert result["probe_full_json_stage"] == "COMMAND_FAILED"
    assert result["original"] == "RUNNING_HEALTHY"
    assert result["docker"] == "PARTIAL"
    assert result["observer_writes"] == 0
    assert len(calls) == 4
    assert b"PRIVATE_807" not in observer.canonical(result)
    observer.verify(observer.canonical(result) + b"\n", R81_ATTEMPT, LEGACY_ID)


def test_historic_r78_pins_still_attest_same_stopped_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adding #807 must not silently reassign or invalidate the old #795 mapping."""
    _rootless(monkeypatch)
    calls = _docker_fixture(
        monkeypatch,
        attempt=R78_ATTEMPT,
        probe=_probe(attempt=R78_ATTEMPT, source=R78_SOURCE, image=R78_BROWSER),
    )
    result = observer.observe(R78_ATTEMPT, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)
    assert result["probe"] == "PRESENT_PIN_MATCH"
    assert result["probe_full_json_stage"] == "BELOW_CLEANUP_LIMIT"
    assert result["original"] == "RUNNING_HEALTHY"
    assert len(calls) == 4
    observer.verify(observer.canonical(result) + b"\n", R78_ATTEMPT, LEGACY_ID)


@pytest.mark.parametrize("unknown", ["42341290484", "42341290486", "807", "0", "x"])
def test_unreviewed_attempt_fails_before_any_host_read(
    monkeypatch: pytest.MonkeyPatch, unknown: str
) -> None:
    monkeypatch.setattr(observer, "_runtime_stat", lambda _name: pytest.fail("host lstat"))
    monkeypatch.setattr(observer, "_docker", lambda *_args: pytest.fail("Docker read"))
    with pytest.raises(observer.InspectError):
        observer.observe(unknown, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)


def test_unreviewed_attempt_cannot_forge_a_verified_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _rootless(monkeypatch)
    _docker_fixture(monkeypatch, present=False)
    record = observer.observe(R81_ATTEMPT, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)
    record["attempt"] = "42341290486"
    with pytest.raises(observer.InspectError):
        observer.verify(observer.canonical(record) + b"\n", "42341290486", LEGACY_ID)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observer_writes", 1),
        ("foreign_resources_touched", True),
        ("cutover_authorized", True),
        ("version", "boca-worker-recovery-v1"),
        ("legacy_id", "f" * 64),
        ("probe_list_stage", "OK"),
    ],
)
def test_r81_hostile_receipt_is_rejected(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    _rootless(monkeypatch)
    _docker_fixture(monkeypatch, present=False)
    record = observer.observe(R81_ATTEMPT, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)
    record[field] = value
    with pytest.raises((observer.InspectError, ValueError)):
        observer.verify(observer.canonical(record) + b"\n", R81_ATTEMPT, LEGACY_ID)


def test_r81_duplicate_receipt_key_cannot_override_observer_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _rootless(monkeypatch)
    _docker_fixture(monkeypatch, present=False)
    record = observer.observe(R81_ATTEMPT, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)
    raw = observer.canonical(record) + b"\n"
    corrupted = raw.replace(b'"observer_writes":0', b'"observer_writes":1,"observer_writes":0')
    assert corrupted != raw
    with pytest.raises((observer.InspectError, ValueError)):
        observer.verify(corrupted, R81_ATTEMPT, LEGACY_ID)


def test_r81_cli_verify_reports_readonly_no_go_even_for_clean_inventory(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _rootless(monkeypatch)
    _docker_fixture(monkeypatch, present=False)
    record = observer.observe(R81_ATTEMPT, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)
    monkeypatch.setattr(
        observer.sys,
        "stdin",
        io.TextIOWrapper(io.BytesIO(observer.canonical(record) + b"\n"), encoding="ascii"),
    )

    status = observer.main(["verify", R81_ATTEMPT, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE])

    assert status == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert f"BOCA_WORKER_INSPECT state=READ_ONLY_NO_GO attempt={R81_ATTEMPT}" in captured.out
    assert "observer_writes=0 retry=NO_GO" in captured.out


def _workflow_gate() -> str:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    first = "            cutover-a-worker-inspect)\n"
    last = "            cutover-a-stage-recover|cutover-a-image-retire)"
    assert workflow.count(first) == 1
    gate = workflow.split(first, 1)[1].split(last, 1)[0].rstrip()
    assert gate.endswith(";;")
    # Execute the actual guarded shell branch, not a textual assertion that it exists.
    return "set -euo pipefail\n" + gate.removesuffix(";;")


def _gate_env(attempt: str = R81_ATTEMPT, **changes: str) -> dict[str, str]:
    values = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "BOCA_HOST_READONLY_ENV_READY": "ready",
        "BOCA_DEPLOY_ENV_READY": "ready",
        "BOCA_PROTECTED_ACTION_CONTEXT": attempt,
        "BOCA_LEGACY_CONTROLLER_ID": LEGACY_ID,
        "BOCA_LEGACY_SOURCE_SHA": LEGACY_SOURCE,
        "BOCA_LEGACY_IMAGE_REF": LEGACY_IMAGE,
        "BOCA_LEGACY_RELEASE_RUN_ID": "",
        "BOCA_SOURCE_SHA_SUBMITTED": "",
        "BOCA_IMAGE_REF": "",
        "BOCA_BROWSER_IMAGE_REF": "",
        "BOCA_RELEASE_RUN_ID": "",
        "BOCA_SITE_ENVELOPE": "",
        "BOCA_TELEGRAM_ENVELOPE": "",
        "BOCA_OWNER_ENVELOPE": "",
        "BOCA_OWNER_CAPABILITY_SHA256": "",
        "BOCA_FAILED_TELEGRAM_RUN_ID": "",
        "BOCA_OFFICIAL_CONTROLLER_ID": "",
        "BOCA_OFFICIAL_NEWS_RUN_ID": "",
        "BOCA_OFFICIAL_NEWS_SOURCE_SHA": "",
        "BOCA_OFFICIAL_NEWS_ARTIFACT_ID": "",
        "BOCA_OFFICIAL_NEWS_ZIP_SHA256": "",
        "BOCA_OFFICIAL_NEWS_JSONL_SHA256": "",
        "BOCA_OFFICIAL_NEWS_HTML_SHA256": "",
        "BOCA_OFFICIAL_NEWS_OBSERVED_AT_UTC": "",
    }
    values.update(changes)
    return values


@pytest.mark.parametrize("attempt", [R78_ATTEMPT, R81_ATTEMPT, R86_ATTEMPT])
def test_workflow_shell_gate_accepts_only_three_protected_readonly_incidents(
    attempt: str,
) -> None:
    result = subprocess.run(  # noqa: S603 - local bash evaluates isolated input gate only
        ("/bin/bash", "-c", _workflow_gate()),
        capture_output=True,
        text=True,
        env=_gate_env(attempt),
        timeout=3,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "changes",
    [
        {"BOCA_PROTECTED_ACTION_CONTEXT": "42341290486"},
        {"BOCA_PROTECTED_ACTION_CONTEXT": "42353468230"},
        {"BOCA_PROTECTED_ACTION_CONTEXT": "42353468232"},
        {"BOCA_PROTECTED_ACTION_CONTEXT": "42341290485; echo UNAUTHORIZED"},
        {"BOCA_LEGACY_CONTROLLER_ID": "f" * 64},
        {"BOCA_LEGACY_SOURCE_SHA": "f" * 40},
        {"BOCA_LEGACY_IMAGE_REF": R81_BROWSER},
        {"BOCA_LEGACY_RELEASE_RUN_ID": "42340930071"},
        {"BOCA_SOURCE_SHA_SUBMITTED": R81_SOURCE},
        {"BOCA_IMAGE_REF": R81_BROWSER},
        {"BOCA_BROWSER_IMAGE_REF": R81_BROWSER},
        {"BOCA_RELEASE_RUN_ID": "42340930071"},
        {"BOCA_SITE_ENVELOPE": "hostile"},
        {"BOCA_TELEGRAM_ENVELOPE": "hostile"},
        {"BOCA_OFFICIAL_NEWS_RUN_ID": "42340930071"},
        {"BOCA_HOST_READONLY_ENV_READY": ""},
        {"BOCA_DEPLOY_ENV_READY": ""},
    ],
)
def test_workflow_shell_gate_rejects_unreviewed_inputs(changes: dict[str, str]) -> None:
    result = subprocess.run(  # noqa: S603 - no SSH/host, only local gate statements
        ("/bin/bash", "-c", _workflow_gate()),
        capture_output=True,
        text=True,
        env=_gate_env(**changes),
        timeout=3,
        check=False,
    )
    assert result.returncode != 0
