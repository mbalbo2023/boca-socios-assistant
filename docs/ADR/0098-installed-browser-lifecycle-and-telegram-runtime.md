# ADR 0098: ciclo instalado del navegador y sender Telegram protegido

**Estado:** candidato de #250/#251, 2026-11-02. Código y pruebas aisladas;
no constituye evidencia de instalación, entrega Telegram ni Chrome reales.
Complementa ADR0094/0095 y ADR0084/0085 sin repetir el instalador new-only.

## Problema observado

El instalador aislado crea controller, browser-worker y el volumen IPC. La
aceptación y la custodia Telegram heredadas verificaban un único controller
con tres montajes y rechazaban correctamente esa nueva topología. Además,
`restart: no` y la parada posterior a la aceptación dejaban el par apagado,
sin una operación protegida para iniciar los mismos contenedores. El paquete
Telegram tenía worker y outbox durables pero no una activación operativa
protegida ni prueba durable ligada al bot/destino antes del consumo continuo.
Son defectos de integración de contratos, no prueba de fallo del droplet.

## Identidad instalada y operaciones acotadas

`--browser-attempt-id existing` recupera el ID original únicamente del
marcador canónico protegido. Sus digests, SHA de código, hashes de Compose y
seccomp deben coincidir exactamente con los argumentos de la publicación
aprobada. El helper continúa siendo un programa standalone de biblioteca
estándar, apto para transporte por `python3 -` sin imports del checkout.

Las operaciones `browser-status`, `browser-start`, `browser-restart` y
`browser-acceptance` verifican inventario completo del daemon rootless Boca,
ambas imágenes/IDs/revisión, configuración, montajes, UID, aislamiento,
puerto, redes, capacidad y continuidad de data/key/owner/IPC. No hay pull,
init, migración, `compose up`, recreación ni borrado de volúmenes en este
ciclo. La procedencia exige los mismos IDs antes y después.

Start exige todos los servicios positivamente detenidos; inicia worker,
espera salud acotada, inicia controller y verifica salud/loopback. Restart
valida primero el par activo y lo detiene en orden controller/worker. Si
existe sender aprobado lo detiene antes y lo inicia al final, conservando
su ID y sus dos etiquetas de intento. No hay reintento automático. Un
socket IPC residual tras una terminación forzada no se elimina a ciegas:
el worker debe fallar cerrado y la recuperación necesita revisión del
residuo exacto. La política `restart: no` se conserva.

La aceptación ejecuta el recorrido sintético por `UnixSyntheticBrowser`
desde el controller real UID10001 hacia el worker UID10002, y reutiliza el
probe HTTP con DB temporal aislada. No contacta Boca ni Telegram ni crea
avisos en la DB de la aplicación. El recibo sintético con métricas se emite
sólo después de verificar de nuevo identidad y almacenamiento, seguido de
un recibo lifecycle. La operación protegida detiene el par al finalizar;
una operación start explícita posterior es necesaria para dejarlo accesible.
La aceptación no reemplaza la prueba pública autorizada del sitio ni la
ceremonia Chrome/passkey del titular.

Las fases de custodia/migración/one-shot Telegram pueden reutilizar la
identidad dual detenida mediante las coordenadas browser. El camino legacy
sin esas coordenadas sigue exigiendo exactamente su topología anterior.
Ningún inventario acepta un contenedor adicional por nombre solamente.

## Sender durable opt-in y prueba de identidad

La custodia y la afirmación humana de ADR0085 siguen siendo obligatorias:
`BOCA_TELEGRAM_OWNER_READY=ready`, bot numérico esperado y HMAC esperado del
chat privado. No se infiere ningún bot/destino. El token y el ID de chat
continúan exclusivamente en el volumen privado; no van a inputs, variables,
argumentos, repositorio ni logs. El SHA y las dos aserciones se pasan como
argumentos obligatorios tanto en Compose como en el comando Docker explícito.

`telegram_one_shot test SHA BOT HMAC` conserva la exigencia de outbox y ledger
completamente vacíos y hace un único intento. Por ello debe ejecutarse antes
de la primera simulación persistente del usuario. Su UUID de aceptación se
deriva por HMAC del token sobre un dominio versionado, SHA, bot y HMAC del
chat. Sustituye el UUID genérico fijo de ADR0085; no agrega un archivo de
secretos ni modifica el schema. La aceptación de la API no prueba lectura
humana del mensaje.

`telegram_one_shot verify-ready SHA BOT HMAC` verifica offline la custodia
0400, UID10001/nlink1 y los cgroups efectivos, y exige el aviso HEARTBEAT
aceptado más su ledger `api_accepted`, intento único, message_id positivo y
tiempos consistentes. Cualquier intento prepared/ambiguous bloquea el gate.
Un recibo genérico antiguo o de otra identidad/SHA no satisface la prueba.
`notify.telegram_worker serve SHA BOT HMAC` repite ese gate antes de reclamar
avisos, fija en memoria la misma custodia y emite un recibo acotado READY.
No crea un heartbeat al iniciarse. El host usa sólo los logs desde el
StartedAt actual para no aceptar el READY de una ejecución anterior.

Cambiar SHA, token o destino no hereda la aceptación; una actualización
futura necesita un procedimiento explícito y revisado de reconciliación.
No se borra el fence ni se reenvía automáticamente el one-shot para salvar
ese bloqueo. La carga privada del envelope y la verificación humana de
bot/chat deben estar resueltas antes de activar; este cambio no inventa una
interfaz de custodia para tablet ni configura secretos ausentes.

El sender usa sólo la red dedicada `boca-socios_telegram_egress`, sin puertos,
capabilities ni acceso a owner/key/IPC; data RW y Telegram RO. UID10001,
rootfs RO, `no-new-privileges:true`, IPC/cgroup privados, restart no, init,
tmpfs 8 MiB, 0.25 CPU/128 MiB/32 PIDs y healthcheck heredado deshabilitado son
comprobados exactamente. La red bridge permite la API Telegram según el
transporte acotado ya revisado; no se afirma que sea un firewall de dominios.
El browser-worker sigue sin red IP.

## Presupuestos y recuperación selectiva

El gate dispatch requiere `--browser-ipc-v2 --telegram-runtime` para el
presupuesto total de los tres servicios `1.75cpu-1152m-224pids`. El presupuesto
dual `1.5cpu-1024m-192pids` no habilita el sender. El reinicio del conjunto
completo requiere 1792 MiB disponibles, 2 CPU de headroom y 288 PIDs libres;
para agregar sólo el sender al par activo se exigen 512 MiB, 0.5 CPU y
64 PIDs residuales. Los límites de contenedor y los márgenes host son
controles distintos; ninguno implica capacidad real sin recibo del host.

`browser-telegram-preflight` identifica el par/custodia y prueba sender y red
ausentes antes de habilitar el marcador de intento. Start crea únicamente
esa red y el sender. Ambos reciben el intento original de instalación y
`boca.socios.telegram-runtime-attempt=$GITHUB_RUN_ID`, exigido mediante
`--telegram-attempt-id` sólo en preflight/start/cleanup del sender. Una carrera
que revele recursos de otra ejecución impide su eliminación.

Ante fallo o cancelación, `browser-telegram-cleanup` valida el intento exacto
antes de detener/quitar sólo el sender y su red vacía, conserva ambos
contenedores preexistentes y todos los volúmenes, y verifica la ausencia de
residuos. Para recuperar un fallo de recursos no exige salud del par ni el
mínimo de espacio de una instalación: verifica positivamente la identidad
y configuración de cada servicio en su estado actual, sin arrancarlos ni
ejecutar probes que requieran salud. Cambios en IDs, imágenes, montajes,
puertos, privilegios, dueño, marcador o almacenamiento siguen bloqueando.
Esto también permite recuperar residuos después de un stop-test que dejó
el par detenido. Un recibo separado registra bytes e inodos antes/después;
no se promete recuperar un número predeterminado porque los otros procesos
pueden consumir almacenamiento en paralelo. Nunca hay prune global.

Si SSH impide verificar la limpieza, el estado es indeterminado, se detiene
la activación y se usa esta recuperación exacta al restablecer conectividad.
No se considera PASS una limpieza incompleta. La parada rootless selectiva
posterior mantiene su propio control de identidad e inventario.

`inspect-prerequisites` añade sólo cifras agregadas de memoria/CPU/PIDs y,
cuando es comprobable, versión del binario dockerd. Daemon y almacenamiento
permanecen explícitamente `unverified`; no convierte un socket ausente o un
preflight fallido en aprobación y no inspecciona otras aplicaciones.

## Regresiones y evidencia pendiente

`tests/test_host_browser_runtime_lifecycle.py` cubre start/restart sin
recrear, fallo IPC sin arrancar controller, aceptación real del contrato IPC
con doble validación, estados detenidos, identidad dual de Telegram,
instalación/cleanup selectivo del sender, intento ajeno, recursos residuales,
falta de prueba READY, permisos/puertos/redes/destino alterados, cleanup con
poco espacio o par unhealthy/parado, y preservación del ciclo completo.
`tests/test_deploy_inputs.py` separa presupuestos; el contrato de
`compose.telegram.json` exige pins y aislamiento. Las pruebas del worker y
one-shot cubren el gate durable y rechazo de replay/identidad diferente.

Las pruebas falsas no verifican Docker inspect real ni una instalación en el
droplet. CI debe ejecutar el smoke descartable de running/stopped y el
parser workflow sobre stdout real del helper. La revisión independiente y
las ejecuciones del SHA integrado, publicación, host, Telegram humano y
Chrome/passkey se registran por separado en el checkpoint canónico #45.
