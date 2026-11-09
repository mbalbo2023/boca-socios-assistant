# R122 — Clasificación verificable de ExitCode=1 en Cutover V3

Fecha: 2026-11-08 ART. Issue #417; continuidad #45. Alcance: CODE_ONLY.

## Hechos frente a inferencias

El único Cutover V3 #42426260583 (fuente `f57173862df3143062a136452f2ffc7e3cc51d35`)
terminó en `PREPARE_WORKER/HEALTH_EXITED`, con `ExitCode=1`,
`OOMKilled=false` y compensación `VERIFIED`. Por la secuencia comprobada del
adaptador, el comando `docker start` devolvió el CID exacto antes de que el
inspector observara `Running=false`. Es una **inferencia sobre el recorrido
del código y un claim tipado del host**, no un nuevo ACK físico independiente.

La excepción específica **no puede recuperarse**: el mismo proceso remoto
descartó SSH stderr; el runner no publicó su archivo transitorio; el supervisor
no conservó `State.Error`, logs ni detalles de proceso y la compensación
retiró el worker. No atribuir el fallo a importación Python, permisos,
seccomp, memoria, IPC o código del BLACKBOX sin evidencia adicional.

Además, el comentario [A45-R119.5 de #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6728616133)
identificó una brecha de validación: el smoke offline de Chromium utilizó
otro entrypoint y el preflight calificó `ipc_worker=NOT_TESTED`. El CI verde
no cubría necesariamente el arranque IPC; ello no demuestra la causa del #878.

## Alternativas evaluadas y decisión consensuada

1. **Solo diagnóstico de Action, R122 (elegida).** Añadir al reporte
   `--report-host-failure` una clasificación derivada, de vocabulario cerrado,
   para `ssh_rc=3` y la combinación exacta y ya aceptada
   `PREPARE_WORKER + HEALTH_EXITED + compensation=VERIFIED + exit_code=1 +
   oom=NO`. Los transportes `TIMEOUT` (`124`) y `SSH_255` no habilitan la
   inferencia aun cuando haya texto de recibo. Campos nuevos:
   `worker_start_ack_claim=EXACT_CID_IMPLIED_BY_HEALTH_PHASE`,
   `worker_internal_cause=UNKNOWN` y
   `worker_cause_evidence=INFERENCE_NOT_CAUSE`. Cualquier entrada ausente,
   distinta, ambigua o no canónica usa `UNVERIFIED` para los campos de
   inferencia; el motivo interno permanece `UNKNOWN`.
2. **Telemetría prospectiva del mismo inspect, R123 (solo diseño).** Añadir
   observaciones categóricas de `State.Error` presente/ausente, fase de health
   y duración en rangos, sin valores libres, nuevos comandos ni lectura de
   módulos BLACKBOX. Requeriría recibo V4 y consumidores versionados; el
   margen de ZIP de R119 es estrecho (2876 bytes declarados). No se implementa
   ni ejecuta en R122.
3. **Volcar logs, stderr, traceback o repetir Cutover (rechazada).** Riesgo
   de secretos, violación de custodia del BLACKBOX y repetición de un intento
   compensado que no puede restaurar la evidencia histórica.

Consenso atribuible: Arquitectura/QA, IPC externo y DevOps/Infra votan
**GO CODE_ONLY R122**, **GO solo diseño R123**, **NO_GO a host, nuevo Cutover
o navegación real**. No hay cambios a `host_first_deploy.py`, CLI host,
workflow YAML, protocolo terminal v3, parser de recibos, `synthetic.py` o
`ipc_worker.py`.

## Contrato de seguridad

- Fuente: la misma `classify_cutover_ssh_failure` y sus expresiones regulares
  exactas existentes; nunca nuevas lecturas del host ni datos privados.
- Los campos derivados son metadata del runner, **no** `host=VERIFIED`:
  conservar `state=NO_GO host=UNVERIFIED terminal=UNVERIFIED no_retry=true`.
- La salida permanece exclusivamente en el vocabulario cerrado. Rechazar
  duplicaciones, cadenas adicionales, ExitCode malformado, OOM no canónico,
  otras fases y `compensation=INDETERMINATE`.
- Pruebas ejecutan el parser real con fixtures sintéticos; el input malicioso
  contiene marcadores secretos ficticios que no deben salir jamás.
- Se conserva la frontera de auditoría: no ejecutar ni inspeccionar los
  archivos de navegación reservados al propietario.

## Aceptación

TDD RED/GREEN de la inferencia específica, negativos por fase/compensación/
tipo/multilínea, suite completa + lint + formato + mypy + política. Un PR
acotado desde `main` con SHA exacto y CI verde debe preceder cualquier merge.
No se afirma RCA interno resuelto ni BETA instalada por un cambio CODE_ONLY.
