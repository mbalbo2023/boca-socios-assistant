# Próxima apertura: protocolo de observación y criterios GO/NO-GO

**Versión:** 2026-10-28. **Estado:** diseño; sin ejecución ni autorización implícita de compra.

## Propósito y límites

Llegar a la próxima apertura de Boca Socios con una prueba reproducible y
respetuosa del servicio, para despejar incógnitas de integración sin inferir
que múltiples pestañas o tokens mejoran la posición. El alcance inicial es
**observación de un flujo legítimo por socio autorizado y evento**, con
intervención humana para autenticación adicional y para cualquier reserva o
pago. No significa autorización para ejecutar el experimento ahora.

**Prohibido en esta fase:** multiplicar artificialmente entradas a la cola,
eludir desafíos/captchas o límites, rotar IP o identidades, transferir pases,
forjar tokens, probar endpoints no publicados, automatizar reservas reales,
registrar secretos en telemetría o hacer pruebas de carga contra Boca/Queue-it.

La implementación real será una decisión separada y explícita, después de
validar condiciones de uso y consentimiento vigente.

## Qué sabemos y qué es una hipótesis

| Elemento | Estado | Evidencia necesaria |
| --- | --- | --- |
| El cliente público Boca contiene referencias a Queue-it y `queueittoken`. | Indicio en código público; ver [auditoría](QUEUEIT_AUDIT.md). | Captura **redactada** de un flujo legítimo para determinar dónde se usa. |
| Prefila programada puede distribuir posiciones aleatoriamente. | Comportamiento documentado del proveedor, **no prueba de configuración Boca**. | Aviso oficial del evento y observación de cambios de estado. |
| Sesiones duplicadas representan posiciones independientes. | **No demostrado** y sujeto a configuración/controles de unicidad. | No hacer experimentos de multiplicación de identidades. |
| La fila ocurre siempre después del login. | **Desconocido**: puede variar según punto de entrada/venta. | Cronología observable sin credenciales en logs. |
| Token de cola equivale a entrada. | **Falso conceptualmente**. | Confirmación de reserva distinta del pase de Queue-it. |

Fuentes: [Queue-it — Scheduled Waiting Room](https://queue-it.com/product/scheduled),
[Queue-it — Bots & Abuse Management](https://queue-it.com/developers/bots-abuse-management/),
[Queue-it — server-side connectors](https://github.com/queueit/Documentation/blob/main/serverside-connectors/README.md).

## Preparación que sí podemos probar hoy

1. Ejecutar toda la CI, simulación determinista y pruebas de idempotencia
   **sin conectividad a Boca ni Queue-it**.
2. Verificar la restauración de una base **sintética**, límites Docker y
   detención de emergencia sin afectar otras aplicaciones del host.
3. Probar un canal de notificación simulado; medir aceptación por adaptador,
   no afirmar lectura del mensaje por una persona.
4. Medir 1, 2, 4 y 8 `BrowserContext` con una web **local falsa** y detenerse
   ante presión de memoria, CPU, PIDs o `/dev/shm`. Estos números no implican
   concurrencia permitida ni disponible en Boca.
5. Probar que un solo `(member_id, event_id)` crea una única intención lógica,
   también ante reintentos y carreras. No equivale a exactamente una reserva
   externa si Boca no ofrece semántica idempotente.
6. Aprobar por revisión humana PR, acciones de despliegue y arquitectura de
   adaptador. El despliegue futuro al droplet compartido, si se aprueba,
   será **solo por GitHub Actions**, Docker independiente y preflight de
   capacidad/aislamiento. Por defecto queda deshabilitado.

## Durante una futura observación autorizada

Un operador confirma antes del evento: partido y sector elegible, hora
publicada en Argentina/Buenos_Aires, identidad con consentimiento vigente,
reglas de uso del sitio, dispositivo/navegador permitido y cuenta correcta.
No enviar credenciales, códigos de verificación ni links de admisión a
Telegram, repositorios, logs o terceros.

Registrar únicamente **datos estructurales minimizados**:

| Campo permitido | Uso |
| --- | --- |
| `observation_id` aleatorio, evento interno sintético o público | Correlacionar observaciones sin exponer persona/correo. |
| Timestamps UTC y horario local derivados | Reconstruir apertura, pre-queue, cola y notificación. |
| `stage` observado: login/eligible/prequeue/waiting/admitted/checkout | Aclarar orden del proceso; distinguir inferencia de señal verificada. |
| Señal genérica de redirección, código HTTP clasificado y fuente | Distinguir encabezado de fila de confirmación real. |
| Latencia de detección, latencia de aviso y uso local de recursos | Medir mejora de confiabilidad y costo de ejecución. |
| Resultado: no observado, expirado, humano tomó control, confirmado externamente | Evitar interpretar pase de cola como ticket. |

**No almacenar:** URLs completas con query string, `queueittoken`, Queue ID,
`QueueITAccepted` u otras cookies, JWT, credenciales, emails, número de
socio, datos de pago, capturas sin redactar, cuerpos de respuesta, HAR,
identificadores permanentes de dispositivos o huellas de navegador.
Una bitácora mínima con campos permitidos debe configurarse con retención
definida y acceso restringido **antes** de la sesión.

No se abrirán sesiones adicionales, se refrescará compulsivamente ni se
harán reintentos agresivos para obtener mejores posiciones. Ante desafío
antibot, 403, 429 sostenido, condición de uso incompatible o señal de abuso,
**STOP** y revisión manual. La elección de la posición pertenece al
proveedor/operador y no existe promesa de mejora.

## Métricas de éxito medibles

| Métrica | Interpretación correcta |
| --- | --- |
| `valid_session_continuity` | % de sesiones legítimas que conservaron su estado esperado. |
| `admission_to_human_alert_p95/p99` | Rapidez de avisar, **no** mejora del puesto en cola. |
| `duplicate_local_intents` | Debe ser cero por `(member,event)` en pruebas. |
| `unknown_outcome_count` | Reservas ambiguas que exigen reconciliación humana, no reintento automático. |
| `resource_peak` y fallos de worker | Evidencia para dimensionar un Docker separado. |
| `external_requests_per_user` | Visibilidad del uso para prevenir tormentas de reintentos. |

**Resultados inválidos:** comparar puestos entre cuentas sin controlar reglas
de elegibilidad, interpretar screenshots de bots comerciales como capacidad
verificada, afirmar que 250 Queue IDs son 250 entradas, o extrapolar la
simulación a posiciones reales de Boca.

## Puertas de decisión

- **GO en CI:** simulador y pruebas de concurrencia verdes, secretos ausentes,
  logs redactados, límites fijados, cancelación y rollback ensayados.
- **GO para observación manual:** consentimiento comprobado, condición de uso
  revisada, horario confirmado, sin trabajo adicional sobre el sitio,
  registro mínimo definido y persona lista para resolver desafíos.
- **NO-GO para bot en producción:** sin flujo real verificado, sin política
  de errores documentada, sin presupuesto del host, sin aprobación posterior
  de integración/compra, o con mecanismos de defensa activados.
- **Después de la observación:** documentar únicamente hallazgos
  redactados y distinguir cada hecho visto de cada hipótesis por validar.

**Enlace técnico de base:** [investigación Queue-it](QUEUEIT_EVIDENCE_2026.md).
