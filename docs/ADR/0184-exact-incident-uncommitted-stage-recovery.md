# ADR 0184 — Boca Cutover A: recuperación de Stage abandonado con identidad exacta

## Candidato V3 genérico — 2026-11-07, CODE_ONLY

La operación existente `cutover-a-stage-recover` se adapta para incidentes
V3 sin PREPARE; `protected_action_context` es únicamente un selector numérico
no confiable, seleccionado mediante GitHub y no solicitado al usuario. GitHub
debe acreditar incidente manual V3, propietario/triggering owner, main, primer
intento y failure, con SHA derivado del run, PR0 y una sola recuperación por
incidente en historial paginado completo. El lector de historial falla cerrado
ante truncamiento o el límite de 1000 resultados. `cutover-a-stage-recover-844`
y sus verificadores históricos permanecen separados.

Bajo el lease Boca, el host compara el SHA de GitHub con intent/result
encadenados, exige dos observaciones V3 idénticas, controlador original sano
y único en `127.0.0.1:8443`, ningún candidato/worker/promoción y autenticación
del Stage exacto, marcador, archivos y Compose original. Solo se llama al
`discard_recovered` existente; un tercer snapshot y ACK validan el resultado.
No se modifica Docker ni se eliminan imágenes o volúmenes. Las referencias
de imágenes y hashes del plan se comparan entre recibo y marcador; no se
revalida aquí la release dual, que es requisito del Cutover posterior.

El observador #858 es evidencia histórica READ_ONLY, no un artifact de
autorización ni prueba del estado futuro. #853 reportó `PREPARE_WORKER` con
subcausa desconocida; `STAGE_ROOT_ENTRIES` no demuestra su causa. La propuesta
no es recuperación física, mantiene `cleanup=INDETERMINATE` y
`go_for_retry=false`; exige inventario Boca-only de imágenes, IPC y capacidad
antes de considerar un nuevo Cutover. No autoriza repetir #853.

Estado: **CODE_ONLY / NO_GO físico**. Incidente canónico issue #386, intento físico
`42236673419`, PREPARE `42217108000`, base de integración
`cb1f0102f2324802c476051d8c81858c141ec0f6`.

## Hallazgo reproducible y alcance

El APPLY protegido anterior terminó con recibo durable `NO_GO`,
`cleanup=INDETERMINATE`, `original_restored=true`,
`irreversible_commit_started=false`. El READ_ONLY posterior observó el controlador
legacy original vivo/sano, 8443 en loopback, ningún worker ni candidato, pero
`stage=PRESENT`, `stage_preflight.reason=STAGE_ROOT_ENTRIES`,
`root_entries_count=2`. El conteo por sí solo **no** identifica la segunda
entrada. La causa del rechazo del próximo Stage reside en que
`host_cutover_stage.initialize` exige un root con solo `compose.beta.yaml`.

El backend existente únicamente descarta el Stage si su limpieza general Docker
termina en `ACCEPT`. Ante `INDETERMINATE`, retiene Stage como cuarentena aunque
el controlador original haya sido restaurado. **No** deducir que el Stage se
puede borrar por el solo conteo de dos entradas o por espacio libre.

## Decisión arquitectónica

Agregar `scripts/host_cutover_stage_recovery.py` como operación Boca-only
explícita y única en workflow protegido. No modificar `host_cutover_stage.py`,
el motor de Docker Cleanup, ni el workflow desde este scope. No realizar SSH
directo. Esta operación hace **cero acciones Docker** y no considera resuelto
el `cleanup=INDETERMINATE` de la imagen; ese punto conserva ownership separado.

Condiciones obligatorias **antes de cualquier unlink**:

1. Lease exclusivo `protected_boca_job_lease` por **incident run ID**, verificado
   antes y durante el efecto.
2. Intent y resultado durables canónicos y privados, hash del intent ligado al
   resultado; mismo legacy ID, revisiones, digest Compose, imágenes y roles.
3. Terminal `NO_GO`, cleanup `INDETERMINATE`, original restaurado y compromiso
   irreversible no iniciado.
4. Dos observaciones independientes y estables del runtime Boca via observer
   READ_ONLY: una sola instancia original (mismo CID/revision), sana, ejecutando
   y publicada exclusivamente en `127.0.0.1:8443`; cero candidato y worker.
5. Root con set **exacto** `{compose.beta.yaml, cutover-a-42236673419}` probado
   por `_authenticated_stage` con dirfd `O_NOFOLLOW`, ownership/mode, Compose
   inode/sha y marker canonical ligado *campo por campo* al intent durable.
6. Stage únicamente con marker y subconjunto de ficheros revisados, cada uno
   autenticado por su SHA. No `.part`, symlinks, entradas desconocidas, marcador
   de promoción ni cambio de identidad.

Solo entonces reusar `host_cutover_stage.discard_recovered`, que elimina nombres
exactos mediante `dir_fd`, elimina el directorio exacto del intento y preserva
el Compose vivo. Sin borrados recursivos, sin `docker prune`, sin borrar
imágenes, redes, volúmenes ni contenedores. Si cualquier prueba falla, devolver
`NO_GO` y retener la cuarentena.

Después del efecto: observer nuevo confirma Stage ausente, root exactamente con
Compose cuyo digest coincide, runtime Boca byte-a-byte igual al observado antes,
ambos recibos durables inmutados, y ningún otro servicio tocado. Si falta esta
confirmación, mantener `NO_GO` aunque el Stage físico ya se haya eliminado.

## Contrato reproducible para integrar en Actions

El paquete revisado transporta:

- `scripts/host_cutover_stage_recovery.py` (este cambio).
- `scripts/host_cutover_postapply_reconcile.py` (READ_ONLY ya existente).
- `src/boca_socios/host_boca_cleanup.py` y `src/boca_socios/host_cutover_stage.py`
  y dependencias Python revisadas (ya existentes).

Comandos dentro del único workflow protegido, con `PYTHONPATH` configurado
al root y `src/` del paquete revisado:

```bash
python3 -m scripts.host_cutover_stage_recovery host 42236673419 42217108000
python3 -m scripts.host_cutover_stage_recovery verify 42236673419 42217108000
```

`host` no recibe por CLI un CID legacy inventado: lo deriva de los registros
durables y Stage. `verify` recibe el JSON del host **por stdin**, una sola línea
ASCII canónica de máximo **2048 bytes**. Ambos modos devuelven **0 solo si**
la limpieza Stage ha quedado positivamente probada; errores e incertidumbre
devuelven **3**, sin detalles sensibles. La salida positiva lleva
`state=STAGE_CLEARED`, `stage_before=PRESENT`, `stage_after=ABSENT`,
`docker_writes=0`, `foreign_resources_touched=false`, `go_for_retry=false`.
No crea un nuevo GO, PREPARE ni habilita reaplicar automáticamente el Cutover A.

El integrador debe mantener predeploy, sha/pinning y aprobaciones de Actions
vigentes, publicar recibo y resumen en issue #386/#45 (Regla 84). No modificar
BLACKBOX (`synthetic.py`, `ipc_worker.py`) ni servicios ajenos a Boca.

## QA y límites de evidencia

- Tests offline de identidad, recibo adversarial, symlink/unknown `.part`,
  intent/result alterados, promoción, Compose inmutable, Stage exacto, Docker
  intacto y postcondiciones: `tests/test_host_cutover_stage_recovery.py`.
- Tests preexistentes de Stage y observer: `tests/test_host_cutover_stage.py`,
  `tests/test_host_cutover_postapply_reconcile.py`.
- Evidencia CODE_ONLY no implica liberación física. Solo el protected Actions
  con recibo físico autenticado puede constatar la instalación en droplet.

## Riesgo residual explícito

El lease protege frente a participantes cooperativos del mecanismo protegido;
no demuestra ausencia absoluta de trabajos antiguos que no respeten ese lease.
Un cambio de runtime/Stage durante las lecturas fuerza NO_GO. La limpieza
indeterminada de Docker queda sin resolver hasta su propia verificación.

## Integración R47 — ruta manual protegida, aún sin efecto físico

`boca-first-deploy.yml` agrega `cutover-a-stage-recover` exclusivamente para
incidente `42236673419`, PREPARE `42217108000` y reconciliación READ_ONLY
positiva `42237830418`. Solo `main`, actor propietario, ambiente protegido,
`GITHUB_RUN_ATTEMPT=1`, SHA actual y presupuesto `1.5cpu-1024m-192pids` pueden
alcanzar el SSH fijo `boca-deploy`. No acepta IDs de contenedor, imagen o
archivos arbitrarios. Transporta el código revisado por ZIP digest-bound,
comprobado por bootstrap Linux memfd, sin dejar fuente en disco del host.

El PR sólo prueba que ese recorrido está cableado; **no** equivale a una
ejecución aprobada. Un solo recibo host canónico y verificación runner
adicional son obligatorios. Ante falta de ACK, no se re-dispara la misma
operación; corresponde una observación física READ_ONLY nueva. La limpieza
de la imagen histórica mantiene su ruta y evidencia independientes.

## Resultado físico del 06/11/2026 — Stage resuelto; verificador del runner corregido

- El PR #404 se fusionó en `main` (`90a904fccc7b6c5557f98823ef27080344961540`).
- La ejecución protegida #42243714580 completó su único SSH de recuperación
  sin error registrado, pero la **verificación posterior del runner** devolvió
  código 1 por `ModuleNotFoundError: No module named 'boca_socios'`. El paso
  invocaba `python3 scripts/host_cutover_stage_recovery.py verify` sin los
  dos roots de import de este repositorio (`src` y `.`). Por eso el resumen
  `physical_ACK_missing_or_invalid` era ambiguo, no una prueba de fracaso host.
- La nueva ejecución **READ_ONLY** #42244158822 confirmó la postcondición
  física exacta: `stage=ABSENT`, `stage_preflight.reason=STAGE_PREFLIGHT_MATCH`,
  `root_entries_count=1`, SHA de Compose coincidente, modo legado 0644
  aceptado, mismo único CID original `27ef39ed49d2...`, `running=true`,
  `health=healthy`, loopback `127.0.0.1:8443`, cero candidatos/workers,
  `commit_started=false`, `foreign_resources_touched=false`. El stage está
  **efectivamente eliminado**. **No repetir** #42243714580 ni invocar
  `cutover-a-stage-recover` una segunda vez.
- Fix-forward estrictamente de runner: exportar `PYTHONPATH: src:.` en el paso
  de verificación y ejecutar el entrypoint como módulo
  `python3 -m scripts.host_cutover_stage_recovery verify ...`. Test de regresión
  lanza el módulo desde checkout con entrada vacía: se espera NO_GO por ACK
  ausente, **nunca** `ModuleNotFoundError`.
- La clasificación global `cleanup=INDETERMINATE` continúa referida al
  inventario histórico Docker; no implica que Stage siga presente. La
  eliminación exacta de la imagen antigua requiere su operación separada,
  un nuevo recibo físico y ninguna limpieza global.

## Extensión R49 — segundo Stage abandonado, solo candidato CODE_ONLY

El `PREPARE` [#42246824073](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42246824073)
fue aceptado para `main=f3a8841817307daa084fe0472720f4444235c9bb`.
El APPLY [#42249350458](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42249350458)
pasó el GO independiente, pero terminó por salida remota 3 sin ACK físico.
La inspección de un solo SSH READ_ONLY
[#42250420345](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42250420345)
mostró `intent=PRESENT`, `result=PRESENT`, `terminal_state=NO_GO`,
`cleanup=INDETERMINATE`, `commit_started=false`, `original_restored=true`,
exactamente el controlador legacy sano en `127.0.0.1:8443`, sin candidato
ni worker, y `stage=PRESENT` con dos entradas en el root. El Stage continúa
sin identidad de contenido demostrada hasta que `_stage_identity` la verifique
bajo lease; **el conteo no justifica por sí solo eliminarlo**.

La ruta Python de recuperación ya exige dos observaciones idénticas, hashes,
identidad del Stage y unlink exacto. R49 solo cambia la habilitación del
workflow para el nuevo trío inmutable:

| Propósito | Run | Resultado previo exigido |
| --- | --- | --- |
| Incidente a reparar | `42249350458` | `failure` |
| PREPARE ligado | `42246824073` | `success` |
| READ_ONLY independiente | `42250420345` | `success` |

La ruta de retiro histórico de imagen **no se reasigna** y mantiene
`42236673419`/`42217108000`/`42237830418`. Ambas verifican que los tres
runs del grupo pertenezcan al actor/repo/evento previstos y compartan SHA,
y que el nuevo workflow se ejecute solo en `main` con SHA exacto y primer
attempt. La salida segura sigue siendo NO_GO ante drift o ACK ausente.

## Extensión R51 — tercer incidente #750, después de recuperar #740

**Estado: CANDIDATO CODE_ONLY, sin limpieza física ni autorización de reintento.**
El PREPARE [#748](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42262494064)
(`42262494064`) pasó en `main=96cd69518488e9dabdec9af15c50915e6b4c136e`.
El APPLY [#750](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42266188095)
superó el GO_B pero su única transacción SSH terminó con salida 3 y sin
recibo físico ACCEPTED. La reconciliación READ_ONLY
[#752](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42267016352)
comprobó intención y terminal `NO_GO` durables, `original_restored=true`,
`commit_started=false`, un único controlador original `healthy` y
publicado solo en `127.0.0.1:8443`, sin candidato ni worker. La Stage raíz
tiene dos entradas tras el fallo, compatible con el directorio creado por el
propio intento. **No está demostrado que el Stage haya causado el rechazo.**
El marcador preparado `UNREADABLE/DIRECTORY` refleja la imposibilidad del
observador de validar la identidad de un volumen rootless desde el host,
no la inexistencia del GO. Docker cleanup sigue `INDETERMINATE`, con una
imagen antigua de procedencia insuficiente; no se borró.

Esta enmienda actualiza exclusivamente los tres IDs de la recuperación
Stage ya revisada, preservando la ruta separada de retiro histórico:

| Rol | Run nuevo | Estado exigido |
| --- | --- | --- |
| Incidente Cutover A a recuperar | `42266188095` | `failure` |
| PREPARE que autorizó aquel APPLY | `42262494064` | `success` |
| READ_ONLY posterior independiente | `42267016352` | `success` |

Un solo nuevo PR y su SHA exacto deben validar estos pins con los tests
`test_cutover_a_repair_workflow_r47.py` y los de recuperación. La ejecución
protegida de Stage solo puede borrar el directorio exacto si sus marcadores,
hashes y Compose son autenticados bajo lease, confirma ausencia de transición
irreversible y verifica el mismo runtime antes/después. Si falla, conserva
Stage y da NO_GO. Tras ACK `STAGE_CLEARED`, verificar la postcondición con
nuevo observador; **no repetir APPLY #750**.

La reconciliación #752 también midió 3.370.577.920 bytes libres, frente a
4.294.967.296 bytes de admisión previa al primer `docker pull` dual. La
falta de 924.389.376 bytes (aprox. 882 MiB) es un bloqueo para un
**intento nuevo bajo la política vigente**, pero no prueba el motivo
histórico del exit3. No hacer `prune` de Docker, tocar otros servicios ni
reducir la protección de datos, clave, owner o imagen activa.

**RCA pendiente:** #741 no identifica si la salida 3 ocurrió durante
Compose staging, pull GHCR, validación de imagen/capacidad o preparación del
worker. La presencia del Stage y ausencia de worker acotan el intervalo,
pero no prueban un fallo de descarga. Además, `UNREADABLE/DIRECTORY` en
el observador del GO marker significa que el **directorio padre** no pasó
su comprobación de UID/mode host (`host_cutover_postapply_reconcile.py`),
no que el marker tenga tipo directorio; el UID 175536 observado en el host
es compatible con el mapeo rootless de UID 10001 dentro del container.
No efectuar chmod/chown sobre el volumen ni consumir otra vez ese PREPARE.
El inventario clasifica una imagen histórica sin referencias como incierta;
la limpieza separada exige procedencia positiva y no se fusiona con Stage.

Esta extensión es **CODE_ONLY hasta PR/CI/merge/recibo del host**. Un stage
eliminado tampoco autoriza un segundo APPLY: antes debe investigarse la
causa inicial y producir nuevo release/PREPARE/GO de SHA exacto. Fuera de
alcance: BLACKBOX, servicios/volúmenes ajenos, backups, órdenes, puertos y
Docker prune global.

## Extensión R53 — cuarto incidente #757, Stage sin commit

**Contexto físico verificado:** el Stage del incidente #750 fue saneado
mediante [recuperación #754](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42269139909)
con `STAGE_CLEARED` y ACK físico; el observador
[#755](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42269530227)
corroboró `stage=ABSENT` y una sola entrada raíz. El nuevo release dual
[#698](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42269631510)
publicó ambos digests para `main=70f374e273093007319b007e7ca22aff7cb75c4f`.
PREPARE [#756](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42270247581)
culminó exitosamente; la variable independiente de Environment se vinculó
al digest `2390f22bf62bb4f451324ed34487262e9838d3585df8984eff00145b78f38360`.
El APPLY [#757](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42270552485)
validó dicho GO, pero SSH retornó 3 y no hubo recibo terminal ACCEPTED.
**Prohibido reintentar el run #757**.

El observador READ_ONLY independiente
[#758](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42270841732)
verificó `stage=PRESENT` (`root_entries_count=2`), `commit_started=false`,
`promotion_intent=ABSENT`, `promotion_result=ABSENT`, un único controlador
original en ejecución y sano, cero candidatos, cero workers, puerto
`127.0.0.1:8443` y cero efectos extranjeros. `go_for_retry=false` aplica
al intento antiguo, no autoriza reintentar. `prepared_go_marker=UNREADABLE/DIRECTORY`
refleja el límite de visibilidad host/rootless documentado, no demuestra
ausencia del marcador.

| Vinculación inmutable R53 | Run ID | Conclusión |
| --- | --- | --- |
| Incidente #757 | `42270552485` | `failure` |
| PREPARE #756 | `42270247581` | `success` |
| Observación física #758 | `42270841732` | `success` |

Actualizar exclusivamente los tres pins de la recuperación Stage bajo
lease y los chequeos existentes de actor/SHA/primer intento/ACK. La ruta de
retiro histórico de imagen mantiene sus pins distintos. El cambio R53
**no contiene operaciones de limpieza de disco**; el usuario confirmó un
frente separado. Se observaron 3.370.475.520 bytes frente al piso de
admisión de 4 GiB, compatible con una negativa de pre-pull, pero la causa
histórica de `exit3` no está probada por esa coincidencia.

Hasta el ACK físico de la recuperación, Stage permanece en cuarentena.
Después será necesario release/PREPARE/GO_B nuevos del SHA exacto de
`main` para un intento distinto, sin reutilizar PREPARE #756 ni APPLY #757.
No tocar blackbox, otros servicios, backups o Docker global.

## Extensión R55 — quinto incidente #763, recuperación unitaria exacta

**Estado de este cambio: candidato CODE_ONLY, no equivale a recuperación
física.** La recuperación protegida del Stage del incidente #757
[#760](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42273287046)
finalizó con `STAGE_CLEARED`, `physical_ACK=ACCEPT`, cero escrituras Docker y
Compose inalterado. El observador posterior
[#761](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42273489927)
verificó `stage=ABSENT` y el original sano en loopback 8443.

La pareja inmutable [Image Release #700](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42273375991)
corresponde al `main=bc2d31669da5f360a659de896041ac3619ce2ce9`.
PREPARE [#762](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42274019739)
pasó sin escrituras Docker y quedó ligado al GO_B independiente SHA256
`f8291f8d9033fc4bf83ef22649f27db1c1b1afd588d4ed55790c00571a1689d7`,
actualizado en Environment. El APPLY [#763](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42274349061)
superó el GO, pero el SSH remoto terminó con código 3 sin ACK final.
**No se instaló la BETA nueva y no está permitido reintentar #763.**

El observer READ_ONLY independiente
[#764](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42274552585)
vio intent/result presentes, terminal `NO_GO`, cleanup `INDETERMINATE`,
`stage=PRESENT`, dos entradas en la raíz, `commit_started=false`, promoción
ausente, cero workers/candidatos, un solo legacy CID
`27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793`
sano y publicado solo en `127.0.0.1:8443`. Ningún recurso extraño fue
tocado. El conteo de Stage no basta para autorizar unlink: siguen siendo
obligatorios marker, digests, root identidad, observaciones estables y lease.

| Vinculación inmutable R55 | Run ID | Resultado verificado |
| --- | --- | --- |
| Incidente #763 | `42274349061` | `failure` |
| PREPARE #762 | `42274019739` | `success` |
| READ_ONLY posterior #764 | `42274552585` | `success` |

Este PR cambia únicamente los tres pins de la ruta existente de recuperación
Stage, sus aserciones de regresión y esta evidencia documental. **No** cambia
los pins ni la ruta de retiro histórico de imágenes, no levanta reservas de
almacenamiento ni ejecuta ningún cleanup Docker. La limpieza de disco está
delegada explícitamente a otro frente. La medición de bytes libres describe
el host, pero **no prueba** la fase exacta que produjo `exit3` por SSH.
Después del merge, la operación protegida solo podrá ejecutarse una vez
contra estos IDs; debe exigir ACK `STAGE_CLEARED` físico y observación
posterior. Una recuperación satisfactoria tampoco reutiliza GO_B/APPLY #763:
una instalación distinta necesita release/PREPARE/GO por SHA exacto nuevos.

## Extensión R57 — sexto incidente #770, Stage no comprometido

**Estado: CANDIDATO CODE_ONLY; no hay limpieza física atribuible a este cambio.**
La recuperación Stage de #763 se ejecutó por #766 y fue comprobada por
#767 con `stage=ABSENT`; no repetirla. El GO_B PREPARE
[#768](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42277201326)
terminó `success` para un intento distinto, pero el APPLY protegido
[#770](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42307268117)
terminó `failure`, SSH remoto 3 y sin ACK terminal aceptado.

El READ_ONLY independiente
[#771](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42307426818)
comprobó `stage=PRESENT`, `root_entries_count=2`,
`commit_started=false`, sin promoción, cero candidato y worker, original
legacy `27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793`
healthy en `127.0.0.1:8443` y recursos ajenos preservados. La causa
exacta de la salida 3 no se prueba mediante el conteo de Stage.

| Vinculación inmutable R57 | Run ID | Estado exigido |
| --- | --- | --- |
| Incidente Cutover #770 | `42307268117` | `failure` |
| PREPARE #768 | `42277201326` | `success` |
| READ_ONLY #771 | `42307426818` | `success` |

Únicamente se reasignan los pins de recuperación Stage en
`.github/workflows/boca-first-deploy.yml`, sin modificar los pins de
`cutover-a-image-retire` ni su ruta histórica. Se reutilizan el lease,
las verificaciones independientes de runs/SHA/actor y de Stage por identidad,
marker y hashes, así como verificación posterior/ACK; ante cualquier drift,
retener Stage y devolver NO_GO. Un Stage saneado **no habilita** repetir el
APPLY #770 ni consumir otra vez PREPARE #768: corresponde un futuro
release/PREPARE/GO_B de `main` exacto. La limpieza de disco la ejecuta otro
frente; aquí no hay Docker writes, cambios de umbral ni efectos físicos.

## Extensión R62 — Cutover #778, disco ampliado y fase durable observable

El droplet fue reiniciado/ampliado por un frente independiente. En Boca no
se repitió limpieza. Release dual #704 (run `42309505084`) y PREPARE
#776 (run `42309967399`) son `SUCCESS` para el
`main=a8b577161288fe653fef65d3d5890f3661fb15d4`. El GO_B exacto
protegido validó el digest
`27c24d339110241992c23fbbc8d443957cdf146af37e4b300e2341594fe5a89f`
en APPLY #778 (run `42317092809`), que terminó con salida SSH 3 y
**sin** ACK `ACCEPTED`. No se repite #778.

El READ_ONLY #779 (run `42317342897`) verificó: `stage=PRESENT`
con `root_entries_count=2`/`STAGE_ROOT_ENTRIES`, intent/result durables,
terminal `NO_GO`, cleanup `INDETERMINATE`, original restaurado,
`commit_started=false`, cero candidato/worker y promoción ausente;
único controller `27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793`
`healthy` en `127.0.0.1:8443`; libre 39.770.513.408 B / 7.437.094
inodos. `UNREADABLE/DIRECTORY` del marker es una verificación fallida
del directorio **padre** mapeado del volumen, no prueba sobre el marker.

| Rol Stage R62 | Run exacto | Verificación |
| --- | --- | --- |
| Cutover fallido #778 | `42317092809` | `failure` |
| PREPARE #776 | `42309967399` | `success` |
| READ_ONLY posterior #779 | `42317342897` | `success` |

Cambio exclusivo de pins en `cutover-a-stage-recover`, conservando todos
los checks preexistentes: actor/main/primer intento, mismo SHA entre
tres runs, dos observaciones estables, identidad de Stage, marker,
Compose inode/SHA, lease exclusivo, unlink exacto y ACK bajo una sola SSH.
No cambiar el retiro histórico de imagen ni ejecutarlo: su intento
#746 (run `42261978336`) ya falló sin ACK, el objeto permanece
`retained_uncertain` y no puede ser eliminado por inferencia.

El observer `host_cutover_postapply_reconcile.py` amplía su recibo
READ_ONLY con `worker_id_recorded` y `candidate_id_recorded`:
dos booleanos `true/false` (o `null` sin resultado) derivados de los
IDs ya autenticados del resultado persistente. Distinguen si un worker y
un candidato fueron **registrados antes de la compensación**; no dicen
por qué falló una fase ni exponen IDs de contenedores. Regresión
con resultados de fase 0/1/2, sin comandos Docker de escritura.
Un resultado `false/false` acota el intervalo a staging/preparación
de worker; `true/false` a posterior a worker y anterior a candidato;
`true/true` a posterior a ambos. Ninguna de esas inferencias por sí
sola demuestra el RCA de `exit 3`.

Hasta SHA exacto CI verde, revisión técnica, merge y único ACK
`STAGE_CLEARED`, esta modificación es CODE_ONLY. Tras sanear Stage,
el nuevo Cutover requiere release+PREPARE+GO_B **nuevos** y diagnóstico
del stopper funcional, no repetir #778. No afectar BLACKBOX,
otros Docker/Porota, datos ni puerto 8443, ni ejecutar navegación real.

## R68 — RCA del pipeline y diagnóstico de Cutover (06/11/2026 ART; CODE_ONLY)

El Stage del incidente #778 fue recuperado por #788 y observado ABSENT por
#789. El controller legacy permaneció sano. **No** conservar la instrucción
histórica de R62 como si Stage continuara en cuarentena.

Los APPLY #763/#770/#778 terminaron en el mismo SSH, con 19/14/77 s dentro
de esa fase. El código 3 de `host_boca_cutover_cli.run_cli` significa
`NO_GO` genérico, no prueba corte de SSH ni causa Docker. La fase original
(Stage, pull GHCR, create/start/health del worker o compensación) sigue
INDETERMINADA. Dos defectos **sí** quedaron evidenciados:

1. El runner `boca-first-deploy.yml` abortaba por `set -e` al recibir rc3,
   sin clasificar/publicar el contenido redaccionado del stdout, mientras
   descartaba deliberadamente stderr para evitar exfiltración de secretos.
2. `check_cutover_a_go.py --assert-host-receipt` imprimía
   `host=untouched` si faltaba el ACK, aunque el host podía haber iniciado
   un Stage/worker reversible. La frase solo es válida ANTES de SSH.

**Cambio candidato R68:** mantener código de salida remoto original, recibo
positivo con verificación exacta y resultado rojo ante fallos; añadir una
clasificación runner de `ssh_rc`, `TIMEOUT/SSH_255/EXIT_NONZERO` y afirmación
allowlist de CLI (nunca texto bruto ni owner/secretos). Ante falta de ACK,
`host=UNVERIFIED`; el claim remoto NO acredita resultado durable ni
compromiso irreversible. Las pruebas adversariales deben impedir que un
stdout inventado transforme un exit3 en verde. Esta primera fase hace
diagnosticable el **tipo de retorno**; todavía **NO instrumenta la fase
interna de Stage/pull/health**, por lo que no autoriza nuevo APPLY hasta
completar un preflight rootless inocuo, con recibos exactos.

**Cuello de botella medido:** #412 ejecutó cuatro workflows PR sobre el mismo
SHA, reconstruyendo `Dockerfile.browser` cuatro veces (~295 s acumulados).
Camino crítico de PR ~204 s; release manual #704 ~179 s, PREPARE #776 ~25 s,
Cutover fallido #778 ~93 s. Separación PREPARE→APPLY ~65m22s, no
atribuible exclusivamente a CI. Existe un workflow de 3611 líneas y 45
operaciones; separar lógica de validación por reusable workflow manteniendo
un único workflow físico es una propuesta P1, no una modificación R68.
Los guards de seguridad no causan las cuatro reconstrucciones redundantes.

**Plan de validación adicional:** pruebas de error/fase sin host, verify SSH
runtime con recibo sanitizado y chequeo final original/volúmenes/8443, después
preflight reversible rootless de digests y worker. Sólo entonces release
congelado + nuevo PREPARE/GO_B + un único APPLY. Sin desplegar BLACKBOX ni
navegar Boca; cero cambios sobre Porota, otras aplicaciones o Docker host.
Véase #45 R67/R68. Los indicadores R68 son propuestos hasta SHA/Actions verdes.

## R70 — Etapa de fallo informativa, sin levantar las barreras de Cutover

Los #763/#770/#778 devuelven `exit=3` sin identificar por sí mismos si la
falla fue SSH, GHCR, rootless Docker, staging, worker o salud. Desde el
PR #413 ya fusionado, el runner distingue exit/no-ACK y evita declarar
`host=untouched` después de intentar SSH. **El RCA físico sigue abierto.**

R70 agrega `failed_phase` **solo al recibo de transacción en memoria**:
`ATTEST_ORIGINAL`, `CONSUME_PREPARE`, `STAGE`, `PREPARE_WORKER`,
`PARK_ORIGINAL`, `BOOTSTRAP_SESSION`, `ACTIVATE_CANDIDATE`,
`ACCEPT_CANDIDATE`, `RETIRE_ORIGINAL`, `FINALIZE`. En retornos normales
NO_GO el CLI publica exclusivamente la fase allowlist, sin divulgar la
excepción, la identidad del owner o los datos. El runner la conserva como
`phase_claim`, nunca como recibo terminal autenticado. Si falta SSH, el ACK
o el formato exacto, `phase_claim=UNVERIFIED` y el trabajo permanece rojo.
La línea positiva ACK permanece **byte a byte idéntica** y el esquema del
recibo durable v1, la transacción, GO, lease, puerto y cleanup no cambian.

Limitación explícita: ante caída física antes del retorno, la fase todavía
puede ser desconocida porque no se escribe un checkpoint de fase durable.
Un backend de recibos por etapas requerirá revisión separada. **No repetir
APPLY** antes de una comprobación rootless/worker inocua y evidencia física
actual. Los tests agregados ejercitan falla por etapa, falsificaciones y
no conversión de NO_GO en ACCEPTED.

Para acelerar CI, la imagen browser full ocupa ~2,7 GB lógicos según
benchmark del repo; no habilitar sin medición una exportación masiva de cache
remota en cuatro pipelines. El próximo experimento debe cronometrar frío y
caliente, probar almacenamiento y separar caches de PR vs main; mantener
todos los scans y los controles obligatorios.

**Incidente de CI detectado en R70:** el PR #414, SHA inicial
`591404c42889fc3c0ff260c93d3f5157617022dd`, tuvo tres workflows
verdes pero falló `CI #42324715791` en
`test_owner_readonly_snapshot_is_accepted_without_a_write`. La causa
concreta está en el test: comparaba `os.stat_result` completo, incluyendo
`st_atime`; una lectura legítima puede actualizar ese timestamp según el
montaje Linux sin escribir/modificar el archivo. La implementación
`official_snapshot._identity` ya excluía `atime` correctamente. Se ajustan
dos aserciones del mismo módulo para comparar identidad, modo, tamaño, inode,
propietario y nanosegundos de `mtime/ctime`, preservando la detección de
escrituras reales. Este defecto de test es ajeno al fallo físico de Cutover;
se clasifica como falsa alarma dependiente del filesystem, no como motivo
para relajar el gate de calidad.
