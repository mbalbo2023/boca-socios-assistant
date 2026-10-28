# ADR 0017: Outbox durable como puerto local de simulación

Status: Proposed, 2026-10-28. Issue #35.

`OfflineSimulation` recibe un `LocalNoticeStore` estructural con `enqueue`.
Tanto el outbox en memoria como el SQLite implementan este contrato. El
instante de aviso se inyecta en segundos Unix para que el almacenamiento
durable conserve plazos válidos después de reinicios; el in-memory exige que
las llamadas sucesivas no retrocedan. Un UUID determinista derivado del
request_id local evita dos registros de la misma notificación.

No se añade una ruta web, transport Telegram, cliente Boca ni import en el
runtime por defecto. El aviso se escribe **después** del paso de pantalla
ficticia y en otra transacción que el ticket intent: un error o corte entre
pasos puede dejar un intento `planned` sin aviso. El reintento local conserva
la fila única, pero no resuelve una operación externa ambigua. Antes de una
reserva real se necesita single-flight durable, reconciliación y política de
reintento del proveedor.

El panel de estado #29 sólo recibe snapshots validados y no presenta IDs ni
credenciales. El servicio de alta #31 permanece sin endpoint hasta aprobar
el diseño #28 y completar autenticación, autorización y TLS. La portada
pública de Boca observada una vez y el script #33 no verifican una reserva.
