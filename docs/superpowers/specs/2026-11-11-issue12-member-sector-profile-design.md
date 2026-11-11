# Issue #12 — preferencias de sector en el perfil existente

## Intención aprobada

Cada socio registrado una sola vez en `/socios/nuevo` debe configurar y
recuperar preferencias multisector desde su **página existente** `/socios/{id}`.
La pantalla reutiliza el `member_id`, nombre y correo ya guardados: **no hay
nuevo formulario de alta ni segunda bóveda de credenciales**. La selección
simulada para un evento se deriva de un único conjunto de preferencias por socio.

## Alternativas evaluadas

1. **Agregar columnas o `0008` a `boca.sqlite3`**: rechazado. El gate de
   custodia del controller prohíbe expresamente migración legacy `0008`.
2. **Archivo suelto por socio en el volumen**: evita tocar la DB, pero añade
   cientos de archivos y manejo de consistencia individual.
3. **SQLite lateral único en el mismo volumen Boca** (elección): conserva
   una sola identidad de socio, no duplica credenciales y no altera la
   base legacy. Sigue el patrón de aislamiento de la sesión del dueño.

## Diseño

- SQLite lateral `boca_sector_preferences.sqlite3`, directorio **existente**
  de `boca.sqlite3`, UID/GID actual y modo `0600` sin enlaces simbólicos.
- Dato mínimo por `member_id`: `mode` `ALL` o `ORDERED_ALLOWLIST`, lista
  ordenada de IDs sintéticos, revisión y fecha. Sin email, contraseña, URL ni
  credenciales. A lo sumo un registro por socio. Se comprueba el socio contra
  la **base principal existente**, solo lectura, antes de guardar y mostrar.
- Migración de lateral **explícita**, nunca en constructor, GET del perfil,
  login ni inicio del worker. Si no está instalada, el perfil existente
  sigue funcionando, la escritura informa indisponibilidad.
- En `/socios/{id}` se añade un formulario de preferencias con `csrf`,
  `operation_id` y permiso `members:write` existentes. No se modifica el
  formulario de alta. Orden visible, sin formularios paralelos.
- El panel ya limitaba a 16 operaciones pendientes por sesión. El nuevo
  formulario **comparte el identificador de un solo uso de revocación**:
  no reduce la cantidad histórica de aperturas de perfil admitidas.
  Guardar sectores o revocar desde una misma versión de página exige luego
  refrescar antes de usar la otra acción; los POST conservan fingerprints
  separados por ruta, por lo que no confunden operaciones.
- Para un evento ficticio, `MemberSectorDefaults.for_event(event_id)` genera
  el `SectorPreference` previo, conservando `TicketIntent.quantity=1`.
- No se cambia la navegación, el `SITE_URL`, workers, IPC, Docker, migraciones
  legacy ni la lógica de reservas reales. No se desplegará con Cutover activo.

## Criterios de aceptación

1. Socio preexistente puede abrir `/socios/{id}` y ver preferencias actuales.
2. Guarda modo y prioridad, recarga el perfil y encuentra la misma configuración
   sin reintroducir correo, contraseña o datos de alta.
3. Otros socios no comparten las preferencias; usuario inexistente no se crea.
4. CSRF, origen, permisos, replay y rutas UUID siguen siendo obligatorios.
5. `ALL` limpia preferencias anteriores; lista duplicada, mal formada o
   excesiva se rechaza sin alterar datos.
6. Migración lateral no cambia ni el checksum ni el esquema legacy.
7. La sexta apertura consecutiva del perfil no falla por añadir un tercer
   nonce independiente; se conserva el límite de la sesión anterior.

## Integración y propiedad

La implementación vive en una rama descendiente de
`feature/12-sector-preferences-offline-20261111`; **sin PR ni merge** hasta
que el otro chat libere sus archivos y el Cutover. El aprovisionamiento
explícito del fichero lateral debe incorporarse en una etapa posterior con
owner del despliegue. No se declara GREEN físico de droplet en esta fase.
