# Development backlog and agent work order

## Milestone F0 — immutable foundation (current)

- [x] Independent repository source snapshot with clean public history.
- [x] Document one-ticket-per-member-per-event invariant.
- [x] Implement encrypted credential persistence and DB constraints.
- [x] Define Boca-only Compose with bounded resources and fail-closed simulation.
- [x] CI, tests, lint/type quality gates, CODEOWNERS and agent runbook.
- [x] Exact bootstrap PR CI GREEN: quality-and-tests and image-build.
- [x] Docker image builds in CI; no host deployment.
- [ ] Enable and verify enforced branch protection on public GitHub Free;
      an independent reviewer is required before mandatory approval count 1.
- [ ] Enable available dependency, code and image scanning; verify permissions.

## Milestone F1 — simulation and domain workflow

- [ ] State-machine model: scheduled, prequeue, waiting, admitted,
      expired, cancelled, reserved, failed.
- [ ] Deterministic Queue-it simulator with randomized/fifo modes;
      simulator is not proof of Boca's configuration.
- [ ] Identity, event and category models; one ticket quota.
- [ ] Idempotency keys, transactional winner confirmation and
      concurrency regression tests.
- [ ] Retry policy, backpressure and observer-only diagnostics.

## Milestone F2 — owner-facing operations

- [ ] Accessible tablet-first control panel and Telegram alerts.
- [ ] Explicit consent and owner-only secure credential enrollment UI.
- [ ] Credential rotation, deletion, backup and restore tests.
- [ ] Event timing in America/Argentina/Buenos_Aires and official notice
      ingestion with source provenance.
- [ ] Redacted structured event traces and visibility/notification SLA.

## Milestone F3 — navegador real con límites explícitos

- [ ] Playwright worker as separately profiled container with strict CPU
      and memory quota; no broad parallel session launch on a shared host.
- [ ] Isolated BrowserContext per approved session, bounded by config.
- [ ] CI comprueba arranque y cierre de Chromium sin egress; no lo cuenta como
      prueba funcional de reserva ni visita Boca desde cada PR.
- [ ] Observación opt-in de una sola portada **real y pública** de Boca (#27,
      #32), con egress acotado, plazo, stop-on-block y salida redactada.
- [ ] Queue adapter con transporte reemplazable, límites y kill switch; ninguna
      evasión de fila/CAPTCHA ni sesión autenticada sin su gate de aprobación.
- [ ] Medir recursos de **una sesión** en entorno separado (#11). Un test de
      carga sobre Boca necesita autorización explícita distinta y condiciones
      del proveedor; no se infiere capacidad desde una página ficticia.

## Milestone F4 — authorized observation

- [ ] Owner-approved one-account browser walk-through with selective
      redacted observation and no queue-abusive traffic.
- [ ] Confirm actual login/queue order, provider flow, signed pass
      validation, session linkage, eligibility, ticket confirmation.
- [ ] Record evidence vs inference and update ADRs.
- [ ] Human-in-the-loop reservation step and audit trail.
- [ ] Separate policy review prior to live operation.

## Work sequencing

Un issue y una rama por alcance, contratos y pruebas verificables. Las ramas
apiladas #36 → #38 → #40 siguen en borrador: cada PR fuente requiere revisión
humana y CI exacta antes de una fusión. No hay despliegue durante F0-F3 ni
credenciales reales hasta completar alta privada, identidad, respaldo y clave.

