# Boca G17 — evidencia comprensible de los dos motores

**Fecha:** 2026-11-18 ART. **Fuente:** G16 `main@75b00d8e1cd903d3d727a2628134a27fd740fc42` instalado mediante APPLY #1228 ACCEPTED; no repetir. **Caso QA:** captura del titular 08:55 ART, `Motor A: Falló`, sin URL, error ni tokens comprensibles. **Trazabilidad y 4GO PRE_CODE:** [issue #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6978194497).

## Hechos separados

- G16 oculta en el resumen de Motor A la navegación que sí calcula la proyección y que muestra parcialmente B; el resumen omite URL/fecha/HTTP, aun cuando una sesión los haya comunicado. El registro compartido del ejecutor se coloca dentro de esa tarjeta sin diferenciación visual suficiente. Los controles repiten estado/título.
- `EngineSessionCoordinator` puede terminar `WORKER_RECEIPT_UNVERIFIED` sin sesión, cuando el inicio físico no recibe acuse. Con `sessions=[]` no existen URL visitada, HTTP, evento, cola o tokens por sesión. La captura no permite atribuir causa al proveedor.
- Action Boca READ_ONLY #1237 (run `44300816017`, 09:07 ART) confirmó controller HEALTHY y worker `CREATED/PID0`, STOP APPLIED/cause NONE. **Es un estado físico posterior, no el RCA de la falla lógica observada a las 08:55.**

## Decisión de diseño

Reutilizar **sin cambios de contrato** `GET /control/motores.json`, `_live_projection`, `navigation_attempt`, `configured_url`, `display_url`, `event_state`, `queue_state`, `has_target_url`, `has_auth`, el sondeo de cinco segundos y la inspección privada `/control/sesiones/{uuid}`.

En una tarjeta principal visible, Motor A y Motor B deben distinguir:

1. **Estado lógico y etapa** con la hora de la última modificación real, no la hora del refresco. Ante `WORKER_RECEIPT_UNVERIFIED`/0 creados, explicar que no se confirmó la apertura del navegador, que no hay inspección de página y que la causa física específica no consta. No sustituirlo por una conjetura de HTTP, permisos, red o CAPTCHA.
2. **URL configurada**, **última navegación efectivamente registrada** (propósito, URL saneada, hora, resultado y HTTP sólo si `RETURNED` lo acredita) y **última URL final observada**, cada una con su propio origen/evidencia. URL guardada en Configuración no acredita navegación. Si no hay sesiones, no inventar SITE_URL: mostrar “No disponible en observación; ver Configuración”. Si la sesión está inactiva, marcar navegación/URL como *evidencia histórica*.
3. **Evento**, **cola** y **tokens** por sesión, distinguiendo `observado`, `ausencia explícitamente informada por página` y `no comprobado`. No asociar un resultado de una sesión con todas las demás ni confundir `NO_EVENT_OBSERVED` agregado con confirmación del proveedor.
4. **Tokens/enlaces observados** mediante presencia y conteo, nunca bearer en resumen ni logs. Enlace existente de inspección privada visible sólo cuando `has_target_url` o `has_auth` lo acredita; indicar qué sesión se podrá abrir.
5. **Diagnóstico global del ejecutor** en `<details>` cerrado por defecto, rotulado como fuente compartida sin navegación del motor; conservar mensajes allowlist y ventana temporal. Quitar el prefijo de origen duplicado sólo en la presentación si puede hacerse sin alterar allowlist ni procedencia.
6. **Acciones y sesiones avanzadas** debajo de la tarjeta principal, sin repetir estado/etapa en otro bloque inmediato. Tres destinos principales Control/Actividad/Configuración conservados; no crear otro menú, API, polling, página ni motor. Botones y enlaces accesibles mediante Voice Access.

## Fuera de alcance

No tocar coordinador, `except Exception`, worker, navegación Boca/Queue-it, `synthetic.py`, `ipc_worker.py`, IPC, datos, secrets, Docker, Telegram sender, Workflows, real bookings ni Porota. La clasificación tipada de errores internos requiere RCA y un voto separado. `/ingresar` y activación/configuración Telegram conservan los pendientes funcionales conocidos; esta corrección no los declara resueltos.

## Aceptación

- HTML inicial y sondeo JS coinciden en los mismos campos y etiquetas; la actualización fallida marca histórico, sin reescribir evidencia previa como actual.
- Fixtures: `FAILED/WORKER_RECEIPT_UNVERIFIED/25 solicitados/0 creados`, sesión con navegación fallida, HTTP `RETURNED`, token privado, evento `NO_EVENT_CONFIRMED` frente a `UNRECOGNIZED`, cola `QUEUE_ACTIVE`, sesiones cerradas/históricas, error de polling; A/B aislados.
- La URL pública saneada sólo conserva `origin + pathname`, nunca query, fragment, userinfo ni tokens. CSP hash y rutas protegidas inalterados; ningún GET activa trabajo.
- Captura offline móvil y tablet Voice Access verificada antes de `GO_FINAL`; captura de fixture no sustituye QA de la página privada instalada ni acredita tokens reales.
- Un candidato G17, un PR revisado y gates exactos; cualquier nueva release/deploy requiere 4GO_OPERATION, observaciones Boca P→C y la higiene de PRs vigente, sin repetir G16.
