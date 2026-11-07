# ADR 0187 — Diagnóstico de un preflight worker fallido sin efectos físicos

**Fecha:** 2026-11-06 ART. **Estado:** candidato CODE_ONLY hasta CI/merge y
ejecución protegida; no equivale a aceptación BETA.

## Incidente y RCA delimitado

El preflight físico [#42329475083](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42329475083)
terminó `failed_phase=CLEANUP cleanup=INDETERMINATE` para release dual
[#42329201039](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42329201039),
`main=92624ed6b7e75c6010f59670c866df00a29766dd`. Su `finally` intenta
eliminar el contenedor temporal **por ID exacto** y comprobar otra vez el
controlador original. La fase final `CLEANUP` puede ocultar dónde comenzó la
falla; no acredita que el probe siga presente ni que el original haya caído.

El observador READ_ONLY histórico
[#42329673385](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42329673385)
devolvió `host_observation_failed` sin inventario. La implementación
`host_cutover_postapply_reconcile.py` está diseñada para un APPLY de Cutover A:
no atribuye identidad a `boca.socios.cutover-preflight-attempt`, y el workflow
suprime las causas remotas. **RCA de observabilidad comprobado**: herramienta
equivocada y error agregado. **RCA físico todavía NO DEMOSTRADO**.

## Decisión de diagnóstico mínimo

Agregar `cutover-a-worker-inspect` al **mismo workflow manual protegido**:

1. Admite únicamente el intento #42329475083 y los pins exactos del
   controlador histórico (CID, commit y digest); prohíbe imágenes/descargas,
   release nuevo, enlaces de GO y datos secretos.
2. Por SSH `boca-deploy`, observa solamente el socket rootless del UID 10001,
   el inode seccomp temporal por `lstat`, el nombre/label exacto del contenedor
   descartable y el CID original. `docker ps`/`inspect` están restringidos a
   esas identidades; nunca ejecuta `docker exec`, `stop`, `rm`, `pull` o `prune`.
3. Emite un JSON ASCII canónico acotado y estados categóricos independientes:
   socket, Docker, probe, seccomp y salud/puerto del original. Si no se puede
   observar, conserva `UNVERIFIED` y no convierte ausencia de datos en ausencia
   física. `PRESENT_LABEL_MATCH` prueba solo coincidencia de nombre, etiquetas
   y repositorio; **no** certifica el digest exacto para una futura limpieza.
   El runner verifica su forma antes de guardar un resumen.
4. El recibo es siempre `READ_ONLY_NO_GO`, aunque el observer termine SUCCESS.
   No autoriza un nuevo preflight, PREPARE ni APPLY. Cualquier residuo requiere
   otra revisión de identidad positiva y fix-forward acotado.

## Límites

- No se alteran las cajas negras del navegador, el código de navegación ni
  el controlador instalado, sus volúmenes, claves, datos o puerto 8443.
- No se consulta otro daemon Docker, proyecto Compose ni servicio del host.
- No se reintenta #42329475083 ni #42329673385; esta es una observación
  diferencial específica del incidente, no un retry del efecto anterior.
- La ejecución de esta ruta y cualquier futura reparación requieren primero
  QA, checks exactos y merge del PR que contenga este ADR. Una modificación a
  main exige nueva certificación/release de imágenes antes de un futuro
  Cutover; nunca reutilizar un GO preparado para un SHA anterior.

## Evidencia de aceptación del cambio

Tests offline `tests/test_cutover_worker_readonly_inspect.py`, linter,
tipado y suite aplicable para el SHA final; resultados de GitHub Actions
se añadirán en issue #45 cuando existan. Ningún resultado físico se infiere
de las pruebas locales.
