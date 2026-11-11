# R177 — Inventario dual instalado, actualización in situ y motor de prueba

Fecha: 2026-11-11 (ART). Checkpoint canónico: issue #417. Este documento
registra **evidencia observada**, no autoriza Cutover ni representa una
certificación de funcionamiento físico posterior a una actualización.

## Estado certificado en GitHub

- El PR #478 se integró por squash; `main`
  `bd6c1212f129454f10e5d4a25585c3f4eeb8edea`; cero PR abiertos al
  iniciar R177. CI posmerge #43057151190 e Image Security #43057151370
  fueron SUCCESS. El runner de CI del candidato comprobó 6826 tests y
  34 subtests PASS, además de IPC real entre UID10001 y UID10002, rechazo
  de UID10003 y STOP. Estos recibos son CODE_ONLY / runner, no el droplet.
- Publicación dual protegida #43057984253 SUCCESS, intento único del titular.
  Controller:
  `ghcr.io/mbalbo2023/boca-socios-assistant@sha256:0e6b54c984605948b96f0679bf7dcb142dcbd7fcb862d61362c21a9d0a9f94e9`.
  Worker:
  `ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:9c193489a08a561d392e2a8aa839328adedd0d90a91b4c2d20fd0bd46cb78ae2`.
  Manifiestos originales: artifacts #13873545429 / #13871669274.
  **Estos digests se publicaron, pero NO hay evidencia de instalación.**

## Causa raíz del stopper físico

- El Cutover V3 **sí instaló antes** un controller y un worker: workflow
  #42806447101 (run #926), SHA
  `03df9a14bdd78cf768386a865876fed9d5656911`, release histórico
  #42805726586. Recibo: `state=ACCEPTED terminal=RECORDED cleanup=ACCEPT
  installation=IDLE_INSTALLED controller_restart=VERIFIED worker=CREATED
  pid=0 engine=STOPPED owner_start=UNVERIFIED`. La verificación de host
  fue `receipt=EXACT runtime=UNVERIFIED`; NO equivale a bot funcional.
- El diagnóstico antiguo #42912586832 terminó `LEGACY_SINGLETON` porque
  la operación `cutover-a-apply` PREPARE exige un único controller legacy,
  sin worker. Ya no corresponde a la topología dual instalada.
- Censo físico nuevo #43058130210 desde `main=bd6c121`, Action protegida
  `cutover-a-census` en `boca-deploy`, UID10001: `controllers=1`,
  `workers=1`, `other_boca=0`, `total=2_PLUS`, `legacy_shape=ABSENT`,
  `state=READY`, `observer_writes=0`, `foreign_resources_touched=0`,
  `double_read=STABLE`, `cutover_authorized=false`. La forma `ABSENT` es
  compatible con el V3 que etiquetó el controller con el intento de IPC;
  no prueba corrupción ni residuos.

**No eliminar, renombrar, detener ni sobrescribir los dos contenedores**
por su nombre o por una suposición de estado. `RootlessCutoverBackend`
prepara un worker nuevo asumiendo que no existe otro: suprimir el guard
de singleton sin diseñar una transición dual provocaría colisiones.

## Dos frentes R177 en ramas aisladas

1. **Observación de par existente, solo lectura.** Reutilizar el atestado
   rootless de `host_boca_census`, doble observación y rechazo de recursos
   extranjeros. La nueva operación debe aportar identidad exacta de ambos
   contenedores, imágenes/procedencia, estado, red y volúmenes de Boca,
   sin inspeccionar `Env`, secretos, datos de socios ni otros Docker. La
   operación jamás confiere `cutover_authorized=true`.
2. **Motor bajo demanda.** `boca_socios.browser.ipc_server` utiliza
   `OfflineNoGoExecutor()` por defecto; el Chromium probado en CI está
   separado. La prueba IPC del runner no demuestra navegación del bot.
   Integrar únicamente un camino explícito, no transaccional y con fixture
   ficticio para comprobar ciclo de vida; conservar NO_GO por defecto y
   nunca presentar una cookie/token como reserva realizada. La navegación
   al `SITE_URL` de sandbox requiere un contrato de observación separado y
   prueba física posterior, sin reconectar automáticamente el orquestador
   antiguo o módulos de scraping.

Tras certificar estas dos ramas, elaborar un **upgrade dual in situ** en el
workflow Boca, usando un único lease rootless, recibos exactos de imagen
histórica y nueva, y un plan de compensación de ambos CIDs. No reutilizar
la ruta controller-only ni instalar una segunda pila/puerto. Preservar
volúmenes del propietario, SQLite, configuración URL y claves; no tocar
Porota, PPI Watch, Docker ajeno ni otros puertos. `boca-first-deploy` y
su entorno protegido siguen siendo la única vía de SSH operativa.

### Diseño de upgrade R178 condicionado al observador R177

La revisión independiente identifica un bloqueo adicional: el binding
persistente del socket systemd de `host_on_demand_service` está asociado al
`installation_run_id` anterior. `install_control` no lo reemplaza y
`remove_control` no acepta otro lease. Se necesita un pequeño primitivo
**transaccional de sustitución verificable** del binding, con respaldo del
recibo anterior durante compensación; no basta con cambiar la imagen Docker.

Secuencia bajo **un único lease rootless**, solo si el observador ha
atestiguado identidad exacta, imágenes históricas, estado inactivo, hashes
Compose, volúmenes, socket/servicio, 8443 y disco:

1. Revalidar main, cero PR pendientes, release dual nuevo y manifiestos
   históricos. Confirmar dos CIDs, ningún otro contenedor, engine STOPPED,
   titular y namespaces ajenos intocados. Guardar identidad de SQLite,
   volúmenes y binding old como condiciones de compensación.
2. Verificar capacidad e inodos; traer únicamente los dos digests nuevos y
   validar Compose/overlay/seccomp de Boca antes de cambiar servicios.
3. Cerrar temporalmente activación socket, detener y estacionar **ambos**
   CIDs anteriores de forma reversible y por identidad. Crear candidato
   worker IDLE y controller usando los mismos volúmenes, con nombres
   originales liberados y etiquetas de intento único. Nunca abrir segundo
   puerto 8443 ni un endpoint público.
4. Probar UID/socket, worker PID0, controller healthy en loopback, datos
   SQLite con mismo inodo, engine STOPPED, owner/passkey, SITE_URL y
   ausencia de envío Telegram. Sustituir binding systemd solo tras
   verificar ambos candidatos; probar un ciclo de panel y el control.
5. Registrar una aceptación irreversible O_EXCL antes de retirar por
   **ambos IDs anteriores exactos**. Cerrar con postflight y cleanup
   selectivo de Boca bajo el mismo lease, preservando data/key/owner.

P0 de implementación: el planner genérico de `host_boca_cleanup` solo
retira contenedores etiquetados con el *attempt* nuevo. Los dos antiguos
pertenecen al intento histórico #42806447101, así que hay que construir
un retiro especializado con atestado positivo de ambos IDs y digests,
después del marcador ACCEPT. **No** relajar `_attempt_owner` ni pasar
IDs históricos a `retire_containers` del cleanup general. Asimismo, los
nombres canónicos de controller/worker colisionan mientras estén los viejos:
estacionar ambos antes de crear candidatos, sin borrar. Durante esa etapa
cuatro CIDs son esperables; el verificador final de par estricto de dos
debe ejecutarse solo después del retiro exacto y aceptación.

Si falla antes de aceptación: retirar solo candidatos atestados, restaurar
**ambos** CID anteriores y su binding/socket, verificar salud y entregar
`RECOVERED/NO_GO`. Si falta una confirmación o hay estado incierto,
`INDETERMINATE`: preservar recursos y evidencia, sin `prune`, reintento
automático ni eliminación amplia. La implementación y las pruebas de
compensación siguen PENDIENTES: **este diseño aún no habilita APPLY**.

## Verificaciones de aceptación aún no realizadas

- Panel 8443/passkey desde Samsung, cookies persistentes, POST Origin/CSRF.
- `SITE_URL` dinámica, reinicio, espejo de volumen de solo lectura.
- Controller/worker con imágenes nuevas: CID, digest, health, socket,
  UID, arranque/STOP, inactividad, red de salida y actividad Chromium.
- Alta de socios ficticia, SQLite e intención única; cero reservas reales.
- Recuperación y limpieza exacta de contenedores/artefactos de Boca bajo
  el mismo lease, incluso en fallo.
- Telegram: sender OFF hasta una custodia propia y rotación del token
  previamente expuesto; el actual workflow `telegram-activate` conserva
  NO_GO de backend host no verificado.

Registrar cada campo como **NO_VERIFICADO/NO_GO** hasta recibo genuino,
sin reinterpretar un build o una Action CODE_ONLY como éxito del droplet.
