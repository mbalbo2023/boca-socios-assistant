# ADR0220 — R128: reconciliación READ_ONLY del intento #893

Fecha: 2026-11-09 ART. RCA: [#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417), continuidad: [#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).
Estado: **CODE_ONLY** hasta revisión, CI, merge y posterior observación física por Actions.

## Evidencia observada

El Cutover A V3 `workflow_dispatch` #893 (run `42658939650`, intento 1,
`main=759a1dbadd6e50ab8c331daefc4e39608025a66f`) terminó `failure`.
Su diagnóstico de runner fue:

`PREPARE_WORKER / HEALTH_EXITED / exit=1 / OOM=NO /
EMPTY.EXITED.EARLY_LT_5S.NOT_RUN / worker_internal_cause=UNKNOWN`.

Aunque el runner declaró compensación `VERIFIED`, el host y su recibo terminal
quedaron `UNVERIFIED`. Este resultado no identifica la excepción dentro del
worker y no autoriza otro arranque. El #893 no tiene PREPARE independiente.
GitHub REST verificó el repositorio, `workflow_dispatch`, `main`, SHA,
`run_attempt=1`, `status=completed`, `conclusion=failure`, nombre/path y
`actor` más `triggering_actor` `mbalbo2023`.

## Decisión limitada

1. Añadir **solamente** #893 y su SHA inmutable a los cuatro selectores V3
   existentes de `cutover-a-reconcile`. No admitir números arbitrarios, otro
   SHA ni un PREPARE ficticio. Mantener los incidentes anteriores #853/#878.
2. Reutilizar exactamente `host-v3` y `verify-v3` del observador existente,
   con UID Boca 10001, raíz rootless, lectura acotada de recibos privados,
   inventario Boca, validación del terminal V4 y política fail-closed.
3. Omitir **sólo para #893** el planificador histórico de cleanup: no hay CID
   legado autenticado para ese intento. No eliminar ni modificar recursos.
4. Conservar `runtime_attested=false`, `go_for_retry=false` y ningún GO para
   Cutover, incluso si la reconciliación READ_ONLY termina en verde.

No se crea un nuevo workflow o código duplicado, no se ejecuta `docker logs`,
`docker exec`, `docker start` ni un servicio, no se inspeccionan los archivos
BLACKBOX `ipc_worker.py` / `synthetic.py` y no se toca Porota o ningún otro
Docker. No hay cambio de secretos, puertos, volúmenes, privilegios o tolerancia
de fallos.

## Certificación requerida

Antes de ejecutar un observador físico: pruebas TDD y regresión completas,
lint/type/policy/CI exactos, revisión de QA, Arquitectura e Infraestructura,
PR resuelta y `main` certificado. Una única ejecución manual
`cutover-a-reconcile` con `protected_action_context=42658939650`, los demás
pins vacíos, `service=controller`, `resource_budget=1.5cpu-1024m-192pids`
y sin cambio de aplicaciones. Si esa lectura falla, mantener
NO_GO y realizar RCA, sin retry de Cutover.

Un registro confidencial y futuro de stderr/stdout del worker **antes** de
compensar queda fuera de alcance: necesitaría diseño independiente y custodia
de claves del titular; no se recopilan logs crudos en GitHub.

Plan: [R128](../superpowers/plans/2026-11-09-r128-893-readonly-reconcile-plan.md).
