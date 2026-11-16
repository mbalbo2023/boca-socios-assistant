# R308 — Observed Opening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** completar la cuenta regresiva desde una fecha de apertura observada, sin inventar actividad ni éxito.

**Architecture:** ampliar el snapshot/IPC de sesión y el monitor existente. El servidor calcula sólo muestras vigentes; la UI reutiliza su polling.

**Tech Stack:** Python, Playwright/JavaScript existente, pytest; ninguna dependencia nueva.

**Spec:** [diseño R308](../specs/2026-11-15-r308-observed-opening-design.md), aprobado4/4 en issue529 antes del código.

## Global Constraints

- Base main1ab24a696bf473f57cdae1ee1f01af024ce1b8e8; no repetir la suite local del árbol base.
- Cuatro fuentes productivas del diseño y sus tests existentes; la adenda aprobada agrega únicamente el cap del runner UI offline y su test. Autor separado; root posee documentación/GitHub/Actions.
- SIMULATION_ONLY; BLACKBOX sin leer/modificar; sin tráfico proveedor, reservas, mensajes ni efectos de host.
- Mantener ETA, navegación, dos motores, contexto50, IPC32768/98304 y passkey.
- Revisión final de Arquitectura/QA/Operaciones/root y gates del SHA exacto antes de integración.

## Review Focus

1. Fecha sola crea falsamente QUEUE_ACTIVE: prueba del snapshot real separado del ticket.
2. Campo opcional defectuoso invalida la cola: excepción local y aceptación de evidencia previa correcta.
3. Evento/generación/STOP cambia mientras hay fecha: cuenta sólo de la identidad actual y muestra coherente.
4. TTL o polling fallido conserva un contador vivo: bordes de edad y catch con retirada de número.
5. Codec acepta UTC ambiguo o upgrade parcial: tres shapes exactas y rechazo de entradas inválidas.

## Task1 — Completar el flujo observado

**Files (autor):**
- Modify: src/boca_socios/browser/automatic_observer.py.
- Modify: src/boca_socios/browser/engine_protocol.py.
- Modify: src/boca_socios/integration/engine_sessions.py.
- Modify: src/boca_socios/panel/engine_view.py.
- Test: tests/test_automatic_observer.py.
- Test: tests/test_engine_sessions.py.
- Test: tests/test_engine_session_coordinator.py.
- Test: tests/test_engine_view.py.

**Interfaces:**
- Consumes: ticket.eventStartTimeUTC, QueuePageObservation PREQUEUE/event_id/observed_at, EngineActivation y _Activation actuales.
- Produces: parse_queue_opening_time(value: object) -> datetime | None en engine_protocol, usado por productor y codec; subconjunto exacto del diseño.
- Produces: SessionInspection.queue_opening_at y queue_opening_event_id, serialización ISO UTC y shapes legacy estrictas.
- Extends: _SNAPSHOT_SCRIPT y AutomaticQueueObserver._snapshot sin modificar queue_page_observation.
- Extends: EngineSessionCoordinator._session_metadata(item, *, now, record, run) y su único caller snapshot; validar identidad completa y autoridad actual antes de calcular.
- Produces: fila con queue_opening_at informativa y countdown int>=0|None; HTML/polling equivalentes.

- [x] Escribir regresiones que fallen por el dato/cálculo faltante, no por dependencias. Incluir fecha aislada sin actividad y muestra PREQUEUE válida con apertura futura.
- [x] Registrar RED causal previo a fuentes productivas.
- [x] Añadir parser/campos/codec y productor opcional sin invalid global. Reemplazar la fecha en cada muestra.
- [x] Proyectar fecha y countdown con now único, edad0..30s, identidad/estado/evento/muestra coincidentes y sin cancelación/cierre/fallo.
- [x] Completar HTML/polling con textos del diseño, ART24h, duración y retirada del contador ante error.
- [x] Verificar UTC/naive/epoch/bool/offset/calendario; bordes0/30/>30/futuro, fracción positiva/cero, drift y STOP; shapes exactas, límites y ETA sin cambios.
- [x] Ejecutar sólo los cuatro módulos focales una vez con el delta, Ruff/formato/mypy afectados; informar fallos reales. La suite completa corresponde al candidato integrado en CI, sin duplicarla localmente.
- [x] Commit únicamente de las ocho rutas. Informe con commits, RED/GREEN, comandos y límites, sin afirmar prueba de proveedor ni host.

## Task2 — Integración y evidencia (root)

- [x] Adenda aprobada 4/4: autor cambia únicamente el cap del JSON offline y su assert de 160000 a 170000; comprobar el fallo de integración y el rechazo sobredimensionado. Medición causal 165160 bytes sobre 72195d9. Sin repetir las suites focales ya acreditadas.

- [x] Revisiones independientes del diff y evidencia, sin repetir suites ya ejecutadas.
- [ ] Registrar RCA y actualizar documentación afectada con estados reales.
- [ ] Consolidar con los otros cambios necesarios del cierre técnico; publicar candidato y obtener gates exactos.
- [ ] Reconciliar dependencia de Telegram antes de una promoción final. No repetir instalaciones ni preparar un binding que vaya a ser reemplazado sin plan de adopción.

## Self-review

Task1 cubre los seis puntos del contrato; Task2 sólo integra y documenta. No
hay escritores concurrentes sobre sus fuentes. Los cinco riesgos de revisión
tienen casos causales. La ubicación del parser evita duplicación/ciclo y no
amplía el diseño aprobado. Producto72195d9 y adenda67f932d revisados4/4;
235 casos distintos aprobados, más dos casos focales de integración y borde
170000/170001. Pendientes CI integrado y promoción, sin evidencia de proveedor.
