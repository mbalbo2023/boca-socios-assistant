# ADR 0254 — R247: productores postflight físicos, identidad y NO_GO real

**Fecha:** 12-NOV-2026 ART. **Issue canónico:** #417. **Estado:** código
preparatorio, READ_ONLY, sin enlace a un Actions protegido y sin ejecución
en el droplet. No constituye aprobación de release ni cierre BETA.

## Problema constatado

R245 creó un `PostflightReadSources` que obliga a inyectar fuentes reales:
una prueba sintética puede llenar los campos, pero un `GET /healthz`
únicamente prueba salud HTTP. No demuestra aceptación del propietario mediante
Chrome y passkey. El monitor `/monitor/tokens.json` exige sesión del
propietario; la capa WSGI **renueva la cookie al consultar**, de modo que
un simple GET autenticado tampoco equivale a un procedimiento estrictamente
sin efectos secundarios. La identidad SQLite persistente debe comprobarse
por metadatos de inodo, no por abrir/leer el contenido de la base.

R246 reforzó la reobservación física del par tras consultar `SITE_URL` y el
worker, los identificadores rootless exactos y los metadatos seguros del
monitor. Persistencia tras reinicio y navegador autenticado siguen sin tener
un recibo físico verificable.

## Solución de integración parcial

`host_boca_postflight_sources_v2.build_protected_postflight_sources(...)` reúne
los observadores existentes sin duplicar motores:

1. `ProductionSiteUrlWitness`: dos huellas SHA-256 obtenidas mediante `docker
   exec` de solo lectura sobre el **CID controller exacto**, sin publicar URL;
   se reobserva el par y el estado frío del worker `CREATED/PID0/EXIT0` antes y
   después. `worker_startup` inspecciona el comando revisado, **no lo inicia**.
2. `ProductionStructuralStorageReader`: exige comprobador de volúmenes/mounts
   proporcionado por la misma ejecución protegida y lease, UID/GID
   `10001:10001`, y doble reobservación del par. Captura sólo metadatos de
   inodo de SQLite, clave y sesión en los tres volúmenes Boca, nunca datos
   personales, claves ni sesiones. Para SQLite y su sesión, la huella V2
   usa device/inode/UID/GID/modo/nlink y omite size/mtime/ctime mutables;
   para la clave conserva además el guard estricto de metadatos R245.
   La comparación contra la identidad previa sigue siendo obligación del
   contrato postflight R245, pero **ambos muestreos deben usar la huella
   estructural V2**, sin mezclar digest de R245 con digest de R247.
3. `durable_cleanup_readback`: reutiliza los lectores privados O_NOFOLLOW de
   cleanup V2. Lee realmente `boca-final-cleanup-v2.receipt` desde el directorio
   previamente autenticado por el actor, con modo 0600, inodo regular y
   contenido/sha256 idéntico al recibo recibido. Valida lease y par a ambos
   lados de la lectura. No fabrica una copia de memoria.
4. Par, installed binding, retained graph y rootless provenance continúan en
   los observadores R177/R188/R245 existentes; el factory sólo vincula
   callbacks a las coordenadas y lease de ese intento.

La creación de estas funciones **no ejecuta** host, Docker, API ni sitio de
Boca. El verdadero host se consulta únicamente cuando un actor protegido,
autorizado y bajo lease activa el callback correspondiente.

## Fallos cerrados por diseño

- `owner_acceptance` y `monitor_metadata` no reciben valores afirmativos
  inventados: quedan `None`, aunque el llamador intente inyectar lambdas
  optimistas. El `ProductionPostflightSnapshotReader` continúa en NO_GO.
- El monitor puede presentar `IN_MEMORY` y cero observaciones, pero esa
  combinación no prueba conexión externa ni producción de tokens. Tampoco
  autoriza recuperación de credenciales o salto de filas.
- La prueba de `SITE_URL` no declara supervivencia de un reinicio hasta que
  exista un hecho de reinicio autenticado, dos huellas coincidentes y
  procedencia de ambos muestreos.
- Una lectura local autenticada de passkey requiere evidencia separada del
  propietario; `HEALTH_HTTP_200` nunca se traduce a `LOGIN_HTTP_200`.
- La ausencia de directorio de recibos, volumen probado o identidad rootless
  es NO_GO; no existe fallback a la ruta host, un volumen genérico o root.
- RCA del falso NO_GO: la huella antigua incluía `st_size`, `st_mtime_ns` y
  `st_ctime_ns` también para SQLite y la sesión. Una transacción legítima
  cambia estos valores sin reemplazar el archivo. V2 preserva la detección de
  sustituciones de inodo, redirecciones mediante symlink, cambios de dueño,
  permisos o hardlinks, pero **no garantiza igualdad de contenido** ni
  ausencia de transacciones SQL; esa validación pertenece a otro contrato.

## Evidencia y faltantes para una futura certificación

El orden físico será: release controller/worker del SHA exacto; lease única;
preflight; APPLY protegido; cleanup V2 final; readback del recibo ya durable;
doble captura R245 con inodos, SITE_URL, mirror y worker detenido; y, en
un circuito distinto, aceptación verdadera de Chrome/passkey y monitor
propietario con pruebas de ausencia de modificaciones. Sólo entonces
puede evaluarse el cierre de BETA.

**Pruebas:** el cambio utiliza TDD: inicialmente no existía el módulo,
provocando error de importación RED. Se introdujeron trece casos de fuente
inyectada, rechazo de evidencia fabricada, owner ausente, inode/recibo
corrupto, lectura real O_NOFOLLOW y doble prueba rootless. No se ejecutaron
acciones en el droplet ni se publicó un GO.
