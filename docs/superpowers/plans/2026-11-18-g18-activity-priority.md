# Boca G18 Activity Priority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hacer visibles primero ambos motores en Actividad, conservando su telemetría veraz, sus sesiones y un solo registro global de worker plegado.

**Architecture:** El renderer `engine_view.activity_content()` reutiliza las tarjetas G17 y pone sesiones/contadores técnicos en detalles cerrados por motor. `private_ui.worker_activity()` mueve el feed compartido a un solo detalle global. El script ya usado por Actividad une la proyección de tarjetas con el sondeo existente de sesiones, sin segundo GET ni función duplicada.

**Tech Stack:** Python 3.12, HTML/CSS/JS vanilla con CSP SHA256, pytest, Node VM, Playwright offline, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-11-18-g18-activity-priority-design.md`

## Global Constraints

- Base exacta `b905ecac90050f0f2d8ff0c483f5864bcc7c856c`; worktree G18 aislado, autor separado de Root, sin modificar #551, sin push/PR/Action/build/deploy antes de 4GO_FINAL.
- Cero nuevas APIs, polls, dependencias o telemetría. `SIMULATION_ONLY`; no operaciones host, externas ni reservas; conservar passkey/CSRF/Origin/CSP y secreto de inspección privada.
- Cambios de producción sólo a `src/boca_socios/panel/engine_view.py` y `private_ui.py`; harness Chromium sólo con fallo reproducido por nuevos details, sin nuevos escenarios de producto.
- La etiqueta FAILED es lógica e histórica, no acredita actividad o fallo físico actual; no inventar URL, evento, cola, HTTP ni token. Adenda 4/4 en [#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6983036738): secuencia `NavigationAttempt.sequence` 1..3 sólo de sesión y socio de activación B sin duplicar.

## Review Focus

1. `FAILED/WORKER_RECEIPT_UNVERIFIED/sessions=[]` debe mostrar causa sin afirmar HTTP, URL visitada, evento o token — Task 1.
2. Deep links de Control no deben saltar a sección colapsada — Task 1.
3. Sesiones sin expansión inicial deben seguir actualizándose y admitir inspección privada tras expandir — Task 2 y 3.
4. Fallo de `/control/motores.json` no debe reemplazar por observaciones físicas falsas — Task 2.
5. Registro global completo con controles reales, aunque plegado, sin doble feed ni IDs — Task 1/3.
6. Secuencia 1..3 con rechazo de valores 0/4/bool/string y sin contar solicitudes como intentos; único socio B visible y polling del `id` original — Task 2.

---

### Task 1: Orden, detalles y enlaces visibles

**Files:** `tests/test_worker_live_activity.py`, `src/boca_socios/panel/engine_view.py`, `src/boca_socios/panel/private_ui.py`.

**Interfaces:** `_live_card(engine, snapshot, *, include_worker_details=True, heading_id=None)` y `_section(..., heading_id=None)` conservan defaults de páginas actuales; `activity_content(snapshot,members)` consume las variantes sin worker y anchors visibles. `worker_activity()` conserva los mismos IDs del worker bajo detalles.

- [x] **RED:** ampliar `test_activity_combines_both_engines_without_minting_operations` con orden de cards A/B antes de global, links a headings principales visibles, tech headings distintos, `aria-labelledby`, `<details>` cerrados, unicidad de IDs, un feed global y no datos de URL/tokens inventados. Ejecutar y observar fallo de orden/ausencia de tarjetas.
- [x] **GREEN:** extraer el feed worker global a `<details>` con sus botones/IDs, poner `engine_view.activity_content` antes, renderizar tarjetas G17 con worker interno omitido, mover sesiones y métricas bajo `<details>` por motor; conservar nav y CSP. Ejecutar pruebas focales.
- [x] **Regresión:** tests de Control/Actividad, links, permisos, estado G17 y `git diff --check`.

### Task 2: Polling de tarjetas y sesiones simultáneos

**Files:** `tests/test_engine_view.py`, `src/boca_socios/panel/engine_view.py`.

**Interfaces:** `_SCRIPT` añade `_LIVE_CONSTANTS`/`_LIVE_PROJECTION_SCRIPT` a `_MOTOR_BODY`, con `refreshPage()` que llama `refreshEngines()` una sola vez y actualiza cada `updateMotorCard`; mantiene `updateSessions` real.

- [x] **RED:** Node VM con `mode="activity"`, dos motores y snapshots cambiantes; afirmar que tras cada ciclo cambian `*-live-state`, `*-live-error`/URL saneada, `*-sessions` y métricas, una solicitud GET motor por ciclo; fallo de consulta marca histórico. Observar ausencia de actualización de las tarjetas.
- [x] **GREEN:** composición mínima de `_SCRIPT`, sin otro worker polling o cambios a Control/dedicados; conservar CSP automático. Ejecutar Node/pytest focales.
- [x] **Regresión:** home/control/dedicados, JS parity G17, CSP, proveedor no contactado.
- [x] **Adenda RED/GREEN:** `tests/test_engine_live_status_ui.py::test_navigation_attempt_number_is_only_a_valid_per_session_sequence` (1/3 versus 0/4/bool/string/None, A/B, SSR+poll y cero sesiones); `tests/test_engine_view.py::test_activity_shows_selected_member_once_above_closed_technical_details` (un ID, nombre en tarjeta superior sin details). Implementar sólo en `_live_projection`/JS actual y extraer el fragmento de socio de `_section` para reusarlo arriba en Actividad, conservando el mismo ID para `updateEngine`.

### Task 3: Preparar harness Chromium para CI y verificar localmente sin navegador

**Files:** `scripts/run_engine_dashboard_ui_offline_chromium.py` **sólo ante defecto de selector/visibilidad demostrado por test DOM reproducible**; ajustar el test unitario asociado sin relajar aserciones.

**Interfaces:** harness existente para posteriores screenshots y métricas 412/800/1536 px **en GitHub Actions de Boca únicamente**, Engine A/B primero, sesiones accesibles al abrir `<details>`, registro global plegado, altura y scroll dentro de cotas.

- [x] **Contrato de DOM reproducido sin navegador:** pytest real prueba que `li.engine-session` reside bajo `<details>` cerrado por defecto y que link `data-session-id` de live card puede existir, de modo que los selectores previos de todo `[data-session-id]` y `a[data-field=inspect]:visible` sin expandir detalles eran incompatibles. Registrar esta causa; no reclamar un fallo Playwright ejecutado.
- [x] **Preparación:** actualizar solamente el harness con selector `li.engine-session[data-session-id]`, apertura/cierre de detalles por motor, y aserción de orden A/B/global. Chequear sintaxis/estilo de Python; **no ejecutar Playwright/Chromium local**.
- [x] **Verificación local y handoff:** pytest relevante incluyendo test de harness (307 PASS), Ruff check y format (7 archivos), mypy (2 módulos) y `git diff --check`; commit local separado de PR/Actions. QA visual y suite CI completa **pendientes** de los gates posteriores; nada de GH ni host.

**RCA de compatibilidad del harness:** en el HTML nuevo hay dos elementos `li.engine-session[data-session-id]` y tres nodos `[data-session-id]` porque la tarjeta G17 tiene un link privado adicional; las sesiones ahora están dentro de `<details>` inicialmente cerrados. El selector genérico antiguo y las aserciones que exigían enlaces visibles antes de expandir no correspondían al DOM. Con la corrección del harness, el test de AST/Node `test_dom_waits_keep_conditions_when_later_eval_is_blocked` devolvió RED (1 fallo de 123) porque el simulador exigía literalmente el selector anterior; el ajuste de **una línea** en ese test lo dejó GREEN (123/123). Esto no acredita un navegador físico ni un sitio externo.
