# R308 — Apertura observada y cuenta regresiva

## Objetivo y autoridad

El titular pidió terminar los pendientes técnicos antes de su prueba integral.
[Issue529](https://github.com/mbalbo2023/boca-socios-assistant/issues/529) registra
la necesidad y los cuatro GO anteriores al código: Arquitectura, Operaciones,
QA y root. Base main1ab24a696bf473f57cdae1ee1f01af024ce1b8e8, árbol2573cc46656559693b776f24b02164a7c6d7ced2.
El monitor actual conserva countdown=None. La fuente fijada en #12,
[faqpauro@345639b](https://github.com/faqpauro/BocaSocios/blob/345639b703f57601a4f7a1e7c85bec4691c63d0d/monitor.py),
lee eventStartTimeUTC separado de ETA y windowStartTime. Es antecedente del
campo; no certifica su entrega actual por el proveedor.

## Decisión y alternativas

Extender el snapshot y la presentación existentes. No crear otro monitor,
timer, motor o sesión. Derivar apertura de ETA/windowStartTime sería una
semántica equivocada. Añadir la fecha a queue_model.ticket convertiría por sí
sola un ticket no vacío en QUEUE_ACTIVE; se descarta expresamente.

## Contrato

1. Leer ticket.eventStartTimeUTC como queue_opening_time_utc FUERA de
   queue_model.ticket. Lectura opcional acotada a string de hasta64 caracteres,
   con excepción local: nunca activa el invalid global del snapshot.
2. Admitir exactamente YYYY-MM-DDTHH:mm:ss[.1..6 dígitos](Z|+00:00), con dígitos
   ASCII y calendario válido. Rechazar naive, -00:00, otros offsets, espacio,
   epoch, bool, números y strings numéricas. No usar fallback. El parser puro
   compartido por productor/codec reside en engine_protocol, sin dependencia
   circular; lo desconocido no altera la observación válida de cola.
3. SessionInspection añade queue_opening_at datetime UTC|None y
   queue_opening_event_id str|None: ambos o ninguno, y observed_at presente.
   Mantener DOM UNVERIFIED. Codec acepta sólo shape nueva completa, R301
   completa y pre-R301 completa. Campos parciales/duplicados/desconocidos y
   UTC inválido se rechazan; límites32768/98304 no cambian.
4. El productor sólo acepta apertura con observación PREQUEUE y event_id de
   la misma muestra; observed_at coincide. Una muestra nueva sin apertura
   borra la anterior. inspect sigue leyendo caché, sin I/O.
5. snapshot toma un now UTC único. La cuenta exige recordRUNNING,
   engine/activation/generation actuales, contexto abierto, sin cancelación,
   cierre o fallo, PREQUEUE, mismo evento/observed_at y edad entre0 y30s.
   Treinta segundos es política nueva explícita de presentación, no gate
   operativo. Calcular max(0,ceil((opening_at-now).total_seconds())). Fuera de
   esas condiciones countdown=None; fecha retenida sólo como histórica.
6. HTML inicial y polling5s existente muestran fecha ART24h y duración.
   Etiqueta: «Tiempo estimado hasta la apertura informada». Cero:
   «Hora informada alcanzada; pendiente de confirmación de la página».
   Ausencia: «Sin fecha de apertura vigente». Un fallo de polling retira el
   número vivo sin añadir timer, controles o cambios de foco. Cero nunca
   cambia la fase ni autoriza acciones.

## Límites

Cuatro fuentes productivas: browser/automatic_observer.py,
browser/engine_protocol.py, integration/engine_sessions.py y panel/engine_view.py.
Mantener ETA, IPC, presupuesto50, SIMULATION_ONLY, passkey y controles.
BLACKBOX synthetic.py/ipc_worker.py sin leer ni modificar; sin proveedor,
reservas, mensajes, host o recursos Porota/PPI durante implementación.
No repetir suites del árbol base ni release/APPLY/recuperaciones aceptadas.
El autor no cuenta como revisor independiente de su código.

## Lo que este cambio no acredita

No resuelve DOM autenticado, confirmación Boca, ganador, comprobante/foto,
destino individual, Telegram físico ni capacidad50. Disponibilidad o formato
actual del proveedor es aceptación pendiente, no un veto al código correcto.
# Adenda de integración — límite del artefacto UI offline

El cierre focal ejecutado por root sobre `72195d9` encontró un fallo real de
`test_http_fixture_models_all_native_redirects_and_preserves_poll_document`:
el JSON determinista ocupa 165160 bytes y excede su límite de 160000. La medida
se obtuvo ampliando el límite sólo en memoria para inspección; no se presentó
esa medida como una prueba aprobada. El import aislado de IPC pasó.

Arquitectura, QA, Operaciones y root dieron GO previo explícito a cambiar
únicamente `_MAX_FIXTURE` y su aserción existente a 170000, en
`scripts/run_engine_dashboard_ui_offline_chromium.py` y
`tests/test_engine_dashboard_ui_offline.py`. Se conserva el rechazo de contenido
sobredimensionado y las demás validaciones. Ningún límite de producto, IPC,
host, CPU, RAM, PID, captura o bundle cambia. Sin minificación de código ajeno.
El autor separado corregirá estas dos rutas y revalidará sólo el fallo y el
borde afectados; el delta requiere revisión independiente final.

