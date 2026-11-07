# R110 Worker Health Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Diferenciar fallos de salud reales sin repetir Cutover ciego.

**Architecture:** Se amplía exclusivamente la fase tipada `worker_primary_phase`
en la transacción V3 existente. El worker conserva control de excepciones y
compensación antes de producir el mismo recibo seguro.

**Tech Stack:** Python 3.12, pytest, GitHub Actions V3.

**Spec:** `docs/superpowers/specs/2026-11-07-r110-worker-health-evidence-design.md`

## Global Constraints

- Sólo Boca, SIMULATION_ONLY, 127.0.0.1:8443; nunca tocar servicios ajenos.
- `synthetic.py` e `ipc_worker.py` son caja negra inviolable.
- Ningún nuevo flujo, secreto, privilegio, retry, log crudo o cambio de timeout.
- Actualizar la enumeración de todos los consumidores existentes sin duplicar
  su validación canónica.

## Review Focus

- Worker sale del proceso: categoría `HEALTH_EXITED`, compensación selectiva.
- Estado Docker unhealthy: categoría `HEALTH_UNHEALTHY`, sin logs privados.
- Health indefinidamente starting: `HEALTH_TIMEOUT` al plazo vigente.
- Fallo de inspección durante espera: `HEALTH_WAIT`, sin confundir con postflight.
- Fallo posterior a healthy: `HEALTH_POSTFLIGHT`, recibo v2 válido.

### Task 1: Pruebas rojas del diagnóstico

**Files:** `tests/test_host_cutover_adapter.py`, tests del recibo/analizador.

- [x] Agregar casos deterministas de cinco fallos y confirmar RED por categorías
      todavía no existentes; probar compensación y rechazo de valor libre.
- [x] Ejecutar únicamente los tests nuevos y registrar fallo esperado.

### Task 2: Instrumentación mínima y esquema canónico

**Files:** `src/boca_socios/host_first_deploy.py`,
`src/boca_socios/host_boca_cutover.py`,
`scripts/host_cutover_postapply_reconcile.py`.

- [x] Implementar las categorías sin cambiar los efectos de host.
- [x] Ejecutar los tests nuevos y las pruebas de terminal v1/v2, CLI,
      reconciliación y compensación; confirmar GREEN.

### Task 3: Documentación, calidad y entrega

**Files:** `docs/ADR/0208-r102-typed-prepare-worker-failure-receipts.md`.

- [x] Documentar la extensión, límites y ausencia de RCA definitivo.
- [x] Ejecutar validación de calidad aplicable y tests amplios sin tocar caja
      negra: 5466 pruebas y 34 subtests verdes, ruff y mypy verdes.
- [ ] Publicar un único PR vinculado a #417, sin segundo escritor del ámbito.
- [ ] Revisar, fusionar sólo GREEN exact-SHA, construir imágenes exactas, y
      comprobar PR0 antes de cualquier Cutover nuevo.
