"""One disposable local browser boundary; never a droplet or Boca provider probe."""

from __future__ import annotations

import http.client
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import qa_guest_navigation_playwright as runner  # noqa: E402
from qa_guest_navigation_playwright import (  # noqa: E402
    allow_boca_qa_request,
    local_synthetic_panel,
)


def test_browser_network_scope_is_exact_loopback_get_allowlist() -> None:
    origin = "http://127.0.0.1:35791"
    for path in ("/", "/control", "/control/actividad", "/configuracion"):
        assert allow_boca_qa_request(origin + path, "GET", origin, owner=False)
    assert allow_boca_qa_request(origin + "/control/motores.json", "GET", origin, owner=True)
    for url, method, owner in (
        (origin + "/control", "POST", False),
        (origin + "/control", "HEAD", False),
        (origin + "/control?token=sensitive", "GET", False),
        (origin + "/control#fragment", "GET", False),
        (origin + "/control/actividad.json", "GET", False),
        (origin + "/monitor/tokens", "GET", True),
        (origin + "/%63ontrol", "GET", False),
        ("http://127.0.0.1:35792/control", "GET", False),
        ("http://localhost:35791/control", "GET", False),
        ("http://127.0.0.1.evil.invalid:35791/control", "GET", False),
        ("https://127.0.0.1:35791/control", "GET", False),
        ("http://user@127.0.0.1:35791/control", "GET", False),
    ):
        assert not allow_boca_qa_request(url, method, origin, owner=owner)


def test_ephemeral_wsgi_fixture_grants_owner_only_with_random_context_header() -> None:
    with local_synthetic_panel() as (origin, mint_owner_header):
        parsed = urlsplit(origin)
        assert parsed.hostname == "127.0.0.1"
        assert parsed.port is not None and parsed.port != 8443
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
        try:
            connection.request("GET", "/control")
            response = connection.getresponse()
            guest = response.read()
            assert response.status == 200
            assert b'<nav aria-label="Principal">' in guest
            assert b"Otras funciones" not in guest
            assert b'<a href="/ingresar">Ingresar para operar motores' in guest
            assert b"<form" not in guest

            connection.request("GET", "/control", headers={"X-Boca-QA-Owner": "invalid"})
            response = connection.getresponse()
            rejected = response.read()
            assert response.status == 200
            assert b"<form" not in rejected

            marker = mint_owner_header()
            assert marker and marker != mint_owner_header()
            connection.request("GET", "/control", headers={"X-Boca-QA-Owner": marker})
            response = connection.getresponse()
            owner = response.read()
            assert response.status == 200
            assert b'<nav aria-label="Otras funciones">' in owner
            assert b'<form id="queues_tokens-start" method="post"' in owner

            connection.request("POST", "/control")
            response = connection.getresponse()
            response.read()
            assert response.status == 405
        finally:
            connection.close()


def test_fixture_browser_owner_uses_header_not_invalid_prefixed_cookie() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "scripts/qa_guest_navigation_playwright.py"
    ).read_text()
    assert ".add_cookies(" not in source
    assert "set_extra_http_headers" in source


def test_manual_workflow_is_branch_owner_only_and_pins_eight_reviewed_blobs() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/panel-preview.yml"
    ).read_text()
    job = workflow.split("  guest-navigation-playwright:\n", 1)[1]
    assert "github.event_name == 'workflow_dispatch'" in job
    assert "github.actor == 'mbalbo2023'" in job
    assert "refs/heads/feat/417-guest-readonly-fast-ci" in job
    assert "timeout-minutes: 8" in job
    assert "uv sync --frozen --group browser" in job
    assert "python scripts/qa_guest_navigation_playwright.py" in job
    for blob in (
        "9e81b3d0ff611be2cb7499d8c39c6c3b328036c1",
        "91b0fcd44c584ca8dc52a53f0bd2358f17878abd",
        "fc631e0748b80842fca5ce09b1efef7a46adc316",
        "38615a314c161b93575ba9839fbfb19aeeeaba4a",
        "d8458fa4bf8c3ee0dee7d195bc00f5c7164e4236",
        "5800fb619b97d03690a781d9a08a9f1742fe537d",
    ):
        assert blob in job
    root = Path(__file__).resolve().parents[1]
    for path in (
        "scripts/qa_guest_navigation_playwright.py",
        "tests/test_qa_guest_navigation_playwright.py",
    ):
        blob = subprocess.run(  # noqa: S603 - fixed Git hash of reviewed local source
            ["/usr/bin/git", "hash-object", path],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        assert blob in job
    assert "docker " not in job.lower()
    assert "ssh " not in job.lower()
    assert "secrets." not in job.lower()


def test_workflow_blob_gate_rejects_product_and_harness_drift(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/panel-preview.yml").read_text()
    section = workflow.split(
        "      - name: Reject any drift in eight independently reviewed blobs\n", 1
    )[1].split("      - name:", 1)[0]
    gate = textwrap.dedent(section.split("        run: |\n", 1)[1])
    paths = (
        "src/boca_socios/panel/private_http.py",
        "src/boca_socios/panel/private_ui.py",
        "src/boca_socios/panel/worker_activity.py",
        "tests/test_guest_readonly_dashboard.py",
        "tests/test_private_engine_controls.py",
        "tests/test_site_url_configuration.py",
        "scripts/qa_guest_navigation_playwright.py",
        "tests/test_qa_guest_navigation_playwright.py",
    )
    repository = tmp_path / "isolated-git"
    repository.mkdir()

    def git(*arguments: str) -> str:
        result = subprocess.run(  # noqa: S603 - fixed Git CLI, disposable exact tree
            ["/usr/bin/git", *arguments],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()

    git("init", "-q", "-b", "main")
    git("config", "user.name", "Synthetic QA")
    git("config", "user.email", "fixture@example.invalid")
    for path in paths:
        destination = repository / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / path, destination)
    git("add", "--all")
    git("commit", "-qm", "exact source")

    def check() -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - reviewed workflow shell, isolated fixture
            ["/usr/bin/bash", "-e", "-c", gate],
            cwd=repository,
            env=os.environ | {"GITHUB_SHA": git("rev-parse", "HEAD")},
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )

    accepted = check()
    assert accepted.returncode == 0, accepted.stderr
    assert "BOCA_GUEST_CANDIDATE_BLOBS state=PASS files=8" in accepted.stdout
    (repository / paths[0]).write_text("def unauthorized_change(): pass\n")
    git("add", "--all")
    git("commit", "-qm", "drift")
    rejected = check()
    assert rejected.returncode != 0
    assert "state=PASS" not in rejected.stdout
    shutil.copyfile(root / paths[0], repository / paths[0])
    git("add", "--all")
    git("commit", "-qm", "restore product")
    assert check().returncode == 0
    (repository / paths[6]).write_text("def unreviewed_harness_change(): pass\n")
    git("add", "--all")
    git("commit", "-qm", "harness drift")
    rejected_harness = check()
    assert rejected_harness.returncode != 0
    assert "state=PASS" not in rejected_harness.stdout


@pytest.mark.parametrize("stage", ["FIXTURE", "CHROME_START", "GUEST_NAV", "OWNER_NAV", "CLEANUP"])
def test_phase_receipt_redacts_exception_and_exposes_only_category(stage, monkeypatch, capsys):
    secret = "member@example.invalid?queueittoken=secret-canary"

    def unavailable(phase):
        phase[0] = stage
        raise RuntimeError(secret)

    monkeypatch.setattr(runner, "run", unavailable)
    assert runner.main() == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert f"state=NO_GO phase={stage} " in output.out
    assert "owner_auth=WSGI_SYNTHETIC_ONLY" in output.out
    assert "page_egress=ROUTE_DENIED" in output.out
    assert "egress=0" not in output.out
    assert secret not in output.out
