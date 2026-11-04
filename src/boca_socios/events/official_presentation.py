"""Offline, explicitly non-actionable projections of official public notices.

These helpers perform no requests, browser navigation, database writes or
bot command routing.  Their inputs are *observations*, not a live official
feed or provider receipts.  Never use them to infer ticket availability.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from html import escape

from .official_catalog import (
    CategoryWindow,
    OfficialCatalogError,
    OfficialNotice,
    assess_official_notice,
    build_observed_catalog,
)

_ART = timezone(timedelta(hours=-3))
_MEMBER_LABELS = {
    "activos_interior": "Activos e interior",
    "adherentes": "Adherentes",
    "plenos": "Plenos",
    "abonados": "Abonados",
    "abono_solidario": "Abono solidario",
    "vitalicios": "Vitalicios",
}
_AREA_LABELS = {
    "generales": "generales",
    "plateas": "plateas",
    "plateas_y_generales": "plateas y generales",
}
_CHANNEL_LABELS = {
    "BOCA_SOCIOS": "Boca Socios, según transcripción no verificada",
    "CONMEBOL": "plataforma de CONMEBOL, según transcripción no verificada",
    "UNKNOWN": "canal no determinado",
}


def _art_time(at: datetime) -> datetime:
    if at.tzinfo is None or at.utcoffset() is None:
        raise OfficialCatalogError("information cut must specify a timezone")
    return at.astimezone(_ART)


def _observed_minutes(notice: OfficialNotice, at: datetime) -> int:
    # Reuse the strict no-pre-observation contract from the catalog.
    assess_official_notice(notice, at=at)
    return int((at - notice.observed_at).total_seconds() // 60)


def _window_document(window: CategoryWindow) -> dict[str, object]:
    return {
        "member_category": window.member_category,
        "seat_area": window.seat_area,
        "opens_at": window.opens_at.isoformat(),
        "closes_at": window.closes_at.isoformat() if window.closes_at is not None else None,
        "close_rule": window.close_rule,
        "exact_close_time_published": window.close_rule == "timestamp",
    }


def export_observed_catalog_json(notices: Iterable[OfficialNotice], *, at: datetime) -> str:
    """Canonical JSON for future *informational-only* panel integration.

    In particular, ``observed_age_minutes`` is age of a supplied capture;
    it **never** verifies source freshness, schedule validity or eligibility.
    """
    as_of = _art_time(at)
    catalog = build_observed_catalog(notices)
    events: list[dict[str, object]] = []
    for notice in catalog:
        assessment = assess_official_notice(notice, at=at)
        events.append(
            {
                "event_key": notice.event_key,
                "title": notice.title,
                "kickoff_at": notice.kickoff_at.isoformat(),
                "source": {
                    "url": notice.source_url,
                    "published_on": notice.published_on.isoformat(),
                    "observed_at": notice.observed_at.isoformat(),
                    "sha256_asserted": notice.source_sha256,
                },
                "observation_age_minutes": _observed_minutes(notice, at),
                "verification_state": notice.verification_state,
                "admission_channel_claim": notice.admission_channel_claim,
                "admission_channel_excerpt": notice.admission_channel_excerpt,
                "admission_channel_verified": False,
                "phase": assessment.phase,
                "actionable": False,
                "windows": [_window_document(window) for window in notice.windows],
            }
        )
    document = {
        "schema": "boca-official-observations-info-v1",
        "as_of_art": as_of.isoformat(),
        "source_mode": "OFFLINE_PREOBSERVED_ONLY",
        "live_feed": False,
        "availability_verified": False,
        "admission_channel_verified": False,
        "actionable": False,
        "events": events,
    }
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _time(value: datetime, *, label: str) -> str:
    stamped = value.astimezone(_ART).isoformat()
    return f'<time datetime="{escape(stamped, quote=True)}">{escape(label)}</time>'


def _window_html(window: CategoryWindow) -> str:
    category = escape(_MEMBER_LABELS[window.member_category])
    sector = escape(_AREA_LABELS[window.seat_area])
    opens = _time(
        window.opens_at, label=window.opens_at.astimezone(_ART).strftime("%d/%m/%Y %H:%M ART")
    )
    if window.close_rule == "timestamp":
        if window.closes_at is None:
            raise OfficialCatalogError("timestamp close rule has no observed time")
        close = "Cierre publicado: " + _time(
            window.closes_at,
            label=window.closes_at.astimezone(_ART).strftime("%d/%m/%Y %H:%M ART"),
        )
    elif window.close_rule == "stadium_open":
        close = "Cierre: apertura del estadio, sin hora exacta publicada"
    else:
        close = "Cierre: no informado en esta observación"
    return f"<li><strong>{category} — {sector}</strong>. Apertura publicada: {opens}. {close}.</li>"


def render_observed_catalog_html(notices: Iterable[OfficialNotice], *, at: datetime) -> str:
    """Accessible HTML fragment, with no active controls or browser scripts.

    The HTML is escaped and labeled in Spanish for Android/Chrome accessibility.
    Nothing here establishes whether an admission window is currently open.
    """
    as_of = _art_time(at)
    catalog = build_observed_catalog(notices)
    lines = [
        '<section aria-labelledby="boca-observed-catalog">',
        '<h2 id="boca-observed-catalog">Avisos públicos de eventos de Boca</h2>',
        '<p role="note">Información publicada observada, sin verificación en vivo. '
        "No confirma disponibilidad, elegibilidad, reservas ni compras. "
        "El canal de admisión no está verificado por este catálogo.</p>",
        "<p>Corte informativo: "
        + _time(as_of, label=as_of.strftime("%d/%m/%Y %H:%M ART"))
        + ".</p>",
    ]
    if not catalog:
        lines.append("<p>No hay avisos oficiales observados cargados.</p>")
    else:
        lines.append("<ol>")
    for notice in catalog:
        assessment = assess_official_notice(notice, at=at)
        minutes = _observed_minutes(notice, at)
        status = (
            "Evento anterior al corte: referencia histórica"
            if assessment.phase == "HISTORICAL"
            else "Evento posterior al corte: horario publicado no verificado en vivo"
        )
        title = escape(notice.title)
        anchor = "boca-observed-" + escape(notice.event_key, quote=True)
        link = escape(notice.source_url, quote=True)
        published = escape(notice.published_on.isoformat())
        channel_label = escape(_CHANNEL_LABELS[notice.admission_channel_claim])
        kickoff = _time(
            notice.kickoff_at,
            label=notice.kickoff_at.astimezone(_ART).strftime("%d/%m/%Y %H:%M ART"),
        )
        observed = _time(
            notice.observed_at,
            label=notice.observed_at.astimezone(_ART).strftime("%d/%m/%Y %H:%M ART"),
        )
        lines.extend(
            [
                f'<li><article aria-labelledby="{anchor}">',
                f'<h3 id="{anchor}">{title}</h3>',
                f"<p>Encuentro: {kickoff}. {escape(status)}.</p>",
                f"<p>Publicado: {published}. Observado: {observed} "
                f"(hace {minutes} minutos respecto del corte). "
                "La antigüedad no acredita actualidad de la noticia.</p>",
                f'<p><a href="{link}" rel="noopener noreferrer">'
                "Ver aviso público oficial (fuente)</a>.</p>",
                f"<p>Canal de admisión mencionado: {channel_label}. "
                "Esta mención no autoriza navegación ni operaciones.</p>",
            ]
        )
        if notice.windows:
            lines.append("<h4>Horarios por categoría y sector publicados</h4><ul>")
            lines.extend(_window_html(window) for window in notice.windows)
            lines.append("</ul>")
        else:
            lines.append("<p>No hay horarios por categoría observados.</p>")
        lines.append("</article></li>")
    if catalog:
        lines.append("</ol>")
    lines.append("</section>")
    return "\n".join(lines)
