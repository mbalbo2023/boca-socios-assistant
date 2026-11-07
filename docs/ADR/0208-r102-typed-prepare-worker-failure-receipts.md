# ADR 0208 — Cutover V3: subfase tipada de PREPARE_WORKER

**Fecha:** 2026-11-07 ART. **Estado:** CODE_ONLY hasta validación exact-SHA y Actions.
**Owner:** RCA #417; continuidad #45; ámbitos host/QA.

## Evidencia y límite del RCA

En código, `RootlessCutoverBackend.prepare_worker` reúne inspección de seccomp,
stage, pulls y creación del worker en la fase externa `PREPARE_WORKER`. Antes,
`_cutover_prepare_worker` convertía cualquier error del worker y su compensación
en el mismo `PreflightError` genérico. El terminal y `classify_cutover_ssh_failure`
retenían sólo esa fase externa. Esto explica **por qué se perdió diagnóstico de
subfase**, no cuál fue la causa física original del intento #853; sigue sin
evidencia suficiente para atribuirla a PULL, CREATE u otro paso.

## Decisión mínima

La captura de errores del worker anota exclusivamente una subfase de la lista
cerrada `ATTEST/STORAGE/PULL/IPC/CREATE/START/HEALTH/UNVERIFIED` y un estado de
compensación `VERIFIED/INDETERMINATE/UNVERIFIED`. La excepción no incluye
stderr, comandos, IDs ni otros datos de Docker. No agrega efectos ni retries.

Para fallas `PREPARE_WORKER` con ambas categorías válidas se persiste el
terminal **v2** con `worker_primary_phase` y `worker_compensation`; un terminal
histórico sin ellas conserva los mismos bytes de la versión **v1**. El CLI
emite opcionalmente `BOCA_CUTOVER_A_WORKER_FAILURE primary=<enum>
compensation=<enum>` antes del antiguo `BOCA_CUTOVER_A_FAILURE_PHASE`.
El analizador del runner acepta sólo un registro exacto y coherente con
`phase=PREPARE_WORKER` y reporta afirmaciones tipadas no autenticadas. Tanto
el resultado fallido como el diagnóstico mantienen
`phase=UNVERIFIED host=UNVERIFIED terminal=UNVERIFIED no_retry=true`.

## Criterios de no regresión

- Tests TDD RED/GREEN para fase STORAGE/PULL, IPC/CREATE/START/HEALTH,
  error de compensación y redacción de excepción privada.
- Terminal v1 byte-compatible, v2 write-once y reconciliación exacta; una
  modificación de subfase no supera verificación del registro persistido.
- Runner rechaza duplicados, campos extras, valores no permitidos y la
  combinación de subfase con una fase superior distinta de PREPARE_WORKER.
- Nunca inspeccionar ni modificar `synthetic.py` o `ipc_worker.py`; no crear
  un nuevo workflow, puerto, privilegio, credencial ni tocar Porota.

**Cierre:** CI exact-SHA y nueva evidencia física del droplet aún son requisitos
para aceptar BETA. Este cambio no certifica retrospectivamente #853.
