"""R179 exact, redacted runner-visible terminal receipts and CLI modes."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from boca_socios import host_boca_pair_upgrade as upgrade
from boca_socios import host_boca_pair_upgrade_cli as cli
from boca_socios import host_boca_sqlite_identity as sqlite

RUN = "43080012345"


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
