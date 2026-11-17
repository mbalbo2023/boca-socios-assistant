# Boca G14 Motor Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dos páginas de motores con estado y cronología visibles de inmediato, actualizadas cada cinco segundos desde señales privadas existentes.

**Architecture:** `engine_view.py` añade una tarjeta server-rendered por motor y usa el polling existente de `/control/motores.json`. Durante el mismo ciclo consulta `/control/actividad.json` solo si hay tarjeta, mostrando hasta cinco eventos globales (rotulados claramente como worker compartido). No agrega control de motor, endpoint, base de datos ni nueva tarea en background.

**Tech Stack:** Python 3, HTML/CSS/JavaScript vanilla, CSP SHA256 existente, pytest y Node VM de tests existentes.

**Spec:** `docs/superpowers/specs/2026-11-17-boca-live-status-delta.md`.

## Global Constraints

- `SIMULATION_ONLY`; nunca reservas reales, bypass Queue-it, pruebas con datos de socio reales ni acreditación ficticia.
- Dos motores lógicos y un worker físico compartido; eventos globales NO atribuibles individualmente al motor.
- GET owner-only `/control/motores.json` y `/control/actividad.json`, `cache: no-store`; un solo intervalo de 5000 ms, sin POST automático.
- Secreto/token solo visible tras inspección privada existente de UUID; nunca volcar links con query, tokens, datos de socio ni credenciales en resumen o feed.
- `WORKER_RECEIPT_UNVERIFIED` NO equivale a `NO_EVENT_CONFIRMED`; distinguir hora de consulta de hora de observación.
- Mantener mismos Start/Stop, CSRF, CSP, redirecciones, navegación y contadores; ningún cambio del backend de Telegram en este plan.
- Accesible en Samsung con control por voz: estado arriba, fuente de texto contrastada, links y botones accesibles, sin scroll lateral.

## Review Focus

- `FAILED`, 25 solicitados, 0 creados: tarjeta nunca dice «no hay evento» ni insinúa browsers activos; prueba en Task 1.
- GET de motores OK pero actividad 503: estado del motor sigue actualizándose; feed histórico y aviso visible; prueba en Task 1.
- GET inválido/caído: conserva valores pasados identificados como históricos y no altera formulario/operación de un solo uso; prueba en Task 1.
- Token o URL con credenciales/query: jamás entra al DOM del resumen; URL de inspección solo `UUID`; prueba en Task 1.
- Eventos sin marca de motor: rotulados «worker compartido» y con hora de señal, distinto de la consulta; prueba en Task 1.

---

### Task 1: Tarjeta de estado vivo y cronología visible

**Files:**
- Modify: `src/boca_socios/panel/engine_view.py` (CSS, `_section`, `_POLL_START`, `_POLL_END`; CSP se mantiene derivada de los scripts)
- Test: `tests/test_engine_live_status_ui.py` (nuevo)

**Interfaces:**
- Consumes: `engine_view.page(snapshot, csrf, operations, members, *, site_url_ready, engine)`; `GET /control/motores.json` `version=1`, `engines` con `state`, `phase`, `updated_at`, `sessions` y métricas; `GET /control/actividad.json` `observed_at`, `events[]` con `at,source,level,message`.
- Produces: tarjeta con IDs específicos del motor (`queues_tokens-live-*` o `browsers_members-live-*`) antes del primer formulario y feed compartido, sin cambiar API externa ni script para controles combinados.

- [ ] **Step 1: RED HTML** — Crear tests de `page(..., engine='queues_tokens'/'browsers_members')` verificando que la tarjeta `aria-label`, estado/etapa/evento/cola/tokens/error, enlace inmediato a `/control/actividad` y feed etiquetado worker compartido aparecen antes de `id='<engine>-start'`. Fixture `FAILED/WORKER_RECEIPT_UNVERIFIED` con `25,0,0` requiere «sin confirmar» y «no comprobado», no «no hay evento».
- [ ] **Step 2: RED JS** — Test Node VM del script real de página: sobre dos snapshots consecutivos cambia fecha de señal, estado y token/enlace inspección, pero no `operation_id` ni selección de socio; feed permite hasta cinco señales con sus horas; fuente global marcada compartida. Otro caso devuelve 503 en `/control/actividad.json` conservando motor actualizado y aviso histórico. Otro falla motor y conserva el estado con aviso de histórico.
- [ ] **Step 3: Confirmar RED** — Ejecutar `.venv/bin/python -m pytest -q tests/test_engine_live_status_ui.py` (esperado tests fallando por tarjeta/feed ausentes).
- [ ] **Step 4: Implementación mínima** — Incorporar tarjeta responsive y progresiva en `_section` o inmediatamente antes, SSR conservador más DOM actualizado vía `textContent`; resumen de evento/cola solo por evidencia de sesión, link de inspección por UUID; feed del worker desde endpoint privado, máximo 5 entradas con `textContent`, tiempo de observación separado, degradación por GET fallido. Reusar el intervalo y evitar aviso ARIA cada 5 s si no cambió el contenido.
- [ ] **Step 5: GREEN** — `.venv/bin/python -m pytest -q tests/test_engine_live_status_ui.py tests/test_engine_view.py tests/test_engine_dashboard_ui_offline.py tests/test_worker_live_activity.py` (esperado PASS).
- [ ] **Step 6: Integración** — correr suite completa y chequeos lint/format del proyecto, inspeccionar regresiones CSP y `git diff --check`; ningún host Action todavía. Adjuntar resultados a PR y issue #417.
- [ ] **Step 7: Commit** — `git add src/boca_socios/panel/engine_view.py tests/test_engine_live_status_ui.py && git commit -m 'feat(panel): show live motor status and shared worker activity above controls'`.

**Fuera del alcance:** recuperar worker START, nuevas reservas, Telegram sin recibo; se tratarán con diagnósticos y autorización técnica propios, en el mismo candidato de integración si corresponde.
