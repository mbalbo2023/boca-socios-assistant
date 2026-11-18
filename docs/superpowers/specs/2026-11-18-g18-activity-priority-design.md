# Boca G18 — Actividad prioriza los dos motores

**Corte:** 2026-11-18 ART. **Base:** `main@b905ecac90050f0f2d8ff0c483f5864bcc7c856c`. **Aprobación previa:** cuatro votos registrados en [#417 G18](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6982664243), con [adenda 4/4 UI-only](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6983036738). **Evidencia de defecto:** captura Playwright G17 #1324: en `/control/actividad` los registros del worker anteceden a los dos motores, que quedan fuera del primer viewport. Es un defecto de presentación; no es prueba de caída física.

## Comportamiento aceptado

1. Mostrar al principio de **Actividad** las tarjetas existentes `_live_card` de Motor A (colas/tokens) y Motor B (navegadores/socios), con estado lógico histórico, causa tipada cuando exista, URL configurada/navegada/final sólo desde sesión, evento, cola, tokens sin secretos, tiempos separados y link privado ya existente. El diagnóstico global **no** encabeza la página.
2. Conservar los fragmentos `#queues_tokens-heading` y `#browsers_members-heading` del Control, apuntando a títulos **visibles** de las tarjetas principales. Los encabezados técnicos anidados tienen IDs distintos y `aria-labelledby` correcto; ningún ID se repite. En pantallas Samsung, conservar controles de tamaño táctil y lenguaje accesible.
3. Por motor, esconder bajo un `<details>` inicialmente cerrado los contadores existentes, distribución, `ol` de sesiones y sus enlaces de inspección. Los IDs y actualizaciones JS de filas permanecen; el dueño puede expandirlas sin perder foco ni contenido.
4. Mostrar **una sola sección global de worker compartido**, inicialmente plegada, después de A/B, con registro, telemetría, pausa/refresco y la misma procedencia. No duplicarla dentro de las tarjetas A/B. Sus IDs y sondeo actual permanecen.
5. Un único GET periódico de `/control/motores.json` actualiza **tarjetas y sesiones** cada cinco segundos mediante los helpers actuales (`_LIVE_PROJECTION_SCRIPT`, `_SESSION_ROWS_SCRIPT`), sin copiar funciones ni crear API. La lectura existente de `/control/actividad.json` conserva su propio sondeo para worker global. CSP calculada para el script real.
6. Nada observado se convierte en “no hay evento”, navegación confirmada, HTTP o token por inferencia; ante error de polling el estado visible queda histórico. Una URL de bearer/query nunca aparece en HTML, JS de estado ni screenshot.
7. **Adenda consensuada:** si `navigation_attempt.sequence` viene como entero estricto 1..3 de una sesión, rotular “Último intento de navegación n.º N de esta sesión”. No sumar intentos por motor ni interpretar 25 contextos solicitados como 25 navegaciones; `0`, `4`, booleanos y cadenas no generan numeración. Mostrar el socio seleccionado de la activación del Motor B en primer nivel **una sola vez**, reutilizando la proyección `member_id`/`MemberView` y el `id` actual `browsers_members-current-member` para polling. La respuesta de tokens no acredita DOM/login exitoso ni entrada/reserva.

## Límites

Único escritor del delta: `src/boca_socios/panel/engine_view.py`, `private_ui.py`, pruebas y estos documentos. El harness offline Chromium sólo puede cambiar si falla concretamente por nuevos `<details>` cerrados o selectores genéricos. No cambiar Control/Configuración, permisos, passkey, CSRF, Origin, formularios, Telegram, motores/worker/IPC, SQLite, fuentes externas, Docker, GitHub Actions ni Porota. **SIMULATION_ONLY y ninguna reserva real.** G17 deploy aceptado; no repetir release ni APPLY.

## Pruebas exigidas

- HTML inicial de Actividad con FAILED/WORKER_RECEIPT_UNVERIFIED/25 pedidos/0 sesiones: A/B preceden a worker global, causa comprensible, URL/HTTP/token no inventado; `<details>` cerrados y sesión/contadores presentes; deep links visibles; sin duplicación IDs/feed ni formularios.
- Node VM de `_SCRIPT` de Actividad con dos respuestas cambiantes: actualización A/B y de sesiones/contadores en ambos motores, una consulta de motor por ciclo; polling fallido etiqueta histórico. Paridad con SSR de los campos básicos, CSP y saneado.
- Playwright Chromium **offline sólo mediante GitHub Actions de Boca tras GO_FINAL**: 412/800/1536 px, encabezados principales visibles, navegación/expansión de sesiones y eventos, sin desbordamiento, controles accesibles, ningún sitio externo. El autor sólo prepara el harness y no ejecuta navegadores locales, ni cloud/browser interno, por instrucción del titular.
- Focales de Actividad, Motor A/B, CSP y seguridad local; regresión completa y Playwright visual por CI del SHA exacto después de los gates pertinentes. No confundir fixture offline con aceptación Samsung privada.
