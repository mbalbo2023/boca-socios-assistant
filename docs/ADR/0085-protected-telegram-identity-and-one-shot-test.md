# ADR 0085: identidad Telegram y un único envío sintético protegido

**Estado:** decisión candidata de issue #202, aceptada sólo al integrar su PR
con checks y revisión exactos. Diseño: 2026-11-01
(America/Argentina/Buenos_Aires). Este cambio sólo agrega código y pruebas
falsas; no configura el droplet ni envía un mensaje real.

## Decisión y custodia del destino

Una operación `telegram-test` se incorpora al workflow manual Boca existente,
después de ADR0084. Hereda actor/repositorio/main, primer intento, entorno
protegido, release y manifiesto exactos, digest inmutable, SSH fijado, hash de
Compose BETA, start-existing y stop-test en el mismo job. Además requiere
`BOCA_TELEGRAM_OWNER_READY=ready` y dos secretos del entorno protegido:
`BOCA_TELEGRAM_EXPECTED_BOT_ID` numérico y
`BOCA_TELEGRAM_EXPECTED_CHAT_HMAC` de 64 hex. El dueño sólo debe establecerlos
después de verificar por un canal propio el bot y el chat privado deseados.
El HMAC-SHA256 se calcula **fuera de GitHub** sobre el ID decimal canónico del
chat, usando el token del bot sellado como clave. Ni token ni chat ID entran a
inputs, argumentos, variables del runner, logs, DB o PR. El HMAC no revela un
ID numérico de baja entropía si el recibo se ve, y el marcador protegido
expresa una afirmación humana separada del resultado de la API. Sin esos tres
datos la operación falla antes del acceso host.

Un contenedor único con imagen exacta lee los archivos privados de ADR0083,
comprueba UID/modo y cgroup v2 efectivo 0.25 CPU/128 MiB/32 PID, y luego
consulta sólo `https://api.telegram.org` con TLS, timeout de 3 segundos por
petición, respuesta limitada a 4096 bytes y sin seguir redirects. `getMe`
debe devolver el ID de bot afirmado y `is_bot=true`; `getChat` debe devolver
el mismo ID del destino numérico positivo y `type=private`. El HMAC del
destino se compara antes de contactar la API. Las especificaciones de los
métodos y tipo privado son las del [Bot API oficial](https://core.telegram.org/bots/api).
El token necesariamente aparece en la ruta HTTPS enviada a Telegram, nunca
en excepciones o recibos. `getChat` y la afirmación humana reducen el riesgo
de destino equivocado; la aceptación posterior de `sendMessage` no prueba
lectura o recepción por una persona.

## Un solo intento y parada

Antes de la primera llamada `sendMessage`, el proceso verifica schema0007
con checksums exactos, exige outbox y ledger de intentos vacíos, e inserta
una única notificación `HEARTBEAT` con UUID determinístico fijo para esta
aceptación. El coordinador ADR0066 reclama sólo una, persiste la intención
`prepared` **antes** de red y usa exclusivamente el texto allowlist
`Simulación: seguimiento sintético activo.`, sin datos de socio ni entrada.
Confirma éxito sólo con un resultado Bot API
para el chat exacto, un `message_id` positivo y el registro local
`api_accepted`. Timeout, crash, respuesta contradictoria o fallo al asentar
son NO_GO/ambiguous y no se reintentan automáticamente. Cualquier dispatch
posterior encuentra el outbox no vacío y se niega a mandar otro mensaje.
No hay login, reserva o compra.

El controller instalado debe estar positivamente **parado** y tener
imagen/revisión, puertos, volúmenes y red exactos por ADR0084. El test usa
una red Boca separada `boca-socios_telegram_egress`, con driver/etiquetas y
sin peers previos, sin puerto publicado; el volumen data es RW para el fence
y el volumen Telegram RO. Un contenedor de nombre
`boca-socios-telegram-test-1`, etiquetas exactas y sin `--rm` conserva su
identidad si el Docker CLI termina o expira. `stop-test` reconoce este caso
únicamente si imagen local/digest/revisión/comando, recursos, UID, mounts,
red, puertos, capacidades y entorno coinciden; ante un elemento extraño no
detiene ninguno. En éxito el host verifica el recibo, el contenedor detenido
y sus montajes/configuración antes de quitar **sólo** ese contenedor
desechable; verifica la red Boca vacía antes de quitar **sólo** esa red. El
inventario vuelve al controller parado y sus volúmenes. Ante incertidumbre
preserva contenedor, red y todos los datos para revisión. Un paso `always()`
tras el marcador exige el recibo de `stop-test` en el mismo job.

## Evidencia y límites

Pruebas falsas de Bot API y SQLite ejercitan bot/chat privados, HMAC erróneo,
grupo rechazado, fence, aceptación y timeout terminal; fake Docker verifica
identidad/aislamiento y la ausencia de `rm` ante un recibo falso. El primer
commit de tests falló porque no existía el módulo de one-shot; SHA, checks y
revisión se consignan en el PR de #202. La validación PR no envía tráfico
público. La operación real sigue **NO-GO** sin token, chat privado y
afirmación del dueño, release/host observados y entorno protegido. El
escritor central actualizará estado y checkpoint después del merge según
regla 84.
