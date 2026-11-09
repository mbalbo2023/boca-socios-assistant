# ADR0219 — R127: captura V4 del worker antes de compensación

Fecha: 2026-11-09 ART. Owner RCA #417, continuidad #45. Estado: **CODE_ONLY**;
ningún nuevo arranque físico ni Cutover acreditados por esta ADR.

## Evidencia y decisión

El intento #878 registró `PREPARE_WORKER/HEALTH_EXITED` con `ExitCode=1`,
`OOMKilled=false`, `docker start` CID aceptado y compensación `VERIFIED`.
El `journal` histórico aportado por el dueño muestra desconexión de shim
aproximadamente 240 ms después de `sbJoin` del worker, pero no contiene la
excepción interna. Linger/rootless fueron medidos en lectura independiente;
la causa interna del #878 **sigue UNKNOWN**.

Se adopta el diseño R123 previamente documentado: el intent durable O_EXCL,
el lease y el contexto de ejecución existente se preparan antes de
`docker start`; el `docker inspect` de `_browser_wait_healthy` observa
`State.Running=false` y deriva cuatro categorías **antes** de compensar.
Es el mismo inspect que ya producía ExitCode/OOM, sin comandos adicionales:

1. `State.Error`: `EMPTY|PRESENT_UNCLASSIFIED|UNKNOWN` (nunca el texto).
2. `State.Status`: `EXITED|DEAD|OTHER|UNKNOWN`.
3. Tiempo entre `StartedAt/FinishedAt`: `EARLY_LT_5S|LATE_GE_5S|UNKNOWN`,
   sólo RFC3339Nano, sin centinela 0001 y con comparación entera en ns.
4. Presencia de `State.Health.Log`: `NOT_RUN|RAN|UNKNOWN` (sin leer contenido).

El valor se codifica como firma finita de cuatro partes, por ejemplo
`EMPTY.EXITED.EARLY_LT_5S.NOT_RUN`. No contiene IDs de procesos, paths,
timestamps originales, args, `Config.Env`, mounts, stdout, stderr, health
output ni trazas del paquete BLACKBOX. Valores inválidos se rechazan o
degradan a `UNKNOWN`; no se diagnostica Python/IPC/OCI por inferencia.

## Propagación y regresión

- `WorkerHealthPhaseError` → `CutoverWorkerPhaseError` tanto con compensación
  VERIFIED como INDETERMINATE → `CutoverReceipt`.
- El terminal O_EXCL/fsync serializa `boca-cutover-a-terminal-v4` únicamente
  cuando existe una firma válida más los dos campos ExitCode/OOM; los
  terminales históricos V1/V2/V3 conservan bytes y esquemas originales.
- CLI emite una línea fija con `signature=...`; runner la valida como *claim*
  `NO_GO`, mantiene `worker_internal_cause=UNKNOWN`, `no_retry=true`.
- El reconciliador READ_ONLY acepta el recibo V4 explícito y sigue anclando
  la admisión histórica #878 al terminal V3 exacto. No promueve V4 a GO.

La prueba TDD usó fixtures sintéticos, canary privado y casos de tipos,
duración inválida, recibo histórico, formato malicioso y compensación
incierta; cero ejecuciones del worker o sus archivos protegidos en QA.

## Presupuesto medido y efectos

Tras `ruff format`, inventario SHA de fuentes: **883.682** bytes full
(techo nuevo **886.000**) y **482.747** preflight (techo **484.000**).
ZIP protegido full **216.893/512.000**, preflight **104.538/128.000**;
recovery mantiene límites anteriores. No cambian ZIP allowlists, transporte
firmado, puertos, volúmenes, privilegios, topología ni límites comprimidos.

El cambio **no** ejecutó Docker real ni invocó `ipc_worker.py` o
`synthetic.py`. Se requiere PR revisada, CI exact-SHA, release dual,
reconciliación de host/owner y un solo `cutover-a-apply` por Actions, con
el arranque del worker **únicamente dentro** de esa transacción protegida.
La ejecución física, si se autoriza por los gates reales, dejará NO_GO
ante otro exit prematuro y no tendrá retry automático. Porota intocado.

Diseño: [R127](../superpowers/specs/2026-11-09-r127-worker-exit-v4-design.md) ·
plan: [R127](../superpowers/plans/2026-11-09-r127-worker-exit-v4-plan.md).
