"""Self-contained fake general-ticket journey for a future Chromium worker.

This module has no live URL, HTTP client, authentication, Queue-it SDK or
external reservation operation. It must never be labeled a Boca confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from boca_socios.browser.contracts import SimulationOutcome


class SyntheticFlowError(RuntimeError):
    """A fake screen did not reach its expected state; fail closed."""


class LocatorPort(Protocol):
    async def click(self, *, timeout: float) -> None: ...

    async def inner_text(self, *, timeout: float) -> str: ...


class PagePort(Protocol):
    async def set_content(self, html: str, *, wait_until: str, timeout: float) -> None: ...

    def locator(self, selector: str) -> LocatorPort: ...

    def get_by_role(self, role: str, *, name: str) -> LocatorPort: ...


@dataclass(frozen=True, slots=True)
class SyntheticStep:
    before: str
    action: str
    after: str


STEPS = (
    SyntheticStep("prequeue", "Entrar en fila ficticia", "waiting"),
    SyntheticStep("waiting", "Admitir visita ficticia", "admitted"),
    SyntheticStep("admitted", "Inicio de sesión ficticio", "authenticated"),
    SyntheticStep("authenticated", "Seleccionar general ficticia", "general_selected"),
    SyntheticStep("general_selected", "Confirmar reserva ficticia", "simulated_reserved"),
)

# No links, fetches, forms, user-controlled URLs, remote scripts or payments.
# Inline transitions exist only to exercise real Chromium DOM interactions.
SYNTHETIC_HTML = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<title>Laboratorio de entradas ficticias</title>
<style>body{font-family:sans-serif;margin:2em}[hidden]{display:none!important}</style>
</head><body><main>
<h1>Simulación local. No es el sitio de Boca.</h1>
<output id="stage" role="status">prequeue</output>
<button data-before="prequeue" data-after="waiting">Entrar en fila ficticia</button>
<button data-before="waiting" data-after="admitted" hidden>Admitir visita ficticia</button>
<button data-before="admitted" data-after="authenticated" hidden>Inicio de sesión ficticio</button>
<button data-before="authenticated" data-after="general_selected" hidden>Seleccionar general ficticia</button>
<button data-before="general_selected" data-after="simulated_reserved" hidden>Confirmar reserva ficticia</button>
<script>
const stage = document.getElementById('stage');
const buttons = Array.from(document.querySelectorAll('button[data-before]'));
for (const button of buttons) {
  button.addEventListener('click', () => {
    if (button.dataset.before !== stage.textContent) return;
    stage.textContent = button.dataset.after;
    for (const next of buttons) next.hidden = next.dataset.before !== stage.textContent;
  });
}
</script></main></body></html>"""


class SyntheticTicketScenario:
    """Drive a deterministic fake DOM through the permitted sequence."""

    def __init__(self, page: PagePort, *, timeout_ms: int = 5_000) -> None:
        if not 1_000 <= timeout_ms <= 15_000:
            raise ValueError("synthetic timeout must be between 1000 and 15000 milliseconds")
        self._page = page
        self._timeout_ms = timeout_ms

    async def _assert_stage(self, expected: str) -> None:
        actual = await self._page.locator("#stage").inner_text(timeout=self._timeout_ms)
        if actual != expected:
            raise SyntheticFlowError("unexpected local simulation stage")

    async def simulate_general_reservation(self) -> SimulationOutcome:
        await self._page.set_content(SYNTHETIC_HTML, wait_until="load", timeout=self._timeout_ms)
        for step in STEPS:
            await self._assert_stage(step.before)
            await self._page.get_by_role("button", name=step.action).click(timeout=self._timeout_ms)
            await self._assert_stage(step.after)
        return SimulationOutcome.RESERVED_IN_SIMULATOR
