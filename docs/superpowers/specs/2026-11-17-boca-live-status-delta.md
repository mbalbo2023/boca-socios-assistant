# Boca G14 — Vista inmediata de estado de los dos motores

Fecha: 2026-11-17. Fuente base: `main=9fe68c3310bfbdb8e44e7f33f7c578e51fc7e3fb`, UI #540 instalada (G13, issue #417).

## Problema observado por el titular

En Samsung, `/control/colas` muestra `FAILED / WORKER_RECEIPT_UNVERIFIED`, 25 contextos solicitados y cero creados/activos, pero la actividad queda por debajo de largos formularios y explicaciones. No hay una ventana breve que conteste «¿qué está haciendo el bot ahora?» ni una cronología visible de sus señales. `/control/socios` necesita el mismo patrón. Las capturas aportadas son evidencia visual de diseño, no prueba de que un worker esté funcionando.

## Contrato de interfaz

1. **Dos páginas, dos estados separados**: la primera sección visible de cada página de motor tendrá una tarjeta «Estado del bot · Motor A/B» antes de configurar o iniciar. Debe identificar estado, etapa, último cambio del *motor* (`engine.updated_at` del ledger), última observación real de la *página* (`sessions[].observed_at`, o sin muestra), evento/cola, contextos creados/activos, tokens o enlaces observados y error o bloqueo. Mensajes breves, legibles con Voice Access y sin scroll horizontal; foco y botones grandes.
2. **Actualización cercana al tiempo real**: reutilizar `GET /control/motores.json` y `GET /control/actividad.json` (privados y existentes); máximo un intervalo de 5 segundos; `cache: no-store`, sin POST ni arrancar automáticamente. Mostrar por separado hora de consulta y fecha de la última señal efectiva; una consulta de estado no constituye un evento. Si falla un GET, conservar último dato identificado como histórico/no verificable. No generar entradas sintéticas ni alterar activaciones.
3. **Cronología legible**: 5 registros recientes como máximo, cada uno con hora, origen y texto allowlisted de `WorkerActivitySnapshot`. Incluye diagnósticos o telemetría histórica y son datos del **worker físico compartido**, no prueba de navegación reciente ni datos adjudicados falsamente a cada motor. Si no hay eventos, decir «Aún no hay actividad verificable». El usuario puede abrir la actividad detallada existente.
4. **Veracidad**: `WORKER_RECEIPT_UNVERIFIED` implica «Arranque sin confirmar», nunca «No hay evento». Si hay cero sesiones, evento y cola quedan «No comprobados». Solo usar `NO_EVENT_CONFIRMED` de una sesión realmente observada para «La sesión N informa que no hay evento», sin extrapolar a las demás. `has_target_url` señala enlace recibido (no ticket confirmado) y permite mostrar acceso **privado** a la inspección/copia mediante `/control/sesiones/<UUID>`; jamás revelar token, cookie, chat ID, query bearer o URL secreta en HTML/JSON público, cronología ni logs.
5. **Motor B**: mostrar fase de acceso SITE_URL/autenticación/DOM cuando esté observada y errores cuando existan. No declarar entrada confirmada, captura terminal o reserva real si no existe recibo funcional; mantener `SIMULATION_ONLY`.
6. **No regresiones**: conservar formularios, operaciones de un solo uso, ACL, CSP basada en hash, identidad de workers, presupuesto de 50 contextos, lógica de parada, datos/passkeys y aislamiento de Porota. No inventar endpoints ni duplicar monitor.

## Telegram: alcance separado, pendiente de dictamen de nueva política

El titular corrigió el criterio de producto: quiere poder ingresar token del bot y chat ID directamente en el panel privado `localhost:8443`, sin el trámite adicional X25519/recibo. Antes de modificar el backend hay que comprobar que el controlador pueda persistir y utilizar ambos secretos en la custodia real, sin exponerlos en HTML, logs, CI o GitHub y sin iniciar el sender por accidente. La mejora visual de motores no depende de esta migración de configuración y no autoriza por sí sola una operación de Telegram ni un nuevo deploy.
