# ADR 0156 — Telegram post-Cutover A: ventana firmada de /start (#315)

Fecha: 2026-11-05 ART. Estado: **DRAFT / CODE_ONLY / NO HOST / NO BOT API**.
Owner exclusivo: Telegram #315. Base: candidato integral #319 R21.9.

## RCA P0: orden temporal de Chrome y Actions

La sesión Chrome V2 sólo puede guardar su sobre cifrado con el nuevo
controller IPC, luego del primer Cutover A. Tincho entonces envía
`/start <code>` a su propio bot y, más tarde, lanza una operación protegida
de Telegram en el único workflow `boca-first-deploy.yml`.

El adaptador `execute_protected_pairing` estaba usando
`OwnerPairingReceipt.issued_at` como inicio de la ventana `getUpdates`.
Pero esa firma necesariamente se emite **después** del staging, al abrir la
**nueva** lease protegida de activación. Un `/start` enviado entre ambos
momentos sería descartado como antiguo. Conservar una lease/SSH de Cutover A
abierta mientras la persona usa Chrome no es una alternativa válida.

## Corrección acotada del contrato

1. El panel existente persiste `staged_at` generado por el **servidor** de
   Boca en el documento cifrado privado, con archivo 0600/no-symlink,
   publicación atómica y verificación de inode. No se acepta un timestamp del
   browser, de GitHub Actions ni de un argumento libre.
2. El emisor de `OwnerPairingReceipt` admite
   `discovery_not_before` **opcional para contratos legacy**, junto a
   `issued_at`. En el camino staged se vuelve **obligatorio** y debe ser
   exactamente igual al `staged_at` del archivo que ya está ligado al hash
   del sobre, al dueño, al recipiente y a las coordenadas. Este campo se
   incorpora al payload HMAC: cambiarlo invalida la autorización. El
   camino anterior sin stage mantiene su contrato compatible.
3. Se exige `0 <= staged_at <= issued_at <= now`,
   `now - staged_at <= 3600 segundos`, recibo owner vigente (máximo 600 s
   desde su emisión), source/image/controller/recipient/lease exactos y
   nonce durable O_EXCL antes del primer GET. Fechas futuras, una ventana
   superior a una hora, timestamp modificado, firma legacy sin campo o
   reescritura del stage producen NO_GO **antes** de Bot API y de consumir
   nonce. No se admite una excepción para mensajes viejos.
4. El parser privado de Telegram sigue requiriendo **un único** `/start`
   de chat privado propio, fecha dentro de esa ventana, y cuatro GET
   allowlisted en secuencia. No se alteran webhooks, offsets ni
   configuración del bot. Nunca se habilita sender por hallar chat.

## Secuencia física futura (aún no implementada)

- **Operación 1** `cutover-a-apply`: release exacto, IPC/panel accesible,
  sender OFF y limpieza Docker Boca-only con recibo terminal.
- Tincho abre Samsung Chrome por Termius `http://localhost:8443`,
  configura token **solo en la página privada cifrada** y envía `/start`
  al bot propio. No necesita introducir token/PIN en GitHub ni terminal.
- **Operación 2** `telegram-activate`, en el **mismo workflow** pero
  despacho nuevo: GO específico, HEAD/image/controller/recipient real,
  clave owner HMAC fuera de SQLite/repositorio, lectura física del stage y
  reloj autenticados, lease exclusiva nueva. Emitir la firma sobre
  `staged_at`, comprobarla bajo esa lease y ejecutar custodia/sender OFF.
  Si transcurre más de una hora, queda NO_GO y se documenta cómo renovar
  legítimamente el stage; no se elimina ni sobrescribe de oficio.
- Luego verificar destinatario y recepción humana con recibo distinto y
  habilitar notificaciones mediante GO separado. `API_ACCEPTED` tampoco es
  prueba de que Tincho recibió una notificación.

## Evidencia y límites

Regresiones offline `test_telegram_same_lease_stage.py`: `stage → /start →
receipt posterior → Bot API sintética`, timestamp firmado exacto,
tamper, valor futuro, firma ausente, ventana caducada y 0 proveedor/nonce
ante rechazo. No se usa token, chat, Docker, SSH, credencial, imagen,
puerto externo ni navegación real. Se preservan BLACKBOX, base SQLite
legacy sin migración 0008, sesión lateral Opción B, Porota, otros
servicios, volúmenes y backups.

El nuevo contrato **no conecta** un CLI/host real, no configura el modo
`encrypted-only` en Compose, no crea el GO de `telegram-activate`, no
activa sender ni envía mensajes. Estas integraciones son P0 del owner
de workflow/host; seguridad no funcional P2 según Tincho. Registrar
HEAD/TREE, Actions exactos y resultado físico por separado (Regla 84).
