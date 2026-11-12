# ADR 0250 — R246 controller: separar dependencias bloqueadas del código

**Fecha:** 2026-11-12 ART. **Issue:** #417. **Estado:** integrado al
candidato de código R246 para CI hospedado; NO_GO de despliegue físico.

## Causa de la invalidación

El Dockerfile controller copiaba `src/` antes de ejecutar un único
`uv sync --locked --no-dev --no-editable`. Cada cambio del código fuente
invalidaba la capa que descargaba e instalaba dependencias de `uv.lock`,
aunque el grafo externo hubiera permanecido igual. El browser ya separaba
la capa del lock y Chromium de la copia del código.

## Cambio revisado y alternativas

Se optó por la ruta mínima de dos comandos existentes, sin introducir
Buildx ni credenciales:

1. Copiar sólo `pyproject.toml`, `uv.lock` y `README.md`.
2. Ejecutar `uv sync --locked --no-dev --no-install-project` para fijar
   únicamente el grafo externo; esa capa no depende de `src/`.
3. Copiar `src/` y ejecutar el `uv sync --locked --no-dev --no-editable`
   original, manteniendo el paquete Boca realmente instalado en la venv.
4. Continuar copiando la misma venv a runtime UID10001; no cambiar la
   imagen de base, librerías OS, healthcheck, origen OCI ni CMD.

Alternativas descartadas por ahora:

- `--offline`: no se demuestra que el backend de build esté previamente
  disponible; una caché vacía fallaría en lugar de reproducir el lock.
- Usar artefactos del PR en la release protegida: no prueba procedencia
  main SHA ni los escaneos separados. Los builders protegidos conservan
  sus propios checks y digests.
- Cache `type=gha` sin A/B: su import/export, especialmente de Playwright,
  podría aumentar la latencia y mezclar ámbitos de confianza.

## Verificaciones realizadas sin Docker

- Dos regresiones RED antes del cambio y GREEN después: separación exacta
  de COPY/uv, paquete final instalado, origen/usuario/entrypoint intactos.
- Smoke local de `uv sync` en carpeta temporal **sin `src/`**: grafo
  externo bloqueado con `cryptography==50.0.2`, sin paquete Boca instalado.
  Luego se copió `src/` y un segundo `uv sync` instaló la wheel no editable
  `boca-socios-assistant==0.1.0`, con import de vault/database y roundtrip
  criptográfico/SQLite satisfactorios.
- El entorno de ejecución no posee el binario `docker`, de modo que no hay
  medición de imagen Alpine, cache hit/miss, Trivy ni latencia GitHub real.
- Suite completa sobre la rama de trabajo derivada de `e799866`:
  **7754 PASS, 1 SKIP ambiental AF_UNIX, 34 subtests PASS y 1 FAIL**
  preexistente de `test_current_cutover_zip_is_pinned_and_excludes_preflight`.
  Esa base aún conserva el pin Cutover R244 `487b55...` pese a generar
  `1fa860...`; el integrador R245 ya corrigió el pin en su commit de
  documentación `65df58d`. Este experimento modifica sólo Dockerfile y
  su test, no los miembros del ZIP Cutover. No se ha omitido ni alterado
  el test fallido para fabricar GREEN.

El cambio no disminuye el número de ocho compilaciones nominales; habilita
reuso de capas únicamente en un runner con caché previa. La evidencia
R244 midió `image-build` 254 s, de los cuales apenas ~50 s son las dos
compilaciones; la mayor optimización futura requiere medir los laboratorios
Docker, que insumen ~171 s. Ver [ADR0245](0245-ci-image-count-vs-latency.md).

## Gate para eventual promoción

La integración R246 sobre `main=b51b66f0` ejecutó la suite completa:
**7781 PASS, 1 SKIP ambiental AF_UNIX, 34 subtests PASS**. El fallo del
pin histórico de la rama experimental ya estaba corregido en la base
R245; `ruff`/`mypy`/policy y la revisión focal independiente pasaron.
La promoción como código no es una autorización de despliegue.

Conservar la evaluación de velocidad como experimento hasta A/B en GitHub
Actions de builds controller con fuente modificada, tanto caché fría como
caliente, con timings separados y verificación del runtime exacto, Trivy,
labels SHA y digest. **No atribuir un ahorro temporal antes de esas
mediciones** ni habilitar un nuevo release/host por un cambio de Dockerfile.
