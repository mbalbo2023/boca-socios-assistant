# ADR 0051: dispatcher sintético acotado sobre el outbox durable

- Estado: propuesta para integración revisada; ensayos offline solamente
- Scope: issue #133, PR #134
- Relacionada: ADR 0016 (outbox durable offline)

## Contexto

El outbox SQLite ya implementa deduplicación, leases con fencing, rate limit,
backoff, TTL y tombstones. Faltaba ejercitar un ciclo de consumo sin introducir
credenciales, destinatarios ni envíos externos. No se necesita otra migración
para esta prueba de integración.

## Decisión

`SyntheticDispatcher` recibe el outbox existente, un reloj de pared inyectado y
un puerto async `SyntheticTransport` exclusivamente de ensayo. No hay transporte
real, red, Telegram, configuración de destinatarios ni integración al runtime.
El puerto recibe sólo UUID opaco, clase de aviso y texto allowlisted; nunca el
payload original ni el token de lease. Sus implementaciones deben cooperar con
la cancelación de asyncio: el timeout no es un sandbox de código arbitrario.

Cada tick reclama de a un aviso y realiza como máximo `max_per_tick` llamadas
(1–100); el rate limit durable del outbox sigue aplicándose. Cada llamada tiene
un timeout configurable mayor a cero y hasta cinco segundos. El tick termina
al agotar el límite o no encontrar trabajo elegible.

| Resultado sintético | Settlement durable |
| --- | --- |
| `accepted` | `accept`, con lease/attempt fencing |
| `retryable` | `fail`, respetando backoff, retry-after, TTL y máximo de intentos |
| `permanent` | `fail(retryable=False)`, tombstone exhausted |
| `ambiguous`, excepción, resultado inválido o timeout | `fail(retryable=False)`, tombstone exhausted |

La cancelación intenta persistir ambigüedad terminal y se propaga. Si falla el
settlement (por ejemplo, lease vencida/reasignada), el tick se detiene con error
redactado, sin modificar una lease más nueva ni reclamar otro aviso. El reporte
sólo cuenta outcomes sintéticos correctamente asentados: no prueba entrega por
un proveedor; un outcome retryable puede agotar el presupuesto existente.

## Límite explícito: crash y ambigüedad

Un crash duro entre la llamada sintética y el settlement deja una lease que el
schema actual vuelve a intentar después de vencer. No hay garantía exactly-once
ni reconciliación durable del resultado desconocido. Una prueba documenta esta
limitación, además de las pruebas de dedup/restart, concurrencia, fencing,
retry-after, timeout, cancelación y límites.

Antes de cualquier transporte real se requiere otra decisión e implementación
para registrar/reconciliar la ambigüedad durable antes de reintentar, incluyendo
la semántica de idempotencia del proveedor. Este dispatcher no habilita por sí
mismo Telegram, notificaciones reales, readiness beta ni evidencia Boca.

## Reconciliación del candidato

El candidato se reconstruye sobre `main`
`4922e45b5e2e38242263b6ba10969a8190aa939a`, conservando la historia de #134
y sin cambiar implementación ni pruebas del dispatcher. Los once casos de
integración local se verificaron nuevamente con el preflight SQLite de #141;
las validaciones completas de Actions se registran sobre el SHA final en el PR.
Este documento describe un candidato hasta su merge, no una capacidad del host.
La integración no conecta el consumidor al panel ni al motor: los avisos locales
requieren un contrato de lectura separado y la entrega externa sigue diferida.
