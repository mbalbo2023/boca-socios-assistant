"""Offline regressions for the Boca-only host health/metadata diagnostic."""

from __future__ import annotations

import http.server
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from boca_socios import host_boca_panel_exact_origin_readonly as observer

_RUN_ID = "43362853913"
_SHA = "a" * 40


class _Panel(http.server.BaseHTTPRequestHandler):
    seen_hosts: list[str] = []
    response_code = 200

    def do_GET(self) -> None:  # noqa: N802
        type(self).seen_hosts.append(self.headers.get("Host", ""))
        body = b"BOCA_BETA_READY"
        self.send_response(type(self).response_code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


def test_exact_origin_health_requests_only_loopback_with_configured_host():
    _Panel.seen_hosts = []
    _Panel.response_code = 200
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Panel) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            assert observer.probe_health(port=server.server_port) == "HEALTH_HTTP_200"
            assert _Panel.seen_hosts == ["localhost:8443"]
        finally:
            server.shutdown()
            thread.join(timeout=5)


def test_real_503_with_exact_host_is_not_promoted_to_health():
    _Panel.seen_hosts = []
    _Panel.response_code = 503
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Panel) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            assert observer.probe_health(port=server.server_port) == "HEALTH_NON_200"
            assert _Panel.seen_hosts == ["localhost:8443"]
        finally:
            server.shutdown()
            thread.join(timeout=5)


def _volumes(root: Path) -> None:
    for name in ("boca-socios_boca_data", "boca-socios_boca_site_config"):
        (root / "volumes" / name / "_data").mkdir(parents=True, mode=0o700)


@pytest.fixture
def safe_site_root() -> Iterator[Path]:
    """Temp host root under a verified no-world-writable ancestor."""
    checkout = Path(__file__).resolve().parents[1]

    def trusted_ancestors(path: Path) -> bool:
        return all(
            stat.S_ISDIR(info.st_mode) and not stat.S_IMODE(info.st_mode) & 0o022
            for directory in (path, *path.parents)
            if (info := directory.lstat())
        )

    # Checkouts with a world-writable ancestor cannot model trusted host paths.
    # Use the account's private home only when its entire ancestry is trusted.
    parent = checkout if trusted_ancestors(checkout) else Path.home()
    assert trusted_ancestors(parent)
    with tempfile.TemporaryDirectory(prefix=".boca-site-fixture-", dir=parent) as folder:
        root = Path(folder)
        assert trusted_ancestors(root)
        yield root


def test_world_writable_ancestor_is_rejected_even_with_absent_site_files(safe_site_root: Path):
    unsafe_root = safe_site_root / "world-writable-host-root"
    unsafe_root.mkdir(mode=0o700)
    os.chmod(unsafe_root, 0o777)  # noqa: S103 - deliberate hostile-host fixture
    _volumes(unsafe_root)
    with pytest.raises(observer.ReadonlyWitnessError):
        observer.probe_site_files(unsafe_root)


def test_absent_site_url_files_are_only_a_metadata_observation(safe_site_root: Path):
    _volumes(safe_site_root)
    assert observer.probe_site_files(safe_site_root) == "BOTH_FILES_ABSENT"


def test_site_url_present_is_not_interpreted_as_configured(safe_site_root: Path):
    _volumes(safe_site_root)
    site = safe_site_root / "volumes/boca-socios_boca_data/_data/boca-site-url.json"
    site.write_text("private-secret-must-never-be-read")
    os.chmod(site, 0o600)
    assert observer.probe_site_files(safe_site_root) == "PRESENT_UNVERIFIED"


def test_site_url_symlink_is_never_followed_or_claimed_absent(safe_site_root: Path):
    _volumes(safe_site_root)
    data = safe_site_root / "volumes/boca-socios_boca_data/_data"
    (data / "boca-site-url.json").symlink_to(safe_site_root / "some-other-file")
    with pytest.raises(observer.ReadonlyWitnessError):
        observer.probe_site_files(safe_site_root)


def test_same_category_with_changed_site_inode_is_refused(safe_site_root: Path):
    _volumes(safe_site_root)
    site = safe_site_root / "volumes/boca-socios_boca_data/_data/boca-site-url.json"
    site.write_text("redacted")
    os.chmod(site, 0o600)
    first = observer.snapshot_site_files(safe_site_root)
    site.rename(site.with_name("boca-site-url.old"))
    site.write_text("redacted")
    os.chmod(site, 0o600)
    second = observer.snapshot_site_files(safe_site_root)
    assert first != second
    with pytest.raises(observer.ReadonlyWitnessError):
        observer.require_stable(first, second)


def test_receipt_schema_never_accepts_private_strings_or_extra_fields():
    receipt = observer.make_receipt(
        "43360000001", "a" * 40, "HEALTH_HTTP_200", "BOTH_FILES_ABSENT", "UID_UNVERIFIED"
    )
    assert observer.verify_receipt(receipt, "43360000001") == receipt
    assert b"https://" not in receipt
    assert b"token" not in receipt
    assert b'"deploy":"NO_GO"' in receipt
    with pytest.raises(observer.ReadonlyWitnessError):
        observer.verify_receipt(
            receipt.replace(b'"deploy":"NO_GO"', b'"deploy":"PASS"'), "43360000001"
        )
    with pytest.raises(observer.ReadonlyWitnessError):
        observer.verify_receipt(
            receipt.replace(b'"schema":1', b'"schema":1,"secret":"x"'), "43360000001"
        )
    with pytest.raises(observer.ReadonlyWitnessError):
        observer.verify_receipt(receipt, "43360000002")


def test_exact_origin_probe_is_only_an_existing_protected_readonly_dispatch():
    flow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
    ).read_text()
    checkout = flow.split(
        "      - name: Checkout exact reviewed main for authenticated artifact discovery\n", 1
    )[1].split("      - name:", 1)[0]
    assert "inputs.operation == 'boca-panel-exact-origin-observe'" in checkout
    budget = next(line for line in flow.splitlines() if line.strip().startswith("BOCA_BUDGET:"))
    assert "inputs.operation == 'boca-panel-exact-origin-observe'" in budget
    assert (
        "boca-panel-exact-origin-observe"
        in flow.split("      operation:", 1)[1].split("      source_sha:", 1)[0]
    )
    heading = "      - name: Observe Boca exact-origin health and site inode presence READ_ONLY\n"
    assert flow.count(heading) == 1
    step = flow.split(heading, 1)[1].split("      - name:", 1)[0]
    for value in (
        "inputs.operation == 'boca-panel-exact-origin-observe'",
        'gh api "repos/$GITHUB_REPOSITORY/git/ref/heads/main"',
        "scripts/check_main_ref.py",
        'test "$(git rev-parse HEAD)" = "$BOCA_SOURCE_SHA"',
        'shlex.join(["/usr/bin/python3", "-I", "-B", "-", "host", *sys.argv[1:]])',
        '"$RUNNER_TEMP/boca-ssh/config"',
        "host_boca_panel_exact_origin_readonly.py",
        "observer_writes=0",
        "deploy=NO_GO",
        "2>/dev/null",
    ):
        assert value in step
    for forbidden in ("docker start", "docker stop", "docker exec", "docker rm", "sudo", "prune"):
        assert forbidden not in step


@pytest.mark.parametrize(
    ("remote_rc", "raw", "reason"),
    [
        (0, b"", "RECEIPT_MISSING"),
        (0, b"secret-url=https://private.example.invalid", "RECEIPT_MALFORMED"),
        (255, b"", "SSH_TRANSPORT_UNVERIFIED"),
        (124, b"", "SSH_TRANSPORT_UNVERIFIED"),
        (3, b"", "REMOTE_EXECUTION_UNVERIFIED"),
        (3, b"private-host-output", "RECEIPT_MALFORMED"),
    ],
)
def test_failure_classification_exposes_only_fixed_categories(
    remote_rc: int, raw: bytes, reason: str
):
    output, accepted = observer.classify_remote_observation(raw, remote_rc, _RUN_ID, _SHA)
    assert not accepted
    assert (
        output
        == (
            f"BOCA_PANEL_ORIGIN_READONLY state=NO_GO reason={reason} "
            "observer_writes=0 deploy=NO_GO\n"
        ).encode()
    )
    assert b"private" not in output


def test_canonical_success_requires_remote_exit_zero_and_exact_run_binding():
    valid = observer.make_receipt(
        _RUN_ID, _SHA, "HEALTH_HTTP_200", "BOTH_FILES_ABSENT", "UID_UNVERIFIED"
    )
    assert observer.classify_remote_observation(valid, 0, _RUN_ID, _SHA) == (valid, True)
    output, accepted = observer.classify_remote_observation(valid, 3, _RUN_ID, _SHA)
    assert not accepted
    assert b"state=NO_GO" in output
    output, accepted = observer.classify_remote_observation(valid, 0, "43362853914", _SHA)
    assert not accepted
    assert b"reason=RECEIPT_MALFORMED" in output

    # The same run is insufficient: the host could return a different source tree.
    other_sha = "b" * 40
    wrong_source = observer.make_receipt(
        _RUN_ID, other_sha, "HEALTH_HTTP_200", "BOTH_FILES_ABSENT", "UID_UNVERIFIED"
    )
    output, accepted = observer.classify_remote_observation(wrong_source, 0, _RUN_ID, _SHA)
    assert not accepted
    assert b"reason=RECEIPT_MALFORMED" in output


@pytest.mark.parametrize(
    "phase",
    [
        "HOST_SCRIPT_VALIDATION_UNVERIFIED",
        "HOST_UID_UNVERIFIED",
        "HOST_SITE_METADATA_UNVERIFIED",
        "HOST_STORAGE_METADATA_UNVERIFIED",
        "HOST_METADATA_DRIFT_UNVERIFIED",
        "HOST_HEALTH_DRIFT_UNVERIFIED",
    ],
)
def test_host_failure_marker_is_exact_run_bound_and_only_advisory(phase: str):
    marker = observer.make_host_failure_marker(_RUN_ID, _SHA, phase)
    output, accepted = observer.classify_remote_observation(marker, 3, _RUN_ID, _SHA)
    assert not accepted
    assert f"reason={phase}".encode() in output
    assert b"state=NO_GO" in output
    output, accepted = observer.classify_remote_observation(marker, 3, "43362853914", _SHA)
    assert not accepted
    assert b"reason=RECEIPT_MALFORMED" in output
    output, accepted = observer.classify_remote_observation(marker, 0, _RUN_ID, _SHA)
    assert not accepted
    assert b"reason=RECEIPT_MALFORMED" in output


def test_host_uid_failure_emits_bounded_marker_not_internal_exception(monkeypatch, capfd):
    monkeypatch.setattr(observer.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(observer.os, "getegid", lambda: 1000)
    assert observer.main(["host", _RUN_ID, _SHA]) == 3
    out, err = capfd.readouterr()
    assert err == ""
    assert out == observer.make_host_failure_marker(_RUN_ID, _SHA, "HOST_UID_UNVERIFIED").decode()


def test_host_site_metadata_failure_identifies_stage_without_path(monkeypatch, capfd):
    monkeypatch.setattr(observer.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(observer.os, "getegid", lambda: 10001)
    monkeypatch.setattr(observer, "probe_health", lambda: "HEALTH_HTTP_200")

    def reject_site():
        raise observer.ReadonlyWitnessError("must-not-appear-in-output")

    monkeypatch.setattr(observer, "snapshot_site_files", reject_site)
    assert observer.main(["host", _RUN_ID, _SHA]) == 3
    out, err = capfd.readouterr()
    assert err == ""
    assert "reason=" not in out
    assert "must-not-appear" not in out
    assert (
        out
        == observer.make_host_failure_marker(
            _RUN_ID, _SHA, "HOST_SITE_METADATA_UNVERIFIED"
        ).decode()
    )


def test_host_storage_metadata_failure_stays_separate_from_site_absence(monkeypatch, capfd):
    monkeypatch.setattr(observer.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(observer.os, "getegid", lambda: 10001)
    monkeypatch.setattr(observer, "probe_health", lambda: "HEALTH_HTTP_200")
    monkeypatch.setattr(observer, "snapshot_site_files", lambda: (None, None))

    def reject_storage():
        raise observer.ReadonlyWitnessError("sensitive-storage-path")

    monkeypatch.setattr(observer, "snapshot_storage_files", reject_storage)
    assert observer.main(["host", _RUN_ID, _SHA]) == 3
    out, err = capfd.readouterr()
    assert err == ""
    assert (
        out
        == observer.make_host_failure_marker(
            _RUN_ID, _SHA, "HOST_STORAGE_METADATA_UNVERIFIED"
        ).decode()
    )
    assert "sensitive-storage-path" not in out


def test_host_invalid_health_proof_yields_validation_not_a_raw_traceback(monkeypatch, capfd):
    monkeypatch.setattr(observer.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(observer.os, "getegid", lambda: 10001)
    monkeypatch.setattr(observer, "probe_health", lambda: "BOGUS_PRIVATE_RESPONSE")
    monkeypatch.setattr(observer, "snapshot_site_files", lambda: (None, None))
    monkeypatch.setattr(observer, "snapshot_storage_files", lambda: (None, None, None))
    assert observer.main(["host", _RUN_ID, _SHA]) == 3
    out, err = capfd.readouterr()
    assert err == ""
    assert (
        out
        == observer.make_host_failure_marker(
            _RUN_ID, _SHA, "HOST_SCRIPT_VALIDATION_UNVERIFIED"
        ).decode()
    )
    assert "BOGUS" not in out


def test_classifier_cli_never_echoes_raw_host_or_ssh_output():
    result = subprocess.run(  # noqa: S603 - fixed local module invocation
        [
            sys.executable,
            "-m",
            "boca_socios.host_boca_panel_exact_origin_readonly",
            "classify",
            "0",
            _RUN_ID,
            _SHA,
        ],
        input=b"https://secret.example.invalid/private?token=SECRET",
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == 3
    assert result.stderr == b""
    assert result.stdout == (
        b"BOCA_PANEL_ORIGIN_READONLY state=NO_GO reason=RECEIPT_MALFORMED "
        b"observer_writes=0 deploy=NO_GO\n"
    )


def test_protected_observer_workflow_classifies_pre_ssh_and_remote_failure():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
    ).read_text()
    name = "      - name: Observe Boca exact-origin health and site inode presence READ_ONLY\n"
    step = workflow.split(name, 1)[1].split("      - name:", 1)[0]
    script = textwrap.dedent(step.split("        run: |\n", 1)[1])
    check = subprocess.run(  # noqa: S603 - Bash parses an offline workflow fixture only
        ["/bin/bash", "-n"], input=script.encode(), capture_output=True, check=False
    )
    assert check.returncode == 0, check.stderr.decode()
    assert 'classify "$remote_rc" "$GITHUB_RUN_ID" "$BOCA_SOURCE_SHA"' in step
    assert "PRE_SSH_MAIN_REF_UNVERIFIED" in step
    assert "RECEIPT_MALFORMED" in step
    assert "2>/dev/null" in step
    assert 'printf \'%s\\n\' "$classified" >> "$GITHUB_STEP_SUMMARY"' in step
    assert '< "$observation_dir/receipt"' in step
    assert 'cat "$observation_dir/receipt"' not in step


def test_prior_auth_or_setup_failure_gets_no_go_without_ssh():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
    ).read_text()
    name = "      - name: Classify exact-origin pre-SSH protected gate failure\n"
    assert name in workflow
    step = workflow.split(name, 1)[1].split("      - name:", 1)[0]
    assert "failure() && inputs.operation == 'boca-panel-exact-origin-observe'" in step
    assert "PRE_SSH_AUTH_OR_SETUP_UNVERIFIED" in step
    assert "boca-panel-origin.started" in step
