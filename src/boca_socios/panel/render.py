"""Render a bounded redacted snapshot as a self-contained accessible HTML page.

The caller supplies status facts. This module cannot query the database, open a
socket, load a credential, confirm an external reservation or change a ticket.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from html import escape
from zoneinfo import ZoneInfo


class PanelStatus(Enum):
    PREPARED = "prepared"
    PREQUEUE = "prequeue"
    WAITING = "waiting"
    ADMITTED = "admitted"
    RESERVATION_PENDING = "reservation_pending"
    SIMULATED_RESERVED = "simulated_reserved"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    FAILED = "failed"


_STATUS: dict[PanelStatus, tuple[str, str]] = {
    PanelStatus.PREPARED: ("Preparado", "waiting"),
    PanelStatus.PREQUEUE: ("En prefila ficticia", "waiting"),
    PanelStatus.WAITING: ("En espera ficticia", "waiting"),
    PanelStatus.ADMITTED: ("Admisión ficticia", "admitted"),
    PanelStatus.RESERVATION_PENDING: ("Reserva ficticia pendiente", "admitted"),
    PanelStatus.SIMULATED_RESERVED: ("Reserva ficticia", "result"),
    PanelStatus.EXPIRED: ("Simulación vencida", "result"),
    PanelStatus.CANCELLED: ("Simulación cancelada", "result"),
    PanelStatus.FAILED: ("Simulación fallida", "result"),
}
_OPAQUE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_BUENOS_AIRES = ZoneInfo("America/Argentina/Buenos_Aires")
_MAX_ENTRIES = 200


@dataclass(frozen=True, slots=True)
class PanelEntry:
    member_id: str
    event_id: str
    status: PanelStatus
    updated_at: datetime
    quantity: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.member_id, str) or not _OPAQUE_ID.fullmatch(self.member_id):
            raise ValueError("member_id must be a bounded opaque identifier")
        if not isinstance(self.event_id, str) or not _OPAQUE_ID.fullmatch(self.event_id):
            raise ValueError("event_id must be a bounded opaque identifier")
        if not isinstance(self.status, PanelStatus):
            raise ValueError("status must be a supported simulation state")
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ValueError("updated_at must have a timezone")
        if type(self.quantity) is not int or self.quantity != 1:
            raise ValueError("exactly one ticket per member and event is permitted")


def render_panel(entries: Sequence[PanelEntry]) -> str:
    """Return HTML without member/event IDs, secrets, outbound requests or side effects."""
    if len(entries) > _MAX_ENTRIES:
        raise ValueError("maximum 200 simulation records per snapshot")
    if any(not isinstance(item, PanelEntry) for item in entries):
        raise ValueError("entries must be validated PanelEntry records")

    keys = [(item.member_id, item.event_id) for item in entries]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate ticket intent for member and event")

    # Numeric labels are intentionally per-page pseudonyms; the actual IDs are
    # never included in HTML, attributes, JS or logs.
    sorted_entries = sorted(entries, key=lambda item: (item.event_id, item.member_id))
    event_labels = {
        event_id: number
        for number, event_id in enumerate(
            sorted({item.event_id for item in sorted_entries}), start=1
        )
    }
    member_labels = {
        member_id: number
        for number, member_id in enumerate(
            sorted({item.member_id for item in sorted_entries}), start=1
        )
    }
    counts = Counter(_STATUS[item.status][1] for item in sorted_entries)
    controls = (
        ("all", "Mostrar todas", len(sorted_entries)),
        ("waiting", "Mostrar en espera", counts["waiting"]),
        ("admitted", "Mostrar admisión", counts["admitted"]),
        ("result", "Mostrar resultados", counts["result"]),
    )
    buttons = "".join(
        f'<button type="button" data-filter="{category}" aria-controls="statuses" '
        f'aria-pressed="{str(category == "all").lower()}">{label} ({count})</button>'
        for category, label, count in controls
    )
    cards: list[str] = []
    for item in sorted_entries:
        label, category = _STATUS[item.status]
        local_time = item.updated_at.astimezone(_BUENOS_AIRES)
        timestamp = escape(local_time.isoformat(), quote=True)
        visible_time = escape(local_time.strftime("%d/%m/%Y %H:%M"))
        cards.append(
            f'<li class="card" data-category="{category}">'
            f"<h3>Partido {event_labels[item.event_id]} · Socio "
            f"{member_labels[item.member_id]}</h3>"
            f'<p class="state">Estado: {label}</p>'
            f"<p>Una solicitud lógica · 1 entrada ficticia</p>"
            f'<p>Actualizado: <time datetime="{timestamp}">{visible_time}</time> '
            f"(Buenos Aires)</p></li>"
        )
    rows = (
        "".join(cards)
        if cards
        else '<li class="empty">No hay estados de simulación para mostrar.</li>'
    )
    return (
        _PAGE.replace("<!-- FILTERS -->", buttons)
        .replace("<!-- CARDS -->", rows)
        .replace("<!-- COUNT -->", str(len(sorted_entries)))
    )


_PAGE = """<!doctype html>
<html lang="es-AR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Estados de simulación · Boca Socios Assistant</title>
  <style>
    :root { color-scheme: light; font-family: system-ui, sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; background: #f2f5f9; color: #16283f; line-height: 1.5; }
    main { max-width: 1024px; padding: 24px; margin: 0 auto; }
    h1 { font-size: clamp(1.7rem, 5vw, 2.5rem); line-height: 1.15; }
    h2 { font-size: 1.4rem; }
    .banner { background: #153d70; color: white; padding: 16px; border-radius: 12px; font-weight: 700; }
    .hint { max-width: 70ch; }
    .filters { display: flex; flex-wrap: wrap; gap: 12px; margin: 20px 0; }
    button { min-height: 52px; min-width: 52px; padding: 10px 18px; border: 2px solid #153d70;
      border-radius: 12px; background: #fff; color: #153d70; font: inherit; font-weight: 650;
      cursor: pointer; }
    button[aria-pressed="true"] { background: #153d70; color: #fff; }
    button:focus-visible { outline: 4px solid #de8319; outline-offset: 3px; }
    .cards { list-style: none; padding: 0; display: grid; gap: 14px; }
    .card, .empty { background: #fff; border: 1px solid #abbccf; border-radius: 12px;
      padding: 16px 20px; }
    .card h3 { margin: 0 0 8px; font-size: 1.25rem; }
    .card p { margin: 6px 0; }
    .state { font-weight: 700; }
    [hidden] { display: none !important; }
    @media (max-width: 600px) { main { padding: 16px; } button { width: 100%; } }
    @media (prefers-reduced-motion: reduce) { *, *::before, *::after {
      scroll-behavior: auto !important; transition-duration: 0s !important; } }
  </style>
</head>
<body>
  <main>
    <h1>Estados de socios y partidos</h1>
    <p class="banner">SIMULACIÓN SIN RESERVAS REALES</p>
    <p id="filter-help" class="hint">Esta vista usa datos ficticios. Los filtros muestran estados
      locales; no realizan solicitudes ni cambian reservas.</p>
    <section aria-labelledby="filters-title">
      <h2 id="filters-title">Filtrar estados</h2>
      <div class="filters" role="group" aria-describedby="filter-help" aria-label="Filtros de estado">
        <!-- FILTERS -->
      </div>
      <p id="visible-count" role="status" aria-live="polite"><!-- COUNT --> registros visibles</p>
    </section>
    <section aria-labelledby="statuses-title">
      <h2 id="statuses-title">Seguimiento ficticio</h2>
      <ol id="statuses" class="cards"><!-- CARDS --></ol>
    </section>
  </main>
  <script>
    "use strict";
    const buttons = document.querySelectorAll("button[data-filter]");
    const cards = document.querySelectorAll("#statuses li[data-category]");
    const count = document.getElementById("visible-count");
    for (const button of buttons) {
      button.addEventListener("click", () => {
        const selected = button.dataset.filter;
        let visible = 0;
        for (const card of cards) {
          const matches = selected === "all" || card.dataset.category === selected;
          card.hidden = !matches;
          if (matches) visible += 1;
        }
        for (const control of buttons) {
          control.setAttribute("aria-pressed", String(control === button));
        }
        count.textContent = `${visible} registros visibles`;
      });
    }
  </script>
</body>
</html>"""
