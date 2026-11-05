# ADR 0151 — Telegram V2: stage privado y nonce durable bajo única lease Boca

Fecha: 2026-11-05 ART. Frente funcional #315 / Cutover A #227 / canónico #45.

**Estado: DRAFT / CODE-ONLY / NO_GO físico.** Esta revisión no opera el
droplet, no instala Telegram, no consulta Bot API y no habilita sender.
Seguridad de hardening ajena al flujo funcional continúa P2 por decisión de
Tincho; la integridad de la autorización y la custodia privada no se eliminan.

## RCA del enlace faltante

El panel autenticado desde #340/#342 puede escribir un único sobre Telegram
V2 **ya cifrado** en `/data/boca_telegram_pairing_stage_v2.json`, pero su
`stage_id` es un identificador privado sin autoridad. El adaptador existente
`telegram_pairing_cutover.execute_protected_pairing` exige dos callbacks aún
no suministrados por el host: `recheck_host` bajo la misma lease y
`consume_owner_nonce` durable, antes de cualquier GET de Telegram. La
regresión previa de pruebas usaba un `set` temporal en memoria para el nonce,
que no sobrevive restart/crash. Una ejecución protegida no podría presentar
prueba de replay-fence durable con ese simulacro.

## Decisión de implementación acotada

Nuevo módulo **sin ruta HTTP ni CLI**:
`src/boca_socios/telegram_same_lease_stage.py`.

1. Recibe el `BocaJobLease` **ya adquirido** por el único proceso de
   Cutover A. Antes/después de la lectura y de cada fase importante usa
   `verify_protected_boca_job_lease`, que verifica flock efectivo, UID/GID,
   PID, attempt e identidad del inode canónico. No crea segunda lease ni
   segunda operación GitHub Actions.
2. Lee con descriptores `O_NOFOLLOW` y límites de bytes el stage del volumen
   Boca preexistente. Comprueba propietario/mode, `nlink=1`, bytes JSON
   canónicos, campos exactos, hash SHA256 del sobre y fingerprint X25519.
   Conserva su identidad inode/ctime/mtime para revalidarlo antes/después de
   cada host recheck. **No descifra token ni pairing-code** y no borra stage.
   El host debe probar por separado que la carpeta corresponde al volumen
   Docker Boca esperado: un path de Python no es atestación del host.
3. La primitiva `consume_telegram_owner_nonce` recibe el nonce HMAC de
   256 bits **distinto del `stage_id`** y coordenadas de owner/lease/source/
   imagen/controller/recipiente. Tras verificar la misma lease, crea un
   marcador JSON privado 0600, canónico y `O_EXCL`, cuyo nombre deriva del
   **SHA256 del nonce** y cuyo cuerpo nunca incluye el nonce ni credenciales.
   Hace fsync archivo y directorio, preserva el archivo ante crash/fallo de
   fsync y deniega siempre cualquier replay tras restart, aun si la primera
   llamada falló después del consumo. No hay limpieza automática de este
   marcador ni purga de otros datos o volúmenes.
4. `execute_staged_pairing_under_lease` enlaza el stage cifrado, el nonce
   durable y la revalidación de lease con el adaptador V2 existente. Acepta
   sólo un `OwnerPairingReceipt` ya firmado por el dueño bajo autoridad
   protegida, una clave en memoria, reloj/inspección host y `api_fetch`
   suministrados por **el backend físico a desarrollar**; la función no
   puede fabricar autorización, inspección Docker ni proveedor. El adaptador
   anterior sigue ordenando GET-only `getMe/getWebhookInfo/getUpdates/getChat`,
   verificación V2 de custodia y estado `CUSTODY_COMMITTED_NO_SEND`.

## Límites funcionales que NO se deben declarar resueltos

- No existe un caller real en el único workflow `boca-first-deploy.yml` que
  use este nuevo adaptador. El branch no cambia ese workflow, Compose,
  `runtime.py`, `config.py`, host cutover, secretos ni Site/Porota.
- El host protegido aún debe proporcionar recibo autenticado de **owner
  Chrome/passkey actual**, clave HMAC fuera de SQLite y del repo, fuente/main,
  release/imagen, Docker rootless exact-ID y el mismo `BocaJobLease` desde
  observación hasta custodia. No se puede crear un GO a partir de un simple
  booleano, `stage_id` o prueba sintética.
- La lectura Bot API real sólo podrá ocurrir en egress Telegram Boca
  autorizado después de esos checks. Ni parser/resolver de `getUpdates` ni
  fake transport autorizan notificación. Hace falta un recibo humano aparte
  para habilitar sender. No enviar mensajes reales desde esta rama.
- La sesión Chrome Opción B sigue en SQLite independiente. No se migra
  `/data/boca.sqlite3` a 0008, no se hacen backups, no se usan puertos nuevos
  ni HTTPS, y los módulos BLACKBOX reservados son intocables.
- Un consumo de nonce ambiguo o una etapa cifrada reemplazada deja
  `NO_GO`; no hay reintento automático o eliminación ad hoc. La recuperación
  eventual requiere diagnóstico y nuevo stage/owner proof protegidos.

## Evidencia y validación

`tests/test_telegram_same_lease_stage.py` crea un flock real en un directorio
temporal, usa credenciales sintéticas y Bot API falsa. Contrasta el stage
firmado, secuencia de rechecks y cuatro GET con marker persistido, replay
bloqueado después de soltar/adquirir otra lease, pérdida de lease, cambios de
inode, hardlink/symlink, permisos/directorios inseguros, reloj y falla de
fsync con `O_EXCL` retenido. Test inicial rojo por módulo ausente; implementación
posterior pasa 18 casos focales. No produce tráfico real ni modifica Docker.

La evidencia final exacta (SHA/TREE local y GitHub, Ruff/format/MyPy/pytest,
Actions PR-only y estado del host) se consignará en la descripción del PR
DRAFT y en #315 bajo **Regla 84**. Incluso CI totalmente GREEN mantiene
**Telegram OFF / NO_GO físico** hasta un Cutover A autorizado y validado.
