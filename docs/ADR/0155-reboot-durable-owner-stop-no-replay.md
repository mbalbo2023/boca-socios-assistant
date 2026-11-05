# ADR0155 — Reboot del motor sintético sin reactivar un STOP del dueño

Fecha: 2026-11-05 (ART). Estado: **DRAFT / CODE-ONLY / NO_GO físico**.
Ownership #328: `src/boca_socios/runtime.py`, `integration/operational.py`,
`integration/command_host.py`, tests nuevos de reboot y esta ADR.

## RCA funcional

`LocalBetaRuntime.start()` construía siempre `BetaCommandHost.start()`, que
iniciaba un hilo asyncio y ejecutaba `BetaCoordinator.recover()` antes de
entregar el controller. Por eso, luego de un `bot/stop` confirmado en el ledger
existente `audit_events`, reiniciar el contenedor podía **reactivar el motor y
reprocesar una intención sintética** sin una nueva orden del dueño.

Detener el hilo inmediatamente *después* del constructor no sirve: existe una
ventana de ejecución antes del STOP. Tampoco sirve inferir el estado de
`BOCA_ENGINE_MODE=off` o de un botón visual: ninguna de esas señales contiene
un recibo real del último comando protegido.

## Decisión

1. Antes de crear `LocalBetaRuntime`, `build_beta_server()` examina
   `LifecycleIntentStore(Database(...)).current()` mediante el ledger **legacy
   existente**. No migra SQLite, no crea la tabla 0008 ni otra base, y solo
   aplica esta política al futuro backend opt-in `ipc`; el controller legacy
   con backend `off` conserva su arranque habitual.
2. Sin solicitudes lifecycle, continúa el arranque previo (simulación).
   Únicamente un último `bot/start` con ACK **APPLIED** autoriza reactivar
   automáticamente el motor. Un último `bot/stop APPLIED` restaura `STOPPED`.
   Para una última operación Chromium o un ACK `REFUSED`, el estado completo
   del motor anterior no se puede probar desde `current()`, que sólo expone la
   última solicitud global: se restaura `STOPPED` por defecto. Un responsable
   podrá iniciar el motor después mediante nueva acción protegida.
3. Un `REQUESTED`, `CLAIMED` o `UNCERTAIN`, incluso de Chromium, impide
   arrancar el controller IPC: `LocalRuntimeUnavailable` **antes de ejecutar
   cualquier hilo, recuperación, sidecar o listener HTTP**. También falla
   cerrado si la identidad/estructura del ledger es inválida o inaccesible.
   Requiere nueva observación y reconciliación protegida; no hay retry.
4. `BetaCommandHost.start_stopped()` construye solo objetos inertes, cierra
   el loop aún no iniciado y marca el motor como `stopped`. No llama
   `Thread.start` ni `BetaCoordinator.recover`. El panel servido sigue
   disponible y saludable; `start_engine()` en una operación posterior crea
   su propio nuevo hilo y ejecuta la recuperación normal. El modo de primera
   inicialización rechaza `initial_engine_stopped=True` sin un ledger previo.

## Regresiones y límites

- Matriz RED→GREEN en `tests/test_runtime_reboot_lifecycle.py`: ausencia de
  intents, STOP APPLIED con **zero start/zero recover**, START APPLIED,
  REFUSED conservador, pendientes REQUESTED/CLAIMED/UNCERTAIN antes de crear
  runtime, STOP seguido de Chromium STOP, backend legacy `off`, restart
  explícito desde STOP y rechazo de primera instalación suspendida.
- Los tests usan SQLite temporal real y un navegador de simulación; verifican
  que `schema_migrations` no cambia ni incorpora 0008 durante el reboot.
- No se modifican `synthetic.py`, `ipc_worker.py`, protocolo AF_UNIX, schema,
  Docker, workflow, puerto, claves, owner, Telegram, Porota ni otros servicios.
- **No hay recibo físico** de un reinicio integral ni prueba Samsung Chrome.
  El adaptador #348 y el workflow protegido aún deben conectar
  `REQUESTED→CLAIMED→APPLIED|UNCERTAIN` con el host real, bajo su propia GO.
  Un STOP inerte en código es necesario, pero no demuestra que una solicitud
  en el panel haya apagado realmente el contenedor.
- Seguridad adicional permanece P2 por orden de Tincho; este arreglo es P0
  funcional para evitar reactivación no solicitada, no una ampliación de
  hardening ni un cambio en los límites de simulación.

Regla84: anotar SHA/tree exactos, PR, resultados pytest/Ruff/MyPy/policy,
Actions PR-only y pendientes en #328/#45 después de publicar. Nunca heredar
los GREEN de un candidato anterior ni confundir esta propuesta con deploy.
