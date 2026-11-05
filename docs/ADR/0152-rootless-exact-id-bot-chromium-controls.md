# ADR 0152 — Adaptador rootless de controles reales bot/Chromium (#328)

Fecha: 2026-11-05 ART. Estado: **DRAFT / CODE-ONLY / host NO_GO**.

Ownership: sólo `src/boca_socios/host_lifecycle_rootless_adapter.py`,
`tests/test_host_lifecycle_rootless_adapter.py` y este ADR. La integración
canónica es el candidato DRAFT #319 (A45-R21.7). No se modifica la
implementación BLACKBOX del navegador ni los archivos de runtime o workflow
que pertenecen a otros agentes.

## RCA funcional y decisión

El panel ya conserva `REQUESTED` de `bot` o `chromium` en el ledger SQLite,
pero un botón y una solicitud guardada no son una operación física. El
contrato `host_boca_lifecycle.py` dispone de `CLAIMED`/`UNCERTAIN`/`ACK`
independientes y el motor sintético admite `status/start/stop` por AF_UNIX
dentro del controller. Faltaba el adaptador que **observa identidades de
Docker/estado real, ejecuta sólo una acción sobre el ID correcto y verifica
el resultado**. Sin él los controles no deben presentarse como activos en
Samsung Chrome.

El nuevo `RootlessLifecycleProbe` usa un transporte Docker inyectable. Su
implementación productiva delega en el **único daemon Docker rootless del
UID/GID 10001 de Boca**, con socket y argv fijos de
`host_boca_cleanup`. Inventaría ese daemon, rechaza recursos ajenos o
residuales, exige los dos IDs de instalación (`controller`, `browser-worker`)
y, cuando existe sender Telegram, un tercer ID y su binding revisado. Coteja:

- `source_sha`, imagen GHCR por **RepoDigest** exacto y asociación con el
  ID de imagen observado en el contenedor; hashes Docker y referencias OCI
  se tratan como objetos distintos.
- Intento de instalación original y dos `com.docker.compose.config-hash`
  revisados e independientes, nunca deducidos de etiquetas no confiables.
- Labels Compose, usuarios 10001/10002, volúmenes y sus mounts exactos,
  exclusividad de `boca_data` **dentro del grupo Boca autorizado y enumerado**
  (controller y sender, cuando exista), red del worker `none`, controlador
  en la única bridge Boca y puerto sólo `127.0.0.1:8443`.
- `restart: no`, límites de inspección, init, read-only, ausencia de
  `Privileged`, ausencia de puertos publicados extra y salud real del
  controller/worker. El estado del motor se consulta además con un
  `docker exec` **sólo dentro del ID exacto del controller** usando el
  cliente AF_UNIX de la aplicación, sin importar la caja negra.

La **variante explícita de tres servicios** admite sender Telegram OFF u ON
solamente si se proporcionan por separado su ID inmutable, configuración
Compose hash, intento de runtime Telegram y estado esperado. Se atestan su
imagen GHCR, usuario 10001, mounts sólo de `boca_data` y `boca_telegram`,
red `boca-socios_telegram_egress` con los endpoints esperados según su estado
y ausencia de puertos publicados. El sender no recibe Start/Stop de estos
controles; su identidad y estado se revalidan antes y después. Un contenedor
RUNNING no demuestra emparejamiento, custodia ni entrega Bot API: esas pruebas
dependen de #315 y su transacción protegida propia.

`execute_requested_lifecycle()` es un componente de biblioteca **sin
entrypoint ni dispatch**. Un futuro único workflow Boca, con aprobación
independiente y lease canónico, podrá invocarlo tras validar previamente el
release y la solicitud actual. Primero persiste `CLAIMED`, después ejecuta
una sola acción, vuelve a observar identidad+estado y por último registra
un `APPLIED` verificable. Si el estado ya coincidía se registra `REFUSED`
sin efecto; si el efecto pudo ocurrir pero el recibo es ambiguo se conserva
`UNCERTAIN` y **no hay retry automático**.

Para `bot/start` y `bot/stop` el efecto es únicamente
`docker exec --user 10001:10001 <ID_controller> python -m
boca_socios.integration.engine_socket <start|stop>`; no reinicia ni detiene
el proceso HTTP, no crea un puerto y no toca el daemon externo. Para
`chromium/start` o `chromium/stop` se usa únicamente
`docker start|stop <ID_worker>` sin Compose `up`, recreación, pull ni borrado
de contenedores. Antes de detener Chromium debe estar confirmado el motor
del bot en STOPPED; el ACK vuelve a comprobar que el controller y el panel
HTTP siguen vivos y saludables. Un `bot/start` exige además el worker
RUNNING+HEALTHY, conforme a ADR0146.

## RCA adicional reproducido: imagen Docker no es manifest digest

Una primera aserción de prueba asumía erróneamente que
`docker inspect container .Image` es igual al SHA256 de
`ghcr.io/...@sha256:...`. En realidad el primero es el **config image ID**,
mientras el segundo identifica el manifiesto publicado. Sus hashes pueden
ser diferentes aun para la misma imagen correcta. La matriz test-first
fijó deliberadamente IDs distintos y exige verificar que el config ID
pertenece a una imagen cuya lista de `RepoDigests` contiene exactamente la
referencia GHCR aprobada y cuya procedencia es Boca. Así se evita un falso
`NO_GO` permanente por comparación de objetos distintos y un falso
`ACCEPT` por inferencia de nombres.

## Riesgo, límites de evidencia y pendientes P0

1. Este PR **no cablea** `.github/workflows/boca-first-deploy.yml`, no
   ejecuta `workflow_dispatch`, no abre SSH y no realiza acciones en el
   droplet. Las pruebas usan sólo Docker inyectado y una base SQLite
   temporal. Sus recibos no son prueba de disponibilidad física.
2. El modo de operación admite el par controller/worker y su variante con
   sender Telegram OFF u ON. Un tercero sin binding de ID, runtime, config
   hash, red y mounts es `NO_GO`. El sender nunca recibe Start/Stop del
   panel bot/Chromium y su presencia no certifica Telegram operativo. Un
   worker RUNNING pero UNHEALTHY bloquea `bot/start` y `chromium/start`,
   pero **no** `bot/stop` ni `chromium/stop`: el STOP del worker usa el
   estado físico RUNNING aunque su healthcheck esté degradado, siempre que
   el bot ya esté STOPPED, controller HEALTHY y toda identidad/mount/lease
   coincida. Un worker ya STOPPED tampoco bloquea detener el bot; no se baja
   Chromium con el bot todavía RUNNING.
3. **Persistencia STOP del bot tras reinicio completo del controller:**
   sigue P0. Hoy el hilo sintético puede recrearse por el boot legacy; el
   workflow físico no debe usar el adaptador hasta resolver una política
   durable de restauración de STOP sin migrar la SQLite legacy a 0008.
4. La integración de `REQUESTED`→Actions protegida y la obtención de
   `ReviewedInstalledPair` desde dos manifests GHCR y Compose originales
   son pendientes P0; la mera existencia de este código no autoriza
   instalación ni operación. `LifecycleDockerIO` inyectado en tests no
   otorga autoridad productiva. Un host de terceros nunca es un fallback.
5. La seguridad adicional queda P2 hoy por orden de Tincho; ello no relaja
   la segregación mínima de Boca respecto de Porota ni la prohibición de
   tocar el sitio real, credenciales, backups, puertos o BLACKBOX.

## QA y recepción de la propuesta

La matriz sintética nueva comprueba inventario original/cambios adversariales,
UID, etiquetas/release, config hash, manifest digest diferente del image ID,
volumen, puertos, mounts, red, salud, sender OFF/ON exacto y preservado,
protección del panel al detener sólo
Chromium, denegación de ese STOP con bot activo, start/stop efectivo del
motor por ID exacto, una sola invocación Docker y estados SQLite reales
`REQUESTED`→`CLAIMED`→`APPLIED|REFUSED|UNCERTAIN` sin schema 0008.

Antes del merge se documentarán en el PR y en los issues #328/#45:
SHA/tree exactos, número total de pruebas, Ruff/format/MyPy/política,
GitHub Actions con sus runs y límites físicos. **Ningún GREEN de una rama
anterior certifica esta propuesta ni equivale a GO para el droplet.**

## RCA P0, 05/11 — Chromium STOP frente a healthcheck degradado (#351)

La regresión funcional original era doble: el `RootlessLifecycleProbe`
rechazaba a todo Chromium RUNNING+UNHEALTHY incluso para detenerlo, y
`LifecycleHostSnapshot.require()` confundía `RUNNING=true, HEALTHY=false`
con worker parado, por usar `running and healthy` indiscriminadamente.
Así un STOP pedido para recuperar Chromium quedaba en `NO_GO` o
`REFUSED` sin efecto. **No se falsifica HEALTHY**: para Chromium
`stop` la observación física confiable es `State.Running` del ID exacto
atestiguado, mientras `start` mantiene la exigencia de salud y no
admite un worker ya RUNNING+UNHEALTHY. El motor del bot debe estar STOPPED
antes de detener al worker y el controller permanece HEALTHY.

Se amplió temporalmente el ownership de #351 sólo a estas dos funciones
y regresiones de `tests/test_host_boca_lifecycle.py` más
`tests/test_host_lifecycle_rootless_adapter.py`; #348 sigue DRAFT
documental y #356 recoge la corrección en el candidato de integración.
La matriz usa SQLite legacy real temporal + fake Docker Boca exacto:
`RUNNING/UNHEALTHY -> STOPPED/APPLIED` una vez; con bot RUNNING o
controller UNHEALTHY se rechaza, y Chromium START RUNNING/UNHEALTHY sigue
rechazado. ACK sólo tras postflight y relectura ledger. Sin tocar droplet,
BLACKBOX, otros servicios ni workflows.
