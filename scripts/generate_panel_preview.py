"""Print a fixed, synthetic panel preview for tablet accessibility checks.

This entrypoint does not read the runtime database, credentials or environment.
It has no route or network client. Only the existing redacted panel renderer
turns these sample states into HTML.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

from boca_socios.panel import PanelEntry, PanelStatus, render_panel


def build_preview() -> str:
    """Return a self-contained sample page with no actual member or match data."""
    sample_time = datetime(2020, 1, 1, 12, tzinfo=UTC)
    return render_panel(
        (
            PanelEntry("sample-member-01", "sample-match-01", PanelStatus.PREPARED, sample_time),
            PanelEntry("sample-member-02", "sample-match-01", PanelStatus.WAITING, sample_time),
            PanelEntry("sample-member-03", "sample-match-01", PanelStatus.ADMITTED, sample_time),
            PanelEntry(
                "sample-member-04", "sample-match-02", PanelStatus.SIMULATED_RESERVED, sample_time
            ),
        )
    )


if __name__ == "__main__":
    sys.stdout.write(build_preview())
