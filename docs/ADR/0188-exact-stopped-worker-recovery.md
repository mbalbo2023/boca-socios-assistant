# ADR 0188 — Recuperación exacta del worker temporal detenido

**Fecha:** 2026-11-07 ART. **Estado:** R79 CODE_ONLY en evaluación; la
implementación por sí sola no demuestra cleanup físico ni Cutover autorizado.

## Evidencia y decisión

El [run #802 / 42337103473](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42337103473)
de `cutover-a-worker-inspect` (R78 `main=7dc0b477479aec118ed4e46edd1ffb4541558dbc`)
observó bajo UID 10001 y su socket Docker rootless:

- El probe descartable del preflight fallido #795, intento `42329475083`,
  CID `65d844edb438710f44ce83c397906932710ad7f04f3e7a52634f9eaaf1fcc504`,
  coincidió por nombre, proyecto, intento, SHA R72 y digest browser.
- `probe_running=false`, full JSON `BELOW_CLEANUP_LIMIT` (<65536 bytes),
  archivo seccomp temporal `ABSENT`.
- El legacy CID `27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793`
  seguía `RUNNING_HEALTHY` exclusivamente en `127.0.0.1:8443`.
- La Action fue READ_ONLY; **0 escrituras**. No examinó aislamiento Docker
  completo; por tanto, no autorizaba borrar el CID ni reintentar Cutover.

QA, Arquitectura e Infra recomendaron recuperar sólo el contenedor detenido,
previa inspección completa fresca en el mismo lease. Se descartan el cleanup
genérico (`stop`/amplio) y la ruta `_cleanup_exact` histórica (puede detener
un proceso, inspección sin límite durante captura). Todo ocurre mediante la
operación `cutover-a-worker-recover` en el **mismo workflow manual protegido**.

## Implementación y límites de la propuesta

1. `host_cutover_worker_recovery.py` fija en fuente el ID de 64 caracteres,
   el intento, SHA y digest del probe y el controlador legacy; no recibe
   coordenadas Docker libres.
2. Dentro del lock exclusivo Boca, repite **dos veces** el observador R78
   canónico y el inspect JSON completo acotado durante la lectura. Verifica
   nombre/ID, labels/imagen, UID 10002, estado detenido (`created`/`exited`),
   seccomp efectivo, red none, filesystem readonly, namespaces/cgroups,
   variables BOCA exclusivamente de simulación, tmpfs/shm, PID, dispositivos,
   ausencia de mounts, binds, volúmenes y puertos; legacy sano y estable.
3. Único efecto de contenedor admisible: `docker container rm <CID exacto>`
   sin `stop`, `force`, `volumes`, `prune`, imágenes, redes o Compose. El lease
   podría crear su archivo exclusivo en `/run/user/10001`; ninguna otra ruta
   del host se escribe.
4. En postflight exige CID y nombre ausentes con Docker y de nuevo la salud
   del legacy. Toda discrepancia previa es `NO_GO_PRECHECK` sin writes; fallo
   de comando, pérdida de ACK o postflight luego de intentar rm es
   `INDETERMINATE`, **sin retry automático**. Un recibo `VERIFIED` representa
   sólo limpieza, nunca `GO_B` ni Cutover A.
5. El ZIP `worker-recovery` está separado del bundle original de Cutover,
   cuyo límite 860000 bytes está casi agotado y **no cambia**. Transporta siete
   entradas exactas, usa SHA256 + bootstrap memfd existente, límites propios
   256000/128000 bytes y no contiene BLACKBOX ni credenciales.
6. El cliente Docker compartido resuelve siempre `/usr/bin/docker` y pasa
   exclusivamente `DOCKER_HOST` al socket privado, `XDG_RUNTIME_DIR`,
   `PATH=/usr/bin:/bin` y `LANG=C`. La allowlist READ_ONLY del observador
   sigue intacta; el único `rm` está fijado en el ejecutor R79.
7. Contra reruns con distintos IDs, el workflow fija un `run-name` exclusivo
   `BOCA-R79-WORKER-RECOVER-ONCE` y antes de SSH verifica mediante API la
   historia completa y acotada de `workflow_dispatch` desde la fecha de
   introducción (2026-11-07). Debe existir exactamente un run con esa etiqueta
   y ser el **actual**, con SHA, actor e intento 1. Un segundo dispatch bajo
   otro ID o SHA se rechaza antes de cualquier efecto; una historia incompleta
   o mayor a 100 registros también es NO_GO sin intentar reparar.

## Certificación pendiente

Requiere pruebas negativas, QA/Arquitectura/Infra sobre árbol exacto, cuatro
workflows PR verdes, merge con 0 PR abiertos y postmerge CI/security GREEN
antes de **una sola** ejecución física protegida. Una ejecución exitosa aún
requiere release dual fresco, nuevo preflight worker, PREPARE, GO_B independiente,
APPLY y aceptación Samsung/Chrome/Telegram con sus controles separados.

Evidencia de código y cualquier resultado de host se documentan con SHAs y
runs reales en [#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417)
y [#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).
No se modifican `synthetic.py` ni `ipc_worker.py`; otros servicios y Porota son
intocables.
