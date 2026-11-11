"""Owner-visible control receipts cannot imply navigation or a real booking."""

from __future__ import annotations

from uuid import uuid4

from boca_socios.panel import private_ui
from boca_socios.panel.lifecycle_intents import LifecycleIntent


def test_saved_site_url_explains_that_local_simulation_never_visits_it() -> None:
    rendered = private_ui.site_url_configuration(
        "csrf-fixture", str(uuid4()), "https://ensayo.example.invalid/"
    ).decode("utf-8")

    assert "Guardada en el volumen privado de Boca" in rendered
    assert "El próximo arranque verifica la configuración" in rendered
    assert "En la simulación local, SITE_URL no se visita" in rendered
    assert "El nuevo destino se usará" not in rendered


def test_applied_start_receipt_only_claims_control_not_a_completed_simulation() -> None:
    intent = LifecycleIntent(
        operation_id=str(uuid4()),
        component="bot",
        target="start",
        status="APPLIED",
        requested_at="2026-11-11T15:00:00Z",
        on_demand=True,
    )
    rendered = private_ui.bot_control(intent, "csrf-fixture", str(uuid4()), str(uuid4())).decode(
        "utf-8"
    )

    assert "El ejecutor confirmó sólo esta orden de control" in rendered
    assert "No acredita una simulación completada ni una reserva" in rendered
