# ADR0238 — R188: recursos retenidos antes de diseñar otro upgrade

Fecha: 2026-11-12 ART. Issue #417. Estado: **CODE_ONLY; sin observación física nueva**.

## Problema comprobado en fuente

El actor `host_boca_pair_upgrade_backend.py` sigue siendo la migración única
del SHA `03df9a14bdd78cf768386a865876fed9d5656911`, intento `42806447101`.
No sirve para actualizar el par instalado por `43217075287`: exige worker
EXITED/1, ausencia de red egress y volumen SITE, luego crea esos recursos.
Además confunde el intento de instalación anterior con el origen del IPC
preservado. Su finalizer no implementa el retiro completo de stage/imágenes
con recibo de disco/inodos exigido por la política. Cambiar solamente dos
constantes sería incorrecto.

R186 sigue siendo un finalizador de **un incidente único**, no un instalador.
Sus journal y claim no se modifican ni se repite su operación. La evidencia
de par/binding/SQLite no contiene todas las identidades de recursos retenidos
y referencias de imágenes necesarias para diseñar el sucesor.

## Decisión

Añadir únicamente `boca-retained-resource-observe` a la Action manual Boca
existente. No se agrega workflow, secreto, ruta SSH ni autoridad effectful.
El selector inicial sigue siendo `inspect-prerequisites`, sin nuevo default.
Todos los campos opcionales de fuente, imágenes, release, credenciales y
coordenadas deben quedar vacíos; el SHA se obtiene de `github.sha` y se
revalida contra main inmediatamente antes de SSH.

El observador stdlib usa dos capturas completas e independientes:

- Par exacto R183 (SHA, intento, dos CIDs y digests ya publicados en el
  observador postcommit): controller healthy/loopback, worker CREATED/PID0.
- Inventario del daemon rootless Boca que rechaza presencia extranjera
  antes de inspecciones detalladas. No inspeccionar otros proyectos.
- IPC y SITE: labels de proyecto/rol, intento creador **real**, referencias
  de contenedores y SHA256 de metadatos device/inode/owner/mode/links. El
  mountpoint Docker debe coincidir con el directorio local fijo; apertura
  O_PATH y O_NOFOLLOW en cada componente, sin leer contenidos.
- Egress: nombre Boca fijo, ID exacto, intento creador y cero peers del worker
  nunca iniciado. Un ID diferente al observado en el par se rechaza; un
  worker CREATED puede informar UNATTACHED, nunca conectividad probada.
- Imágenes: ID, aliases públicos GHCR permitidos, revisión OCI y referencias
  por contenedor. Alias/provenance desconocidos no habilitan retiro. Imágenes
  sin fuente probada aparecen no verificadas, sin divulgar aliases dudosos;
  las globales no clasificadas se cuentan sin inspección adicional.
- Bind mounts: el perfil exacto ya verificado por el observador de par y
  huella de metadatos del directorio fijo del control socket.

No se publican Env, raw Mounts, rutas del host, UID/inodes crudos, SQLite,
SITE_URL, claves, tokens ni credenciales. Los errores son categóricos. El
ZIP propio SHA256/memfd no incluye Compose, instalador, backend de upgrade,
finalizador R186 ni módulos de navegación. El recibo canónico está limitado
a 48.000 bytes y siempre dice `successor_apply_authorized=false`.

Los orígenes esperados IPC=`42806447101`, SITE/egress=`43217075287` son una
hipótesis verificable de fuente, no una nueva etiqueta asignada. Un origen
distinto se informa con `expected_resource_provenance=false`; nunca se adopta,
reetiqueta, borra o reconstruye el recurso automáticamente.

## Pruebas y límites

TDD observa RED antes del módulo, antes del transporte, para discrepancias
imagen/red y para mountpoint redirigido. Incluye parser canónico/duplicados,
dos snapshots, cambio de inode y symlink real, fuentes/aliases no confiables,
ZIP determinista e imports aislados, y ejecución offline del gate Bash.

Un recibo READ_ONLY exitoso no prueba la claim/terminal R186, disponibilidad
continua, egress real, salud del worker iniciado ni permiso para upgrade.
El actor effectful permanece intacto y NO_GO para este sucesor. El diseño
posterior debe vincular journal original, R186 aceptado, binding, recursos
persistentes y cleanup antes de habilitar una nueva transacción protegida.
