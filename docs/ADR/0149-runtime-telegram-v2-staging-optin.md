# ADR 0149 — Opt-in del controlador para staging Telegram V2 cifrado

Fecha: 2026-11-05 ART

Estado: **DRAFT / código y pruebas solamente / NO_GO Telegram físico**

Ownership: #315 / #328, candidato integral posterior a A45-R21.6.

## RCA del último enlace faltante

El PR DRAFT #340 agregó al panel autenticado un POST exclusivo de
`/telegram/emparejar` con CSRF y operación de un solo uso. Recibe únicamente
un sobre V2 cifrado en Chrome y permite inyectar un
`telegram_pairing_stager: Callable[[bytes], PairingStageReceipt]`. La función
de staging privada fue probada por separado, pero el servidor
`build_beta_server` aún construía `PrivatePanelApplication` sin ese callback.
Por lo tanto, el GET seguía siendo una vista previa y POST 404 aunque existiera
el código de staging. Eso era un **bloqueo de integración de código**, no una
evidencia de Telegram instalado o una autorización para usar el Bot API.

## Decisión mínima de integración

- `Settings.telegram_pairing_stage_mode` se configura explícitamente desde
  `BOCA_TELEGRAM_PAIRING_STAGE_MODE`, con valor predeterminado `off`.
  Únicos valores válidos: `off` y `encrypted-only`. **No contiene ni recibe
  token, chat ID ni clave privada.**
- El modo `off` preserva el comportamiento anterior: panel autenticado con
  GET de vista previa y POST 404; no se inspecciona, crea ni migra ningún
  archivo de staging.
- El modo `encrypted-only` se admite sólo en staging, navegador `ipc`, origen
  exacto `http://localhost:8443` del túnel SSH, listener interno
  `0.0.0.0:8443` en el contenedor Boca (host publicado sólo en
  `127.0.0.1:8443`). No se permite controller-only, otro puerto ni HTTPS.
- Antes de inyectar el callback, el runtime verifica que su SQLite de Boca
  esté en el mismo directorio exacto `/data` que el stage; abre **sin seguir
  symlink** el directorio ya existente, comprueba propietario UID del proceso,
  modo de escritura y ausencia de escritura group/world. No crea directorio,
  archivo, esquema o volumen. Esto no sustituye la futura atestación del
  volumen Docker nombrado por el host protegido.
- Si supera el preflight, el runtime inyecta exclusivamente
  `partial(stage_private_telegram_pairing, Path('/data') / STAGING_FILENAME)`.
  La validación del dueño se realiza antes en el panel con sesión durable
  passkey, mismo origin, CSRF y operación one-use; el callback recibe sólo
  `bytes` cifrados. El stager escribe a lo sumo **un** archivo 0600,
  atomizado, fsync y sin overwrite, con el recibo honesto
  `202 STAGED_PENDING_PROTECTED_CUTOVER`.
- Cualquier configuración incompatible o directorio inexistente/inseguro
  falla al construir el servidor, antes de abrir listener o crear efectos de
  almacenamiento. El stage también revalida el directorio al persistir.

## Alcance funcional y límites

Este PR **no habilita el opt-in en Compose ni en Actions**, no conecta el
bot real, no recibe ni transmite el token por GitHub y no marca
`telegram_connected=true`. No ejecuta ningún efecto físico en el droplet,
ninguna limpieza Docker ni despliegue. No cambia las sesiones Chrome de la
Opción B ni migra SQLite legacy a esquema 0008.

El próximo enlace obligatorio sigue siendo un **único consumo protegido**
del stage bajo lease host de Boca: HMAC de dueño real, nonce durable de un
solo uso, source SHA/image exactos, confirmación del recipient, lectura acotada
del Bot API y recibo verificable de custodia/envío. Sólo después de un GO
protegido y validación Samsung Chrome+Termius podrá declararse Telegram
funcionando. El `stage_id` es un identificador de staging, no un nonce
privilegiado ni ACK.

## QA de candidato

Nuevas regresiones en `test_telegram_pairing_runtime_optin.py` verifican
default-off sin writes, opt-in explícito y recepción del callback desde
`build_beta_server`, archivo cifrado privado/no sobrescritura, directorio
ausente, symlink, permisos inseguros, ruta fuera de Boca y modos de runtime
incompatibles. La prueba de panel propietario y WebCrypto de #340 permanece
independiente. Pruebas offline: sin teléfono, token real, navegador externo,
Docker, host ni red.

Regla84: registrar PR/HEAD/árbol, acciones exact-SHA, regresiones y stopper
físico en issue #315 y checkpoint #45; no copiar estados de pruebas anteriores
como si fueran evidencia de la nueva revisión.
