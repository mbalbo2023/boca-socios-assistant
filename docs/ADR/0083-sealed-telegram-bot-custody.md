# ADR 0083: custodia cifrada del bot Telegram y destino privado

**Estado:** propuesta del issue #198, pendiente de PR, revisión y merge.
Diseño: 2026-11-01 (America/Argentina/Buenos_Aires). Este cambio es biblioteca
y pruebas sintéticas; no configura el droplet ni envía un mensaje.

## Frontera y decisión

El worker opt-in de ADR0078 lee `/run/telegram/bot_token` y
`/run/telegram/chat_id`; el Compose define el volumen externo
`boca-socios_boca_telegram` pero no lo crea ni lo provisiona. Un helper
independiente `python -m boca_socios.telegram_bootstrap` ofrece `prepare`,
`install` y `verify` **explícitos**. Sólo una futura operación protegida del
workflow Boca puede ejecutarlo en la imagen fijada como UID/GID 10001 con el
volumen privado en `/run/telegram`, directorio UID/GID10001 modo 0700. El
helper no crea volumen, consulta Telegram, toca SQLite, inicia worker ni
activa reservas/compras.

`prepare` crea de manera exclusiva una clave receptora X25519 en archivo
regular UID/GID10001 modo 0400, o relee una clave previamente preparada si
ambos secretos están ausentes. Emite sólo la clave pública base64url y su
huella SHA-256. El dueño debe comprobar que ese recibo público proviene de
la ejecución protegida exacta antes de cifrar: una sustitución de clave
redirigiría la confidencialidad. El sobre no autentica por sí solo al
remitente; el workflow protegido, dueño/main y entorno son puertas separadas.

La API pura `seal_for_recipient` recibe fuera de GitHub un token con formato
Bot API y chat numérico canónico distinto de cero. Cifra ambos en JSON
canónico con X25519 efímero, HKDF-SHA256 y AES-256-GCM, sal y nonce nuevos por
sobre. El AAD vincula versión, repositorio, propósito exclusivo
`boca-telegram-bot-v1`, UID10001, clave/huella receptora y parámetros
efímeros; la derivación usa otro dominio
`boca-telegram-bot-envelope-v1`. Así no se acepta un sobre Site ni una
clave receptora ajena. El sobre contiene campos públicos y ciphertext/tag;
el token y chat ID **no** son argumentos, variables de entorno, texto de
issue/PR, imagen, DB, Site ni logs. `install` toma como máximo 4096 bytes
de ciphertext por stdin y no imprime detalles de error o plaintext.

`install` valida el sobre completo, recipient, tag y formatos de ambos
valores **antes de escribir**. Abre el directorio por descriptores sin seguir
symlinks y lee clave/secretos con `O_NOFOLLOW|O_NONBLOCK`, límite, UID/GID,
modo 0400, enlace único y tamaño exacto. Crea exclusivamente `bot_token` y
`chat_id`, modo 0400, sincroniza y verifica el par. Cualquier archivo previo
de uno o ambos impide replay; un crash después del primer write conserva el
estado parcial para revisión y no reemplaza nada. `verify` comprueba custodia
y formato de los dos archivos sin revelar sus valores, pero no prueba que
el bot sea válido, que el destino pertenezca al dueño ni recepción humana.

El archivo privado es compatible con `TelegramTransport` de ADR0066, cuyo
preflight posterior exige valores y modo owner-only. La comprobación real de
identidad Bot API, destino privado, schema0007/procedencia de DB, release/SHA,
presupuesto agregado, puerto/red y un mensaje sintético de prueba requieren
otro PR y operación protegida en el **workflow existente** (#168). El
stop-test reconoce el servicio opcional sólo en código por ADR0080; no se
despachó una parada después de ese cambio. Sin bot y destino verificados,
el estado operativo Telegram es NO-GO.

## Pruebas y límites de evidencia

Los tests usan token/chat totalmente sintéticos y volumen temporal; cubren
cifrado/des-cifrado, domain/tag/recipient, campos duplicados/desconocidos,
replay, symlink, permisos, enlace duro, identidad, fallo del segundo write y
recibos redactados. El test falló inicialmente porque el módulo no existía;
candidate/checks/revisión exactos se consignarán en el PR. No hubo Bot API,
credenciales reales, migración o efecto host. El escritor central actualizará
estado, plan y checkpoint al integrar esta evidencia conforme a regla 84.
