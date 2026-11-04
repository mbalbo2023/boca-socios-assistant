# ADR 0132: rechazo de claves JSON duplicadas en recibos Telegram

**Estado:** candidato acotado del issue #168. La revisión, CI exacto y fusión
se documentan por separado; este archivo no acredita operación de Telegram.
Fecha: 2026-11-04 (America/Argentina/Buenos_Aires).

## Defecto reproducido

El adaptador `TelegramTransport` aceptaba la respuesta del Bot API mediante
`json.loads`, que conserva el último valor de una clave duplicada. Tres
recibos sintéticos contradictorios eran considerados `api_accepted`:
`ok=false` seguido de `ok=true`, `message_id=0` seguido de `42`, y `chat.id`
distinto del destino seguido del esperado. Esto incumple el criterio
fail-closed de ADR0066: una estructura ambigua no acredita aceptación del API.

La nueva prueba
`TelegramTransportTests.test_duplicate_provider_receipt_fields_are_not_verifiable`
reprodujo los tres casos como FAIL antes de la corrección. No se efectuaron
llamadas de red: la conexión HTTPS fue simulada en memoria.

## Decisión

El parser del recibo rechaza cualquier clave duplicada en cualquier objeto
JSON, incluido el nivel superior, `result` y `chat`. Se conserva el resto del
contrato: host fijo `api.telegram.org`, respuesta limitada, TLS, timeout,
`ok=true`, `message_id` entero positivo y `chat.id` entero idéntico al destino.
El rechazo entra en el mismo resultado `TelegramUnconfirmed` redactado.

El coordinador durable de ADR0066 traduce ese rechazo a incertidumbre y
registra el intento como terminal; nunca intenta reenviar automáticamente.
No se cambia esquema, secreto, texto del aviso, API, frecuencia, configuración,
puerto, Compose, workflow, recurso o capacidad. No se inspeccionan ni alteran
los módulos de navegador reservados al dueño.

## Límites y cierre

Una regresión offline no verifica token, chat privado, entrega humana ni
instalación del worker. El controlador BETA físicamente arrancado en el
checkpoint #45 conserva Telegram apagado. `telegram-migrate`, custodia
cifrada, one-shot y arranque integrado siguen sujetos a las puertas
protegidas existentes y a evidencia real separada. No repetir los runs GREEN.

Cerrar este cambio exige el test rojo previo, test corregido en verde,
Ruff/formato, Mypy estricto, suite y policy gate, CI y revisión técnica sobre
SHA exacto, y reconciliación por el dueño documental en el issue #45.
