# ADR 0163 — consumo único de GO PREPARE bajo lease en Cutover A e import oficial

**2026-11-05 ART · issue #364, continuidad #360/#352. Estado DRAFT / CODE_ONLY / sin GO físico / sin host ejecutado.**

## Problema reproducido

El GO PREPARE de ADR0159/0161 ya puede calcularse antes de que GitHub
asigne el ID de APPLY, pero no era de un solo uso: Cutover A tenía un
`boca-cutover-a-intent-<GITHUB_RUN_ID_APPLY>.json` O_EXCL en almacenamiento
durable del owner, mientras import oficial sólo devolvía
`CREATED|UNCHANGED` (idempotencia de datos). Si se autorizara otro APPLY
con el mismo PREPARE, esas garantías por intento/archivo no impedirían un
segundo efecto. La variable de Environment y el recibo GitHub acreditan
autorización independiente **para un PREPARE concreto**, no el consumo único
por sí solos. Una segunda operación no debe reutilizar ese PREPARE.

## Contrato CODE_ONLY añadido (no activo en Actions)

### Cutover A

- Token host opt-in `boca-cutover-a-host-invocation-v2`: todos los pins v1
  (plan, source/legacy/image/config, ZIP SHA, GO digest) más
  `prepare_run_id` numérico positivo, distinto de `plan.attempt_id` (el
  run APPLY real). V1 sigue idéntico, los campos extras son NO_GO por
  comparación de esquema exacto. `run_cli` sólo usa V2 cuando recibe su
  GO exacto inyectado por el verificador de runner; el `main()` publicado
  sigue sin inyectar GO y es inertemente NO_GO.
- `run_cutover_a` recibe el consumidor PREPARE opcional; exige identidad
  PREPARE y callback juntos. Bajo una sola `BocaJobLease`, conserva la
  reserva terminal `O_EXCL` por APPLY, ejecuta el `backend.attest_original`
  exacto **antes** del consumo PREPARE y llama al consumidor **antes** de
  stage, imagen pull, parqueo, bootstrap SQLite o reemplazo de contenedor.
  Si hay rechazo/crash/receipt ambiguo, nunca alcanza la primera mutación
  Docker; no retira ni reanima nada por conjetura.
- El único backend permitido obtiene sus fuentes del ZIP Option B validado,
  atesta una vez más daemon Docker rootless UID10001 y volumen named
  `boca-socios_boca_data`, y ejecuta **una invocación fija**:
  `docker exec -i --user 10001:10001 <CID legacy exacto>` + programa
  Python stdlib constante (sin navegador, sin red nueva ni shell dinámico),
  que abre únicamente `/data` del volumen ya montado por el legacy
  controller, crea `.boca-cutover-prepared-go-<prepare_run_id>.json`
  con `O_EXCL|O_NOFOLLOW`, modo0600, `fsync` de inode/directorio,
  lectura SHA/bytes/inode exacta y recibo público acotado. Reobserva
  el CID original al volver, siempre bajo la misma flock. No escribe el
  volumen desde el host UID rootless porque los subuids Docker pueden
  diferir del UID del proceso del host. No crea volumen, contenedor, red,
  puerto ni backup.
- El JSON durable liga PREPARE y APPLY, ambos SHAs de fuente, imágenes,
  hashes Compose/overlay/seccomp, legado CID, owner digest y origen fijo.
  Nunca guarda cookie/token Telegram, contraseña ni HAR. El nombre
  determina unicidad por PREPARE; replay, symlink, marcador parcial,
  falta de fsync/readback o deriva rootless significa NO_GO irreversible
  sin retry. El recibo terminal histórico por APPLY y el cleanup
  selectivo success/failure **permanecen sin cambios**.

### Importación oficial

- Nuevo sobre público opt-in
  `boca-official-notice-import-prepared-v2` formado por las coordenadas
  exactas v1 y `prepare_run_id`. El shell de host estático v1 sigue
  sin cambios; constructor opt-in v2 reutiliza el mismo rootless
  Docker/socket, verifica UID10001, image digest/CID, único controller
  y volumen `/data` writable, adquiere la misma flock y sólo cambia
  `container-import` por `container-import-prepared` para ese token
  revisado. No integra un nuevo workflow/puerto.
- Dentro del contenedor Boca UID10001, el archivo ZIP ya descargado de
  GitHub se revalida de forma READ_ONLY antes del consumo. Se crea
  `.boca-official-import-go-<prepare_run_id>.json` bajo el volumen actual
  `/data` mediante `O_EXCL|O_NOFOLLOW`, `0600`, `fsync` y lectura
  exacta. El recibo persiste si falla la escritura de noticias. El
  importador informativo existente procede sólo después y sigue
  `actionable=false`; revalida el marcador antes de emitir SUCCESS.
  Reutilizar un PREPARE devuelve NO_GO, aun si la información importada
  sería idéntica (`UNCHANGED`).
- La única diferencia de protocolo es un token público de PREPARE. No
  acepta reemplazo de datos, no escribe SQLite, no altera la custodia
  Telegram ni habilita compra/reserva.

## Guardias que siguen pendientes antes de efecto real

1. Owner del workflow único #352 debe incorporar V2 **sólo** después de
   verificar por GitHub API PREPARE SUCCESS, artifact SHA canónico,
   source/main/owner/release, ventana24h, GO Environment independiente y
   segundo recheck main antes del único SSH. La variable GO no puede ser
   un booleano ni un hash devuelto por el propio input.
2. El GO del runner debe firmar/verificar también el
   `prepare_run_id` del token V2 y el SHA exacto del ZIP/artefactos.
   El backend no interpreta un valor pasado por navegador como GO.
3. Efecto real no aprobado: se necesita nuevo candidato integrado a
   main, release/digests y un único GO físico específico, más evidencia de
   UID/rootless/volumen y cleanup selectivo **del droplet**. Tests CI con
   fakes de Docker no prueban esa topología ni Samsung Chrome.
4. Si la imagen legacy no acepta la invocación stdlib, si el volumen
   `/data` no es 0600/UID apropiado o hay capacidad insuficiente, el
   sistema debe detenerse **antes de stage** y conservar legacy funcionando.
   No hay bypass para crear redes, Docker exec en otros CID, migrar SQLite
   legacy a 0008, borrar marcadores o intentar un segundo PREPARE
   automáticamente.

## Alcance, regresiones y Rule84

Paths de código bajo ownership exclusivo #364:
`host_boca_cutover.py`, `host_boca_cutover_cli.py`,
`host_official_notice_actions.py`, y sólo función
`execute_reviewed_cutover` de `host_boca_cutover_backend.py`,
tests focales, este ADR. No modificar `boca-first-deploy.yml`
(owner #352), BLACKBOX, Porota, otros servicios, backups ni puertos.
Los tests cubren la secuencia lease→attest→consume→stage y NO_GO
temprano, token v1/v2, GO independiente, marcador O_EXCL/0600/fsync,
replay y fallo posterior que conserva el marcador. No se ejecutó ningún
host/SSH/Docker real; registrar SHA, TREE y CI exacta al cierre del PR.

**Estado de autorización:** CODE_ONLY aprobado, GO físico NO OTORGADO.
La seguridad adicional es P2, pero el aislamiento Boca y estas
invariantes funcionales del deploy son obligatorios.

## R25 — runner GO_B compartido, sólo CODE_ONLY

Owner #364 agregó `src/boca_socios/prepared_go_runner.py` como verificador común
de las pruebas generadas por **Actions protegido**. Los tres archivos privados,
O_EXCL y no derivados del input de usuario, son
`$RUNNER_TEMP/boca-protected-legacy-go.{approved,prepare-id,receipt.json}`.
Se acepta exclusivamente recibo v1 de quince campos, representación JSON
canónica exacta, 24 h de vigencia, actor `mbalbo2023`, `main`, intentos
1, SHA de fuente, release, ambos manifiestos, ZIP revisado y owner sujeto
hasheado. La derivación del GO_B tiene dominios distintos, byte NUL final:

- Cutover A: `boca-cutover-a-prepared-go-v1:\x00`, `BOCA_CUTOVER_A_GO_BINDING_SHA256`.
- Import: `boca-official-notice-import-prepared-go-v1:\x00`, `BOCA_OFFICIAL_IMPORT_GO_BINDING_SHA256`.

`check_cutover_a_go.py --prepared-from-actions` genera token Cutover v2
sólo tras recalcular `cutover_prepared_context_sha256`, ambas evidencias
de release y ZIP, y cotejar Env GO_B independiente contra recibo canónico.
El import agrega `runner-preflight-prepared` y
`runner-host-command-prepared`; revalida artefacto oficial, SHA ZIP,
dos manifiestos y GO_B en ambos pasos, sin importar por defecto.

**Dependencias NO_GO de integración:** #352 debe autenticar con GitHub
GET read-only el PREPARE previo SUCCESS/actor/source/attempt/artifact y
recién luego producir los tres archivos privados; debe cablear los modos
runner con GO_B real de Environment y validar recibo físico exacto.
El ZIP Cutover `__main__`/builder necesita una vía independiente para
inyectar al host el GO ya verificado (sigue vacío en entrypoint heredado).
Estos módulos no cruzan por sí solos la frontera SSH/host ni se autorizan
por un `prepare_run_id` del usuario. Workflow y ZIP fuera de ownership #364.

**Prohibiciones intactas:** no deploy ni solicitudes/reservas reales, no
backups, no migrar legacy a 0008, no BLACKBOX, Porota, servicios ajenos,
puertos nuevos ni HTTPS; `127.0.0.1:8443` único panel. Regla 84:
esta ADR/issue/PR contienen los estados reproducibles; evidencias exactas
de CI se agregan sólo tras finalizar Actions sobre el SHA único.
