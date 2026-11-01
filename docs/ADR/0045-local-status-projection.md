# ADR 0045: proyección offline de intenciones locales para futura consola

**Estado:** propuesta de #119, subalcance de #113. Se implementa sólo una
biblioteca; no hay endpoint, listener, autenticación, acceso del Site ni cableado
al runtime. El motor permanece apagado y no hay reserva real.

La proyección abre la SQLite Boca existente en modo lectura, no migra ni escribe.
Comprueba el checksum de las migraciones instaladas y la definición de la tabla
de intenciones; versiones desconocidas y fallos de lectura se rechazan con un
error genérico, sin ruta de DB ni valores privados. Procesa como máximo 200
filas locales. Devuelve conteos tipados con etiquetas que indican su origen
local; el valor SQL `reserved` se presenta únicamente como resultado local
registrado **sin confirmación externa**. Nunca lee IDs, correo, credenciales,
tokens, etiquetas de partidos ni contenido de auditoría.

La antigüedad se calcula a partir del último `updated_at` de una intención,
comparado con un reloj inyectado y un umbral explícito. `empty` significa que
no hay intenciones; `stale` significa que no se modificaron recientemente.
Ninguno indica salud del contenedor, frescura de Boca ni existencia de tickets.
La proyección no es apta para publicarse: incluso conteos agregados podrían
revelar actividad privada. Antes de exponerla, diseñar identidad del dueño,
autorización por lectura, TLS, política de acceso de ChatGPT Sites y un
adaptador HTTP separado, con sus pruebas y revisión. Un Site público sólo
puede usar datos ficticios o agregados aprobados.

Backup/restore sigue diferido por decisión del dueño. Ninguna prueba toca
claves reales, host, Queue-it, Boca, Telegram ni otros proyectos.

## Compatibilidad con migración Telegram 0007 (candidato #175)

La proyección valida también el checksum exacto de la migración opt-in
`0007_telegram_delivery.sql`, integrada por #162. Leer el ledger con un límite
derivado del número de versiones reconocidas más una detecta una versión futura
adicional; cada versión observada debe estar en la lista y conservar su hash.
Esto permite consultar el mismo estado local después de preparar el outbox
Telegram sin aceptar esquemas desconocidos ni modificar la DB por la lectura.
La regresión usa SQLite temporal y comprueba tanto el caso 0007 válido como el
checksum alterado y una versión 8 desconocida. Este cambio no configura bot,
ejecuta la migración en el host, envía avisos ni prueba disponibilidad HTTP.
Los resultados de CI y el SHA exacto se registran en el PR; documentación
central y checkpoint se reconcilian por el responsable de integración.
