# ADR 0183 — Residuo de emergencia tras pull de la BETA Boca (R40)

**Fecha:** 2026-11-06 ART. **Estado:** candidato CODE_ONLY, no instalado.
**Issue:** [#259](https://github.com/mbalbo2023/boca-socios-assistant/issues/259).
**Decisión del propietario:** levantar el mínimo preventivo de 4 GiB **después**
de instalar Playwright completo; mantener la puerta previa, las identidades y
la limpieza selectiva. La autorización para avanzar no acredita que el host
haya instalado nada, ni cambia la seguridad de Porota u otros servicios.

**Actualización R50 (06/11/2026):** la política R40 de **4 GiB antes de cada
imagen** descrita abajo queda corregida para la transacción dual por la
enmienda al final de este ADR. El texto original se conserva como historia
de la condición que impedía continuar después de descargar el controller.

## Problema y evidencia física anterior al cambio

La observación protegida [#42132959174](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42132959174)
en `main=5058bd1ad5a713ac457e183ee7e16eec30f267fb` fue `SUCCESS` solo como
inspección READ_ONLY: staging/rootless Docker libres `5,106,397,184 B`, dos
imágenes Boca, un controller legado, Build Cache `0 B`, ninguna imagen full
Playwright instalada demostrada. Con el antiguo límite antes y después de
pull de `4,294,967,296 B`, restaban solamente `811,429,888 B` sobre la reserva.
El PR de medición [#397](https://github.com/mbalbo2023/boca-socios-assistant/pull/397)
observó en runner disposable controller `66,805,534 B` lógicos, browser
Chromium+Firefox+WebKit `2,695,270,685 B` lógicos y TAR dual sin comprimir
`2,788,377,600 B`. Estos valores **no** son el delta físico del Docker host,
ni una cota superior de capas descomprimidas/temporales. Restar por simple
comparación el TAR del espacio libre daría `2,318,019,584 B` hipotéticos
restantes, **no una proyección certificada**. No se achica Playwright ni se
relaja la instalación en función de esa resta.

## Decisión técnica acotada y reversible por un futuro PR

El contrato único de host Boca conserva siempre inspección rootless UID10001,
socket exclusivo, `DockerRootDir` dentro del HOME privado del dueño, driver
clásico, `st_dev`/`st_ino` de staging, Docker y socket, identidad SHA/digest,
50.000 inodos libres **en cada filesystem**, puerto `127.0.0.1:8443` y
restricciones del runtime/seguridad. Nunca usa rootful Docker ni examina
otros workloads. Dos observaciones en un mismo filesystem no son sumables.

| Etapa | Mínimo libre en **ambos** paths | Resultado bajo el mínimo |
| --- | ---: | --- |
| `beta-preflight`, `beta-stage`, `beta-config`, `browser-preflight`, `browser-stage`, `browser-config` | **4 GiB** | NO_GO antes del pull |
| Antes de **cada** `docker pull` controller/browser, incluyendo Cutover A `prepare_worker` | **4 GiB** | NO_GO antes de la siguiente descarga |
| Después de **cada** pull completo y validado por digest/source, antes de IPC/key/data | **1 GiB (1.073.741.824 B)** | NO_GO + compensación Boca-only de intento |
| Tras `beta-apply`/`browser-apply`, durante verificación, aceptación, START/STOP/RESTART/status de una BETA ya instalada y su Telegram de ciclo | **1 GiB** | NO_GO, conservar recursos y solicitar inventario Boca-only |
| Legacy `first-install`, Site/owner/enrollment, red diagnóstica, preparación de infraestructura y retiro histórico CODE_ONLY | **4 GiB original** | Sin cambios de política |

**1 GiB es una reserva residual de emergencia elegida para evitar operar con
disco cercano a cero**, no una medición del consumo de la BETA ni una promesa
de que el pull entre. No se reduce a cero ni se cambia el límite de inodos.
Los paths se vuelven a medir tras cada pull, incluso el controller pequeño,
antes de permitir el segundo pull del navegador full. Si después del primero
quedan menos de 4 GiB, el segundo **no comienza**, aunque el residual de
1 GiB todavía alcance. Las fases ya instaladas no vuelven a exigir 4 GiB
después de consumir almacenamiento aprobado.

## Compensación y límites físicos

Todo fallo de pull, metadatos, digest, bytes, inodos, Compose, salud o ACK
mantiene `NO_GO` y el mismo workflow protegido debe ejecutar su compensación
positivamente identificada (contrato `host_cleanup.py --browser-ipc-v2`).
Solo se consideran recursos del intento Boca inequívocos; se preservan
contenedor original, imágenes referenciadas, owner, llave, datos y cualquier
artefacto incierto. Ningún `docker system prune`, `docker image rm --force`,
backup, limpieza de Porota, compra, resize ni puerto adicional está incluido.
La pérdida de SSH, marker o recibo deja `INDETERMINATE` y requiere censo
READ_ONLY nuevo; las capas parciales no tienen recuperación de bytes
garantizada. La reserva de 1 GiB es observacional, **no** una cuota por
filesystem: si Boca y otras apps comparten el dispositivo físico, una
descarga puede presionar a todo el host antes del siguiente chequeo.

## Verificación antes de host

TDD exige regresiones para 4 GiB antes de efecto, frontera inclusiva 1 GiB
después, 1 GiB menos un byte rechazado, 49.999 inodos rechazados, deriva
`st_ino` rechazada, segunda descarga detenida si no quedan 4 GiB y selección
explícita de piso bajo tras pull en `_beta_inventory`, `_browser_apply`,
browser installed/lifecycle/Telegram. Lint, formato, tipos, pytest y política
de aislamiento sobre un SHA de PR no equivalen a release ni host. El nuevo
main requerirá **nueva publicación dual por digests exactos**, revisión GO B,
`PREPARE→APPLY` protegido, inventario/cleanup y ACK físico antes de declarar
BETA instalada. No ejecutar un pull en host por mera estimación de TAR.

## Enmienda R50 — admisión única para el par controller/browser (06/11/2026 ART)

**Estado: candidato de código, NO implementado en el droplet.** La prueba
unitaria reproduce una contradicción del *contrato de descarga*, sin demostrar
que haya provocado la salida 3 del APPLY físico
[#42249350458](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42249350458).
Esa ejecución nunca produjo ACK de Cutover y el observer READ_ONLY
[#42254498237](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42254498237)
solo acota el fallo a **antes del compromiso irreversible**, con controller
legacy sano, cero worker y Stage ausente después de su recuperación exacta
[#42254252830](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42254252830).

El chequeo original `_browser_pull_both` aplicaba 4 GiB antes del primer
`docker pull`, **otra vez antes del segundo**, y 1 GiB después de ambos.
Esto no implementaba el alcance operativo de levantar el piso **después de
consumir espacio por el primer pull** dentro de una descarga dual aprobada:
rechazaba cualquier residual entre 1 y 4 GiB aunque la primera descarga
hubiera superado todas sus verificaciones.

Para el par indivisible de dos imágenes **del mismo release**, se decide:

1. Preflight dual inicial: **4 GiB + 50.000 inodos libres** tanto en staging
   como en Docker root verificado, antes de **la primera descarga**.
2. Tras el controller, volver a medir ambos paths: **1 GiB + 50.000 inodos**
   y continuidad de filesystem/inode; misma prueba **antes** del segundo pull.
3. Tras la imagen browser Chromium/Firefox/WebKit, volver a medir y exigir el
   mismo residual de **1 GiB + 50.000 inodos**, antes de crear worker o tocar
   los datos/owner. Cualquier rechazo activa NO_GO/compensación Boca-only.
4. Fuera de esa transacción dual, los preflights previos conservan 4 GiB;
   ninguna validación de UID, digest, SHA, Docker rootless, Compose, puerto,
   límites de contenedor, postflight ni limpieza de exact-ID se relaja.

No hay garantía de que el almacenamiento alcance para la segunda descarga;
la imagen de runner es una medida lógica y no un máximo físico. El arreglo
solamente elimina una doble admisión incoherente. La aceptación exige tests
en runner/Actions, release exact-SHA, nuevos PREPARE/GO/APPLY y recibo físico;
el NO_GO del incidente anterior no puede reutilizarse como GO.
