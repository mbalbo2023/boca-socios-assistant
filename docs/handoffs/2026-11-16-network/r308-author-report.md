# R308 Task1 — informe del autor separado

Estado: DONE (implementación local; revisión independiente/integración pertenecen a root).
Plan: docs/superpowers/plans/2026-11-15-r308-observed-opening.md.
Spec: docs/superpowers/specs/2026-11-15-r308-observed-opening-design.md.
Base del autor: 98ab1f39b2ff39834b0b33f072dd8d37aad336b6; rama feature/529-r308-countdown.
Commit: 72195d97923f6bc7cf8b293eb34c1910d87cd919.

## Delta

Ocho rutas exactas del plan, cuatro fuentes y cuatro tests existentes; 611 inserciones/12 eliminaciones.

- automatic_observer: canal opcional queue_opening_time_utc separado del ticket; getter/observable con excepción local, sólo string<=64. Apertura aceptada únicamente con PREQUEUE/event_id de la misma muestra, sin alterar ETA ni navegación. Cada nueva inspección aceptada reemplaza los dos campos, incluso por None; inspect permanece caché.
- engine_protocol: parser puro compartido, ASCII/calendario válido, UTC exacto Z/+00:00 y fracciones1..6. Dataclass exige datetime de offset UTC, evento válido y observed_at, o ambos campos None. Codec admite tres shapes completas exactas (nueva, R301, pre-R301), rechaza parciales/duplicados/desconocidos y sintaxis de apertura inválida. Límites sin cambios.
- engine_sessions: now UTC único para filas y timestamp del snapshot; countdown ceil/min0 sólo con autoridad RUNNING no liberada, triple engine/activation/generation idéntico, sesión propia activa/contexto abierto, sin cancelación/cierre/fallo, evento y tres timestamps coincidentes, PREQUEUE y edad0..30s. Fecha histórica sigue disponible cuando el número se retira. TTL30 es únicamente presentación.
- engine_view: fecha ART24h y duración HH h MM min SS s, horas acumuladas sin rollover diario; textos exactos de etiqueta/cero/ausencia. El catch del polling existente retira el número y preserva la fecha histórica; no agrega timer ni foco/control.

## Evidencia RED antes de producto

Comando:
`.venv/bin/python -m pytest -q tests/test_automatic_observer.py tests/test_engine_sessions.py tests/test_engine_session_coordinator.py tests/test_engine_view.py -k 'opening or countdown or snapshot_uses_one_now or failed_poll_removes'`

Ejecución inicial:80 FAIL/155 deselected; nueve casos observer tenían un error de test (observe en vez de observe_queue), por lo que no se cuentan como evidencia causal de producto. Log task-1-red.log preservado.

Tras corregir únicamente ese nombre, sin tocar fuentes:80 FAIL/155 deselected, exit1,1.99s; task-1-red-causal.log. Todos por capacidad ausente: campos/parser/canal de snapshot, proyección y textos. Polling devolvía ['61','61','61'] tras fallo donde se requería retirar el número. No hubo fallo de imports/dependencias/entorno en este RED causal.

## Evidencia posterior

Ejecución única de los cuatro módulos focales con producto:
`.venv/bin/python -m pytest -q tests/test_automatic_observer.py tests/test_engine_sessions.py tests/test_engine_session_coordinator.py tests/test_engine_view.py`

Resultado observado:226 PASS/9 FAIL, exit1,5.09s; log task-1-green.log (nombre del archivo no implica que aquella corrida fuera toda verde). Los nueve fallos son del test nuevo: snapshot fake sin recover_cold, y ocho expectativas 'Precola' cuando el texto vigente del producto es 'Prefila'. Se corrigieron sólo fixture/expectativa; no prueban defectos productivos.

Reejecución únicamente de los selectores afectados:
`.venv/bin/python -m pytest -q tests/test_engine_session_coordinator.py::test_snapshot_uses_one_now_for_every_session_and_its_timestamp tests/test_engine_view.py::test_opening_initial_and_actual_poll_show_same_art_duration_and_no_phase_change`

Resultado:9 PASS, exit0,1.01s. Observado en sesión exec54088. No modificación de fuentes productivas desde la corrida226 PASS. Evidencia consolidada:235 casos distintos de los cuatro módulos cubiertos con PASS; no se afirma una segunda corrida conjunta235/235.

Se reforzó el test existente de máximo IPC con fecha fraccionaria e ID128:
`.venv/bin/python -m pytest -q tests/test_engine_sessions.py::test_inspection_maximum_encoded_payload_remains_bounded`
Resultado:1 PASS, exit0,0.15s; task-1-max-payload.log. Es uno de los235, no un caso adicional.

Cobertura nueva:80 casos parametrizados, fecha aislada sin actividad, PREQUEUE futura, lectura opcional inválida/throwing, borrado por muestra sin fecha, inspect sin I/O, UTC/naive/epoch/bool/offset/calendario/ASCII/fracciones; tres shapes/pares/observación/duplicados; edad0/30/>30/futuro; ceil positivo/cero; deriva de identidad/evento/muestra, STOP/cancelación/cierre/fallo/contexto; now único; HTML/polling equivalentes/ART/duración/cero/ausencia/error/reanudación, ETA y foco intactos.

Calidad sobre las ocho rutas exactas del plan:
- `.venv/bin/ruff check <8 rutas>`:All checks passed, exit0; task-1-ruff.log.
- `.venv/bin/ruff format --check <8 rutas>`:8 files already formatted, exit0; task-1-format.log.
- `.venv/bin/mypy <4 fuentes>`:Success:no issues found in4 source files, exit0; task-1-mypy.log.
- `git diff --check`:exit0, sin salida.

El primer Ruff señaló un literal ASCII.encode() innecesario en test; corregido a literal bytes, sin producto. Mypy ya había pasado antes y fue confirmado después. No se ejecutó suite completa/base, sync/install, Docker, host, proveedor o workflows. Las únicas repeticiones fueron el RED causal corregido y los selectores afectados por fallos o por el refuerzo de payload.

## Límites, decisiones y revisión

Se aplica el plan aprobado y las aclaraciones del root; no hay nuevas funciones de producto ni desviaciones de alcance. Informe delegado usado como registro de autor; root conserva ledger/documentación/GitHub/Actions. No se despacharon subagentes y el autor no emite voto independiente de aprobación.

Revisión propia del diff:campo fuera de ticket/invalid global; productor borra valores al crear nueva inspección sin apertura; codec tres shapes exactas; fences y TTL positivos; UI retira countdown en catch. Sin findings propios pendientes. Revisión independiente y gates exactos quedan en Task2.

Root debe reconciliar documentación/RCA y, si corresponde según el cierre del bundle, pin y tamaño de fuentes del full ZIP; no se editaron builder/pins/caps. Evidencia local offline no acredita proveedor actual, DOM autenticado, confirmación Boca/ganador/foto/Telegram físico ni capacidad física50.

BLACKBOX synthetic.py/ipc_worker.py no fueron abiertos ni modificados. Sin push/PR/host/servicios/mensajes/reservas/dependencias; SIMULATION_ONLY y recursos ajenos protegidos.
