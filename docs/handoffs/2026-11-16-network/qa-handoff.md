# Relevo QA — checkpoint sin nuevas acciones

**Ownership de QA liberado.** No queda ninguna edición mía en curso. Esta nota usa exclusivamente evidencia ya reunida; no ejecuté pruebas, código ni operaciones adicionales.

Según el último estado comunicado por root, **main es `b3200f7bc4391156205dab992989a609253ec6ee`**, con **CI1283 y Security1094 SUCCESS**. **El diagnóstico R309 todavía no fue despachado.** R310 tiene tres rutas congeladas y 41 PASS focales informados por su autor, pero **su revisión final independiente sigue pendiente**.

## 1. DOM autenticado, resultado real y comprobante: abiertos

**No está acreditada una sesión Boca autenticada ni un contrato actual de confirmación final.** La autenticación HTTP del child, por sí sola, no demuestra que el frontend tenga incorporada la sesión. `dom_authentication` debe conservar `UNVERIFIED` hasta contar con evidencia positiva y vinculada al socio y a su sesión.

Tampoco está acreditado el productor que conecte una **confirmación real del proveedor** con ganador durable y cancelación de sesiones hermanas. Existen piezas de arbitraje, exclusividad y simulación, pero una señal suministrada por el llamador —incluido `PROVIDER_ACK_REPORTED`— no demuestra una reserva externa. Una respuesta HTTP 200 o una URL de carrito tampoco prueban emisión.

**Decisión expresa de root:** no añadir otro modo de simulación para declarar cerrado ese circuito. Se preservan la simulación y el arbitraje existentes; no hay código nuevo autorizado para adjudicar resultados externos inventados.

**Comprobante/foto:** no se encontró un productor real acreditado ni un contrato de captura y entrega completo. Sigue pendiente junto con la confirmación final.

La búsqueda focal de `capture-25` tampoco recuperó HTML/JS utilizable: los runs `41512196530` y `41537796470` conservan logs y manifiestos de captura pública, pero sus APIs de artifacts devolvieron listas vacías. La captura era del login público; los bytes se eliminaron conforme al diseño histórico. **Los hashes y recibos no reconstruyen esos bytes ni acreditan autenticación.** No repetir Library, referencias de terceros o esas búsquedas sin una pista nueva.

## 2. Destino Telegram por socio: propuesta, sin implementación

La custodia actual es **global**: bot/token/chat y recibos asociados a la instalación. No hay persistencia acreditada de destinos individuales por socio.

La propuesta registrada permite una capacidad de configuración útil sin inventar una reserva: seleccionar socio, stage cifrado, consentimiento firmado del titular, descubrimiento privado con las operaciones de lectura existentes, referencia de destino, visualización y revocación. Reutilizaría custodia y `audit_events`; no requiere inicialmente una migración SQL ni nuevas claves durables.

Quedaron dos obligaciones importantes:

- La identidad durable del destino debe depender de **socio, binding, revisión y bot**, con una vía explícita de adopción global. **No encadenar toda configuración individual al nuevo SHA en cada deploy.**
- No guardar chat plano en logs, duplicar el token global, activar un sender ni enviar mensajes. Un fallo entre escritura privada y asiento durable no puede aparecer automáticamente como `BOUND`.

**Root suspendió cualquier implementación o scaffolding individual hasta resolver el diagnóstico y el contrato global de custodia/adopción.** Si no existe stage o custodia válidos, puede requerirse entrada privada del titular. La propuesta sigue abierta, sin código autorizado.

## 3. R308: revisión de producto cerrada

QA dio GO a `72195d97923f6bc7cf8b293eb34c1910d87cd919` y a la corrección de cota offline `67f932dfdb349c2c006d8e08b7b6155e3437fd71`.

El countdown utiliza la fecha candidata `ticket.eventStartTimeUTC`, separada del modelo de cola, con parseo cerrado y vinculación a PREQUEUE, evento, observación e identidad vigentes. La vigencia de 30 segundos es una decisión de presentación, **no una prueba de autenticación ni una confirmación de apertura efectiva**. Alcanzar cero conserva la indicación de espera de confirmación de la página.

La cota del artefacto offline cambió únicamente de 160.000 a 170.000 bytes ante la medición real de 165.160. No se ampliaron límites productivos.

**La revisión y evidencia offline están cerradas; el comportamiento contra una sesión real del proveedor no está acreditado.**

## 4. R309: código aprobado; diagnóstico real pendiente

GO final de QA al producto corregido en `25ed05ed05f9f7db47cdc489e69922ddc1450ec9`. Se cerraron los tres hallazgos:

1. Uso de los lectores reales de R, conservando guardas de metadatos.
2. Intérprete absoluto `/app/.venv/bin/python` en creación y attestor.
3. Transporte incierto produce primero `INCOMPLETE_NO_GO`; el frame original queda como evidencia no autoritativa, conservando CID y retirada.

También di GO final a `35dffc177f87f05fd5bb14616edc887e067f7cba`: **cuatro archivos de tests, seis literales**, sin cambios del workflow/producto ni eliminación de aserciones; evidencia focal **5 PASS**. Corrige las expectativas históricas que fallaron en CI1281.

La medición del paquete corregido fue **47 entradas, 490.980 bytes agregados y ZIP de 135.443 bytes**, dentro de las cotas autorizadas. El codec diagnóstico continúa limitado a 4.096 bytes.

**Nada de esto acredita `PREPARED`, adopción, custodia válida o la causa de 1167.** R309 es diagnóstico: no prepara, publica, provisiona, envía ni autoriza automáticamente una acción posterior. El próximo resultado debe evaluarse con su transporte, guardas y retirada completos. Root conserva la operación mediante Actions.

## 5. R310: diseño aprobado; revisión final y medición pendientes

Mi GO previo corresponde a C1–C10 de [issue531](https://github.com/mbalbo2023/boca-socios-assistant/issues/531), con las precisiones aceptadas por root:

- Pool y registry reales de **`src/boca_socios/browser/engine_sessions.py`**; el coordinador está en `integration/engine_sessions.py`.
- Dos grupos de 25; cada uno 15 Chromium, 5 Firefox y 5 WebKit. **50 contextos y 50 páginas distintos.**
- Escribir **primero las 50 marcas** y después leer/verificar las 50; la comprobación inmediata por contexto no basta para demostrar aislamiento.
- Cerrar A por activación, comprobar 25 cierres y B utilizable, rechazar replay sin recreación y cerrar finalmente todo. Cierre incierto o pool en estado `poisoned` impiden GO.
- Perfil exacto **1 CPU / 768 MiB / 128 PID**, guardas reales, cadencia de 8 s y límites **600 s de trabajo / 15 s de cierre independiente / 650 s exteriores**.
- Métricas ausentes como `UNKNOWN`, sin convertirlas a cero ni imponer margen preventivo.
- Recibo cerrado de **32.768 bytes como máximo**. GO global exige escenario completo, recibo válido, exit/transporte conocidos y retirada verificada del CID. Un recibo interno favorable no prevalece sobre incertidumbre exterior.
- Sólo runner offline, tres rutas, sin selector host ni proveedor. No tocar BLACKBOX ni ampliar recursos automáticamente.

**Los 41 PASS informados no sustituyen la revisión final independiente del commit congelado.** Después queda la única medición física autorizada por Action, según la secuencia de root y tras cerrar el diagnóstico R309.

Actualmente sigue acreditado el **límite lógico 50**. No está acreditada la capacidad física de 50 en el runner ni en el droplet. Un eventual PASS del runner sólo acreditará su imagen, perfil y entorno; tampoco probará STOP del panel, IPC/coordinador durable, autenticación o reservas.
