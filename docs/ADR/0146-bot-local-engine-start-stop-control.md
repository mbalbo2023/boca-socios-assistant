# ADR0146 — Motor sintético local Start/Stop real sin apagar panel

Fecha: 2026-11-05 ART  
Estado: **DRAFT / código y regresiones solamente / NO_GO físico**  
Ownership: issue #328, candidato posterior a A45-R21 / PR #319.

## RCA verificado

Antes de esta propuesta, `LocalBetaRuntime.start()` creaba un único
`BetaCommandHost` con un bucle asyncio en un hilo permanente dentro del mismo
proceso que sirve HTTP. El panel podía pedir Start/Stop de `bot` en la SQLite
legacy, pero el contrato host `LifecycleHostSnapshot.bot_engine_running` no
tenía una lectura real: `BOCA_ENGINE_MODE=off` no describe el estado del hilo
sintético local, y la pausa global de admisiones es otro control. Un host
podría dibujar un botón y un `REQUESTED`, no acreditar un Start/Stop físico.

## Decisión de código

- La fachada `BetaCommandHost` mantiene su identidad para las vistas del
  panel y ahora expone `stop_engine()`/`start_engine()` idempotentes. STOP
  cancela el trabajo sintético activo mediante `BetaCoordinator.close()`,
  espera su finalización y **une el hilo** antes de declarar `engine_stopped`.
  START construye un coordinador nuevo sobre la misma SQLite, outbox y puerto
  sintético, levanta **un bucle/hilo nuevo**, ejecuta recuperación de comandos
  durables y sólo entonces declara `engine_running`. Fallas parciales quedan
  en estado desconocido/fallido; no se reporta ACK positivo.
- Una parada intencional deshabilita admisiones de comandos, pero mantiene
  `LocalBetaRuntime.ready=True` para preservar el HTTP autenticado de
  `127.0.0.1:8443`. El panel no presenta un `BetaCommandHost.failed=False`
  falso cuando el worker fue detenido. Consultas directas de estado durable
  pueden leer SQLite aun con el bucle parado; ningún comando se reprocesa
  implícitamente.
- En el candidato futuro con `BOCA_BROWSER_BACKEND=ipc`, `ServedBeta` puede
  levantar un socket **AF_UNIX dentro del /tmp privado del controlador**:
  `/tmp/boca-socios-engine-v1.sock`, modo `0600`, identidad del mismo UID/GID
  y `SO_PEERCRED`. Su único protocolo de una solicitud permite
  `status`, `start`, `stop` y devuelve una observación acotada de hilo real,
  no un dato del cliente ni un permiso para tocar Docker. Sin puerto IP nuevo,
  sin conexión a Boca/Telegram y sin acceso al socket del host. El controlador
  legacy con backend `off` **no** arranca este listener.
- Un **futuro** adaptador rootless Docker podría ejecutar el cliente dentro
  del **ID exacto del controlador** con `docker exec` protegido y contrastar
  respuesta/estado con `HostLifecycleSnapshot` bajo la misma lease #328.
  Este PR **no** añade ese adapter, workflow o autorización; `main` y el
  droplet permanecen intactos.

## Límites que prohíben presentar el control como desplegado

1. No hay integración del UI `REQUESTED` con un invocador autorizado de GitHub
   Actions ni implementación host `claim→effect→observe→ACK`, por lo que las
   cuatro acciones siguen pendientes hasta Cutover A y GO exacto. No hay
   prueba física ni heartbeat de Docker/Chromium; no se ha tocado el worker
   BLACKBOX ni implementado navegación real.
2. Tras **reinicio completo del contenedor** el hilo actual se levanta como
   en el flujo previo; el último Stop de `bot` todavía **no se restaura** desde
   un recibo durable validado. No se habilitará el despacho físico de Start/Stop
   sin resolver esa política de recuperación para evitar reactivación
   silenciosa; una solicitud huérfana se mantiene `NO_GO`.
3. Los tests locales de esta sesión corren en un ejecutor donde `socket(AF_UNIX)`
   responde `EPERM`; por eso comprueban el despacho real sobre el bucle y el
   framing/protocolo sin bind kernel. Un test independiente del socket real
   dentro de runner Linux de GitHub y luego host rootless es obligatorio
   antes de registrar disponibilidad del transporte.
4. El motor permanece SIMULATION_ONLY y `BOCA_ENGINE_MODE=off`: no inicia
   sesión en Boca, no accede a Queue-it, no reserva/compra y no envía Telegram.
   Los demás servicios y volúmenes del droplet, la sesión Chrome separada
   de Opción B, puertos y proceso Docker no se modifican.

## Evidencia y criterios posteriores

- Pruebas focales: stop real del hilo, cancelación in-flight, dos ciclos
  idempotentes, recuperación durable sin duplicar, controller ready cuando el
  motor está parado, transiciones de protocolo/framing, aislamiento AF_UNIX
  y cierre del listener. No se usan credenciales ni red real.
- Tras publicación registrar SHA/tree exactos, ejecución completa de pytest,
  Ruff, MyPy, repo-policy y Actions PR-only en #328/#45. Los green del candidato
  original #319 no se heredan automáticamente.
- Integración futura: atestación Docker UID10001, `HostProbe` verdadero,
  controller/worker exactos y sin detener HTTP; autorización de
  `cutover-a-apply` por GO separado, ciclo de estado persistente y ACK
  observable después de reinicio, limpieza selectiva Boca tras cada deploy.

Esta ADR diferencia deliberadamente **motor sintético local físicamente
apagable en código** de **función integrada/desplegada en tablet**.
