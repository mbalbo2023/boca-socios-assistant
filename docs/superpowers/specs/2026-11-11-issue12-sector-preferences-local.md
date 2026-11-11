# Issue #12 — preferencias multisector en simulación local

Fecha: 2026-11-11. Alcance: fase independiente, preparada en la rama
`feature/12-sector-preferences-offline-20261111` desde `main` @
`bd6c1212f129454f10e5d4a25585c3f4eeb8edea`.

## Objetivo y límites

Agregar una unidad de dominio reutilizable de preferencias de sector por
`member_id`/`event_id` sin interferir con el Cutover, IPC, worker, Docker,
`SITE_URL` o el dashboard 8443 que continúan en otro frente.

**Solo simulación**: catálogo inventado, disponibilidad inyectada, sin red,
browser, credenciales, Queue-it real, pases de cola, reservas ni emisión de
entradas. No hay comandos contra el droplet ni cambios en `main`.

## Comportamiento implementado

- `SectorMode.ALL`: prioriza los sectores según el orden del catálogo sintético.
- `SectorMode.ORDERED_ALLOWLIST`: prioriza solamente los IDs elegidos, en el
  orden indicado por el usuario.
- Si un sector está explícitamente no disponible, pasa al siguiente.
- Si faltan datos de disponibilidad, considera el sector no disponible:
  **fail closed**. Nunca presume que hay entradas.
- Valida IDs de catálogo únicos y no vacíos; rechaza preferencias inválidas,
  sectores desconocidos, claves desconocidas y tipos de disponibilidad ambiguos.
- La evaluación produce **a lo sumo un sector seleccionado**, asociado a
  `TicketIntent(member_id, event_id, quantity=1)`. No materializa solicitudes.
- El simulador existente ya reúne varias sesiones locales de una misma persona
  y evento en una única solicitud lógica; una prueba nueva cruza ambos contratos.
- Preferencia inmutable con `version` y `updated_at` informados por el llamador.

## Ficheros propios de esta fase

- `src/boca_socios/domain/sector_preferences.py` — modelo/evaluación pura.
- `tests/test_sector_preferences.py` — casos offline y compatibilidad con
  `OfflineQueueSimulator` existente.
- Este documento — límites y trazabilidad.

## Reutilización y no duplicación

La fase toma como referencia **conceptual** las preferencias `allowed/all` del
proyecto de Joaquín Coronell y los filtros de sector del proyecto de Benja.
No copia código, cookies, rutinas de autenticación, navegación ni automatismos
de compra de esos proyectos. Se conservan referencias y aprobaciones registradas
por el propietario en el issue #12.

## Integración diferida deliberadamente

1. **Configuración del dashboard**: después de R173/Cutover, agregar editor
   de preferencias al formulario y al registro de URLs ya existente. Reutilizar
   `SITE_URL` editable: no crear otro almacenamiento ni URLs fijas.
2. **Persistencia**: estudiar la versión de migración actual (ya existe
   `0007_telegram_delivery.sql`) y reservar una migración siguiente bajo
   ownership exclusivo; no tocar hoy la base de datos.
3. **Worker**: consumir preferencias únicamente después del cierre y
   verificación física de la integración que lleva el otro chat. La selección
   continua siendo synthetic-only hasta una decisión expresa posterior.
4. **PR**: crear PR solo cuando el owner del Cutover libere el bloqueo de PR0,
   revisar su HEAD de nuevo y consolidar sin pisar ramas.

## Evidencia mínima de fase

- RED inicial: `ModuleNotFoundError` por módulo todavía inexistente.
- GREEN local: `PYTHONPATH=src python -m pytest -q
  tests/test_sector_preferences.py tests/test_queue_simulator.py`.
- Sintaxis: `python -m compileall -q` en ambos ficheros Python nuevos.
- Controles `ruff` y `mypy`: ejecutar antes de solicitar merge; pueden no estar
  instalados en el checkout temporal (no considerar GREEN esos controles hasta
  disponer de salida real).

La validación física del droplet y del dashboard queda **no realizada** en
esta fase, no se declara GREEN productivo.
