# ADR 0017: Outbox durable como puerto local de simulación

Status: Proposed, updated 2026-10-30. Issue #35.

`OfflineSimulation` recibe un `LocalNoticeStore` estructural con `enqueue`.
Tanto el outbox en memoria como el SQLite implementan este contrato. El
instante de aviso se inyecta en segundos Unix para que el almacenamiento
durable conserve plazos válidos después de reinicios; el in-memory exige que
las llamadas sucesivas no retrocedan. Un UUID determinista derivado del
request_id local evita dos registros de la misma notificación.

El coordinador mantiene una concesión local por socio mientras espera al
navegador ficticio. Un segundo alias concurrente del mismo socio se rechaza
antes de invocar el navegador; la concesión se libera también al fallar.
Esta barrera vive sólo en **esa instancia** de `OfflineSimulation`: no cubre
otro coordinador, proceso, reinicio ni una llamada externa. La guardia durable
de #38 es una pieza separada y todavía no está conectada a este workflow.

No se añade una ruta web, transport Telegram, cliente Boca ni import en el
runtime por defecto. El aviso se escribe **después** del paso de pantalla
ficticia y en otra transacción que el ticket intent: un error o corte entre
pasos puede dejar un intento `planned` sin aviso. El reintento local conserva
la fila única, pero no resuelve una operación externa ambigua. Antes de una
reserva real se necesita single-flight durable, reconciliación y política de
reintento del proveedor.

El panel de estado #29 sólo recibe snapshots validados y no presenta IDs ni
credenciales. El servicio de alta #31 permanece sin endpoint; el diseño #28
ya fue integrado, pero faltan autenticación, autorización y TLS. La portada
pública de Boca observada una vez y el script #33 no verifican una reserva.
