# R127 — Captura preparada antes de iniciar el worker (diseño)

Fecha: 2026-11-09 ART. RCA #417; continuidad #45. Estado: CODE_ONLY.

## Evidencia y objetivo

Cutover V3 #878 terminó con `PREPARE_WORKER/HEALTH_EXITED`, `ExitCode=1`,
`OOMKilled=false`; Docker devolvió el CID del `start` y después el proceso
terminó, pero la compensación selectiva eliminó su `inspect`. Los diez eventos
de journal aportados por el titular muestran conexión y desconexión de shim,
no la excepción interna. Linger y raíz Docker rootless Boca se observaron por
separado; ninguno explica retrospectivamente el código 1.

El titular solicita preparar la captura **antes** del siguiente arranque
controlado. Reutilizamos el intent O_EXCL/fsync y el lease Boca ya preparados
antes de `docker start`. El cambio de código captura sólo valores finitos del
**mismo** `docker inspect` obtenido durante la espera de salud, antes de la
compensación. No agrega observadores, procesos, llamadas Docker, ni retries.

## Esquema prospectivo V4

Sólo para `HEALTH_EXITED` con ExitCode/OOM válidos:

| Campo | Valores cerrados |
| --- | --- |
| `engine_error` | `EMPTY`, `PRESENT_UNCLASSIFIED`, `UNKNOWN` |
| `state` | `EXITED`, `DEAD`, `OTHER`, `UNKNOWN` |
| `duration` | `EARLY_LT_5S`, `LATE_GE_5S`, `UNKNOWN` |
| `health` | `NOT_RUN`, `RAN`, `UNKNOWN` |

Las cuatro categorías se calculan sin publicar `State.Error`, fechas,
`Health.Log.Output`, logs, trazas, cookies, argumentos o rutas. La duración
requiere `StartedAt` y `FinishedAt` RFC3339Nano estrictos y coherentes,
sin fecha centinela 0001, comparados como enteros en nanosegundos. `Health.Log`
se consulta sólo en su forma de lista: vacía/no vacía; su contenido se ignora.
Datos ambiguos producen `UNKNOWN`, nunca éxito.

Se propaga un esquema V4 opt-in por la excepción de salud, compensación,
`CutoverReceipt`, recibo persistente versionado, salida fija CLI, parser
runner y reconciliador de solo lectura. V1/V2/V3 históricos conservan los
mismos bytes; toda entrada V4 fuera de fase o con un valor desconocido falla
cerrada. El diagnóstico permanece `NO_GO`, `worker_internal_cause=UNKNOWN`.
Las cuatro categorías se serializan como una firma enumerada de cuatro partes,
separadas por puntos, bajo `worker_exit_signature`; no lleva texto libre.

## Presupuestos medidos tras el cambio

- Full: **883.682/886.000** bytes descomprimidos; ZIP **216.893/512.000**.
- Worker-preflight: **482.747/484.000** descomprimidos; ZIP **104.538/128.000**.
- Recovery mantiene 256.000/128.000 y su propia allowlist. No se aumenta
  ningún límite de ZIP comprimido, puerto ni superficie Docker.

## Operación protegida posterior

1. Tests offline RED/GREEN con `docker inspect` sintético, errores canary y
   compensación VERIFIED/INDETERMINATE, sin ejecutar BLACKBOX.
2. Medición de bundle y ajuste solo si está justificado; CI exact-SHA,
   arquitectura/seguridad/QA, rama y PR; cierre de otras PR antes del deploy.
3. Reconciliación actualizada de rootless Boca, release dual y controller.
4. **Una sola** ejecución `cutover-a-apply` del workflow Boca existente, con
   captura preparada y fronteras fail-closed, tras los gates aplicables.
   Nunca reconstruye la causa del intento #878; la nueva ejecución puede
   aportar metadatos adicionales, pero no garantiza explicar la excepción.

No se abren `ipc_worker.py` ni `synthetic.py`, ni se toca Porota, puertos
ajenos, redes ni volúmenes fuera de Boca. No hay login, reservas ni tickets.
