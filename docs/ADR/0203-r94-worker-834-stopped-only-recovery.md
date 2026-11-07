# ADR 0203 — R94: recuperación quirúrgica del worker #834 detenido

**Fecha:** 2026-11-07 ART. **Responsables de diseño:** Arquitectura, QA e Infraestructura.
**Seguimiento:** [RCA #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417), [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).
**Estado:** candidato **CODE_ONLY**, sin recuperación física, instalación ni GO_B autorizados.

## Evidencia exacta, sin extrapolación

El único preflight R92 [#834](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42375050546)
(`42375050546`, job `128410810023`) se ejecutó sobre
`79da7ebe9918d98216ac7eb46ff008d7f6e62429`, con release dual
[#741](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42374319918)
`42374319918` SUCCESS. Terminó `CLEANUP/STOP/ACK_MULTILINE/INDETERMINATE`:
el STOP tuvo respuesta no canónica y **no se intentó `docker rm`**.
Ni el resultado primario anterior al cleanup ni el STOP con exit0 acreditan
limpieza del contenedor. No repetir #834.

El inspector independiente [#836](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42376876875)
(`42376876875`, job `128416172147`, `main=6e75c020001c7de00faad2fcecfa171ac22e361f`)
finalizó SUCCESS de **READ_ONLY_NO_GO**, con `observer_writes=0` y terceros
intactos. Confirmó un solo probe `PRESENT_PIN_MATCH`, detenido
(`probe_running=false`), `seccomp=ABSENT` y controller original
`RUNNING_HEALTHY` con puerto `LOOPBACK_8443`. Es una observación puntual,
no una autorización de eliminación ni evidencia de una BETA integral instalada.

| Pin inmutable | Valor |
| --- | --- |
| Intento fallido #834 | `42375050546`, SHA `79da7ebe9918d98216ac7eb46ff008d7f6e62429` |
| Probe CID detenido | `b2312004b4fc4e789fb58ce0c40eb2dc14ab132150d0da420657c4d29ef326d3` |
| Browser OCI del release #741 | `ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:ed276066b108fad5b130d0fdffdd3f38a5a3d912253b1d4267bd4b6184992ba8` |
| Testigo READ_ONLY #836 | `42376876875`, SHA `6e75c020001c7de00faad2fcecfa171ac22e361f` |
| Legacy CID | `27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793` |
| Legacy SHA | `cabce9f1e452e63ded115f447559a358dc0f4d1b` |
| Legacy OCI | `ghcr.io/mbalbo2023/boca-socios-assistant@sha256:cf6e4266cfcfea0c07fa31301d59c7aaa3b9c2fefb9f6843baddd208cacd3b59` |

## Decisión mínima, recuperador existente

R94 agrega sólo un `RecoveryTarget` fijo para #834 al recuperador R91/R87
(`scripts/host_cutover_worker_recovery.py`), con modo memfd independiente
`cutover-worker-834-recover` / `host-834` / `verify-834`. Reutiliza exactamente
el ZIP recovery de **siete entradas**, allowlist, caps de bytes y verificación
SHA, sin incorporar el bundle completo de Cutover. El host recibe únicamente
el modo fijo; no acepta CID, digests ni comandos libres del formulario.

Antes de SSH, el workflow protegido exige actor/branch/`main` actuales,
PR0, primer intento del run, historial GitHub acotado que demuestre **un solo**
`BOCA-R94-WORKER-834-RECOVER-ONCE` entre SHAs, los jobs/resultados exactos
del preflight fallido #834, del inspector #836 y el release dual auténtico
#741. Evidencia truncada, otro dispatch, cambio de main o gates incompletos:
**NO_GO antes del host**. `service=controller`, presupuesto
`1.5cpu-1024m-192pids` y todos los campos optativos vacíos, incluido
`protected_action_context` y SHA/OCI del intento fallido: esos pins viven
en código revisado, no en el usuario ni en un tag mutable.

El único efecto autorizado, bajo lease del UID rootless Boca, requiere **dos
atestaciones frescas completas** del CID fijo, nombre/imagen/SHA/labels,
`Running=false`, seccomp, aislamiento y controller legacy saludable. Sólo
entonces un `docker container rm <CID completo>` **sin `--force` ni STOP**;
ACK exacto, ausencia posterior del CID y nuevo chequeo legacy son
postcondiciones obligatorias. No se eliminan imágenes, volúmenes, redes,
archivos de aplicación, otros contenedores ni recursos de Porota/BLACKBOX.

Fallo anterior al RM: cero escrituras y `NO_GO_PRECHECK`. Timeout, ACK perdido,
carrera, diferencia de identidad o postcondición incierta después del único RM:
`INDETERMINATE`, **NO_RETRY**; inventario READ_ONLY nuevo antes de decidir
cualquier otro acto. Sólo el recibo canónico `CLEANED/VERIFIED` y artifact
auténtico pueden acreditar la remoción exacta. Ningún recibo autoriza por sí
solo otra operación física.

## Separación de responsabilidades y cierre

R94 **no modifica `docker stop` del preflight**. El uso histórico de
`--time` podría hacer que una versión de Docker CLI imprima una advertencia
en stdout junto al CID, compatible con `ACK_MULTILINE`; **no se verificaron
los bytes ni la versión del cliente del host**. El cambio portable prospectivo
`docker stop -t 5`, sin relajar la igualdad del ACK, pertenece al **PR R95
separado**, con sus propias pruebas, revisión, release dual nuevo y GO físico.
No afirmar que la hipótesis sea RCA demostrado.

TDD debe cubrir CID/lease/ownership/estado detenido, dos FULL inspections,
capacidad del ZIP, colisiones de modo, falso histórico GitHub, replay,
fallos antes/después del RM y cero cambios a otros recursos. Exigir QA,
Arquitectura e Infra 3/3, PR/checks, merge, CI/Security postmerge y PR0
antes de decidir sobre **una única** Action de recuperación. Incluso si esa
Action concluye `CLEANED/VERIFIED`, Cutover, PREPARE, GO_B, APPLY,
Telegram y BETA integral continúan **NO_GO** hasta sus propias evidencias.
