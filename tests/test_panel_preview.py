"""The downloadable panel preview contains only fixed synthetic statuses."""

from __future__ import annotations

import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path


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
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "scripts/generate_panel_preview.py"],
        cwd=root,
        env={"PYTHONPATH": str(root / "src")},
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
