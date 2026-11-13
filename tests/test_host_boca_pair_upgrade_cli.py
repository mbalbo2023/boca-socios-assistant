"""R179 exact, redacted runner-visible terminal receipts and CLI modes."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest

from boca_socios import host_boca_pair_upgrade as upgrade
from boca_socios import host_boca_pair_upgrade_cli as cli
from boca_socios import host_boca_sqlite_identity as sqlite

pytest_plugins = ("test_host_boca_success_cleanup_bridge_v2",)

RUN = "43080012345"


def _protected_apply_args(attempt: str) -> list[str]:
    return [
        "apply",
        attempt,
        "a" * 40,
        "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "1" * 64,
        "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "2" * 64,
        "44000000002",
        "44000000003",
        "44000000004",
    ]


def test_sqlite_observer_positive_and_negative_are_bounded_and_secret_free(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from boca_socios import host_first_deploy as host

    monkeypatch.setattr(
        host, "_checked_docker_storage_dir", lambda: Path("/home/boca-deploy/.local/share/docker")
    )
    monkeypatch.setattr(sqlite, "observe_sqlite_identity", lambda _: "VERIFIED_STABLE")
    assert cli.main(["observe-sqlite", RUN]) == 0
    raw = capsys.readouterr().out.encode("ascii")
    assert cli.verify_sqlite(raw, RUN) == raw
    assert b"VERIFIED_STABLE" in raw and b"/home/" not in raw and b"inode" not in raw
    monkeypatch.setattr(sqlite, "observe_sqlite_identity", lambda _: "NO_GO")
    assert cli.main(["observe-sqlite", RUN]) != 0
    raw = capsys.readouterr().out.encode("ascii")
    assert cli.verify_sqlite(raw, RUN) == raw
    assert b"NO_GO" in raw


@pytest.mark.parametrize(
    "tamper",
    [
        b"BOCA_SQLITE_IDENTITY {}\n",
        b'BOCA_SQLITE_IDENTITY {"state":"VERIFIED_STABLE","state":"NO_GO"}\n',
        b'BOCA_SQLITE_IDENTITY {"state":"ACCEPTED"}\n',
        b'BOCA_SQLITE_IDENTITY {"state":"VERIFIED_STABLE"}\r\n',
        b'BOCA_SQLITE_IDENTITY {"state":"VERIFIED_STABLE"}\nBOCA_IGNORED\n',
    ],
)
def test_sqlite_runner_rejects_uncanonical_or_contaminated_output(tamper: bytes) -> None:
    with pytest.raises(cli.PairUpgradeCliError):
        cli.verify_sqlite(tamper, RUN)


def _receipt(state: str = "ACCEPTED") -> upgrade.PairUpgradeReceipt:
    return upgrade.PairUpgradeReceipt(
        attempt_id=RUN,
        state=state,  # type: ignore[arg-type]
        cleanup="ACCEPT",
        old_restored=False,
        commit_started=True,
        controller_id="3" * 64,
        worker_id="4" * 64,
        failed_phase="NONE",
    )


def test_upgrade_terminal_receipt_canonical_and_runner_verified() -> None:
    raw = cli.encode_upgrade(_receipt())
    assert cli.verify_upgrade(raw, RUN) == raw
    assert b"ACCEPTED" in raw and len(raw) < 512
    assert b"BOCA_PAIR_UPGRADE " in raw


def test_no_go_terminal_is_not_convertible_to_accept() -> None:
    from dataclasses import replace

    refused = replace(
        _receipt(),
        state="NO_GO",
        cleanup="INDETERMINATE",
        commit_started=False,
        old_restored=False,
        controller_id=None,
        worker_id=None,
        failed_phase="ATTEST",
    )
    raw = cli.encode_upgrade(refused)
    assert cli.verify_upgrade(raw, RUN) == raw
    payload = json.loads(raw.removeprefix(b"BOCA_PAIR_UPGRADE "))
    payload["state"] = "ACCEPTED"
    bad = (
        b"BOCA_PAIR_UPGRADE "
        + json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )
    with pytest.raises(cli.PairUpgradeCliError):
        cli.verify_upgrade(bad, RUN)


def test_cli_refuses_extra_args_and_invalid_runs_without_any_host_call() -> None:
    assert cli.main(["observe-sqlite", "0"]) != 0
    assert cli.main(["observe-sqlite", RUN, "extra"]) != 0
    assert cli.main(["apply", RUN]) != 0


def test_existing_apply_selector_cannot_reenter_historical_r179_migration(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from boca_socios import host_boca_pair_upgrade_backend as historical

    monkeypatch.setattr(
        historical,
        "apply",
        lambda *_args: pytest.fail("historical one-shot worker EXIT1 migration invoked"),
    )
    source = "a" * 40
    controller = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "1" * 64
    worker = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "2" * 64
    assert cli.main(["apply", RUN, source, controller, worker, "44000000002"]) == 3
    raw = capsys.readouterr().out.encode()
    assert cli.verify_upgrade(raw, RUN) == raw
    value = json.loads(raw.removeprefix(b"BOCA_PAIR_UPGRADE "))
    assert value["state"] == "NO_GO"
    assert value["commit_started"] is False
    assert value["failed_phase"] == "ATTEST"
    assert value["cleanup"] == "INDETERMINATE"


@pytest.mark.parametrize("accepted", [True, False])
def test_protected_apply_preserves_reviewed_successor_terminal_state(
    accepted: bool,
    frozen_proof: tuple[cli.BoundSuccessorPreflight, object],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An actual successor result, including postcommit failure, cannot become ATTEST NO_GO."""
    preflight, _ = frozen_proof
    attempt = preflight.inputs.plan.attempt_id
    phase = "NONE" if accepted else "RETIRE_OLD"
    outcome = upgrade.PairUpgradeReceipt(
        attempt_id=attempt,
        state="ACCEPTED" if accepted else "NO_GO",
        cleanup="ACCEPT" if accepted else "INDETERMINATE",
        old_restored=False,
        commit_started=True,
        controller_id="3" * 64,
        worker_id="4" * 64,
        failed_phase=phase,
    )
    monkeypatch.setattr(cli, "_successor_preflight", lambda *_args: preflight)
    observed: list[cli.BoundSuccessorPreflight] = []

    def genuine_reviewed_path(value: cli.BoundSuccessorPreflight) -> upgrade.PairUpgradeReceipt:
        observed.append(value)
        return outcome

    monkeypatch.setattr(cli, "_execute_reviewed_successor", genuine_reviewed_path)
    assert cli.main(_protected_apply_args(attempt)) == (0 if accepted else 3)
    raw = capsys.readouterr().out.encode("ascii")
    assert cli.verify_upgrade(raw, attempt) == raw
    payload = json.loads(raw.removeprefix(b"BOCA_PAIR_UPGRADE "))
    assert payload["state"] == ("ACCEPTED" if accepted else "NO_GO")
    assert payload["commit_started"] is True
    assert payload["failed_phase"] == phase
    assert observed == [preflight]


def test_postentry_failure_cannot_masquerade_as_preeffect_attest_no_go(
    frozen_proof: tuple[cli.BoundSuccessorPreflight, object],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The lease and marker might have been crossed; a canonical pre-effect lie is forbidden."""
    preflight, _ = frozen_proof
    monkeypatch.setattr(cli, "_successor_preflight", lambda *_args: preflight)

    def uncertain_after_entry(_value: cli.BoundSuccessorPreflight) -> None:
        raise RuntimeError("private host path and secret must never escape")

    monkeypatch.setattr(cli, "_execute_reviewed_successor", uncertain_after_entry)
    assert cli.main(_protected_apply_args(preflight.inputs.plan.attempt_id)) == 3
    raw = capsys.readouterr().out.encode("ascii")
    assert raw == (
        b"BOCA_PAIR_UPGRADE state=INDETERMINATE reason=POST_ENTRY_UNVERIFIED "
        b"action=READ_ONLY_RCA_NO_AUTOMATIC_RETRY\n"
    )
    assert b"private host path" not in raw
    with pytest.raises(cli.PairUpgradeCliError):
        cli.verify_upgrade(raw, preflight.inputs.plan.attempt_id)


def test_apply_must_not_enter_successor_on_untyped_preflight(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "_successor_preflight", lambda *_args: object())
    monkeypatch.setattr(
        cli,
        "_execute_reviewed_successor",
        lambda *_args: pytest.fail("untrusted transport reached host actor"),
    )
    assert cli.main(_protected_apply_args(RUN)) == 3
    raw = capsys.readouterr().out.encode("ascii")
    assert cli.verify_upgrade(raw, RUN) == raw
    assert b'"state":"NO_GO"' in raw and b'"commit_started":false' in raw


def test_unexpected_preflight_error_cannot_claim_irreversible_commit_before_lease(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No authenticated preflight means no lease, commit marker or installed pair."""
    from boca_socios import host_boca_pair_upgrade as transaction

    def reject_preflight(*_args: object) -> None:
        raise RuntimeError("unexpected local preflight exception")

    monkeypatch.setattr(cli, "_successor_preflight", reject_preflight)
    monkeypatch.setattr(
        transaction,
        "run_pair_upgrade",
        lambda *_args, **_kwargs: pytest.fail("transaction after failed preflight"),
    )
    args = [
        "apply",
        RUN,
        "a" * 40,
        "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "1" * 64,
        "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "2" * 64,
        "44000000002",
    ]
    assert cli.main(args) == 3
    raw = capsys.readouterr().out.encode("ascii")
    cli.verify_upgrade(raw, RUN)
    result = json.loads(raw.removeprefix(b"BOCA_PAIR_UPGRADE "))
    assert result["state"] == "NO_GO"
    assert result["cleanup"] == "INDETERMINATE"
    assert result["old_restored"] is False
    assert result["commit_started"] is False
    assert result["failed_phase"] == "ATTEST"


def test_r251_successor_preflight_returns_inert_typed_sources_and_bound_current_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return only sealed transport, never an effect/host authorization."""
    from dataclasses import replace

    from boca_socios import host_boca_pair_upgrade as transaction
    from test_host_boca_successor_integrations import _inputs_with_proofs
    from test_host_boca_upgrade_adapters import WITNESS_RUN

    value = _inputs_with_proofs()
    mappings = {
        "runner-proof.json": value["release_proof"],
        "boca-release-manifest.json": value["controller_manifest"],
        "boca-browser-release-manifest.json": value["paired_manifest"],
        "observation-proof.json": value["observation_proof"],
        "boca-pair-observation.receipt": value["observation_receipt"],
        "boca-retained-observation.receipt": value["retained_receipt"],
        "current-pair-v2.receipt": value["current_pair_v2"],
        "retained-proof.json": b'{"state":"NO_GO"}\n',
        "compose.beta.yaml": b"services:\n  controller: {}\n",
        "compose.beta.browser.yaml": b"services:\n  browser-worker: {}\n",
        "docker/seccomp_profile.json": b'{"defaultAction":"SCMP_ACT_ERRNO"}\n',
    }

    class Archive:
        def __enter__(self) -> Archive:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, member: str) -> bytes:
            return mappings[member.removeprefix("release/")]

    monkeypatch.setattr(cli.sys, "argv", ["/proc/self/fd/19"])
    monkeypatch.setattr(cli.zipfile, "ZipFile", lambda *_args: Archive())
    args = tuple(
        value[key]
        for key in (
            "attempt_id",
            "source_sha",
            "controller_ref",
            "worker_ref",
            "release_run_id",
            "observation_run_id",
        )
    )
    result = cli._successor_preflight(*args, WITNESS_RUN)
    assert isinstance(result, cli.BoundSuccessorPreflight)
    assert result.inputs.plan.new_source_sha == value["source_sha"]
    assert result.inputs.custody.observation_run_id == WITNESS_RUN
    assert result.apply_authorized is False
    assert result.base == mappings["compose.beta.yaml"]
    assert result.overlay == mappings["compose.beta.browser.yaml"]
    assert result.seccomp == mappings["docker/seccomp_profile.json"]
    assert result.base_sha == hashlib.sha256(result.base).hexdigest()
    assert result.overlay_sha == hashlib.sha256(result.overlay).hexdigest()
    assert result.seccomp_sha == hashlib.sha256(result.seccomp).hexdigest()
    assert len({result.base_sha, result.overlay_sha, result.seccomp_sha}) == 3
    with pytest.raises(cli.SuccessorPreflightIneligible):
        replace(result, base_sha="0" * 64)

    # The preflight alone remains read-only even when the reviewed APPLY
    # selector later consumes its typed result under the protected runner.
    monkeypatch.setattr(
        transaction,
        "run_pair_upgrade",
        lambda *_args, **_kwargs: pytest.fail("inert R251 cannot acquire a Boca lease"),
    )
    second = cli._successor_preflight(*args, WITNESS_RUN)
    assert second.apply_authorized is False
    assert second.inputs.plan == result.inputs.plan

    del mappings["current-pair-v2.receipt"]
    with pytest.raises(cli.SuccessorPreflightIneligible, match="transport unverified"):
        cli._successor_preflight(*args, WITNESS_RUN)


@pytest.mark.parametrize("mutation", ["missing", "same", "empty", "oversize", "bad_memfd"])
def test_r251_preflight_rejects_unsafe_source_transport_before_any_host_effect(
    mutation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_host_boca_successor_integrations import _inputs_with_proofs
    from test_host_boca_upgrade_adapters import WITNESS_RUN

    value = _inputs_with_proofs()
    sources = {
        "compose.beta.yaml": b"new base compose\n",
        "compose.beta.browser.yaml": b"new worker compose\n",
        "docker/seccomp_profile.json": b"new seccomp\n",
    }
    proof = {
        "release/runner-proof.json": value["release_proof"],
        "release/boca-release-manifest.json": value["controller_manifest"],
        "release/boca-browser-release-manifest.json": value["paired_manifest"],
        "release/observation-proof.json": value["observation_proof"],
        "release/boca-pair-observation.receipt": value["observation_receipt"],
        "release/boca-retained-observation.receipt": value["retained_receipt"],
        "release/current-pair-v2.receipt": value["current_pair_v2"],
        "release/retained-proof.json": b'{"state":"NO_GO"}\n',
        **sources,
    }
    if mutation == "missing":
        del proof["compose.beta.browser.yaml"]
    elif mutation == "same":
        proof["compose.beta.browser.yaml"] = proof["compose.beta.yaml"]
    elif mutation == "empty":
        proof["compose.beta.browser.yaml"] = b""
    elif mutation == "oversize":
        from boca_socios import host_cutover_stage as stage

        proof["compose.beta.browser.yaml"] = b"x" * (stage.MAX_FILE + 1)

    class Archive:
        def __enter__(self) -> Archive:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, member: str) -> bytes:
            return proof[member]

    monkeypatch.setattr(
        cli.sys, "argv", ["/home/not-memfd.pyz" if mutation == "bad_memfd" else "/proc/self/fd/19"]
    )
    monkeypatch.setattr(cli.zipfile, "ZipFile", lambda *_args: Archive())
    args = tuple(
        value[key]
        for key in (
            "attempt_id",
            "source_sha",
            "controller_ref",
            "worker_ref",
            "release_run_id",
            "observation_run_id",
        )
    )
    with pytest.raises(cli.SuccessorPreflightIneligible):
        cli._successor_preflight(*args, WITNESS_RUN)


@pytest.mark.parametrize("mode", ["verify-sqlite", "verify-upgrade"])
def test_cli_runner_verifier_reads_exact_one_bounded_line(
    mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = (
        cli.encode_sqlite(RUN, "VERIFIED_STABLE")
        if mode == "verify-sqlite"
        else cli.encode_upgrade(_receipt())
    )
    output = io.BytesIO()
    monkeypatch.setattr(cli.sys, "stdin", io.TextIOWrapper(io.BytesIO(raw)))
    monkeypatch.setattr(cli.sys, "stdout", io.TextIOWrapper(output, write_through=True))
    assert cli.main([mode, RUN]) == 0
    assert output.getvalue() == raw
    monkeypatch.setattr(cli.sys, "stdin", io.TextIOWrapper(io.BytesIO(raw + b"extra")))
    assert cli.main([mode, RUN]) == 3
