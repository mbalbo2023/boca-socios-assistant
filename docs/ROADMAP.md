# Development backlog and agent work order

**Corte vigente:** 2026-10-29 (America/Argentina/Buenos_Aires), `main`
`9aeb005b9dddec663d5e8ecfcf703044205d5be6`. Las casillas indican el
hito completo; un componente integrado no valida por sí solo el uso real de
Boca, la interfaz privada ni el host.

## Milestone F0 — immutable foundation (current)

- [x] Independent repository source snapshot with clean public history.
- [x] Document one-ticket-per-member-per-event invariant.
- [x] Implement encrypted credential persistence and DB constraints.
- [x] Define Boca-only Compose with bounded resources and fail-closed simulation.
- [x] CI, tests, lint/type quality gates, CODEOWNERS and agent runbook.
- [x] Exact bootstrap PR CI GREEN: quality-and-tests and image-build.
- [x] Docker image builds in CI; no host deployment.
- [x] Verify active `protect-main` ruleset on public GitHub Free: require PR,
      exact checks and resolved conversations with zero mandatory approving
      reviews under ADR 0038. Record agent technical review for each PR.
- [ ] Enable available dependency, code and image scanning; verify permissions.

## Milestone F1 — simulation and domain workflow

- [ ] State-machine model: scheduled, prequeue, waiting, admitted,
      expired, cancelled, reserved, failed.
- [ ] Deterministic Queue-it simulator with randomized/fifo modes;
      simulator is not proof of Boca's configuration.
- [ ] Identity, event and category models; one ticket quota.
- [ ] Idempotency keys, transactional winner confirmation and
      concurrency regression tests. #36 ya prueba una sola ejecución local
      ante alias concurrentes y #38 integra una concesión durable SQLite;
      faltan wiring y confirmación/conciliación de la reserva externa.
- [ ] Retry policy, backpressure and observer-only diagnostics.

## Milestone F2 — owner-facing operations

- [ ] Accessible tablet-first control panel and Telegram alerts.
- [ ] Explicit consent and owner-only secure credential enrollment UI.
- [ ] Ciclo de claves y baja completa de credenciales: #40 (recifrado interno)
      sigue draft; #31 no ofrece una interfaz privada de gestión.
- [ ] Event timing in America/Argentina/Buenos_Aires and official notice
      ingestion with source provenance.
- [ ] Redacted structured event traces and visibility/notification SLA.

## Milestone F3 — navegador real con límites explícitos

- [ ] Playwright worker as separately profiled container with strict CPU
      and memory quota; no broad parallel session launch on a shared host.
- [ ] Isolated BrowserContext per approved session, bounded by config.
- [x] CI comprueba arranque y cierre de Chromium sin egress mediante #43,
      integrado en `main`; no lo cuenta como prueba funcional de reserva ni
      visita Boca desde cada PR. #44 también está integrado y midió un solo
      arranque offline; pendiente medición de una visita real autorizada y
      de la capacidad del host.
- [ ] Observación opt-in de una sola portada **real y pública** de Boca (#27,
      #32), con egress acotado, plazo, stop-on-block y salida redactada. La ruta
      pública `/auth/login` se vio manualmente; el script #33 no fue ejecutado.
- [ ] Queue adapter con transporte reemplazable, límites y kill switch; ninguna
      evasión de fila/CAPTCHA ni sesión autenticada sin el hito técnico y
      consentimiento correspondientes.
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

Un issue y una rama por alcance, contratos y pruebas verificables. #36 y #38
ya están integrados; #40 continúa draft y necesita revisión técnica y CI de
su HEAD exacta antes de fusionar. #66 incorporó el contrato de motor `off` y
#69 el diagnóstico sólo lectura y #71 el postflight estricto, pero ninguno
acredita un host listo. Faltan #79/#81/#89/#91/#97 y los gates objetivos de
release, SSH, rootless, recursos y capacidad antes de cualquier dispatch por
el único workflow manual Boca. Sin operación automática por merge.

#29 y #31 no conforman aún una interfaz autenticada de tablet/alta; #110 es
una vista previa sintética en draft. CI verifica Chromium offline sin usar una
página Boca ficticia como prueba funcional. Una futura prueba del flujo real
requiere una sesión legítima, autorización y límites de tráfico separados.
Una falla de la fuente pública se diagnostica por Actions y se informa como
alerta, sin bloquear por sí sola la simulación ni justificar un nuevo
despliegue.

## Hito diferido por decisión del dueño

Backup/restore y recuperación operativa se retoman después de contar con una
versión productiva fiable. #47 incorporó una biblioteca offline; esto no
equivale a custodia ni a un ensayo de restauración. El hito queda fuera del
gate de la BETA de simulación. No se ingresan credenciales reales: ADR 0012/0022
mantienen pendientes sus requisitos de recuperación y custodia antes del alta
real, además del canal privado, identidad, TLS y ciclo de claves.

