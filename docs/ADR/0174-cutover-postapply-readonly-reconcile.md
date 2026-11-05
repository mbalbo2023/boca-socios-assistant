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
  exacta de entradas, hash contra la intención persistente y separación
  de los digest por rol: destino/overlay/seccomp distintos, histórico distinto
  de overlay y seccomp, pero Compose histórico==destino permitido. Devuelve
  únicamente códigos acotados (`STAGE_ROOT_ENTRIES`, `STAGE_COMPOSE_SHA`,
  `PLAN_ROLE_DIGEST_INVALID`, `STAGE_PREFLIGHT_MATCH`, etc.), sin
  publicar bytes ni rutas privadas adicionales.
- `prepared_go_marker_reason`: desambigua `UNREADABLE` con códigos como
  `DIRECTORY`, `MARKER_METADATA`, `READ_PERMISSION`, `DOCKER_READ`; no hace
  `docker exec` ni modifica permisos, marcadores o volúmenes.

El recibo sigue imponiendo `runtime_attested=false`, `go_for_retry=false`
y `scope=OBSERVER_ONLY`. No se reejecuta el APPLY original. Incluso una
precondición de staging hoy positiva sólo acredita el estado actual, **no**
demuestra cuál era la condición temporal durante el APPLY anterior.

## R24 — RCA determinística de contrato Stage y corrección DRAFT #390

[READ_ONLY #42102926149](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42102926149)
confirmó `stage=ABSENT`, `commit_started=false`, `original_restored=true`,
`cleanup=INDETERMINATE`, `prepared_go_marker_reason=DIRECTORY` y
`stage_preflight.reason=PLAN_SHA_COLLISION_OR_INVALID`. La última etiqueta
procedía de una política **incorrecta** del lector y era consistente con un
bloqueo previo a crear el stage. No equivale a un fallo de integridad del artefacto.

Contraste inmutable de GitHub en los dos SHAs revisados:

- Compose histórico `cabce9f1e452e63ded115f447559a358dc0f4d1b` y destino
  `8a1a09805c17dad777105ece6fe5324bd4737474`: 1747 bytes **idénticos**,
  SHA256 `b9e9465d6ec8e484b615d7bd65aab5a3c150d34a9893ad181167d2099893d811`.
- Overlay SHA256 `a9a9490f92936bcd58c78ea0ec0ad6e7465ab89cf17f90937a906d498b8a7f8b`.
- Seccomp SHA256 `cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849`.

La validación canónica `host_boca_cutover.CutoverPlan.validate` **ya** permite
reutilizar Compose para upgrades de código/imagen, siempre que las
referencias/source y los otros hashes independientes estén verificados.
Pero `host_cutover_stage._marker_payload` exigía **cuatro hashes diferentes**,
y `initialize` invoca esa validación *antes del `mkdir`*. Ésta es una
causa raíz precisa y reproducible del rechazo de Stage para el plan registrado;
no se afirma que sea la única condición física fallida, pues la raíz/owner de
Stage no pudieron inspeccionarse por el retorno prematuro del lector anterior.

El DRAFT [#390](https://github.com/mbalbo2023/boca-socios-assistant/pull/390)
alinea estrictamente Stage y lector con el contrato existente: Compose
histórico==destino permitido, overlay/seccomp siempre separados, byte-digest
por rol intacto, revisiones/imágenes/etiquetas independientes y ninguna edición
artificial de YAML. El lector observa las condiciones reales de raíz incluso
si el digest del plan fuese inválido; su campo de compatibilidad
`plan_hashes_unique` significa ahora **independencia entre roles que deben
ser distintos**, no "cuatro hashes siempre distintos".

Se agregan pruebas offline para aceptación legítima y rechazo de SHA/bytes
adulterados y roles colisionados. Nada de esto habilita reintentar el APPLY
histórico ni limpiar Docker con `prune`. El `cleanup=INDETERMINATE` exige
reconciliar los recursos exclusivamente Boca y el estado de raíz antes de
cualquier transacción **nueva** con RELEASE/PREPARE/GO_B renovados.

## R24.2 — observación desagregada de metadatos Compose (P0, CODE_ONLY)

El diagnóstico físico READ_ONLY
[#42104978077](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42104978077),
desde `main=3d0e4ff288ab41e10a5cd1eef930f6d12e18cca5`, encontró
`root_entries_expected=true`, `legacy_target_compose_equal=true`,
`plan_hashes_unique=true` pero `STAGE_COMPOSE_INODE_MODE`. Ese resultado
solamente afirma que falló **al menos una** de seis condiciones del archivo;
`compose_digest_match=false` es el valor inicial de un hash **no evaluado**
porque `_stage_preflight` retorna antes de leer bytes. No declarar
hash corrupto ni permiso concreto hasta obtener metadata física.

La corrección diagnóstica incremental mantiene el `open` existente
`O_NOFOLLOW` bajo el directorio Boca ya comprobado y reutiliza **el mismo
descriptor abierto** en `fstat`: `compose_inode_checks` informa seis
booleanos acotados (`regular`, `uid_ok`, `gid_ok`, `nlink_one`, `mode_0600`,
`size_ok`); `compose_inode_mode_octal` contiene sólo el modo POSIX de ese
inode, sin nombre adicional, contenido ni dato privado;
`compose_digest_evaluated` separa explícitamente **no leído** de un digest
calculado y diferente. Si no llegó a abrir el Compose, los checks/modo
permanecen `null`. Cada condición falsa sigue generando
`STAGE_COMPOSE_INODE_MODE` y bloquea toda lectura de bytes. No existe
`chmod`, `chown`, borrado ni cambio de política de admisión en esta etapa.

El contrato histórico de instalación (`host_first_deploy._verify_beta_compose`)
aceptaba UID10001, archivo regular, tamaño hasta 32768 y ausencia de escritura
grupo/otros (por ejemplo `0640`, `0644`); no exigía GID10001, `nlink=1`,
`0600` exacto ni tamaño positivo. El stage de Cutover A
(`host_cutover_stage._read_file`) sí exige esos cuatro atributos, además de
los compartidos. **Esto prueba una discrepancia de contratos de código, no
cuál atributo real la activó**. Una vez observado el conjunto de booleans,
un RCA con evidencia cruzada determinará si es apropiada una adaptación
estrictamente Boca del contrato o una normalización protegida del archivo;
no se modificará el inode live ni se relajará el stage anticipadamente.

Los tests offline simulan cada una de las seis diferencias en un FD abierto,
comprueban que ninguna provoca lectura de bytes y ejercitan el caso sano
SHA-comprobado y la ausencia de evidencia ante raíz inaccesible. Resultado
de pruebas locales no prueba metadata del droplet; falta PR/CI exact-SHA,
merge revisado y nueva Action `cutover-a-reconcile` **READ_ONLY**. También
continúa el stopper independiente `cleanup=INDETERMINATE`, con ownership
Docker separado; ninguna observación es GO de retry ni de deploy.

## R24.4 — normalización de contrato por compatibilidad histórica 0644 (CODE_ONLY)

**Nueva evidencia física decisiva:** la operación protegida READ_ONLY
[#42112927157](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42112927157)
desde `main=b0a731a5b9f9115713bb39e48218653ed4035d76` comprobó
`root_entries_expected=true`, roles/digests de plan válidos y, sobre el
**mismo FD legacy**, seis checks `{regular:true,uid_ok:true,gid_ok:true,
nlink_one:true,mode_0600:false,size_ok:true}` con
`compose_inode_mode_octal="0644"`. `compose_digest_evaluated=false` porque
el verificador antiguo no abrió el contenido al fallar el modo estricto;
no se declara aún PASS SHA físico. Controlador legacy único sano, original
restaurado y sin comienzo de commit. Esta prueba confirma el desajuste de
modo sospechado y permite restringir la solución a un atributo.

En el `beta-install` histórico del SHA `cabce9f1...`, GitHub Actions
copiaba el YAML mediante `scp -p`, conservando el modo de checkout
`0644`, y `host_first_deploy._verify_beta_compose` ya lo admitía sin
escritura para grupo/otros. Stage exigía por error `0600` **también al
archivo existente**, aunque prometía no mutar su inode durante Cutover A.

**Decisión fix-forward más acotada, sin modificar el host:**

- Las **tres** lecturas del Compose histórico en la raíz existente
  (`initialize`, relectura, autenticación previa) reciben un opt-in interno
  `historical_compose=True`, válido exclusivamente para
  `compose.beta.yaml`, `MAX_FILE` y SHA esperado. Sólo acepta modos
  exactos `0600` o **`0644` observado**. No acepta `0640` como extensión
  preventiva, `0664`, `0444`, bits especiales ni permisos desconocidos.
- Se conservan de manera idéntica comprobaciones FD/O_NOFOLLOW, regular,
  UID10001, GID10001, nlink1, tamaño 1..32768, lectura acotada, SHA y
  estabilidad dev/ino/tamaño/mtime/ctime. El inode/YAML live no se toca.
- Marker, target, overlay, seccomp, promoción y archivos nuevos continúan
  con **`0600` exacto**. Tras promoción autorizada los nuevos inodes del
  Compose/overlays siguen siendo 0600; no existe `chmod` en legacy.
- El diagnóstico READ_ONLY conserva su dato fáctico
  `compose_inode_checks.mode_0600=false`, publica
  `compose_legacy_mode_accepted=true` separado y ahora, sólo después de
  aprobar los otros cinco atributos, comprueba digest real antes de informar
  `STAGE_PREFLIGHT_MATCH` o `STAGE_COMPOSE_SHA`.

La suite offline agregada cubre Cutover completo con Compose histórico
0644 sin cambiar su inode hasta promoción, permisos estrictos de archivos
nuevos, rechazo de 0640/0444/0664/0755/bit setuid, mismatch SHA y seis
flags observacionales. **No hay prueba nueva en el droplet aún**: después
de PR+CI+revisión+merge se requiere nueva observación protegida READ_ONLY
desde main exacto, y limpieza Docker independiente concluyente antes de
release/PREPARE/GO_B/APPLY nuevos. Ningún efecto real ni GO se infiere.

El marcador PREPARE histórico observado como
`UNREADABLE`/`DIRECTORY` corresponde al intento del observador host de
abrir directamente un mountpoint rootless; no confirma presencia/ausencia.
El consumidor GO real usa otro camino, `docker exec` dentro del controller
histórico UID10001 para crear/verificar el marcador bajo `/data`. Son
contratos diferentes: no relajar el lector para simular un marker válido,
ni afirmar que el nuevo PREPARE funcionará sin su propio ACK exacto.
