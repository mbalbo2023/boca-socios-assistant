# R172 — Browser worker bajo demanda: IPC, SITE_URL y actividad

Fecha: 2026-11-11 ART. Propietario: #417; continuidad: #45. Estado: diseño CODE_ONLY.

## Evidencia y problema

- `main=361e3ff42c44e1b8699d7a3e2d158c9a367b2f86`, PR #472/#473 integrados.
- El último intento físico W1 #934 registró `MISSING_BARE_SYNTHETIC`, `ExitCode=1`, `OOM=false`; su corrección de `PYTHONPATH` no cuenta con prueba física posterior.
- `ipc_client.py` exige un servidor AF_UNIX en `synthetic.sock`, frames constantes y peer UID/GID 10002; `ipc_worker.py` del dueño es un orquestador puntual de tres sesiones que no abre ese socket.
- `SITE_URL` se almacena en `/data/boca-site-url.json` del controlador, pero el contenedor navegador no monta ese volumen ni recibe cambios con `docker start`.
- `/control/actividad` ya está implementado, aunque la telemetría del Chromium integrado no ha sido acreditada y puede mostrar eventos históricos como si fueran actuales.

## Diseño elegido

1. Mantener los módulos `synthetic.py` y `ipc_worker.py` protegidos: no alterar navegación, sesión, autenticación, reservas ni salida estructurada; respetar excepciones explícitas del dueño para wiring/imports/env/IPC/eventos de categorías fijas.
2. Recuperar la *infraestructura de protocolo*, no el motor antiguo, desde Git histórico en un nuevo `browser/ipc_server.py` no protegido. Comprobar identidad, permisos, framing acotado, concurrencia, STOP y cancelación. Arrancar el listener únicamente cuando el dueño solicite **Iniciar**. Para CI, usar un executor offline inyectable; no importar ni ejecutar los módulos protegidos.
3. Separar disponibilidad IPC y ejecución del orquestador del titular. Un contrato de simulación verificado nunca deberá afirmar navegación o reserva real. Para cualquier integración futura al ejecutor del titular se requiere el mismo perfil de simulación y prueba aislada, sin login/Queue-it.
4. `SITE_URL` será la única fuente de destino de prueba, editable desde configuración privada del 8443, persistente entre STOP/START, sin requerir rebuild por cambio de valor. Transportarlo por una superficie de configuración mínima y Boca-only, atestada, de sólo lectura para UID10002. No exponer el volumen de socios, claves, credenciales, token de Telegram o sockets del daemon al worker. Revalidar límites de URL y rechazar credenciales embebidas y destinos de metadatos; no imponer un veto general a URL pública/privada por clasificación.
5. Reutilizar `activity_events.py` y el visor actual; distinguir eventos históricos de un START vigente con correlación opaca o caducidad. No registrar URLs, tokens, cookies, DOM, PII ni stderr crudo. Probar vista y API con estado de engine detenido, fallo de arranque y archivo antiguo.
6. No rehacer SQLite de socios ni Telegram. Mantener `sender=OFF` y exigir rotación del token comprometido antes de una activación independiente. No tocar otras aplicaciones, Porota ni PPI Watch.

## Alternativas descartadas

- Volver a usar directamente `ipc_worker.py` como servicio: no implementa AF_UNIX y termina tras una ejecución, de modo que no cumple el healthcheck.
- Reemplazar el módulo privado por el `UnixSyntheticWorker` histórico: sobrescribiría el código aportado por el dueño.
- Compartir con el navegador todo `/data`: expondría SQLite y credenciales sin necesidad.
- Añadir URLs al frame IPC: rompería el protocolo constante autenticado y mezclaría configuración con órdenes.
- Crear otro dashboard, otra DB o otro emisor Telegram: ya existen implementaciones integradas.

## Aceptación

Pruebas RED→GREEN en runner descartable para socket/peer/framing, arranque-demanda y STOP, URL persistida/cold-start y seguridad de los mounts, frescura de actividad, QA de controller, imagen exacta, dependencias y red exclusiva. CI GREEN no demuestra droplet. Sólo una operación específica y protegida Boca Actions con recibos físicos puede probar el worker, su socket, la salida Internet del bridge Boca, Chromium simulado, panel 8443 y limpieza selectiva. No ejecutar navegación real ni reservas.
