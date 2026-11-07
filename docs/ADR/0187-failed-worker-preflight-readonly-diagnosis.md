# ADR 0187 — Diagnóstico de un preflight worker fallido sin efectos físicos

**Actualización R86 (07/11/2026):** este ADR documenta el origen histórico
#795 del inspector. Después de #807 y del nuevo fallo físico #819, el contrato
exacto y exclusivamente READ_ONLY de este último incidente está en
[ADR0195](0195-r86-worker-819-exact-readonly-inventory.md). Los intentos viejos
conservan sus pins y sus recibos, pero no autorizan recuperación de #819.

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

## R77 — Evidencia adicional y separación de fallos

El run físico [#798](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42331553991)
del observador R76 terminó SUCCESS, pero **siempre** con resultado funcional
`READ_ONLY_NO_GO`: `socket=PRESENT_OWNED`, `seccomp=ABSENT`,
`probe=PRESENT_UNVERIFIED`, `docker=READ_FAILED`, `original=UNVERIFIED`.
La búsqueda del probe por nombre exacto devolvió un CID candidato. El único
`try` anterior no identifica cuál de las dos inspecciones falló; tampoco
permite inferir que el controlador haya caído. RCA de acoplamiento del
observador **comprobado**; RCA físico **todavía no demostrado**.

Decisión de dos revisiones independientes de QA e Infra: mantener la misma
operación manual READ_ONLY; dividir la lista de probe, metadata de probe e
inspección del legacy original en etapas independientes, cada una con estado
y rc categorizados (sin exponer Docker stdout/stderr, secretos o mensajes de
excepción); preservar `probe_candidate_id` como un mero candidato. Solo
ante error no cero del `inspect` completo, después de intentar ambas
identidades, permitir una consulta mínima distinta del **mismo** ID
`docker inspect --format '{{.Id}}'`, hasta dos como máximo. Igualdad de ID
significa únicamente metadata básica alcanzable en ese momento, no prueba
de plantilla incorrecta, pertenencia, salud ni autorización de limpieza.

La validación del recibo es fail-closed y coherente por etapa. No toca los
dos BLACKBOX, otras apps/daemons, puertos, SQLite ni contenedores. Se exige
CI, revisión y merge antes de volver a observar; tras leer el nuevo recibo,
ningún estado de este observador concede GO de Cutover físico.

## R78 — Inspección diferencial contra el límite real de cleanup

La evidencia R77 (run #42332735732) identifica el CID temporal por nombre
exacto y muestra `probe_inspect=COMMAND_FAILED rc=1`, mientras que la lectura
mínima de ID sí funcionó. La hipótesis de ausencia de HEALTHCHECK en un
contenedor creado sin iniciar sigue siendo hipótesis, NO RCA. La ruta real de
cleanup (`host_first_deploy._browser_inspect_record`) consume
`docker inspect --format '{{json .}}'` y rechaza longitud `>=65536`; es
distinta del template compacto anterior, por lo que su error no se puede
inferir del rc=1 del observador.

El diagnóstico R78 mantiene el mismo `cutover-a-worker-inspect` manual,
siempre READ_ONLY y `cutover_authorized=false`, y limita cada observación a
**cuatro consultas Docker de 12 segundos o menos**, bajo SSH 75s:

1. Un `docker ps -a -q --no-trunc` filtrado por el nombre completo del único
   intento #42329475083, sin listar otros contenedores.
2. Por el CID candidato obtenido, `docker inspect --format` con las mismas
   etiquetas y campos compactos, pero `health:null` constante. Se exige CID,
   nombre, proyecto, intento, revisión exacta R72
   `92624ed6b7e75c6010f59670c866df00a29766dd` y digest browser
   `sha256:3894cfff995858d7c0ffdb994180a0d28a8a92bb69a0526fb040db2297fd8bf9`.
3. Por el mismo CID, `docker inspect --format '{{len (json .)}}'`, de donde
   sólo sale la banda `BELOW_CLEANUP_LIMIT` o `AT_OR_ABOVE_CLEANUP_LIMIT`
   (o una categoría de error), nunca JSON, Env, Mounts ni stderr.
4. `docker inspect` compacto por CID exacto del controlador legacy, separado
   de los errores del temporal y con identidad, health y loopback 8443.

El recibo canónico v3 conserva los campos de seguridad de R77, reemplaza las
consultas básicas repetidas por el estado de tamaño y permite distinguir:
template incompatible, metadatos muy grandes, pins/labels distintos o falla
Docker aún indeterminada. `PRESENT_PIN_MATCH` significa **sólo coincidencia de
identidad compacta**, NO prueba de aislamiento completo, autorización de
stop/rm, cleanup ni Cutover. El resultado positivo de una consulta no limpia
un artefacto; ningún recurso del host se modifica. El controlador legacy se
inspecciona independientemente y, si no se verifica, permanece UNVERIFIED.

Prueba de integración de formato: `CI / image-build` crea y elimina por CID
exacto un contenedor descartable, **sin arrancarlo**, en el runner efímero
de GitHub Actions para comprobar realmente los dos templates de Docker;
no usa el daemon del droplet. La evidencia exacta de los checks y cualquier
recibo físico posterior se vincula en #45/#417, sin describirlos como hechos
antes de que existan.

### R78 — Corrección independiente solicitada por QA

La revisión de QA detectó que el observador anterior comprobaba el tamaño de
`stdout` después de que `subprocess.run(capture_output=True)` hubiera
acumulado una cantidad arbitraria de datos. El `stderr` tampoco estaba acotado.
Se corrigió la causa **antes del PR**: la función `_docker` usa `Popen` con
lectura no bloqueante de ambos pipes y un máximo de **2048 bytes por stream**,
durante la ejecución y dentro del límite total de 12 segundos por comando.
En exceso o timeout mata y espera al subproceso, descarta el contenido y
conserva sólo un estado categórico. No almacena ni imprime `stderr`. Las
regresiones usan procesos descartables locales que emiten `stdout` progresivo,
`stderr` voluminoso y caracteres UTF-8 multibyte. No son pruebas del daemon
del droplet ni acreditan limpieza física.
