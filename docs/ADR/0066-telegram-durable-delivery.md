# ADR 0066: envío Telegram con incertidumbre durable

**Estado:** candidato de #158, pendiente de PR, revisión y CI. Fecha de decisión
de diseño: 2026-11-01 (America/Argentina/Buenos_Aires).

## Alcance y contrato

El dueño amplió la BETA para incluir Telegram en el
[checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6552258326).
Este candidato agrega un adaptador de **envío saliente explícito**, sin arrancar
un trabajador al importar el módulo o iniciar el controlador. La composición
runtime, los secretos del bot/destino y la prueba de recepción siguen siendo
gates separados. Un aviso local persistido no acredita envío Telegram.

El único método remoto implementado es
[`sendMessage`](https://core.telegram.org/bots/api#sendmessage) del Bot API,
por HTTPS a `api.telegram.org`, sin redirecciones. El cuerpo contiene un chat
numérico configurado por archivo privado y el texto estático de `_SAFE_NOTICE`;
no incorpora socios, credenciales, identificadores de intento, URLs, cookies,
payloads ni errores. Una respuesta HTTP 200 con `ok=true`, `message_id` entero
positivo y `chat.id` igual al destino se registra como `api_accepted`: **aceptación
del API**, no entrega al dispositivo, lectura humana ni reserva.

El token y chat ID se leen de dos archivos externos regulares, no symlinks,
legibles sólo por su dueño (sin bits de grupo/otros). El adaptador no guarda
esos valores en DB, imagen, GitHub ni `repr`; errores públicos son genéricos.
La prueba previa a reclamar un aviso exige archivos y formato válidos. Aun así,
un cambio entre prueba previa y envío se trata como incertidumbre, nunca como
permiso para repetir. La conexión usa TLS del sistema, plazo de socket de tres
segundos, respuesta limitada a 4096 bytes y límite total de cinco segundos
desde el coordinador. No se parsean instrucciones ni se aceptan callbacks del
proveedor.

## Estado durable y fallo por cierre

La migración opt-in `0007_telegram_delivery.sql` crea
`telegram_delivery_attempts` con UUID lógico, intento, estado, tiempos y, sólo
tras confirmación del API, ID de mensaje. No guarda destinatario ni texto.
El coordinador reclama el outbox SQLite existente y **confirma la marca
`prepared` antes** de cualquier llamada de red. La selección del outbox excluye
para siempre un UUID con marca Telegram, aun si la lease vence o el proceso
reinicia. `api_accepted` y `ambiguous` se asientan junto con el estado terminal
del outbox en una sola transacción. Una excepción, cancelación, timeout,
respuesta inválida o rechazo del API se clasifica conservadoramente como
`ambiguous`/`exhausted`, sin reintento automático. Un crash duro después de
`prepared` deja `needs_review` visible; puede haber ocurrido antes, durante o
después del envío. No se afirma entrega exactamente una vez.

La recuperación de una marca incierta exige una reconciliación manual
específica antes de cualquier nueva intención. El Bot API `sendMessage` no
ofrece una clave de idempotencia comprobada para reintentar a ciegas. Tampoco
hay una opción de "reenviar" en este cambio. El dispatcher sintético histórico
permanece aislado y no se usa como transporte real. `list_local_notices` sólo
lee metadata de avisos, con límite de 1 a 100 y sin crear una DB. Su caller
debe comprobar identidad/permisos de dueño antes de mostrar los datos; el
Site no recibe token, chat ID, SQLite ni acceso al envío.

## Evidencia y límites de este candidato

Base comprobada al comenzar: main
`213be4903669c6e88122a536ad8fee6785c997ac`; CI
[41263234770](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41263234770)
y scan [41263234803](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41263234803)
verdes sobre esa base. Este PR aún no es main ni host. Pruebas locales con HTTP
falso y SQLite temporal verifican aceptación del API, secreto ausente antes de
claim, respuesta no verificada, excepción, concurrencia y crash tras marca o
ack previo al settlement. Los controles completos de candidato/Actions se
registrarán en el PR sobre su SHA exacto. No hubo token, destino ni mensaje
real; sin esos recursos no puede validarse Telegram extremo a extremo.

No se ejecutaron acciones Boca, migraciones sobre datos del droplet, release,
instalación, backup ni operación de otro proyecto. La selección de recepción,
custodia de bot/destino y composición de un trabajador Boca apagado por defecto
son trabajo de integración documentado por #45; no hay envío automático desde
el panel. Si el Bot API falla, mostrar el aviso y su estado en el panel sin
inventar entrega.
