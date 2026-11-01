# ADR 0094: IPC de un comando sintético con Chromium separado de BETA

**Estado:** candidato de **código y pruebas local**, sin PR, integración ni
activación sobre el droplet. Implementación aislada de #227 basada en el
worktree #233 `d259ed2`; antes de abrir PR hay que incorporarla sobre el
`main=53c4a69610a0eb2b73e0c5edc32c5146d6d117ff`, que ya incluye la
corrección posterior de cancelación de #233. No constituye autorización para
alterar Compose, Dockerfile, GitHub Actions, red, volumen o servicio alguno.

## Decisión de código, sin runtime instalado

Se agrega `UnixSyntheticBrowser`, un `SyntheticBrowserPort` explícitamente
inyectable al `build_beta_server(settings, browser=...)` existente. Construir
el cliente **no inicia procesos, no abre sockets, no importa Playwright ni
activa Chromium**. El servidor BETA conserva por defecto su resultado local
determinista. El coordinador sigue siendo propietario de la garantía
persistente de **una solicitud de cantidad 1 por socio/partido**, estados,
cancelación, idempotencia y notificaciones locales.

El código opcional `python -m boca_socios.browser.ipc_worker`, aún **no
empaquetado ni desplegado como servicio**, espera conexiones AF_UNIX dentro
de un proceso independiente UID/GID 10002. Solo invoca el adapter revisado
`OnDemandSyntheticBrowser(isolated_playwright_page)`: cada comando crea y
destruye un único contexto Chromium, ejecuta únicamente el HTML ficticio de
`SyntheticTicketScenario` y devuelve `reserved_in_simulator`, jamás una
confirmación de Boca, Queue-it o una reserva externa.

## Socket, autenticación y protocolo

El único punto de conexión propuesto es
`/run/boca-browser-ipc/synthetic.sock`. El montaje **todavía no existe**:
una operación futura tendría que preparar un directorio propio, regular,
no redirigido, UID/GID 10002, modo `0711`, y permitir solamente a los dos
contenedores Boca atravesarlo. El socket creado por UID10002 es modo `0622`
(clientes pueden conectar, pero no leer/listar el directorio). La autorización
**no** depende del permiso de escritura global del socket: el kernel Linux
`SO_PEERCRED` debe identificar en cada dirección PID positivo, UID/GID
10001 del controlador y UID/GID 10002 del worker, respectivamente. El
cliente verifica antes y después de conectar el tipo socket, dueño/grupo,
modo e inode del archivo; el worker no pisa archivos preexistentes ni borra
un socket cambiado o incierto. Un fallo de mapeo de UID entre *user namespaces*
rootless es **NO-GO**, no motivo para relajar el chequeo.

Los frames son `uint16` big-endian más un máximo de **64 bytes**. La única
petición válida es exactamente `BOCA_SYNTHETIC_V1_RUN`, sin campos, parámetros,
miembro, partido, URL, cookie, credencial ni token. El cliente cierra su mitad
de escritura, el worker exige EOF tras esa única trama; replays y datos
adicionales se rechazan. Las únicas respuestas son constantes:
`BOCA_SYNTHETIC_V1_RESERVED_IN_SIMULATOR`, `BOCA_SYNTHETIC_V1_BUSY` y
`BOCA_SYNTHETIC_V1_NO_GO`. El cliente exige EOF exacto y nunca convierte
respuestas inválidas, fallas de red local, timeouts ni cancelaciones en éxito.
Ninguna excepción, página, dato personal o texto libre cruza el IPC.

Los límites configurados por código son 2 s para trama/handshake del worker,
20 s de operación sintética, 5 s de cancelación del worker y 25 s totales
del cliente (máximo configurable 30 s). El worker y el cliente impiden
**single-flight** concurrente; no hay segunda cola ni retry automático.
Una ejecución tardía después de vencido el deadline **no** genera éxito.
Si el browser ignora la cancelación, el servidor queda permanentemente
cerrado, deja su socket como evidencia de estado incierto y el entrypoint
descartable termina su **propio proceso** con código no exitoso; la limpieza
selectiva del contenedor y volumen sigue siendo responsabilidad exclusiva del
workflow/host que se apruebe más adelante.

### RCA de carrera STOP/respuesta y cierre de conexiones ([#235](https://github.com/mbalbo2023/boca-socios-assistant/issues/235))

Durante el desarrollo local se reprodujeron dos fallos de aceptación/cierre
que bloquearían la aprobación si quedaran sin resolver. En el cliente, un
`return SUCCESS` antes de `wait_closed()` podía entregar un resultado tardío
si `close()` ocurría durante una espera que suprimía cancelación. La corrección
mantiene el *single-flight* activo durante toda la limpieza, incluye el cierre
en el deadline y verifica `closed`, `task.cancelling()` y reloj **después**
de cada `await`, justo antes del único retorno. Regresión:
`test_close_during_slow_socket_teardown_fences_late_success`.

En el worker, `server.wait_closed()` sin tope aguardaba un handler aún abierto
y podía bloquear indefinidamente el STOP, mientras una respuesta sintética
terminada podía emitirse después de la orden de cierre. La corrección cancela
primero la operación activa, limita también la espera del servidor a 5 s,
contamina/falla permanentemente el worker si no termina y verifica estado
cerrado, cancelación y deadline **sin un await intermedio** antes de encolar
`SUCCESS`. Una eventual cancelación no cooperativa exige muerte del proceso
aislado, sin resultado positivo ni retry. Regresión exacta:
`test_worker_stop_between_fake_success_and_reply_sends_no_go`.

## Cero egress y límites de activación

Antes de crear el socket y de cada ejecución, el worker valida sus límites
cgroup v2/UID de ADR0093 y exige que la única interfaz de red observable se
llame `lo`. Esta segunda inspección no reemplaza el bloqueo **obligatorio**
del kernel/Docker con `--network none`: un filtro de rutas Playwright, su
`about:blank` inicial o el modo `simulation` no prueban por sí mismos ausencia
de sockets salientes. El controlador nunca recibe Docker socket, permisos
del daemon, navegador ni acceso a volúmenes de claves/datos del worker.
El IPC no publica **ningún** puerto IP y no altera el puerto privado
`127.0.0.1:8443` de #225.

### Gate independiente pendiente de aprobación del dueño

Antes de habilitar este IPC se necesita una **decisión concreta separada**
sobre el agregado del worker al modelo Boca: imagen browser reproducible y
revisada (el `Dockerfile.browser` actual todavía no copia/empaqueta estos
módulos), `network_mode: none`, montaje IPC desechable y limitado a esos
dos servicios, compatibilidad SO_PEERCRED real bajo UID10001/10002 y
rootless, no secret/env ajeno, seccomp/sandbox Chromium, raíz read-only,
`/dev/shm` acotado y cgroups privados ≤1 CPU/768 MiB/128 PIDs. El worker
no puede recibir montajes owner/key/data ni publicar un puerto. Hacen falta
inventario exclusivo Boca, capacidad, health/stop, deadline de muerte de
proceso, limpieza exacta de contenedor/volumen tras fallo con recibo
redactado, nuevo artefacto inmutable, revisión y checks CI sobre el SHA
final, todo bajo el **único workflow protegido de Actions**. Este PR
propuesto no incorpora ninguna de esas mutaciones.

## Evidencia y Regla 84

Las pruebas locales con AF_UNIX real bajo UID de fixture verifican protocolo
fijo, `SO_PEERCRED` en ambos extremos, permisos e inode, exceso de bytes,
segundo comando, concurrentes, deadline, cancelación, resultado tardío y
reutilización durable de la misma solicitud `quantity=1` a través del
`BetaCoordinator`. No levantan Chromium real, no instalan Docker, no
comunican con Internet ni prueban mapeos entre dos contenedores rootless.
El informe de entrega registra su conteo exacto y SHA local; el escritor de
integración debe reconciliar README/OPERATIONS/estado/#45 cuando exista PR
revisado, sin presentar código como beta activa.

**Resultado de activación:** **NO-GO** hasta aprobación de infraestructura
acotada, empaquetado, revisión, pruebas de kernel/socket en contenedores
aislados y aceptación protegida posterior. La corrección de cancelación
integrada en #233 debe conservarse al rebasar este trabajo.
