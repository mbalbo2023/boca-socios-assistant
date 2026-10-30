"""The owner panel renders only synthetic, redacted status snapshots."""

from datetime import UTC, datetime
from html.parser import HTMLParser

import pytest

from boca_socios.panel import PanelEntry, PanelStatus, render_panel


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.buttons: list[dict[str, str | None]] = []
        self.cards: list[dict[str, str | None]] = []
        self.live_regions = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "button":
            self.buttons.append(attributes)
        if tag == "li" and "data-category" in attributes:
            self.cards.append(attributes)
        if attributes.get("aria-live") == "polite":
            self.live_regions += 1


def entry(
    member_id: str = "opaque-1",
    event_id: str = "event-1",
    status: PanelStatus = PanelStatus.WAITING,
) -> PanelEntry:
    return PanelEntry(member_id, event_id, status, datetime(2026, 10, 28, 12, tzinfo=UTC))


def test_semantic_touch_and_voice_controls_for_filtered_snapshot() -> None:
    page = render_panel(
        [
            entry(),
            entry("opaque-2", status=PanelStatus.ADMITTED),
            entry("opaque-3", status=PanelStatus.SIMULATED_RESERVED),
        ]
    )
    parser = PageParser()
    parser.feed(page)

    assert len(parser.buttons) == 4
    assert {button["data-filter"] for button in parser.buttons} == {
        "all",
        "waiting",
        "admitted",
        "result",
    }
    assert all(button["aria-controls"] == "statuses" for button in parser.buttons)
    assert all(button["type"] == "button" for button in parser.buttons)
    assert {card["data-category"] for card in parser.cards} == {
        "waiting",
        "admitted",
        "result",
    }
    assert parser.live_regions == 1
    assert 'lang="es-AR"' in page
    assert 'name="viewport"' in page
    assert "min-height: 52px" in page
    assert ":focus-visible" in page
    assert "SIMULACIÓN SIN RESERVAS REALES" in page
    assert "Reserva ficticia" in page
    assert "28/10/2026 09:00" in page  # Buenos Aires, never host-local time.


def test_opaque_identifiers_never_leave_the_renderer() -> None:
    page = render_panel([entry("private-member-123", "private-event-456")])
    assert "private-member-123" not in page
    assert "private-event-456" not in page
    assert "Socio 1" in page
    assert "Partido 1" in page
    assert "fetch(" not in page
    assert "XMLHttpRequest" not in page


def test_rejects_duplicate_ticket_intents_and_nonunit_quantity() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        PanelEntry("opaque-1", "event-1", PanelStatus.WAITING, datetime.now(UTC), 2)
    with pytest.raises(ValueError, match="duplicate"):
        render_panel([entry(), entry(status=PanelStatus.ADMITTED)])


def test_rejects_naive_time_and_unbounded_or_untrusted_data() -> None:
    with pytest.raises(ValueError, match="timezone"):
        PanelEntry("opaque-1", "event-1", PanelStatus.WAITING, datetime(2026, 10, 28))
    with pytest.raises(ValueError, match="opaque"):
        entry("email@example.com")
    with pytest.raises(ValueError, match="status"):
        entry(status="<script>alert(1)</script>")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="maximum"):
        render_panel([entry(f"opaque-{number}") for number in range(201)])


def test_empty_snapshot_remains_usable_and_explicitly_synthetic() -> None:
    page = render_panel([])
    assert "No hay estados de simulación para mostrar" in page
    assert "SIMULACIÓN SIN RESERVAS REALES" in page
    assert "0 registros visibles" in page
