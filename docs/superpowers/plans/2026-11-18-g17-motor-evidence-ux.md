# G17 Motor Evidence UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corregir en una sola rama la falta de URL, resultado, causa conocida y estado observable del Motor A, sin atribuir resultados no registrados ni repetir G16.

**Architecture:** Extender la proyección HTML inicial y su equivalente JS dentro de `engine_view.py`, consumiendo exclusivamente los campos de sesión existentes. Exponer una tarjeta principal por motor, plegar los registros globales y eliminar el resumen técnico redundante. Mantener rutas, datos, permisos y proceso físico intactos.

**Tech Stack:** Python 3.12, HTML/CSS/JS vanilla con CSP SHA256, pytest + Node offline harness, Ruff, mypy, GitHub Actions Boca.

**Spec:** `docs/superpowers/specs/2026-11-18-g17-motor-evidence-ux-design.md`

## Global Constraints

- Base **exacta** `main@75b00d8e1cd903d3d727a2628134a27fd740fc42`; rama `feature/417-g17-motor-evidence-ux`; un solo writer para `engine_view.py` y pruebas. Cero cambios host, workﬂow, proveedor, navegador, coordinador, SQLite o Telegram.
- G16 #1228 ACCEPTED, #1229 PROVISIONED y #1237 READ_ONLY SUCCESS son evidencia histórica/física, no nuevo deploy; BETA NO_CERTIFIED.
- Se preservan dos motores lógicos y un worker, tres páginas primarias, pasarela de sesiones privada, `simulation:write`, passkey/CSRF/Origin, CSP, anti-replay y `SIMULATION_ONLY` sin reservas reales; Porota intocable.
- El error sin recibo tipado se muestra como “causa técnica no registrada”; jamás interpolar excepción, bearer o URL con query ni atribuir NO_EVENT a falta de evidencia.
- El owner Root escribe documentación/issue e integra; autor distinto modifica fuente/test, reviewers Arquitectura/QA/Operaciones verifican diff. Sin PR/release/build duplicados.

## Review Focus

1. `sessions=[]` con 25 solicitudes y 0 creados: ninguna URL ni HTTP observados, evento/cola no comprobados — Task 1.
2. `navigation_attempt` incluye userinfo/query/bearer: resumen y polling jamás filtran secretos; URL invalidada o saneada según validador actual — Task 1.
3. Sesión cerrada con URL reciente: rótulo “histórica”, nunca sugerir navegación activa — Task 1.
4. `NO_EVENT_CONFIRMED` real frente a `NO_EVENT_OBSERVED` agregado: ausencia explícita separada de desconocimiento — Task 1.
5. Polling `/control/motores.json` falla mientras actividad global responde: estado anterior rotulado histórico, sin confundir un evento global con el motor — Task 2.

---

### Task 1: Exponer URL/HTTP y estado de evidencia por motor

**Files:** `src/boca_socios/panel/engine_view.py`, `tests/test_engine_live_status_ui.py`.

**Interfaces:** `_live_projection(Mapping) -> tuple[dict[str,str],str|None]` y `projection(item)` JS producen idénticos identificadores `configured-url`, `navigation`, `final-url`, además de los actuales `state`, `phase`, `event`, `queue`, `tokens`, `error`, `motor-time`, `page-time`. `_live_card` muestra los campos en A y B, sin otro endpoint.

- [ ] **Step 1 RED:** en `tests/test_engine_live_status_ui.py`, agregar fixture sin sesiones y pruebas `test_motor_a_card_explains_unverified_start_without_navigation` que exija `configured-url` no disponible, `navigation` no registrada, `final-url` sin observación, etapa `WORKER_RECEIPT_UNVERIFIED`, `event/queue` desconocidos, token no observado, 25/0 y ausencia de HTTP inventado. Ejecutar selector y verificar FAIL por campo ausente.
- [ ] **Step 2 GREEN:** agregar mínima proyección server+JS a partir de `configured_url`/`navigation_attempt`/`display_url` de las sesiones reales usando `_evidence_url`, `_navigation`, `evidenceURL`, `navigation`, `formatPrivateTime`; en ausencia de sesión, textos de evidencia no disponible. Mostrar los campos en tarjeta de A/B y mejor mensaje de falta de acuse.
- [ ] **Step 3 RED/GREEN:** fixtures con navegación SITE_URL `FAILED`, HTTP `RETURNED 403`, URL con bearer/query/userinfo, sesión `CLOSED` y token/cola/evento recibido; afirmar igualdad de campos iniciales y tras `_poll`, y que el link privado sólo se habilita cuando existe la evidencia. Hacer fallar cada caso antes del ajuste mínimo correspondiente.
- [ ] **Step 4:** ejecutar el archivo focal y tests de CSP/permiso/inspección relevantes; confirmar 0 secretos en resumen HTML, JS o registros; commit de fuente+test.

### Task 2: Desacoplar registro global y quitar repetición de primer nivel

**Files:** `src/boca_socios/panel/engine_view.py`, `tests/test_engine_live_status_ui.py`; usar los mismos tests y no crear fixture adicional innecesaria.

**Interfaces:** `_live_card` conserva `worker-status`, `worker-advisory`, `record-0..4`, `worker-time` para `refreshWorkerFeed`. `_section` conserva forms y operaciones; el panel por motor sigue incluyéndolos sin duplicar el estado ya visible arriba.

- [ ] **Step 1 RED:** test de HTML exige `<details>` plegado “Registro técnico global del worker compartido (no corresponde a navegación del motor)” y que no aparezcan dos rótulos de estado del motor antes del form; comprobar que el JS sigue leyendo ambos endpoints y renderiza los 5 registros allowlist originales.
- [ ] **Step 2 GREEN:** envolver únicamente el feed global en `<details>`; simplificar heading/estado duplicado de la sección de controles sin cambiar endpoints, forms, links, nombres de operaciones ni protección CSP.
- [ ] **Step 3:** ejecutar pruebas focales, motor B, expiración de actividad y Voice Access fixture; validar que no hay segundo panel/refresh, scroll horizontal ni texto secreto.
- [ ] **Step 4:** commit del cambio con nota sobre lo que no se ha demostrado físicamente.

### Task 3: Documentación factual y paquete final para revisión

**Files:** `AGENTS.md`, `docs/BETA_INTEGRATION_STATUS.md` (Root), spec/plan actual y changelog concreto; no regenerar README histórico entero.

**Interfaces:** consume SHA final del autor, tests RED/GREEN, ruta de captura y votos independientes; produce comentario #417 con CODE_ONLY vs INSTALLED vs QA.

- [ ] **Step 1:** registrar la causa UX confirmada, el recibo READ_ONLY #1237, los límites de evidencia y pendientes Telegram/login/QA en documentos de estado afectados, sin afirmar versión instalada.
- [ ] **Step 2:** run `git diff --check`, pytest focal+completo, Ruff format/check, mypy e isolation/pin gate conforme CI; identificar y resolver cualquier prueba roja antes de reclamar GO_FINAL. Conservar resultados brutos y números, sin reutilizar pases históricos.
- [ ] **Step 3:** reviewer Arquitectura/QA/Operaciones + Root inspeccionan SHA y diff *después* del código, votan GO_FINAL e integración de un único PR; sólo entonces publicar rama. No build/release/deploy en este paso.

## Después de la implementación

El nuevo artefacto y cualquier APPLY son decisiones posteriores a QA del candidato y reconcilian 6 PR Dependabot automáticos #544–549 bajo política PR0. La inspección del titular en Samsung y los recibos de operaciones Boca determinan la certificación funcional, no los fixtures offline.
