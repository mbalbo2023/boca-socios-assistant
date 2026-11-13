"""Offline regressions for the Boca-only host health/metadata diagnostic."""

from __future__ import annotations

import http.server
import os
import stat
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from boca_socios import host_boca_panel_exact_origin_readonly as observer


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
