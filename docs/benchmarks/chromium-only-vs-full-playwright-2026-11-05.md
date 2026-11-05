# R28 — Comparación aislada de tamaño Chromium-only (NO PRODUCTIVO)

**Fecha:** 2026-11-05 ART. **Estado:** benchmark comparativo medido en runner;
NO PRODUCTIVO, sin merge ni instalación.
**Issue de procedencia:** [#386](https://github.com/mbalbo2023/boca-socios-assistant/issues/386).

## Requerimiento conservado

El propietario ordenó preservar **Playwright completo** (Chromium, Firefox,
WebKit) en la BETA final. `Dockerfile.browser`, imágenes de release,
manifiestos, Compose y despliegue **no cambian**. El único objetivo de este
experimento es responder con medidas reales cuánto ocuparía una variante
Chromium-only, sin recomendar ni aplicar su sustitución.

## Método y límites

Una GitHub Action disparada **solo por PR con cambios en `benchmarks/` o su
workflow** ejecuta en runner descartable:

1. Descarga `ubuntu:24.04` y fija **para el mismo run** su `RepoDigest` antes
   del build. Noble permite una comparación del mismo sistema base.
2. Construye sin copiar código del propietario ni módulos BLACKBOX: Python
   3.12 del sistema, `playwright==1.64.1` y el comando exacto
   `playwright install --with-deps chromium`; no instala los binarios Firefox
   y WebKit de la imagen Microsoft productiva.
3. Verifica **solo** `scripts/verify_chromium_worker.py` de forma offline,
   UID10002, red `none`, seccomp, cgroup y límites, página `about:blank`.
4. Registra `.Size` lógico y TAR sin comprimir por stream, SHA y digest base
   con marcador `BOCA_CHROMIUM_ONLY_BENCHMARK` en log y resumen.

**No existe publicación, release workflow_dispatch, pull de host ni efecto
en el droplet.** Se conservan la reserva pre/postpull de 4 GiB y 50k inodos
y el resto de requisitos de limpieza. Las medidas de runner no equivalen a
bytes incrementales de un pull ni a un ahorro garantizado de disco físico.

## Línea base full real, ya observada

En [GitHub Actions #42117458795](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42117458795):

- Controller lógico: `66,805,534` bytes.
- Browser full Playwright lógico: `2,695,268,890` bytes.
- TAR de ambos juntos: `2,788,375,552` bytes.

La comparación solo será válida si el nuevo Chromium-only pasa **el mismo
smoke offline**, y si se documenta su SHA/digest base y bytes reales. Un
FAIL debe mantenerse como FAIL sin emitir tamaños presumiblemente útiles.
No se integra este Dockerfile a la BETA final, cualquiera sea el resultado.

## Evidencia medida R28

El job de comparación descartable en
[Actions #42121468183](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42121468183)
registró `BOCA_CHROMIUM_ONLY_BENCHMARK` tras smoke **offline PASS**.
SHA de merge de PR observado:
`01f4e252c6d57f74ab65fc8f80d63b26f8ccf0a0`; base Ubuntu resuelta
en ese run: `ubuntu@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852`.

| Imagen | `.Size` bytes runner | TAR individual o par, sin comprimir |
|---|---:|---:|
| Browser full Playwright (Chromium/Firefox/WebKit) | 2,695,268,890 | — |
| Browser Chromium-only (benchmark NO PRODUCTIVO) | 1,352,733,959 | 1,360,442,368 |
| Controller de producto | 66,805,534 | — |
| Controller + browser full | 2,762,074,424 suma lógica | 2,788,375,552 |

En este runner Chromium-only fue **1,342,534,931 bytes menor** en tamaño
lógico que browser full (~49.8% de reducción), pero **1,352,733,959 bytes
supera en 540,738,823 bytes** los `811,995,136 bytes` de holgura sobre el
piso de 4 GiB del droplet. Ni esta cifra ni el TAR prueban un delta físico
de pull; además el benchmark usa otro base OCI, por lo que comparación
de capas/deltas no es intercambiable. Requisito de tres navegadores permanece.

La medición no habilita GO de deploy, no justifica bajar el piso de 4 GiB
ni autoriza tocar imágenes/volúmenes ajenos. Para desplegar la BETA full
es imprescindible evidencia actualizada de capas OCI compartidas/compresión
y de capacidad real, o ampliación específicamente aprobada de almacenamiento.
