# ADR0279 — R259: puente de mapping rootless PREDEPLOY bajo lease Boca

**13-NOV-2026 UTC · #417 · CODE_ONLY · DEPLOY NO_GO.**

## RCA: contrato postflight imposible antes de instalar

El atestador R255 `observe_boca_mapped_file_custody(expected, lease, …)`
exige un `PostflightExpected` validado con receipt `SUCCESS` de cleanup V2
del mismo intento físico. Un diagnóstico READ_ONLY anterior al upgrade **no
dispone de ese recibo**. Construirlo a partir del formulario, del ZIP de
GitHub o de un resultado sintético daría una falsa certificación y violaría
la prohibición de repetir R186. Ese callable permanece reservado para el
postflight posterior a un APPLY genuino.

## Resolución de alcance restringido

El nuevo `host_boca_rootless_mapping_cli observe <GITHUB_RUN_ID>` sólo
produce un recibo **preliminar** mediante fuentes ya revisadas:

1. Abre exclusivamente el flock canónico Boca preexistente mediante
   `O_RDWR|O_NOFOLLOW|O_CLOEXEC` **sin `O_CREAT`**. Requiere UID/GID 10001,
   archivo 0600, directorio 0700, inode único, bloqueo exclusivo y la
   verificación real `verify_protected_boca_job_lease` antes, durante y al
   final. Si no existe, no crea archivo: `NO_GO`.
2. `pair.observe` toma un censo global de IDs y rechaza cualquier recurso
   externo en el daemon dedicado. `pair.verify` y
   `service.read_installed_binding` más `binding._attest` exigen los CIDs,
   imágenes OCI, mounts, estado del worker y archivo systemd autenticados.
   Los CIDs se toman exclusivamente del par observado, nunca de parámetros
   ni del nombre de un contenedor no demostrado.
3. Para ese CID exacto, compara dos lecturas Docker `State.Pid` con el PID
   informado por R177, abre solamente `uid_map/gid_map` de `/proc/<PID>`
   por los mecanismos `O_NOFOLLOW` y valida traducciones no solapadas.
4. Reutiliza los tres validadores `host_first_deploy._validate_*_volume`
   para comprobar nombres, labels, mounts `local` y directorio rootless
   exacto. `capture_mapped_custody` coteja con `O_PATH` el propietario
   traducido y metadatos de los tres archivos privados, sin leer bytes de
   SQLite, clave o sesión. Repite volúmenes, owner, inodes y par/binding;
   cualquier cambio, error de permisos, lock ocupado o symlink aborta.
5. El CLI `verify <GITHUB_RUN_ID>` admite sólo una línea JSON canónica,
   acotada a 1024 bytes, con prefijo `BOCA_ROOTLESS_MAPPING `, esquema 1,
   `stage=PREDEPLOY`, estado `PRELIMINARY_PREDEPLOY` (lease verificada) o
   `NO_GO`, `observer_writes=0`, `foreign_resources_touched=0` y
   `cutover_authorized=false`. No publica UIDs, GIDs, rutas, CIDs ni hashes.

**No se abre red, navegador ni flujo de tickets**, no se escribe el lock,
no se toca Porota y el recibo no prueba la aceptación BETA, la passkey, el
monitor, SITE_URL, el cleanup final ni el postflight técnico.

## Despliegue y evidencia pendientes

- Integrar en un solo PR del owner de workflow el selector
  `--rootless-mapped-observe`, y en el owner de bundle la entrada
  `boca-rootless-mapping-observe`. Exigir digest SHA de ZIP y `main`
  autenticado, Action oficial/manual única y lectura sin efecto bajo rootless.
  Este módulo por sí solo **no ejecuta ningún despacho al droplet**.
- Medir los límites existentes del ZIP; no aumentar cap ni importar
  dependencias ajenas a Boca. No mezclar la ruta PREDEPLOY con el backend
  efecto/APPLY ni presentar `PRELIMINARY_PREDEPLOY` como `VERIFIED_FINAL`.
- Una futura observación física genuina determinará si los tres archivos
  están realmente mapeados. Falta además recopilar cleanup V2 auténtico y
  postflight posterior del controlador+worker, panel 8443, passkey, sitio,
  monitor y SQLite para considerar BETA instalada.

Pruebas unitarias R259: framing/anti-inflación del recibo; PID y binding
drift; lock preexistente sin creación; UID map e inodes O_PATH; atestación
de volúmenes, doble lectura y ocultamiento de datos privados. Pruebas
locales no sustituyen medición física del droplet.

**Actualización R260, integración CODE_ONLY:** el selector workflow R258 y
el transporte protegido dedicado ADR0277 ya están incorporados en la rama
candidata. Se conserva `PRELIMINARY_PREDEPLOY` y el bloqueo de APPLY;
siguen pendientes CI exact-main y observación física genuina mediante Actions.
