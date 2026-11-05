"""Synthetic exact-GO and authenticated-memfd CLI contract; no host effects."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path

import pytest

from boca_socios import host_boca_cutover_cli as cli
from boca_socios.host_boca_cutover import CutoverPlan, CutoverReceipt

ROOT = Path(__file__).resolve().parents[1]
GO = "b" * 64
OLD = "1" * 64
WORKER = "2" * 64
NEW = "3" * 64


def _plan() -> CutoverPlan:
    return CutoverPlan(
        attempt_id="42025021984",
        legacy_id=OLD,
        legacy_sha="a" * 40,
        legacy_image="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "4" * 64,
        legacy_compose_sha="5" * 64,
        target_sha="c" * 40,
        target_image="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "6" * 64,
        browser_image="ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "7" * 64,
        target_compose_sha=hashlib.sha256((ROOT / "compose.beta.yaml").read_bytes()).hexdigest(),
        overlay_sha=hashlib.sha256((ROOT / "compose.beta.browser.yaml").read_bytes()).hexdigest(),
        seccomp_sha=hashlib.sha256((ROOT / "docker/seccomp_profile.json").read_bytes()).hexdigest(),
        owner_subject="synthetic_owner",
    )


def _encode(plan: CutoverPlan, bundle_sha: str, go_sha: str = GO) -> str:
    payload = {
        "version": cli.VERSION,
        "plan": asdict(plan),
        "bundle_sha256": bundle_sha,
        "go_binding_sha256": go_sha,
    }
    return (
        base64.urlsafe_b64encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
        )
        .rstrip(b"=")
        .decode("ascii")
    )


def test_runner_encode_matches_canonical_request() -> None:
    plan = _plan()
    token = cli.encode_invocation(plan, bundle_sha256="a" * 64, go_binding_sha256=GO)
    assert token == _encode(plan, "a" * 64)
    assert cli.CutoverInvocation.decode(token).plan == plan


@pytest.fixture
def reviewed_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[str, CutoverPlan, str]]:
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import build_protected_boca_bundle as builder

    archive = tmp_path / "reviewed.pyz"
    digest = builder.build(ROOT, archive)
    fd = os.memfd_create("boca-cutover-cli-test", flags=0)
    try:
        os.write(fd, archive.read_bytes())
        monkeypatch.setattr(sys, "argv", [f"/proc/self/fd/{fd}"])
        plan = _plan()
        yield _encode(plan, digest), plan, digest
    finally:
        os.close(fd)


def test_cli_default_no_go_before_any_effect(
    reviewed_context: tuple[str, CutoverPlan, str], capsys: pytest.CaptureFixture[str]
) -> None:
    encoded, _, _ = reviewed_context
    calls: list[str] = []
    result = cli.run_cli(encoded, execute=lambda _plan: calls.append("effect") or None)  # type: ignore[arg-type]
    assert result == 3 and calls == []
    assert capsys.readouterr().out == (
        "BOCA_CUTOVER_A_HOST state=NO_GO receipt=UNVERIFIED runtime=UNVERIFIED\n"
    )


def test_cli_exact_go_fake_effect_requires_persisted_terminal_result(
    reviewed_context: tuple[str, CutoverPlan, str], capsys: pytest.CaptureFixture[str]
) -> None:
    encoded, plan, _ = reviewed_context
    events: list[str] = []

    def fake_execute(received: CutoverPlan) -> CutoverReceipt:
        assert received == plan
        events.append("cutover-fake")
        return CutoverReceipt(plan.attempt_id, "ACCEPTED", "ACCEPT", False, True, NEW, WORKER)

    def fake_reconcile(received: CutoverPlan, receipt: CutoverReceipt) -> None:
        assert received == plan and receipt.accepted and events == ["cutover-fake"]
        events.append("durable-result-observed")

    assert (
        cli.run_cli(
            encoded,
            approved_go_binding_sha256=GO,
            execute=fake_execute,
            reconcile=fake_reconcile,
        )
        == 0
    )
    assert events == ["cutover-fake", "durable-result-observed"]
    assert capsys.readouterr().out == (
        f"BOCA_CUTOVER_A_HOST state=ACCEPTED attempt={plan.attempt_id} "
        f"target_sha={plan.target_sha} cleanup=ACCEPT "
        "receipt=RECORDED runtime=UNVERIFIED\n"
    )


def test_cli_wrong_go_and_bundle_digest_refuse_even_injected_executor(
    reviewed_context: tuple[str, CutoverPlan, str],
) -> None:
    encoded, plan, digest = reviewed_context
    called: list[str] = []

    def fail_if_effect(_plan: CutoverPlan) -> CutoverReceipt:
        called.append("effect")
        raise AssertionError("no host effect authorized")

    assert cli.run_cli(encoded, approved_go_binding_sha256="a" * 64, execute=fail_if_effect) == 3
    assert (
        cli.run_cli(_encode(plan, "9" * 64), approved_go_binding_sha256=GO, execute=fail_if_effect)
        == 3
    )
    assert cli.CutoverInvocation.decode(encoded).bundle_sha256 == digest
    assert called == []


def test_cli_terminal_missing_or_recovery_is_never_positive(
    reviewed_context: tuple[str, CutoverPlan, str],
) -> None:
    encoded, plan, _ = reviewed_context

    def accepted(_plan: CutoverPlan) -> CutoverReceipt:
        return CutoverReceipt(plan.attempt_id, "ACCEPTED", "ACCEPT", False, True, NEW, WORKER)

    def restored(_plan: CutoverPlan) -> CutoverReceipt:
        return CutoverReceipt(plan.attempt_id, "RECOVERED", "ACCEPT", True, False, None, None)

    assert (
        cli.run_cli(
            encoded,
            approved_go_binding_sha256=GO,
            execute=accepted,
            reconcile=lambda _plan, _receipt: (_ for _ in ()).throw(
                cli.terminal.TerminalReceiptError("terminal result absent")
            ),
        )
        == 3
    )
    assert (
        cli.run_cli(
            encoded,
            approved_go_binding_sha256=GO,
            execute=restored,
            reconcile=lambda _plan, _receipt: None,
        )
        == 3
    )


def test_cli_unexpected_host_error_never_leaks_exception_or_claims_success(
    reviewed_context: tuple[str, CutoverPlan, str], capsys: pytest.CaptureFixture[str]
) -> None:
    encoded, _, _ = reviewed_context

    def host_error(_plan: CutoverPlan) -> CutoverReceipt:
        raise RuntimeError("synthetic private host detail must remain redacted")

    assert cli.run_cli(encoded, approved_go_binding_sha256=GO, execute=host_error) == 3
    report = capsys.readouterr()
    assert report.err == ""
    assert report.out == ("BOCA_CUTOVER_A_HOST state=NO_GO receipt=UNVERIFIED runtime=UNVERIFIED\n")


@pytest.mark.parametrize("encoded", ["a", "!!", "", "____", "ZXJyb3I="])
def test_cli_malformed_input_is_bounded_error(encoded: str) -> None:
    with pytest.raises(cli.CutoverCliError):
        cli.CutoverInvocation.decode(encoded)


def test_prepared_v2_cutover_invocation_has_exact_nonce_and_keeps_v1() -> None:
    plan = _plan()
    v1 = cli.encode_invocation(plan, bundle_sha256="a" * 64, go_binding_sha256=GO)
    assert cli.CutoverInvocation.decode(v1).prepare_run_id is None
    v2 = cli.encode_invocation(
        plan,
        bundle_sha256="a" * 64,
        go_binding_sha256=GO,
        prepare_run_id="50000000001",
    )
    parsed = cli.CutoverInvocation.decode(v2)
    assert parsed.plan == plan
    assert parsed.prepare_run_id == "50000000001"
    assert parsed.go_binding_sha256 == GO
    assert v2 != v1
    for bad in ("", "0", plan.attempt_id, "not-digits"):
        with pytest.raises(cli.CutoverCliError):
            cli.encode_invocation(
                plan,
        bundle_sha256="a" * 64,
        go_binding_sha256=GO, prepare_run_id=bad
            )


def test_prepared_cutover_cli_requires_separate_go_and_receipt(
    reviewed_context: tuple[str, CutoverPlan, str],
) -> None:
    _, plan, digest = reviewed_context
    encoded = cli.encode_invocation(
        plan,
        bundle_sha256=digest,
        go_binding_sha256=GO,
        prepare_run_id="50000000001",
    )
    seen: list[str] = []

    def effect(actual: CutoverPlan, prepared_id: str) -> CutoverReceipt:
        assert actual == plan and prepared_id == "50000000001"
        seen.append("prepared-effect")
        return CutoverReceipt(plan.attempt_id, "ACCEPTED", "ACCEPT", False, True, NEW, WORKER)

    assert cli.run_cli(encoded, execute_prepared=effect) == 3
    assert seen == []
    assert (
        cli.run_cli(
            encoded,
            approved_go_binding_sha256=GO,
            execute_prepared=effect,
            reconcile=lambda _plan, _receipt: seen.append("receipt"),
        )
        == 0
    )
    assert seen == ["prepared-effect", "receipt"]
