# ADR 0137 — Sesión Chrome persistente y SQLite independiente (opción B)

**Fecha:** 2026-11-04 ART. **Estado:** DRAFT / código y tests; **sin merge,
release, migración física ni deploy**. Decisión y RCA: issue #321 comentarios
[6646898884](https://github.com/mbalbo2023/boca-socios-assistant/issues/321#issuecomment-6646898884)
y [6647073475](https://github.com/mbalbo2023/boca-socios-assistant/issues/321#issuecomment-6647073475).
Checkpoint principal: issue #45 A45-R11.

## Decisión vigente: opción B autorizada

Tincho autenticó su panel privado mediante Samsung Chrome + Termius, con
passkey, en `http://localhost:8443`. Autorizó desarrollar una **única
autorización durable del dueño** sin los antiguos vencimientos rutinarios
de 15 minutos de inactividad u 8 horas absolutos. El primer login y cualquier
reautenticación siguen requiriendo WebAuthn real, presencia/verificación de
usuario, origen y RP exactos; no se pide volver a registrar PIN/clave.

Un `OwnerBrowserSessionStore(Database("/data/boca.sqlite3"), ...)` almacena
exclusivamente en **`/data/boca_owner_session.sqlite3`**, archivo vecino
dentro del volumen existente `boca-socios_boca_data`. El nombre es fijo,
derivado del directorio del controller DB. **No hay volumen, puerto, servicio,
HTTPS ni recurso host adicional**. El DB del controller
`/data/boca.sqlite3`, miembros, credenciales, esquema, ledger, claves,
owner y Telegram permanecen sin cambios por la función de bootstrap de
sesión. En el almacenamiento propio, el esquema se identifica con
`owner_session_schema(version=1,checksum)`, `PRAGMA user_version=1` y DDL
exactamente validado. El SQL ahora vive exclusivamente bajo
`panel/owner_session_sql/0001_owner_browser_session.sql`, **fuera** de
`storage/migrations`.

### RCA P0 que invalida opción A

El controller legacy instalado `cabce9f1e452e63ded115f447559a358dc0f4d1b`
empaqueta y valida sólo migraciones 0001–0007.
`integration.operational.validate_existing_beta_storage` y el lector de
estado rechazaban 0008 desconocido. Aplicar `0008_owner_browser_session.sql`
a la **base legacy** antes del cambio impide recuperarlo si el cutover falla.
La alternativa A (puente legacy + otra release) se examinó pero **NO fue
elegida**. En la opción B ya no hay SQL 0008 en el paquete del controller;
`upgrade_existing_owner_schema_0008()` y
`pre_cutover_upgrade_0008()` **rechazan siempre**, incluso con una prueba
legacy aparentemente positiva. No es lícito restaurar ese DDL por simplificar
un corte.

## Semántica de la sesión

- Una sola cookie activa globalmente. Otra autenticación WebAuthn sustituye
  atómicamente el hash anterior; logout de cookie vieja no revoca la nueva.
  Igual perfil Chrome/pestañas comparte autorización; no habilita sesiones
  múltiples, categoría rechazada por el dueño.
- Bearer aleatorio de 256 bits, cookie
  `__Host-boca_session; Secure; HttpOnly; SameSite=Strict; Path=/`;
  `Max-Age=34560000` (400 días) renovado en peticiones autenticadas.
  Chrome limita duración de una cookie a 400 días desde la última emisión:
  conservar el perfil y entrar periódicamente evita pedir passkey de rutina;
  borrado de cookies/incógnito/cambio de perfil o dispositivo sí la requiere.
  Referencia primaria: https://developer.chrome.com/blog/cookie-max-age-expires .
- SQLite guarda sólo SHA-256 del token, SHA-256 del binding público del
  verificador WebAuthn (credential ID, clave pública, owner, RP, origin,
  permisos) y SHA-256 del sujeto, con timestamp. Jamás se guarda bearer
  plaintext, clave privada, contraseñas, CSRF, operación ni permiso libremente
  reutilizable.
- Tras restart, se vuelve a comprobar el hash durable y se reconstruye en RAM
  una sesión con **nuevo CSRF/fingerprint/operation cache**. Formularios,
  operaciones y POST antiguos no sobreviven reinicio. Un verificador/permiso
  modificado invalida la autorización. Error SQLite/ledger/identidad niega
  acceso; nunca se autentica por un flag o header elegido por el cliente.
- La cookie es bearer y no está ligada criptográficamente al hardware.
  Priorizar persistencia aumenta el período de exposición si se roba el
  token, mitigado por túnel SSH-local y atributos anteriores; no se promete
  persistencia infinita ni protección ante copia de cookie.

## Inicialización y cutover — contratos separados

**Primera instalación nueva:** `runtime.initialize_beta` ya crea el
almacenamiento controller en su fase explícita `initialize_new`. Sólo
si hay owner configurado llama
`OwnerBrowserSessionStore.migrate_schema(runtime.database)`, que crea el
**SQLite lateral**, sin llamar `Database.migrate`, DDL ni INSERT de ledger
sobre el controller. Un initializer sin owner no crea autorización por sí.

**Controller existente:** la nueva interfaz de solo código
`owner_session_upgrade.bootstrap_existing_owner_session(evidence, path)`
exige una instancia de `ControllerStoppedEvidence` vinculada al
`DockerStoppedControllerEvidence` físico (UID/GID10001, rootless socket,
legacy ID 64hex, etiquetas, digest, volumen, controller parado, no otro
writer y `borrowed_lease_fd` del **mismo lock canónico**
`/run/user/10001/boca-socios-protected-job.lock`). Dentro de una única
ventana de exclusividad:

1. Revalida identidad `(dev,inode,uid,gid,0600,nlink=1)` del controller.
   Comprueba su ledger conocido 0001–0007, sin tabla owner ni ledger 0008,
   con integridad SQLite y consistencia opcional 0004/0007.
2. Calcula el archivo vecino dentro del mismo volumen exacto. Si no existe,
   crea sólo ese archivo con `O_EXCL|O_NOFOLLOW`, modo `0600` y el UID/GID
   del proceso rootless; si existe, exige archivo regular, dueño único,
   `nlink=1`, esquema/checksum idénticos. Una creación interrumpida deja
   evidencia parcial y **NO_GO**, sin reparación, reemplazo ni purga.
3. Usa transacción SQLite `BEGIN IMMEDIATE` para el DDL propio,
   verificando `owner_session_schema` y `user_version`. Si la sesión ya
   existía y es válida, retorna `ALREADY_APPLIED` sin borrar el hash.
   Revalida controller y volumen después; no modifica el DB legacy.
4. En el único host transaction #227 deberá retenerse la misma lease
   durante parqueo, bootstrap, candidate apply, observación y limpieza
   Boca-only postdeploy en éxito o fallo. Código de host y workflow final
   **todavía no están completamente conectados**, y no se ha ejecutado esta
   operación sobre el droplet.

**Contrato de transporte sin dependencias del paquete:** el módulo nuevo
`panel/owner_session_disk_bootstrap.py` importa únicamente bibliotecas
estándar. El bundle ZIP/memfd del único proceso host debe transportar sus
bytes exactos y los bytes SQL de `panel/owner_session_sql/0001_*.sql`;
su invocación es
`bootstrap_attested_session_file(legacy_path, held_lease_fd,
expected_db_identity, session_schema_bytes)`. Exige que el descriptor de
lock canónico realmente esté retenido (contendiente independiente bloqueado
y misma open-file-description), UID/GID 10001, SHA empaquetado del SQL y
checksums conocidos del ledger 0001–0007, owner/session DB privados y
postflight. Retorna únicamente `APPLIED` o `ALREADY_APPLIED`.
No inspecciona Docker, no posee API CLI, no cambia host ni ejecuta
despliegue; la atestación de contenedor/volumen/digest y el arranque final
siguen siendo responsabilidad de #227. Esta separación evita copiar
dependencias transitivas de `storage`/`integration` al ZIP privilegiado.

La construcción del panel, login, consulta, healthcheck y startup **no
ejecutan bootstrap**. Sin archivo lateral preexistente válido, el nuevo
panel falla cerrado. El controller antiguo puede conservar su SQLite
original, pero su recuperación física sigue requiriendo la prueba real
del host y de la transición #227, no sólo la prueba de esquema offline.
No usar backup, rollback destructivo, recreación de owner ni limpieza
Docker global como estrategia de recuperación.

## Pruebas, gates pendientes y exclusiones

Las pruebas sintéticas del frente #321 cubren ledger legacy inalterado con
y sin 0007, fila de socio/credencial y clave conservadas, base lateral
idempotente, bearer y verificador, restart/CSRF nuevo, relogin/logout,
base/archivo ausente, symlink, hardlink, modo inseguro, schema incompleto,
checksum alterado, origen/UID/inode drift, fake stop, lease prestada
y host Docker simulado sin invocar daemon real. Otros tests del panel
comprueban atributos 400d y permisos. Todos los casos son **offline**;
la suite focal incluye diez casos del adaptador stdlib-only bajo lock real
de prueba, SQL manipulado, UID/inode/ledger incorrecto, FD sin lock y archivo
parcial; y la construcción del wheel verifica que el SQL lateral esté
empaquetado (package-data explícito en `pyproject.toml`), mientras el
antiguo 0008 queda fuera.
la aceptación real Samsung Chrome, reinicio de controller, bot/Telegram y
recibo Docker requiere cutover posterior protegido y autorización específica.
PR #322 debe publicar HEAD exacto, suite completa, Ruff, MyPy, política
y GitHub Actions; un test verde en branch no equivale a deploy.

Las BLACKBOX `synthetic.py` e `ipc_worker.py` no se leen, importan,
ejecutan, editan ni prueban. No se activa Boca real/Queue-it, compras,
reservas, login/fila, backups, multisesiones, rotación/eliminación total de
clave, Site, HTTPS adicional, Porota ni otro servicio. La única ruta de
operación host sigue siendo GitHub Actions Boca protegido, en fase aparte.

**Evidencia histórica:** el diseño A, pruebas preliminares y sus recibos
anteriores al GO de B permanecen en los commits anteriores de PR #322 y
en comentarios #321. No son evidencia vigente de compatibilidad o deploy.
