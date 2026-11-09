# ADR0216 — R122: significado del ExitCode 1 sin inventar una RCA interna

Fecha: 2026-11-08 ART. Issue #417, continuidad #45. Estado: **candidato
CODE_ONLY, pendiente de PR/CI/merge; NO_GO físico**.

## Evidencia y límite histórico

En el único Cutover V3 [#878](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42426260583),
fuente `f57173862df3143062a136452f2ffc7e3cc51d35`, se observó
`PREPARE_WORKER/HEALTH_EXITED`, código entero `1`, `OOMKilled=false` y
compensación `VERIFIED`. La ruta del adaptador exige un retorno de CID exacto
del comando `docker start` **antes** de la lectura `Running=false` que genera
`HEALTH_EXITED`: el problema no ocurrió como rechazo del comando `docker
start`. No sabemos si el intérprete, alguna dependencia, la configuración,
el IPC u otro componente fue responsable del fin del proceso.

SSH stderr fue descartado; la salida temporal del runner no quedó como
artefacto; `State.Error`, los logs y la excepción interna no se conservaron.
La compensación retiró el worker. El último diagnóstico físico READ_ONLY
[#886](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42547709593)
no puede reconstruir esos detalles. Por tanto, la **causa interna del #878
permanece UNKNOWN** y ningún cambio de reporte la recupera.

El comentario [A45-R119.5 en #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6728616133)
documentó una limitación separada de CI: el smoke offline de Chromium no
ejecutó el mismo punto de entrada que el proceso IPC real y un preflight
anterior declaró `ipc_worker=NOT_TESTED`. Esto explica una brecha de cobertura
entre CI y despliegue; **no permite adjudicar la causa del ExitCode 1**.

## Decisión, alternativas y consenso

El propietario pidió buscar el motivo y mejorar el diagnóstico sin recurrir a
comandos manuales ni otro Cutover. QA/Arquitectura, IPC externo y
Infra/DevOps emitieron dictámenes independientes de **GO CODE_ONLY R122**
sujeto a QA, **GO al diseño de R123** y **NO_GO a cualquier efecto remoto**;
su cierre debe quedar registrado en la continuidad del issue #45:

- R122 añade exclusivamente tres campos de vocabulario fijo al resumen del
  runner `check_cutover_a_go.py --report-host-failure`. Para la única
  combinación de salida `ssh_rc=3` y *claims* v3 tipados
  `PREPARE_WORKER + HEALTH_EXITED + VERIFIED + exit_code=1 + oom=NO`:
  `worker_start_ack_claim=EXACT_CID_IMPLIED_BY_HEALTH_PHASE`,
  `worker_internal_cause=UNKNOWN` y
  `worker_cause_evidence=INFERENCE_NOT_CAUSE`. Todo otro caso produce
  `worker_start_ack_claim=UNVERIFIED`, causa interna `UNKNOWN` y evidencia
  `UNVERIFIED`.
- No cambia la lectura física, la compensación, el esquema terminal v3,
  `assert_actions_host_receipt`, el YAML, el CLI host ni el bundle ZIP.
  El resultado sigue `state=NO_GO host=UNVERIFIED terminal=UNVERIFIED
  no_retry=true`. Un claim de texto del host no es un nuevo ACK físico.
- Se rechazó publicar stderr, logs/tracebacks o volver a ejecutar el
  worker/BLACKBOX: no ofrece evidencia retroactiva y puede exponer datos
  sensibles o alterar el entorno. La imagen histórica en cuarentena R108,
  los volúmenes y todo Docker ajeno permanecen intactos.

Un timeout (`ssh_rc=124`) o fallo del transporte SSH (`ssh_rc=255`), incluso
con texto de recibo, no habilita la inferencia de arranque:
`worker_start_ack_claim=UNVERIFIED`. Un recibo ausente/truncado tampoco.

## Validación y continuidad

Las pruebas del parser verdadero fueron escritas primero: 11 casos fallaron
**RED** al faltar los campos, después los mismos 11 pasaron **GREEN** con el
ajuste; incluyen uno positivo y 10 negativos con fases distintas, ExitCode
0/137/UNKNOWN/01, OOM YES, compensación incierta, doble línea y campos
privados maliciosos. Se añadieron 4 negativos: transportes 124/255 (RED antes
del gate exacto `ssh_rc=3`), archivo ausente y recibo truncado. Se requiere la suite completa, Ruff, formato, Mypy,
política, revisión independiente y CI exact-SHA antes de integración.

El diseño prospectivo R123 evalúa únicamente metadatos tipados derivados
del **mismo** `docker inspect` antes de compensación (banderas de error del
daemon, progreso del healthcheck y franja temporal). Exigiría versión V4,
presupuesto de ZIP medido y nuevas pruebas. No se autoriza ni implementa ese
cambio aquí. Ver [diseño R122](../superpowers/specs/2026-11-08-r122-worker-exit-1-diagnostic-design.md)
y [plan](../superpowers/plans/2026-11-08-r122-worker-exit-1-diagnostic-plan.md).
