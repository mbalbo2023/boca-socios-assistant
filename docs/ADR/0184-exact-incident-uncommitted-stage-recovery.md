# ADR 0184 — Boca Cutover A: recuperación de Stage abandonado con identidad exacta

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
