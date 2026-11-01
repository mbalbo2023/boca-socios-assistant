# Development backlog and agent work order

**Corte vigente:** 2026-10-31 (America/Argentina/Buenos_Aires), `main`
`dc6c69f9746cc4514c7e268846dece9ff30842b5`. Las casillas indican el
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

- [ ] Accessible tablet-first control panel and Telegram alerts. #113 ya tiene
      un Site privado publicado con datos sintéticos; #110 aportó la vista
      previa y #121 la lectura local agregada de SQLite. Faltan servidor
      autenticado, conexión al Site y transporte de notificaciones. El Site
      no accede directamente al archivo SQLite ni acredita gestión operativa.
- [ ] Explicit consent and owner-only secure credential enrollment UI.
- [ ] Ciclo de claves y baja completa de credenciales: #40 integró recifrado
      interno dormido con migración 0004 opt-in; faltan coordinación de
      escritores, bloqueo de DELETE, recuperación y canal privado de #31.
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

Un issue y una rama por alcance, contratos y pruebas verificables. #36/#38
y #40 ya están integrados; el recifrado de #40 permanece desconectado del
runtime y no autoriza rotación real. #66 incorporó motor `off`, #69 diagnóstico
de sólo lectura y #71 postflight estricto. #79/#81 fijaron el límite rootless
y la clave; #89 el digest escaneado; #91 el UID y dos filesystems; #97 la
limpieza selectiva. #99/#117 bloquean reruns, SHA obsoleto y duplicados de
release. #116 integró pruebas de red/cgroups efectivos y capacidad después
de pull/up en runner. #124 corrigió el transporte de argumentos vacíos por
SSH; la nueva inspección manual #70 llegó al helper remoto como UID10001.
Observó directorio privado, user manager y D-Bus propios, controladores
cpu/memory/pids y socket rootful no escribible, pero el socket rootless
estaba ausente. No prueba si el daemon está sin instalar, detenido o fallando.
Faltan diagnóstico de esa causa y preflight real de daemon, límites efectivos,
espacio y aislamiento. Release e instalación siguen NO_GO por esa evidencia;
ningún merge dispara operación automática. Actions sí permite los manuales.

Los alcances disjuntos avanzan en paralelo con un escritor por ruta. La
integración se serializa sobre la HEAD exacta de `main`, con revisión técnica
y checks nuevos del candidato reconciliado. #45 registra el handoff para no
repetir operaciones ni confundir una CI histórica con evidencia vigente.

#124 deja 8 lecciones RCA aceptadas y CI exige sus 21 selectores;
el aprendizaje nuevo se incorpora por una prueba y un PR revisado, sin
autoeditar código.

#29 y #31 no conforman aún una interfaz autenticada de tablet/alta; el Site
privado de #113 sigue siendo demostración. CI verifica Chromium offline sin
usar una página Boca ficticia como prueba funcional. Una futura prueba del
flujo real requiere una sesión legítima, autorización y límites de tráfico
separados. Una falla de la fuente pública se diagnostica por Actions y se
informa como alerta, sin bloquear por sí sola la simulación ni justificar un
nuevo despliegue.

## Próximas integraciones independientes

| Frente | Entrega siguiente y aceptación |
| --- | --- |
| Host | Distinguir instalación, unidad detenida y fallo del daemon Boca con diagnóstico acotado; después preflight, release por digest, instalación y postflight por el único workflow |
| Simulación | Conectar guardia durable y coordinación con pruebas de reinicio, concurrencia y resultado ambiguo; el controlador dormido no es todavía BETA funcional |
| Panel | Exponer la proyección agregada de #121 mediante una capa servidor mínima con identidad y permiso; probar denegación y redacción antes de conectar el Site |
| Notificaciones | Integrar un dispatcher con transporte inyectable, límites, fencing y clasificación de errores; `accept()` actual sólo confirma aceptación local simulada, no entrega externa |
| Chromium | Conservar imagen/smoke existentes; preparar egress de sistema para la observación pública de una sola página y medir una sesión. Los filtros de Playwright no sustituyen ese límite de red |
| PR históricos | Reconciliar #77/#83/#87 con módulos ya integrados; revisar las aportaciones documentales #75/#67/#15 y solapamiento mypy #3/#101 antes de cerrar, rescatar o fusionar |

La base configurada es `/data/boca.sqlite3`, persistida por Compose en
`boca-socios_boca_data`. La inspección #70 no creó ni inventarió ese volumen;
no existe todavía evidencia de una base Boca operativa en el droplet. Las
bases temporales de las pruebas de Actions no son la base del servicio.

Evidencia del corte: [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6551007644),
[inspección #70](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41255522108),
[CI main](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41255414416)
y [escaneo main](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41255414443).

## Hito diferido por decisión del dueño

Backup/restore y recuperación operativa se retoman después de contar con una
versión productiva fiable. #47 incorporó una biblioteca offline; esto no
equivale a custodia ni a un ensayo de restauración. El hito queda fuera del
gate de la BETA de simulación. No se ingresan credenciales reales: ADR 0012/0022
mantienen pendientes sus requisitos de recuperación y custodia antes del alta
real, además del canal privado, identidad, TLS y ciclo de claves.
