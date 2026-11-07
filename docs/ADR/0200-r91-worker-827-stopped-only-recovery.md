# ADR 0200 — R91: recuperación exacta stopped-only de #827

**Fecha:** 2026-11-07 ART. **Owners:** Arquitectura, QA e Infraestructura.
**Fuente canónica:** [RCA #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6706605034) y [continuidad #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6706605240).
**Estado:** inicialmente CODE_ONLY; sin Docker writes/GO_B/APPLY.

## Pruebas físicas y límites de inferencia

El preflight único [#827/42368541950](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42368541950)
terminó FAILURE `CLEANUP/STOP/ACK_MISMATCH/INDETERMINATE`; el helper abortó
antes de `docker rm`. No repetir. El observer [#829/42370005970](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42370005970)
job `128395981058`, `main=bd45f2e234a17ba12743ff12cf0c0199497b66f6`
confirmó `READ_ONLY_NO_GO`: probe `PRESENT_PIN_MATCH`, `probe_running=false`,
`socket=PRESENT_OWNED`, `docker=OBSERVED`, `seccomp=ABSENT`,
`probe_full_json_stage=BELOW_CLEANUP_LIMIT`, original `RUNNING_HEALTHY`,
`original_port=LOOPBACK_8443`, `observer_writes=0`, `foreign_resources_touched=false`.
Pérdida del ACK del STOP es hipótesis, no RCA demostrado.

| Pin inmutable | Dato verificado |
| --- | --- |
| Fallo #827 | run `42368541950`, job `128391674779`, SHA `8a69d155354362e0712dab1229f7d7e4b3e24dd6` |
| CID detenido único | `0ae6b61d97ccae77e8373a597f617df52b28ed63f6e49cae1df57f368e46e8e5` |
| Browser OCI | `ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:902276a94bbec0ed0be30432baf97b5bd1298fc15e21eda750ccb785fa76bde0` |
| Testigo #829 | `42370005970`, job `128395981058` |
| Release dual #737 | `42361009081`, mismo SHA que el fallo |
| Legacy | CID `27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793`, SHA `cabce9f1e452e63ded115f447559a358dc0f4d1b`, OCI digest `cf6e4266cfcfea0c07fa31301d59c7aaa3b9c2fefb9f6843baddd208cacd3b59` |

## Diseño de decisión unánime

Extender el **mismo** `host_cutover_worker_recovery.py` R87 sin duplicar
backends ni tocar BLACKBOX. Nuevo `TARGET_827` frozen, modos `host-827` y
`verify-827`, bootstrap memfd `cutover-worker-827-recover` con siete entradas
y hash SHA; no parámetros de CID/imagen/órdenes al host. Nuevo workflow
`cutover-a-worker-recover-827` con marcador GLOBAL y único
`BOCA-R91-WORKER-827-RECOVER-ONCE`.

Pre-SSH el checker `--r91` exige: run #827 FAILED, #829 SUCCESS, release
#737 SUCCESS, jobs exactos con 157 pasos `1..155,310,311`, #827 gate59
SUCCESS/host60 FAILURE/receipt61 FAILURE, #829 inspector43 SUCCESS, actor
`mbalbo2023`, main vivo, primer intento, PR0 y un único run R91 entre SHAs.
El título R84 se reutilizó por #819 y #827: resolver el fallo por ID exacto,
**no** exigir título histórico R84 único. Historial incompleto o más de 100:
NO_GO antes de SSH. Todos los optional inputs del formulario deben quedar
vacíos; `service=controller`, `resource_budget=1.5cpu-1024m-192pids`.

Bajo lease dedicado Boca UID10001 se verifican **dos snapshots y dos
inspecciones completas frescas** del CID, imagen/SHA/labels/env, estado
detenido, perfil seccomp por hash binario, red `none`, ausencia de montaje,
capabilities, puerto legacy sólo loopback y original sano. Se permite
**exactamente un** `docker container rm <CID completo>` *sin force ni stop*.
ACK exacto, CID ausente y original sano nuevamente requeridos; receipt
canónico `cleanup=VERIFIED`, `docker_writes=1`, `cutover_authorized=false`,
`retry_authorized=false`, artifact sólo si verificado.

Error antes de la remoción: `NO_GO_PRECHECK`/0 writes. Error, timeout, ACK
perdido o postcheck incierto después de intentar remover: `INDETERMINATE`/1
attempt máximo/sin rerun. Limpiar sólo carpeta privada del runner. **Nunca**
`docker prune`, force, otras imágenes/redes/volúmenes, controller legacy,
base/keys/owner, apps ajenas o Porota. Nada de navegación/reservas reales.

## QA/Release y salida

RED en TDD: target #827 y gate R91 ausentes. Exigir tests R91 de identidad,
aislamiento, seccomp/lease/race/ACK, job REST falsificado, Bash fake-gh,
ZIP 7-entry y suites R87/R82; lint, MyPy, políticas, pytest integral.
Revisión independiente 3/3 del SHA exacto, PR único con cuatro checks verdes,
merge, main CI/Security, PR0 y luego **único** dispatch protegido. Hasta ese
recibo `CLEANED/VERIFIED`, NO_GO físico. Incluso `VERIFIED` **no** equivale a
Cutover/BETA instalada ni autoriza automáticamente preflight, PREPARE,
GO_B/APPLY o Telegram; requerir sus revisiones y evidencias propias.
