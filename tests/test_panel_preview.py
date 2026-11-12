"""The downloadable panel preview contains only fixed synthetic statuses."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/panel-preview.yml"


def _step_section(name: str) -> str:
    raw = WORKFLOW.read_text(encoding="utf-8")
    marker = f"      - name: {name}\n"
    assert marker in raw
    return raw.split(marker, 1)[1].split("      - name:", 1)[0]


def _run_synthetic_guard(tmp_path: Path, page: bytes) -> subprocess.CompletedProcess[str]:
    section = _step_section("Verify generated preview contains only public synthetic data")
    assert "        run: |\n" in section
    body = textwrap.dedent(section.split("        run: |\n", 1)[1])
    preview_dir = tmp_path / "panel-preview"
    preview_dir.mkdir()
    (preview_dir / "index.html").write_bytes(page)
    env = os.environ | {"RUNNER_TEMP": str(tmp_path)}
    return subprocess.run(  # noqa: S603 - execute workflow's actual bounded local shell
        ["/usr/bin/bash", "-e", "-c", body],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )


class PreviewParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.buttons: list[dict[str, str | None]] = []
        self.live_regions = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "button":
            self.buttons.append(attributes)
        if attributes.get("aria-live") == "polite":
            self.live_regions += 1


def test_workflow_entrypoint_prints_touch_and_voice_preview_without_member_data() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/generate_panel_preview.py"],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    assert completed.stderr == ""
    page = completed.stdout
    parser = PreviewParser()
    parser.feed(page)

    assert 'lang="es-AR"' in page
    assert "SIMULACIÓN SIN RESERVAS REALES" in page
    assert "Esta vista usa datos ficticios" in page
    assert "min-height: 52px" in page
    assert ":focus-visible" in page
    assert parser.live_regions == 1
    assert {button.get("data-filter") for button in parser.buttons} == {
        "all",
        "waiting",
        "admitted",
        "result",
    }
    assert "4 registros visibles" in page
    assert re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", page) is None
    for forbidden in (
        "sample-member-",
        "sample-match-",
        "<form",
        'type="password"',
        "fetch(",
        "XMLHttpRequest",
        "http://",
        "https://",
    ):
        assert forbidden not in page


def test_internal_main_pr_uploads_synthetic_preview_without_bypassing_quality() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    # A separate, optional four-second preview; never a CI/release gate.
    assert "on:\n  pull_request:" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "deploy" not in workflow.lower()
    assert "secrets." not in workflow
    assert "docker " not in workflow
    assert "ssh " not in workflow
    job = workflow.split("jobs:\n", 1)[1]
    assert "github.event.pull_request.head.repo.full_name == github.repository" in job
    assert "github.repository == 'mbalbo2023/boca-socios-assistant'" in job
    assert "github.event.pull_request.base.ref == 'main'" in job
    upload = _step_section("Upload tablet preview")
    assert "github.event_name == 'pull_request'" in upload
    assert "github.event.pull_request.head.repo.full_name == github.repository" in upload
    assert "github.event.pull_request.base.ref == 'main'" in upload
    assert "github.actor == 'mbalbo2023'" in upload
    assert "if-no-files-found: error" in upload
    assert "retention-days: 7" in upload
    assert "boca-panel-synthetic-preview-${{ github.sha }}" in upload
    render = _step_section("Render fixed synthetic statuses")
    assert "env -i" in render
    assert "PYTHONPATH=src" in render
    assert "GITHUB_TOKEN" not in render


@pytest.mark.parametrize(
    "extra",
    [
        b'<form action="/control/bot/iniciar">',
        b'<a href="https://untrusted.example/">bad</a>',
        b'<img src="https://untrusted.example/">',
        b"user.name@example.com",
        b'<iframe src="/admin">',
        b'fetch("/private")',
        b'<input type="password">',
        b'<script src="/other.js"></script>',
        b'onload="alert(1)"',
        b"javascript:alert(1)",
        b"A" * 80000,
    ],
)
def test_preview_upload_guard_fails_closed_on_nonpublic_or_active_html(
    tmp_path: Path, extra: bytes
) -> None:
    good = subprocess.run(
        [sys.executable, "scripts/generate_panel_preview.py"],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        check=True,
        timeout=5,
    ).stdout
    assert _run_synthetic_guard(tmp_path, good + extra).returncode != 0


def test_preview_upload_guard_accepts_own_fixed_sample_only(tmp_path: Path) -> None:
    good = subprocess.run(
        [sys.executable, "scripts/generate_panel_preview.py"],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        check=True,
        timeout=5,
    ).stdout
    result = _run_synthetic_guard(tmp_path, good)
    assert result.returncode == 0, result.stderr
