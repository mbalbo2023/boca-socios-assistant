# BOCA G2 — tres pantallas para QA Samsung (diseño congelado)

Fuente canónica: [issue #417, diseño G2](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6920849607), [QA y RCA](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6920724311), [cierre de G1](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6921080464), [4/4 PRE_CODE](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6921095928). Base W `55da98df6713d40ebf1455fb328005544043d091`.

## Intención

Tincho controla la BETA desde Samsung con Voice Access. El menú de 11 enlaces lleva a varias vistas idénticas y es difícil entender si los motores están trabajando. Debe haber exactamente tres destinos principales: **Control**, **Actividad**, **Configuración**; las secciones secundarias siguen disponibles. La UI sólo exhibirá observaciones recibidas: no confundirá 25 solicitudes con sesiones físicas, un refresh de panel con un worker activo, ni un fallo de acuse con ausencia de evento.

## Alternativas consideradas

1. **Elegida: reorganizar componentes existentes**. Mantener formularios y sus campos de cada inicio en Control (los conteos bajo `<details>`; socio requerido visible); conservar SITE_URL persistente y accesos secundarios en Configuración. Combinar la vista existente del worker y las observaciones de los dos motores lógicos en Actividad. No añade almacenamiento ni backend.
2. Mover conteos y socio a Configuración: exige persistencia entre pantallas, crea dos fuentes de estado y cambia alcance de CSRF/POST. Descartada.
3. Crear dashboard/monitor independiente: duplicaría polling, inventario de sesiones y políticas de revelación. Descartada.

## Contratos vinculantes

- Menú privado primario de 3 enlaces claros y accesibles. `/` permanece alias o redirección a Control; `/control` es sólo Control; `/control/actividad` muestra actividad y preserva el parche exacto P1. `/monitor/tokens` resuelve a Actividad **sólo si la sesión tiene `simulation:write`**; los lectores que sólo tienen `local-status:read` conservan la vista de monitor legada. `/monitor/tokens.json`, revelaciones y permisos no cambian.
- Dos motores **lógicos** A colas/tokens y B navegadores/socios comparten **un** worker físico. START/STOP, antifraude y fence actual del POST quedan intactos: `csrf`, `operation_id`, `activation_id`, `generation`, Origin y operación única. El GET de Actividad no consume operaciones ni causa efectos host.
- Control muestra dos tarjetas, fase/estado/última muestra, START/STOP y motivo verificable de cada botón deshabilitado. Conteos propuestos 15 Chromium/5 Firefox/5 WebKit en un `<details>` **dentro del formulario de inicio**; selector `member_id` requerido **visible** para que el foco y la validación HTML funcionen. Ninguna nueva preferencia persistente.
- Actividad muestra dos motores, contadores y sesiones existentes, evidencia de navegación `SITE_URL` (sólo `STARTED`/`RETURNED`/HTTP/`FAILED` realmente observados), evento/cola/Queue ID/tokens observados sin secretos, actividad redacted del worker y tiempos separados de consulta y actividad. Reutiliza `/control/motores.json` y `/control/actividad.json` con polling de cinco segundos y mensajes de error/histórico. `WORKER_RECEIPT_UNVERIFIED` significa falta de acuse físico, no NO_EVENT.
- Configuración conserva SITE_URL, acceso a Socios, Telegram, Estado, Avisos, Simulación y eventos. No provisión de admin/custodia ni sender Telegram; no navegación externa ni reserva real.
- Mantener passkey, CSP estático con hash, CSRF, permisos, almacenamiento privado y revelación de secretos sólo por canales propietarios originales. Preservar `synthetic.py` e `ipc_worker.py` BLACKBOX, Porota/PPI y otros recursos host. Todas las operaciones físicas futuras exclusivamente mediante GitHub Actions Boca y nuevos GO_OPERATION.
- P1 (2 archivos, SHA de diff `f0607e6dcd2a37b4c5e024df1dfaf2e84f0e7a9f481ff40efd1b1047bc1613b6`) y G3b A1c (7 archivos, SHA de diff `39e2a100d12f0000a61ceb26c1a71f5cdde5f802ecb61b922b8480473a487300`) se recuperan de respaldos exactos, nunca se reescriben. UX+P1+G3b+docs viajan en **un único PR candidato**, sin duplicar suites/builds históricos.

## Criterios de aceptación

1. Las tres páginas son realmente distintas, con navegación Voice Access y deep links secundarios. Ningún enlace circular vuelve falsamente a Control; lectores con permisos limitados no reciben 403 nuevo.
2. Dos motores con controles aislados, botones con causa de deshabilitación visible y validación accesible del socio. Ningún GET crea trabajo.
3. Actividad consulta estados y eventos a intervalos existentes, etiqueta históricos/UNKNOWN y no representa falta de ACK como ausencia confirmada de evento, cola o token. El polling nunca revela secretos.
4. Contratos pasarela, CSP, origin, CSRF, one-use y links protegidos se mantienen. URL configurada no se confunde con visita HTTP real.
5. PR único, TDD focal RED→GREEN por cambios nuevos, cuatro GO_FINAL independientes sobre diff y SHA exactos, cuatro GO_INTEGRATION antes de integración, cuatro GO_OPERATION nuevos antes del host. G3b metadata física antes del APPLY, con engine siempre UNVERIFIED.

## No objetivos

No arreglar a ciegas `WORKER_RECEIPT_UNVERIFIED`, no lanzar procesos/browser/proveedor desde pruebas, no introducir DB/worker extra, no certificar 50 físicos, no real bookings, no Telegram sender ni cambios de Docker/OCI. La causa física requiere RCA específica posterior.
