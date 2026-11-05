# ADR 0174 — observación posterior a Cutover A sin repetir efectos

**Fecha:** 2026-11-05 ART. **Estado:** candidato DRAFT de diagnóstico P0;
no prueba que la BETA integral esté instalada ni concede GO de reintento.
**Issue:** [#386](https://github.com/mbalbo2023/boca-socios-assistant/issues/386).

## Incidente y distinción probatoria

En [APPLY #42096941815](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42096941815),
`main=8a1a09805c17dad777105ece6fe5324bd4737474`, las aprobaciones
GO_B y el SSH pinado pasaron, pero el SSH effectful terminó en `exit 3`
en el paso 40 y faltó el ACK terminal. En código fuente,
`host_boca_cutover_cli.run_cli()` retorna `3` tanto con un resultado físico
NO_GO *registrado* como ante una excepción/receipt no verificado. La salida
fue guardada en archivo temporal del runner y stderr descartado: **no se
puede inferir ausencia de efectos, commit, recuperación ni limpieza**.

El observador previo `cutover-a-observe`
([#42097454923](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42097454923))
falló a su vez. Su contrato requiere singleton original sano, ninguna
imagen/worker/carpeta de intento adicional y estado Compose legacy original;
no es un reconciliador para un APPLY interrumpido. El mensaje histórico
`Original BETA not changed` después de su fallo puede inducir a una
conclusión inexistente y debe corregirse en el workflow.

## Decisión P0 acotada

Incorporar al **mismo** workflow manual de Boca una operación diagnóstica
separada `cutover-a-reconcile`, sin ruta de mutación ni salto automático a
APPLY. Su código stdlib independiente se transmite por SSH **sólo** al
usuario `boca-deploy` y acepta los dos ID cortos de Actions ya registrados:
incidente `42096941815` y PREPARE `42091200929`. Nunca necesita PIN,
cookie, credencial, URL pública, digest nuevo, release ni acceso a BLACKBOX.

La observación abre en modo sólo lectura y sin seguir enlaces simbólicos:

1. Los marcadores persistentes exactos de intent y terminal, bajo el home
   privado de Boca; al validar bytes canónicos no publica sujeto/credencial.
2. El directorio exacto `cutover-a-<incident>` y sus marcadores de promoción
   (`intent`/`result`), sin crear ni borrar staging.
3. **Únicamente** IDs de contenedores con etiqueta
   `com.docker.compose.project=boca-socios`, con proyección limitada de
   ID/nombre/Running/health/revision/servicio/port binding (sin Config.Env).
   Dos inventarios consecutivos idénticos evitan tomar estado mutable por
   estable. La observación de `127.0.0.1:8443` corresponde al binding Docker,
   **no** acredita HTTP ni aplicación sana.
4. Identidad del volumen Boca de datos y, si el UID permite lectura sin
   mutar, marcador exacto del PREPARE. Si el UID no puede leerlo se conserva
   `UNREADABLE`, sin usar un contenedor auxiliar ni modificar permisos.

No hay `docker exec`, `pull`, `start`, `stop`, `rm`, `prune`, `compose`,
`docker run`, escrituras SQLite/archivos, escaneo de otros proyectos o
red/servicio nuevo. La falta de un marcador, datos contradictorios, JSON
malformado, UID/socket incorrecto o inventario cambiante causa NO_GO.

El resultado es un JSON acotado y canónico, y el verificador del runner
comprueba ID exacto y los campos fijos `go_for_retry=false`,
`runtime_attested=false` y `foreign_resources_touched=false`.
El último campo describe **únicamente el proceso lector nuevo**; no prueba
que el APPLY anterior no haya tocado nada (ni dentro ni fuera de Boca),
cuyo efecto físico permanece **desconocido** hasta la reconciliación.
Una observación correctamente ejecutada puede quedar verde **como
diagnóstico**, pero su clasificación operativa sigue siendo `READ_ONLY_NO_GO`.

## No decisiones inferidas

- El intervalo de ~22 segundos es compatible con el `docker exec` preparado
  que tiene timeout de 20 segundos, **pero no permite atribuirle causalidad**
  hasta encontrar recibos de intent/result y topología concreta.
- NO repetir el APPLY #42096941815, no borrar/prestar el marker PREPARE, no
  recuperar/retirar contenedores por heurísticas ni limpiar con prune.
- La remediación se decidirá *después* de leer los marcadores y el inventario
  Boca y de contrastar con al menos otra evidencia de Actions/runtime.
- El diagnóstico nuevo no habilita navegación Boca, Telegram real, compra,
  reserva, cambio de volumen, puerto, HTTPS, Porota u otro Docker del droplet.

## Evidencia y aceptación futura

El PR de #386 llevará QA exacta de código y políticas. Después de integrar
el observador, únicamente una operación manual READ_ONLY, con recibo remoto
canónico, podrá precisar el estado del incidente. El PR, aun verde, **no es
la aceptación del host**. El root owner conserva merge/deploy físico y las
comprobaciones Android Chrome + Termius, salud Chromium y Telegram.

## R23 — reconciliación física posterior (#42100840815)

El workflow READ_ONLY #42100840815 terminó **SUCCESS** y entregó un recibo
canónico: `intent=PRESENT`, `result=PRESENT`, `state=NO_GO`,
`cleanup=INDETERMINATE`, `original_restored=true`, `commit_started=false`,
`stage=ABSENT`, `original=RUNNING/healthy`, un único contenedor Boca, cero
worker/candidato y binding Docker exclusivo en `127.0.0.1:8443`.
El marcador PREPARE aparece `UNREADABLE`, **no** ausente ni inválido.

### Inferencia del código con límites

En `host_boca_cutover.run_cutover_a` se establece `effect_started=True`
**después** de que regresa el consumidor de PREPARE y justo **antes** de
`backend.stage()`. Con `original_restored=true` y `cleanup=INDETERMINATE`
se demuestra que se ejecutó la ruta de recuperación precommit; no demuestra
qué llamada inicial lanzó la excepción. `backend.finalize()` sólo devuelve
`INDETERMINATE` como recibo de `cleanup.execute_protected` bajo un estado
`RECOVERED` o `COMMITTED`; `commit_started=false` excluye el último.
El staging ausente es compatible con fallo en validaciones previas a `mkdir`
de `host_cutover_stage.initialize`, pero también podría haber cambiado entre
el incidente y la observación posterior. No se afirma timeout del marcador.

### Diagnóstico incremental sin efectos

Se amplía el mismo lector `cutover-a-reconcile` con dos pruebas independientes:

- `stage_preflight`: comprueba sólo el directorio `/srv/boca-socios` y el
  `compose.beta.yaml` existente mediante O_NOFOLLOW, UID/GID/modo, lista
  exacta de entradas, hash contra la intención persistente y unicidad de
  las cuatro SHA de Compose/overlay/seccomp. Devuelve únicamente códigos
  acotados (`STAGE_ROOT_ENTRIES`, `STAGE_COMPOSE_SHA`,
  `PLAN_SHA_COLLISION_OR_INVALID`, `STAGE_PREFLIGHT_MATCH`, etc.), sin
  publicar bytes ni rutas privadas adicionales.
- `prepared_go_marker_reason`: desambigua `UNREADABLE` con códigos como
  `DIRECTORY`, `MARKER_METADATA`, `READ_PERMISSION`, `DOCKER_READ`; no hace
  `docker exec` ni modifica permisos, marcadores o volúmenes.

El recibo sigue imponiendo `runtime_attested=false`, `go_for_retry=false`
y `scope=OBSERVER_ONLY`. No se reejecuta el APPLY original. Incluso una
precondición de staging hoy positiva sólo acredita el estado actual, **no**
demuestra cuál era la condición temporal durante el APPLY anterior.
