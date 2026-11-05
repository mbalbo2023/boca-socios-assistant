# ADR0143 — Intenciones de inicio/detención del bot y Chromium con ACK protegido

**Estado 2026-11-04 ART:** propuesta de código y pruebas del issue #328,
PR DRAFT separado. **No es autorización de despacho, instalación ni recibo
de host.** Es complemento de ADR0133, no reemplaza el control de admisión.

## Necesidad y límite arquitectónico

El dueño opera Samsung Chrome mediante Termius en `http://localhost:8443`.
El panel ya puede pausar/reanudar **nuevas simulaciones**, pero no iniciar ni
detener procesos. El navegador/worker todavía requiere cutover físico #320.
El controlador HTTP no tiene Docker socket, secretos de Actions, ni un puerto
de administración; detener el contenedor del controlador dejaría inaccesible
el propio botón de arranque. Esta propuesta conserva el panel vivo y trata
«bot» como **motor de simulación**, no como apagado del servidor privado.
El único ejecutor de operaciones físicas continúa siendo el workflow Boca
protegido en GitHub Actions, con lease único, atestación de IDs, source SHA,
imagen, Compose, rootless, aislamiento y recibo de postestado. No se añade
ningún servicio, puerto, cron, supervisor o camino SSH de despliegue.

## Contrato implementado en el panel (sin efecto físico)

- En `/control`, el dueño autenticado ve cuatro botones de texto visible:
  solicitar inicio y detención del motor del bot, y solicitar inicio y
  detención de Chromium. Se preservan los botones de **admisión**, claramente
  separados de las acciones de host. La vista usa `role=status`, se actualiza
  con GET y funciona sin JavaScript. Los botones pendientes se deshabilitan.
- POST exige sesión WebAuthn del dueño (`simulation:write`), origen exacto,
  CSRF, UUID canónico y deduplicación. El número de solicitudes se limita
  también por el presupuesto temporal existente de sesión. Una solicitud
  nunca importa Playwright, no invoca IPC ni efectúa tráfico externo.
- La tabla `audit_events` de la SQLite **legacy existente** contiene un
  registro append-only de cada solicitud. No se modifica ni migra el esquema
  SQLite ni se escribe la base independiente de sesiones Chrome de #321.
  La forma del evento es `owner_lifecycle_v1_request_{bot|chromium}_{start|stop}`
  y su `audit_id` es el UUID del formulario. Repetir el mismo UUID es
  idempotente aun tras reiniciar el controlador.
- Sólo puede existir **una solicitud global sin cierre**; no se permiten
  instrucciones contradictorias mientras esté REQUESTED, CLAIMED o
  UNCERTAIN. SQLite `BEGIN IMMEDIATE` serializa solicitudes concurrentes.
  Ante caída, corrupción, identidad incierta, marca desconocida, error de
  permisos o consulta incompleta, se devuelve 503 y se evita una nueva
  escritura. No hay expiración automática ni retries del host.
- La vista distingue `REQUESTED` (**PENDIENTE**, sin ACK), `CLAIMED`
  (ejecutor tomó la solicitud, sin confirmación), `APPLIED` (recibo protegido
  confirmó la transición), `REFUSED` (recibo protegido acredita que no hubo
  efecto) y `UNCERTAIN` (sin nueva operación hasta reconciliación protegida).
  Incluso `APPLIED` describe un recibo puntual, **no monitoreo continuo ni
  garantía de que un proceso siga actualmente ejecutándose**.

## Protocolo de recibos para el futuro host — todavía NO conectado

El helper puro `host_marker(op, component, target, status)` genera un
par `(audit_id, action)` sin ejecutar nada. Requiere UUID canónico y sólo
admite `CLAIMED`, `APPLIED`, `REFUSED` y `UNCERTAIN` como marcadores de host.
`audit_id` es UUIDv5 del namespace fijo
`7a5e4b3a-2781-4f2d-978c-98bd64391508` con el nombre
`boca-lifecycle-v1:{claim|uncertain|ack}:<request_uuid>`. Acciones de host:

| Fase | Acción persistida | Semántica obligatoria |
| --- | --- | --- |
| CLAIMED | `owner_lifecycle_v1_claim_{component}_{target}` | Lease Boca retenido y solicitud exacta reclamada; aún sin efecto confirmado |
| APPLIED | `owner_lifecycle_v1_ack_applied_{component}_{target}` | Cambio físico ejecutado y re-atestado, con recibo de Actions externo |
| REFUSED | `owner_lifecycle_v1_ack_refused_{component}_{target}` | Rechazo seguro con **ausencia de efecto positivamente probada** |
| UNCERTAIN | `owner_lifecycle_v1_uncertain_{component}_{target}` | Marca provisional: resultado o inventario incierto; bloquear toda orden nueva |

El lector requiere `rowid(CLAIMED) > rowid(REQUESTED)` y
`rowid(ACK) > rowid(CLAIMED)`, IDs derivados y acción exacta. Si se marcó
UNCERTAIN, un futuro reconocimiento protegido puede registrar **un único ACK
posterior** (`rowid(ACK) > rowid(UNCERTAIN)`) sin borrar ni sobrescribir
evidencia; debe demostrar positivamente APPLIED o ausencia de efecto para
REFUSED. No se puede
forjar una confirmación mediante ninguno de los endpoints HTTP: el servidor
sólo escribe `REQUESTED`. La firma/identidad de la operación física sigue
siendo responsabilidad de la autorización del workflow, sus recibos privados
y las validaciones del host; un registro SQLite por sí mismo no certifica
Docker. La aplicación no expone una operación para marcar ACK.

Antes de habilitar estas solicitudes en una BETA integral, #320 y el
workflow protegido deben **implementar y probar**:

1. `beta-browser-stop` seguro, con inventario completo de IDs exactos y
   parada worker/controlador en el orden aprobado; si mantener vivo el panel
   lo impide, no ejecutar hasta que haya arquitectura de separación.
2. Semántica concreta de `bot` START/STOP como motor sintético con drenaje,
   cancelación reconocida e imposibilidad de nuevo trabajo. No llamar «bot
   detenido» a una simple pausa de admisión.
3. Lectura read-only de la solicitud UUID bajo lease canónico, CLAIM atómico,
   verificación de vigencia justo antes de efectos, postestado y ACK exacto
   en la **misma operación protegida**, sin múltiples ejecutores ni retry.
4. Recibo externo redacted (run, SHA, imágenes/IDs positivos, tiempos,
   estado previo y posterior), limpieza Docker **selectiva Boca en éxito y
   fracaso**, preservación de volúmenes/servicios ajenos y fallback NO_GO en
   caída/ambigüedad. El panel no puede confundir ACK con despliegue completo.

Si Actions todavía no ha implementado esta fase, una solicitud queda en
PENDIENTE y bloquea otras hasta una reconciliación explícita y verificada.
Eso es intencional: no existe un segundo canal privilegiado autorizado.

## QA e integración — Regla 84

Tests #328 comprueban escritura única, concurrencia, recuperación tras
reiniciar, estado pendiente, claim/ACK exactos, rechazo de ACK sin claim,
recepción incierta, adulteración del ledger, origen/CSRF/sesión y textos
accesibles. Todo se ejecuta con SQLite sintética y host simulado. **Ninguno**
demuestra arranque/parada real, servicio Docker del droplet o navegador vivo.

Se requiere integrar el PR en el candidato único #319 después de checks
exact-SHA y revisión, sin tocar los módulos `synthetic.py` ni `ipc_worker.py`.
El responsable central actualizará README/OPERATIONS y issue #45 cuando el
host tenga un implementador del mismo protocolo. El faltante de ejecutor
físico mantiene **NO_GO funcional** hasta evidencia protegida y aceptación
en Samsung Chrome + Termius. No se autorizan compras ni reservas reales.
