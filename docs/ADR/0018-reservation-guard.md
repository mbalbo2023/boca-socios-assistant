# ADR 0018: una concesión local antes de cualquier intento externo

**Estado:** Propuesto, actualizado 2026-10-29 ART. Issue #37; PR #38 depende de #36. No se
habilita ningún adaptador real.

## Decisión

`ReservationAttemptGuard` se apoya en `ticket_requests.request_id`, que ya
representa una única intención por `(member_id, event_id)` y cantidad 1. La
migración 0003 añade una fila por intención, con FK restrictiva, token aleatorio
de concesión y estados `in_flight`, `needs_review` y `provider_ack_reported`.
Una transacción `BEGIN IMMEDIATE` inserta esa fila **antes** de cualquier I/O
externo. Sólo el primer competidor recibe el token; los siguientes reciben
`None`. Si el proceso cae entre el commit y la llamada externa, la concesión
queda consumida. El vencimiento sólo marca `needs_review` y jamás reabre la
concesión. Se necesita comprobar el resultado con Boca y decidir por separado
un eventual reintento. En esta fase no existe operación para rearmar el gate.

`resolve` acepta el token original y una declaración de resultado. Repetir la
misma declaración es idempotente; un token distinto, declaración contradictoria
o éxito declarado después del plazo falla cerrado. `provider_ack_reported`
significa **declaración del futuro llamador**, no evidencia de reserva. El
modelo no guarda usuario, contraseña, URL, cookie, cola, confirmación externa,
ni texto libre. Los timestamps son segundos Unix de un reloj confiable que el
futuro adaptador tendrá que aportar; la clase no consulta el reloj del host.

## Límite de seguridad

La DB sólo impide dos concesiones locales para el mismo `request_id`. No puede
impedir una llamada externa hecha fuera de este gate ni ofrecer idempotencia de
compra con Boca. Tampoco vincula dos IDs internos que representen al mismo
socio; hace falta identidad de membresía única y verificada. Antes del uso
real, revisar la semántica del proveedor, consulta de resultados ambiguos,
elegibilidad, error humano, cancelación, conservación y borrado de datos,
coordinación multiworker, clock skew y cuenta autorizada. Los estados del
panel de simulación no se modifican y no se confirma ninguna entrada real.

## Verificación

Pruebas locales de 12 competidores, reinicio, vencimiento sin reintento,
fencing, resolución contradictoria, FK, cancelación y checksum. Todos los
casos usan SQLite y datos ficticios, sin abrir páginas sintéticas ni Boca.
La migración es aditiva y no se ejecuta en el runtime actual. CI y revisión
técnica del agente de SHA exacto, registradas según ADR 0038, preceden el
merge. El despliegue de simulación conserva sus gates de Actions y capacidad;
esta pieza no constituye un intento externo ni cambia el semáforo de fuentes.
