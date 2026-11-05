# ADR 0179 — Capacidad de imágenes duales en runner descartable (R27)

**Fecha:** 2026-11-05 ART. **Estado:** PR, evidencia del runner pendiente.
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
