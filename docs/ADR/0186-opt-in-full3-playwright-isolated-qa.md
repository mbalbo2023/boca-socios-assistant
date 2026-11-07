# ADR 0186 — Full3 Playwright QA opt-in y procesos aislados (#402)

**Fecha:** 2026-11-06 ART. **Estado:** propuesta CODE_ONLY, sin dispatch.
**Ownership:** Release/QA; issues #259 y #45. **Base:** main `9f187901892e6d26ce7e4a5253cbda215ac146b2`.

## Evidencia y RCA delimitado

En [Release #42136993840](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42136993840)
(SHA experimental #402 `063b77c1c221df762181deb3e427861d0937bacf`),
los cuatro booleanos del HOME UID/GID10002, modo privado y escritura fueron
`true`, pero Firefox falló en `new_page` con excepción genérica `Error` y
categorías `unclassified`. Un ensayo anterior falló en `goto` después de
`new_page`. **No hay evidencia suficiente para atribuir causa a HOME, seccomp,
IPC, memoria, el proceso PID1 ni Firefox mismo.** El smoke experimental corría
Chromium, Firefox y WebKit sucesivamente dentro de un único proceso Python PID1
y una sola instancia `sync_playwright`; tampoco aislaba efectos del navegador
anterior. La [documentación oficial de Playwright](https://playwright.dev/docs/docker)
recomienda `--init` para evitar acumulación de procesos zombie en contenedores.

## Cambio mínimo y por qué no bloquea el Cutover

El workflow de release existente **no cambia**: mantiene presencia de los tres
motores, Chromium `about:blank` offline, escaneo, control de publicación y
release manual protegido. El PR #402 cerró sin merge por añadir un gate de
ejecución experimental no requerido por el contrato productivo.

Se agrega `boca-playwright-offline-diagnostic.yml`, invocable exclusivamente
mediante `workflow_dispatch`, sin ejecución programada ni por PR. Construye
una sola imagen browser descartable del SHA seleccionado y ejecuta **tres
contenedores descartables distintos**, en orden Chromium → Firefox → WebKit.
Cada uno recibe `--init` y un proceso Playwright fresco, con la misma seccomp,
UID10002, sin red, filesystem de solo lectura, CPU, memoria, PID y shm acotados;
el HOME temporal se monta con UID/GID y modo POSIX correcto, como demostró
el ensayo #402. Sólo abre `about:blank`. La salida se limita a `engine`,
`phase`, clase, categorías acotadas y estado; los logs crudos quedan en tmpfs
dentro del contenedor y no se publican como artefactos.

No se leen/importan/prueban/modifican los BLACKBOX `synthetic.py` ni
`ipc_worker.py`; no hay Boca/Queue-it externo, host, SSH, token, GHCR push,
Porota, otros Docker ni cambio del Compose productivo.

## Verificación y siguiente evidencia

La prueba de estructura de CI valida el único disparador manual, límites,
scripts parseables, separación del release y los tres motores. El executor
local no dispone de Docker: **no hay recibo físico de Firefox/WebKit y no se
declara RCA cerrada ni PASS de los tres motores**.

- Si Actions GREEN: repetir al menos una vez con el mismo SHA para distinguir
  aislamiento de un éxito transitorio; documentar probable interferencia de
  proceso/PID1 como hipótesis confirmada sólo si el control previo es comparable.
- Si Firefox sigue rojo: usar fase y categorías, formular una sola variable de
  contraste bajo runner descartable; no modificar seccomp, límites o host a
  ciegas ni habilitar Cutover por este diagnóstico.
- En ambos casos, #259 conserva la deuda física de Firefox/WebKit, mientras
  #45 sigue gobernado por los recibos reales del droplet.
