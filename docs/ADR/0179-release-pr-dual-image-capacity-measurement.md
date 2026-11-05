# ADR 0179 — Capacidad de imágenes duales en runner descartable (R27)

**Fecha:** 2026-11-05 ART. **Estado:** PR, lectura runner R27 obtenida; host NO_GO.
**Ownership:** QA/release de Boca BETA; incidente [#386](https://github.com/mbalbo2023/boca-socios-assistant/issues/386).

## Hechos de partida

El READ_ONLY físico del Docker rootless de Boca observó `5,106,962,432`
bytes libres. La puerta de preflight exige `4,294,967,296` bytes libres
**antes y después del pull**; por lo tanto el margen sobre ese piso es
`811,995,136` bytes (aproximadamente 774.38 MiB). Esta medición no estima
la descarga ni expansión real de controller + browser, y no habilita un pull.
El host conserva el controller legacy, y la procedencia de una imagen local
adicional seguía pendiente de conciliación en ese corte.

## Decisión: observación sin efecto en el host

Se extiende **únicamente** `pr-validation` de
`.github/workflows/release-image.yml`, después de construir ambas imágenes
locales y verificar sus labels de revisión. En el runner desechable:

- `docker image inspect --format '{{.Size}}'` obtiene bytes de tamaño lógico
  individual de controller y browser, identificados con el SHA del PR.
- `docker image save controller browser | wc -c` mide los bytes de un archivo
  TAR **sin comprimir** que incluye las dos imágenes y sus capas. Se consume
  por tubería, sin crear artefactos TAR persistentes.
- Se registran los tres valores, la suma lógica y el SHA en stdout y
  `GITHUB_STEP_SUMMARY` mediante `BOCA_PR_DUAL_IMAGE_CAPACITY`; ante error,
  valor vacío o no numérico la medición falla cerrada.

**Ninguno de esos tamaños es el incremento físico del Docker rootless en el
droplet.** Las capas compartidas, capas ya presentes, compresión en tránsito,
metadatos y filesystem pueden cambiar los bytes efectivamente requeridos.
La comparación contra el margen `811,995,136` solo sirve como
**señal de riesgo**; el GO de capacidad necesita un recibo de host con
espacio/inodos antes y después del pull, sujeto al umbral existente.

El job `publish` protegido **no cambia**. No se habilita ni se despacha
`workflow_dispatch` de `release-image.yml`, no se publica GHCR, no se hace
`docker pull` en el host y no se alteran las reglas de unicidad de release.
Esta observación no lee, edita ni ejecuta los módulos BLACKBOX, ni toca
Porota, servicios ajenos, credenciales, puertos, reservas, compras o backups.

## Gate de pruebas y registro (Regla 84)

Pruebas estructurales confirman que la medición existe una sola vez y
solamente en el job PR, usa ambas tags locales, requiere tamaños válidos,
informa `host_delta=UNVERIFIED` y no contiene operaciones mutadoras o SSH.
Una vez ejecutado el PR, registrar el run/SHA y la línea con valores
observados en #386 y transmitirla al propietario del diagnóstico Docker.
Un green de PR **no prueba** pull ni instalación de BETA en el droplet.

## Evidencia R27 — runner descartable 2026-11-05

En [release-image PR #42117458795](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42117458795),
el paso `Measure disposable dual-image logical and archive bytes` terminó
**SUCCESS**, y emitió:

| Magnitud | Bytes reales del runner |
|---|---:|
| controller lógico | 66,805,534 |
| browser lógico | 2,695,268,890 |
| suma lógica | 2,762,074,424 |
| TAR conjunto sin comprimir | 2,788,375,552 |

La imagen browser representa el ~97.6% de la suma lógica. El TAR combinado
supera en `1,976,380,416` bytes (~1.84 GiB) el margen `811,995,136`
bytes observado en el host;
**esto indica riesgo importante y NO_GO prudente para un pull dual sin
capacidad adicional**, pero **no es un cálculo de delta físico**, pues las
capas OCI de imagen previamente presentes pueden reducir transferencia y
expansión. El valor de un `docker image save` no es tamaño comprimido de
GHCR. Verificar la identidad exacta de capas digest/layers remotas y
espacio efectivo del daemon rootless antes de cualquier release real.

La primera CI del PR registró `I001` (import block) solo en el test nuevo;
se corrige sin cambiar la medición. No extrapolar ese primer check a GO.

## R27.1 — Comprobación de los tres navegadores de la imagen final

Por instrucción explícita del propietario, la BETA **conserva Playwright
completo**, incluidos Chromium, Firefox y WebKit. No se optimiza reduciendo
navegadores, ni se cambia `Dockerfile.browser`. El PR valida con `docker run`
offline (`--network none`, UID10002, filesystem read-only, cap-drop y
seccomp) únicamente el paquete Playwright instalado, comprueba con `Path.is_file`
los `executable_path` de los tres browser types y emite
`BOCA_FULL_PLAYWRIGHT_BUNDLES ...` sin iniciar navegación ni importar los
módulos BLACKBOX. Este segundo recibo es evidencia de **disponibilidad de
binarios**, no de ejecución funcional Firefox/WebKit, no acredita instalación
en el droplet y no reemplaza los gates de capacidad.
