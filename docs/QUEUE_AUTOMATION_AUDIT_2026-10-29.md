# Auditoría de automatización y colas virtuales — 2026-10-29

**Alcance:** investigación de fuentes primarias públicas para Boca Socios
Assistant. No se visitó Boca en esta tarea, no se inició sesión ni se obtuvo
una posición de cola. Este documento no autoriza tráfico, reservas ni un
motor de compra. El objetivo del producto es asistencia accesible para un
socio consentido, con una entrada como máximo por socio y partido.

## Hechos, inferencias y límites de evidencia

- El [relevamiento previo del cliente público](QUEUEIT_AUDIT.md) registra
  ramas y cadenas compatibles con Queue-it (`queueittoken`, `/queueit/validate`,
  `inqueue`). Ese relevamiento no demuestra que una cola esté activa hoy, ni
  en qué paso se valida el pase para un partido concreto.
- Queue-it describe varias configuraciones: preventa programada con
  aleatorización al abrir, FIFO después de abrir, modalidad permanente y
  protecciones en rutas distintas. Su documentación es un conjunto de
  posibilidades del proveedor, **no** la configuración observada de Boca.
  [Flujo oficial de Queue-it](https://queue-it.com/developers/how-queue-it-works/).
- Cloudflare Waiting Room es otro ejemplo de proveedor: documenta cookies de
  sesión y renovaciones periódicas. No hay evidencia en este trabajo de que
  Boca use Cloudflare Waiting Room. [FAQ oficial](https://developers.cloudflare.com/waiting-room/troubleshooting/).
- Playwright aísla cookies, almacenamiento y sesiones entre `BrowserContext`.
  Esto sirve para pruebas reproducibles de usuarios distintos; **no** prueba
  que varios contextos de un mismo socio obtengan plazas independientes ni
  autorizadas. [Aislamiento de Playwright](https://playwright.dev/docs/browser-contexts).

## Modelo de amenazas y decisión de ingeniería

| Patrón documentado | Riesgo para socios y el servicio | Control de este proyecto | Verificación admisible |
| --- | --- | --- | --- |
| OAT-005 scalping y OAT-021 denegación de inventario | Acaparamiento o bloqueo de plazas limitadas | Un socio, un partido, una solicitud lógica y una entrada; reconciliación antes de cualquier nuevo intento | Invariantes y concurrencia en DB; contrato externo sólo con revisión |
| OAT-020 agregación de cuentas | Un intermediario puede multiplicar escala y exposición de credenciales | Consentimiento verificable, claves cifradas fuera de DB, cupo por identidad, trazas sin PII | Pruebas sintéticas de aislamiento; alta privada tras revisión #28 |
| OAT-002 token cracking, OAT-009 CAPTCHA defeat | Eludir admisión, desafiar la cola o exponer pases | No adivinar, clonar, transferir o regenerar tokens; parada ante challenge | Observación humana autorizada y redactada, sin resolver challenges automáticamente |
| Tráfico de volumen, múltiples plazas por persona | Afecta equidad, tasa y disponibilidad | Una sesión aprobada por observación; límites estrictos, sin proxies ni paralelismo para mejorar posición | Medición local de recursos, no pruebas de carga en Boca |
| Sesión vencida o resultado incierto | Repetición puede duplicar una acción externa | Estado ambiguo para revisión manual; sin retry automático de reserva | Reinicios y fallos simulados, conciliación externa sólo tras contrato aprobado |

La taxonomía OAT procede de [OWASP Automated Threats](https://owasp.org/projects/automated-threats-to-web-applications/)
y su [guía de gestión de bots](https://cheatsheetseries.owasp.org/cheatsheets/Bot_Management_and_Anti-Automation_Cheat_Sheet.html).
Queue-it documenta medidas de identificación de visitantes y validación de
pases antes de transacciones; también trata múltiples posiciones o compartir
sesiones como abuso. Son controles posibles del proveedor, no pruebas de una
regla concreta de Boca. [Queue-it, bots y abuso](https://queue-it.com/developers/bots-abuse-management/).

## Práctica admisible para el asistente

1. Mantener el contenedor saludable y el motor apagado al arrancar. Un
   diagnóstico sintético bajo demanda debe tener una acción manual, límite de
   tiempo, identidad del operador y evidencia, dentro del único workflow Boca
   protegido. Un deploy o reinicio nunca inicia un navegador ni reserva.
2. Antes de cualquier observación real, definir un objetivo mínimo y una
   sola cuenta consentida, ruta/ventana permitidas y parada explícita ante
   403, 429, CAPTCHA, WAF o página de cola. Preservar los redireccionamientos
   y cookies de una sesión legítima; no fabricar ni modificar pases.
3. Separar hechos observados del sitio, comportamientos descritos por un
   proveedor y supuestos del código. Registrar sólo estados y tiempos
   agregados, con redacción de identidad, cookies, tokens y URL sensible.
4. Probar localmente idempotencia, concurrencia, reinicios, expiración y
   resultado ambiguo. La prueba funcional real requiere el sitio real y
   autorización acotada; un simulador verifica nuestra lógica, no la cola
   de Boca.
5. Antes de una reserva real, exigir revisión del diseño de alta #28,
   protección de `main` #10, identidad externa única, contrato de
   elegibilidad/confirmación/reconciliación, límites del proveedor y decisión
   humana para cualquier compra. Nada de esto está demostrado por una CI
   verde ni por un contenedor saludable.

## Resultado de la auditoría

Las fuentes apoyan una arquitectura de asistencia **de bajo volumen,
consentida, observable y detenible**. No respaldan la hipótesis de que abrir
muchas sesiones equivalga a muchas oportunidades válidas: la posición puede
aleatorizarse, vincularse a identidad o validarse al final según la
configuración. Tampoco hay evidencia de que pasar un URL o token entre
sesiones permita reservar. El estado de Boca y sus condiciones de uso deben
verificarse por separado antes de conectar un motor real. Esta auditoría no
incluye instrucciones ni código para saltar la cola o controles antibots.
