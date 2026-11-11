# ADR0232 — R178: PLAN sin efectos para actualizar el par Boca instalado

Fecha: 2026-11-11 (ART). Issue #417. Estado: **CODE_ONLY, NO_GO para APPLY**.
Base local de diseño: `main` R177 `bcabf499`, con evidencia física
[`boca-pair-observe` #43066120206](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43066120206).

## Decisión y evidencia

El censo físico #43058130210 confirmó **un controller y un browser-worker**
en el daemon rootless dedicado. El Cutover histórico #42806447101 registró
`IDLE_INSTALLED`, pero nunca probó la activación física del bot. El antiguo
`cutover-a-apply` falla en `LEGACY_SINGLETON` porque su admisión exige un
único contenedor sin worker. Es un rechazo correcto del **flujo equivocado**
para una instalación dual; no justifica suprimir la guarda.

La observación física R177 #43066120206 identificó sin escrituras en host el
controller exacto `cc489d7010b2ddd1307086422bf28553f06348939bc33d0344a84dbb4c3d63c4`
RUNNING, healthy y PID1133025, junto al worker exacto
`a3293c4e48c4ee11b52749fdd64a33e50fa2ac0805cbf64ce7e6028d86520033`
**EXITED, ExitCode=1, PID=0, unhealthy y red `none`**. El origen histórico
de ambos es SHA `03df9a14bdd78cf768386a865876fed9d5656911` del intento
#42806447101. El controller conserva el puerto 127.0.0.1:8443 y volúmenes
de data, key, owner e IPC; el worker conserva solamente IPC. Un worker
EXITED=1 no equivale a un worker CREATED ni a una prueba de funcionamiento:
hay que investigar el error 1 y no reintentar START automáticamente.

Los CIDs e IDs de imágenes son **observación física en aquel instante**,
no identidad duradera de la instalación. Todavía faltan evidencias físicas
del binding systemd, inode SQLite, red de salida del worker actualizado y
release destino. El recibo R177 no contiene Env, Mounts crudos, tokens,
datos de socios ni contenido de SQLite.

## Por qué no usar `docker compose up --force-recreate`

Una recreación por proyecto/nombre no ata cada cambio a un CID auténtico;
puede reemplazar los dos contenedores sin un journal de recuperación, dejar
activa una unidad systemd que señala el `installation_run_id` anterior o
abrir un intervalo con el puerto 8443 libre/ocupado ambiguamente. Tampoco
cumple el retiro diferido de los dos CIDs históricos ni la limpieza por
identidad positiva. No se usará Compose directamente para mutar la pila:
solo se reutilizará para calcular/verificar su configuración, hashes y
montajes bajo la misma transacción futura.

## PLAN R178 implementado y sus límites

El módulo `host_boca_pair_upgrade_plan.py` **no importa ningún ejecutor
Docker/systemd ni obtiene lease**. Recibe el recibo R177 canónico, verifica
sus campos mediante el parser R177 y exige:

- exactly 1 controller RUNNING/healthy y 1 worker con PID=0
  (CREATED o EXITED con ExitCode=1 **solo** para la identidad histórica
  probada por R177);
- red privada dedicada del controller y red `none` **solo** para el worker
  histórico EXITED=1; el futuro worker requiere egress comprobado;
- IPC en ambos servicios, los cuatro volúmenes protegidos en controller,
  worker sin acceso a datos/clave/owner;
- nuevo SHA distinto, digests GHCR por rol, IDs de run sintácticamente
  válidos y ausencia de reuse/replay de los runs conocidos.

Emite `BOCA_DUAL_UPGRADE_PLAN`, con CIDs/imágenes viejos y SHA/digests nuevos,
pero **siempre** `state=CODE_ONLY_HOST_PROOF_PENDING`, `docker_writes=0`,
`host_binding=UNVERIFIED`, `database_inode=UNVERIFIED`,
`release_provenance=RUNNER_VERIFICATION_REQUIRED`,
`candidate_cids=UNCREATED`, `apply_authorized=false`. El parser rechaza
cualquier mutación del último campo o intento de convertirlo en GO. No se
agregó selector effectful a GitHub Actions, no se realizó SSH ni Docker.
El PID=0 del worker está acreditado **solamente en el recibo histórico**;
el PLAN marca `worker_pid0=OBSERVED_HISTORICAL`, nunca lo convierte en
garantía del estado actual. La respuesta del socket IPC y conexión HTTP
efectiva tampoco se infieren del binding Docker. Por ello el PLAN conserva
`ipc_socket_handshake` y `panel_live_http` en `UNVERIFIED` hasta pruebas
físicas independientes, y `target_egress_bridge=UNVERIFIED`.
Una llamada de Python con valores válidos no autentica por sí sola una
release ni un recibo físico: ambos necesitan la verificación independiente
de GitHub y del host.

## Diseño de implementación posterior, aún NO aplicado

Un único `workflow_dispatch` **dentro de** `boca-first-deploy`, desde main,
titular, attempt=1, Environment protegido, PR0, CI exact-SHA, release dual
verificada por manifests auténticos. Nunca segundo workflow, deploy por push
ni permisos de host global. Su operación futura será `boca-pair-upgrade`;
este nombre no existe todavía en el formulario.

1. **Admisión y lectura bajo un solo lease rootless UID/GID10001.** Verificar
   el digest del paquete SHA256/memfd y reobservación completa R177 de los
   CIDs que el runner autenticó, sin inferencias de nombres; controller
   healthy en 127.0.0.1:8443, worker PID=0/detenido y engine STOPPED.
   `read_installed_binding(lease)` debe coincidir exactamente con ambos CIDs,
   imágenes, SHA e intento anterior, y con las unidades systemd cargadas.
   Las rutas de montaje de datos y control socket, volumen URL, seccomp,
   permisos, UID/GID, red/puerto y device/inode SQLite deben verificarse
   desde ese mismo namespace. Si hay otro contenedor/servicio, binding
   ausente, Stage inseguro o deriva, NO_GO antes del primer efecto.
2. **Preparación sin interrupción.** Verificar espacio/inodos Boca; pull
   de los dos digests destino y procedencia OCI; stage exacto de Compose,
   overlay, seccomp y URL-only volume; calcular hashes nuevos para ambos
   servicios. Prohibido importar/configurar live site, Telegram sender o
   reservas. Durability journal O_EXCL/fsync con ambos IDs actuales,
   digests/paths cifrados solo por referencia, estados y condición de
   compensación **antes** de abrir fase con efectos.
3. **Quiesce y park reversible de ambos CID exactos.** Cerrar admisión
   socket/activación del worker vía sus unidades Boca verificadas, aguardar
   no ejecución, verificar engine STOPPED y worker PID0. Detener por **CID
   exacto** únicamente el controller Boca (ACK mismo CID); estacionar y
   renombrar por ambos CIDs exactos a nombres temporales del intento,
   sin borrar. No usar nombres/globs ni tocar otros Docker. Un worker que
   estuviera activo bloquea la operación hasta STOP autorizado por dueño.
4. **Crear y aceptar candidatos.** Crear worker nuevo inactivo y controller
   nuevo con los nombres canónicos liberados, usando exactamente los
   volúmenes persistentes validados; no duplicar SQLite, clave, passkey o
   puerto. Comprobar worker PID0, misma identidad device/inode SQLite,
   engine STOPPED, controller healthy, único 127.0.0.1:8443, aislamiento
   redes/UID, IPC, configuración SITE_URL solo lectura y ausencia de sender.
   Reiniciar **solo** el controller candidato una vez y repetir pruebas.
5. **Binding systemd transaccional.** `install_control()` no reemplaza
   instalaciones anteriores y `remove_control()` no puede borrar un binding
   de otro intento. Se necesita un primitivo nuevo, estrecho y reversible:
   comparar bytes/inode/unidades viejas, registrar el binding anterior en
   journal privado protegido, instalar unidades/plan nuevos con fsync y
   recarga del user manager; verificar socket listening y par nuevo exacto,
   rollback de todos los fragmentos anteriores ante fallo. No usar una
   desinstalación simple que borre el socket anterior antes de tener
   capacidad de restaurarlo.
6. **Commit/retire y limpieza postflight.** Registrar ACCEPT O_EXCL/fsync
   antes del primer retiro irreversible. Retirar por sus dos **CIDs antiguos
   exactos** únicamente después de reconciliar ambos hashes/imagenes y
   la aceptación, nunca utilizando el planner genérico de cleanup, que
   restringe `retire_containers` al attempt **nuevo**. Conservar datos,
   clave, owner, IPC y configuración; retirar imágenes Boca inactivas solo
   si no tienen referencias en ningún contenedor y se verifica cada ID,
   con excepción histórica R108 exacta. Medir disco/inodos antes/después;
   terminal ACK y limpieza Boca-only completa bajo el mismo lease.

### Estados de fallo y recuperación

| Momento | Acción segura | Resultado |
|---|---|---|
| Antes de quiesce | Sin modificaciones; conservar par actual | `NO_GO` |
| Entre park y commit | Retirar candidatos **solo si IDs/procedencia inequívocos**; devolver nombres, CIDs y binding antiguos; restaurar controller, health y motor STOPPED; preservar worker idle | `RECOVERED/NO_GO` si TODO verificado |
| Cualquier ACK o identidad incierta | Conservar todos los recursos e historial, bloquear retry automático y requerir censo nuevo | `INDETERMINATE` |
| Después de ACCEPT O_EXCL | Nunca reactivar viejos en paralelo; terminar retiro/cleanup exacto o solicitar recuperación especializada | `NO_GO/INDETERMINATE` hasta ACK |

La coexistencia temporal de **cuatro CIDs Boca** en una fase atestada es
compatible con la transacción, pero el observador estricto R177 de
**exactamente dos** se invoca solo antes de quiesce y después del retiro
aceptado. Durante transición se requiere un observador especializado
cuádruple limitado a los cuatro IDs del journal, no relajar el censo
general ni la exclusión de recursos ajenos.

## Tests exigidos antes de cualquier operación effectful

- Recibo R177 genuino de GitHub Actions, release dual y manifest con SHA
  exacto, role/digest e historial anti-replay autenticado.
- Pruebas offline RED→GREEN de PLAN con par sano, worker activo, IPC
  parcial, red compartida, volumen ausente, SHA repetido, token/manifiesto
  adulterado y ausencia total de llamadas Docker.
- Laboratorio de failpoints **en cada transición** de binding/systemd,
  stop, rename, create, health, journal y cleanup, incluyendo pérdida
  de SSH/cancelación. Nunca compensar por nombre amplio.
- Prueba desechable de `install_control`/`replace_control` sobre unidades
  de usuario simuladas, y de aceptación de UID10001/10002, `SO_PEERCRED`,
  worker idle y continuidad de SQLite.
- Solo tras PR/CI exact-SHA, revisión y Action protegida con recibos
  físicos se podrá evaluar `boca-pair-upgrade` y aceptación Chrome.

**Decisión R178:** PLAN CODE_ONLY sí; APPLY/rollout/despliegue físico
**NO_GO** pese a la identidad del par probada por R177: aún falta
el binding systemd, el inode SQLite, diagnosticar EXIT=1, la procedencia
de la release nueva y construir/verificar la transacción bajo lease.
