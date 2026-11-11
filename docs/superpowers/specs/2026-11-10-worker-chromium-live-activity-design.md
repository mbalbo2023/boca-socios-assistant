# Boca BETA: actividad en vivo del worker y Chromium (issue #417)

## Alcance autorizado

Mostrar en el panel privado `8443` una secuencia accesible y actualizada de
hechos observados: solicitud y acuse de inicio/detención, estado del trabajo
sintético y etapas de creación/cierre de Chromium. La lectura no inicia el bot.

## Arquitectura

- La identidad y el estado de solicitudes siguen perteneciendo a SQLite y a
  los recibos protegidos del ejecutor. Ninguna petición HTTP ejecuta Docker.
- El *page factory* existente, **fuera** de `synthetic.py` e `ipc_worker.py`,
  registra únicamente códigos fijos de etapas reales de Chromium. No inspecciona
  el DOM, URLs, socios, credenciales, tokens, cookies ni respuestas.
- Los eventos acotados se escriben en un archivo dedicado dentro del volumen
  IPC Boca ya existente (`/run/boca-browser-ipc`): escritura exclusiva del
  worker UID 10002 y lectura del controlador UID 10001, cuyo montaje sigue `ro`.
  No se abre puerto nuevo ni se concede acceso a Docker al controlador.
- El lector valida directorio, propietario, modo, enlace, tamaño, formato,
  etiquetas permitidas y tiempos. Un registro inválido no se muestra ni se
  transforma en una confirmación física.
- Rutas GET `/control/actividad` y `/control/actividad.json`: requieren la
  misma sesión passkey y permiso que `/control`; JSON `no-store`, sin IDs,
  identidad ni texto libre del worker. El panel consulta cada cinco segundos;
  ofrece actualizar, pausar y estados accesibles para control por voz.
- La vista separa "recibo del ejecutor", "estado de simulación" y
  "etapa reportada por Chromium". La tercera fuente es telemetría indicativa
  del proceso, no una certificación de la salud del host ni la traza de la web.

## Límites y seguridad

- Revisión 11/11: el dueño levantó sólo la prohibición de editar el **wiring**
  de `synthetic.py` e `ipc_worker.py`. El import relativo y la carga de `SITE_URL`
  cambiaron, sin alterar el algoritmo de navegación, y ambos siguen excluidos
  del análisis/ejecución sintética de CI. El entrypoint `ipc_worker.py` todavía
  no implementa el servidor Unix IPC exigido por el Cutover; permanece NO_GO.
- No se presenta stdout/stderr crudo ni una supuesta navegación real: Boca
  continúa en simulación, `network_mode: none`, sin reservas ni compras.
- Escritura y rotación sólo del archivo de telemetría Boca, con tamaño limitado;
  se preserva el socket Unix y su modo 0711/0622. Si falta la fuente, se indica
  "sin telemetría" sin cambiar el estado del worker.
- Se conserva la instalación por imágenes OCI inmutables y Actions protegidas.
  No se sustituye por montajes editables de código en producción ni se toca Porota.
- La aceptación física exige un nuevo artefacto por digest, Cutover V3 seguro,
  evidencia de eventos reales desde una simulación local y comprobación en móvil.

## Casos de prueba

1. Acceso sin passkey y permiso insuficiente: rechazo, sin datos.
2. Inicio, acuse, trabajo y cierre: orden y procedencia sin IDs/secretos.
3. Archivo ausente, malformado, symlink, propietario o permisos incorrectos,
   gigante o con eventos desconocidos: ninguna filtración, fuente degradada.
4. Creación real de Chromium en doble de pruebas: etapas fijas y cierre incluso
   ante fallo, sin tocar lógica del navegador protegido.
5. CSP del panel permite sólo el script exacto; actualización manual/automática
   sin desactivar login ni bloquear controles de la BETA.

## Ampliación de configuración 11/11 — SITE_URL

- Ruta owner-only `GET/POST /configuracion`: formulario accesible bajo la misma
  sesión passkey, permiso `simulation:write`, `Origin`, CSRF y operación de un
  solo uso; usa `SITE_URL` como única variable de destino de navegación.
- El valor se guarda en un JSON atómico de modo `0600` dentro del **volumen
  privado Boca de datos**, sin migrar SQLite ni almacenar tokens. Por orden
  posterior del titular, **no discrimina entre URL públicas y privadas**.
  Valida estructura HTTP(S), ausencia de credenciales, query, fragmento,
  caracteres de control y direcciones link-local de metadatos.
- En la biblioteca ZIP aparece además una URL pública literal en su módulo
  navegador y una URL de API de Telegram con un **token embebido**. Esos
  componentes no se incorporan automáticamente: se conserva el stack revisado,
  se evita subir secretos y se requiere rotar el token comprometido.
- El almacenamiento en el panel no equivale todavía a aplicación en el worker:
  la ruta de transporte al contenedor rootless está pendiente de integrar.
  Su `network_mode:none` **actual** y las verificaciones exactas de volúmenes/identidad
  impiden simular una conexión interna inexistente. El propietario verá
  "pendiente de aplicar" hasta que el ejecutor protegido confirme el traslado
  y el siguiente arranque. Ni Docker `start` ni `stop` modifican el Env de
  un contenedor ya creado; no se presume hot-reload sin pruebas físicas.

## Ampliación de red 11/11 — salida a Internet requerida

- El dueño pidió expresamente que Chromium tenga salida a Internet. Migrar
  el worker desde `none` a un bridge propio **sólo de Boca rootless**,
  separado de la red del controller, de Porota y de cualquier otra app.
  Sin nuevos puertos publicados, permisos root ni socket Docker en panel.
- `compose.beta.browser.yaml`, `host_first_deploy.py`,
  `host_lifecycle_rootless_adapter.py` y cada attestor de inventario requieren
  una promoción coordinada: sus contratos de red exactos hoy impiden el cambio.
- Permitir guardar un dominio público **no autoriza** por sí solo un flujo
  de reservas o evasión de colas. La aceptación exige evidencia de egreso
  real desde el worker autorizado, DNS, ausencia de puertos de entrada y
  límites de custodia Boca, además de un IPC worker saludable.
