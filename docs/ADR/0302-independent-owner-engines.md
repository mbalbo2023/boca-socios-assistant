# ADR0302 — R297: dos motores funcionales bajo demanda

Fecha: 2026-11-15 UTC. Estado: implementado y revisado en el candidato PR517;
pendiente de gates del SHA publicado, despliegue y certificación física.

## Autoridad y continuidad

El [contrato DUAL-01..12 y los cuatro votos de diseño](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6886406162)
registran la instrucción del titular antes del código. Complementa ADR0299–0301
y sustituye el límite funcional anterior de una sesión para este desarrollo.
Main/última instalación certificada: `c5a143541ccfcaf26f29cf252a4cb33fd7c540f7`.
Base de trabajo: PR517 `b23dc20b382cf3b22694afab0b754e687f12588f`.
No se repite la certificación de ese árbol ni se cambia de candidato.

## Decisión

`queues_tokens` observa colas y pases. `browsers_members` observa y autentica al
socio seleccionado. Cada motor tiene activación, generación, START, STOP,
estado y contextos propios. Chromium, Firefox y WebKit son tipos de navegador
dentro de esos motores; no son motores funcionales adicionales.

Se reutilizan el supervisor físico, worker, socket autenticado, observador,
parsers, vault, monitores y guard de reserva existentes. Un coordinador del
controller administra dos trabajos lógicos sobre una activación física. El
primer trabajo pide START al ejecutor actual; el segundo comparte esa
activación. Sólo después del cierre de ambos trabajos y del trabajo local
pendiente se admite STOP físico. Una caída del proceso común se informa como
fallo común; independencia lógica no promete aislamiento de fallo de proceso.

La autoridad durable usa `audit_events` existente con namespace nuevo, separado
de `owner_lifecycle_v1_`. No se modifica el esquema ni se migra al abrir una
página. Holds/releases de cada activación impiden que el cierre automático de
una simulación apague el worker utilizado por otro motor. START y última
liberación se deciden con el mismo bloqueo SQLite de escritura; un contador
en RAM no autoriza operaciones físicas. El reinicio comienza frío: ningún
START histórico autoriza reanudar una sesión.

## Sesiones, transporte y capacidad

La identidad de cada sesión contiene motor, activación, generación, UUID de
sesión y tipo de navegador. El mismo socket AF_UNIX incorpora una orden privada
versionada y acotada. Conserva SO_PEERCRED, identidad de inode, plazo, EOF y
nonce de autenticación. Cancelar una sesión o motor no espera un poll/login
de otro. Resultados de una generación cerrada se descartan antes de publicar.

Un pool crea como máximo un proceso ordinario por tipo y un contexto aislado
por sesión. Los observadores reciben un préstamo de ese proceso y poseen sólo
su contexto/página. La apertura del adaptador BLACKBOX se serializa porque la
supresión de su salida es global al proceso; las observaciones y STOP de los
contextos ya abiertos siguen independientes. No se lee ni modifica BLACKBOX.

El presupuesto lógico total es 50 contextos, compartido por los dos motores.
Los formularios proponen 15 Chromium + 5 Firefox + 5 WebKit por motor: 25 cada
uno, 30/10/10 al trabajar ambos. Son cantidades solicitadas y configurables;
no prometen que el host pueda sostenerlas. El panel distingue solicitado,
creado, activo, cerrado, fallido y capacidad pendiente. Los caps del contenedor
permanecen y una falta de capacidad se informa, sin elevarlos silenciosamente.

La inspección de una sesión conserva la misma página y no hace otro goto.
Las URLs/pases se muestran sólo en el panel privado con revelación/copia
existentes; telemetría pública y logs no reciben credenciales ni bearer.
Posición, Queue ID, tiempo y ausencia de evento requieren señales recibidas;
fallo o desconocido no significan ausencia. No se copian cookies/pases entre
A/B. Cualquier handoff futuro requiere transferencia explícita de propiedad.

## Autenticación y resultados

El socio y su credencial activa se cercan por activación y por sesión. Se
reutilizan readiness, nonce de un uso, transporte supervisado y parser
existentes. Mantener un contexto abierto después de obtener tokens no prueba
que el DOM esté autenticado: el monitor debe distinguir ambas evidencias.
No se inventa un mecanismo de almacenamiento o endpoint de reserva para llenar
esa diferencia. El recorrido permitido conserva la sesión y declara los
requisitos o evidencia que le faltan.

La lectura de la credencial valida activación, generación, socio y revisión
del ciphertext dentro del mismo snapshot SQLite de solo lectura. La conexión
se cierra antes de descifrar e intercambiar; una segunda comprobación autoriza
el envío. Una rotación posterior a ese punto puede cancelar un intercambio ya
admitido, pero nunca autoriza publicar su resultado en una activación revocada.

SIMULATION_ONLY, cantidad 1 y autoridad socio/evento compartida permanecen.
Ningún pase, login, Queue ID ni captura equivale a entrada confirmada. No se
envían avisos de entrada por estos resultados; el requisito de Telegram con
captura exige confirmación real y destinatario verificado antes de habilitar
ese envío. No se ejecutan reservas/compras reales durante esta integración.

## Validación y operación

La matriz cubre ambos apagados, cada uno solo, ambos activos, STOP aislado,
doble START, STOP durante apertura/login, generación tardía, revocación,
reinicio frío, cierre incierto y agotamiento del presupuesto. Fakes de 50
contextos comprueban coordinación; no son medición de memoria ni participaciones
reales de cola. La revisión final del código requiere nuevos votos reales.

El [plan](../superpowers/plans/2026-11-15-r297-independent-engines.md) asigna
archivos y verificación del delta. La promoción consolidada sigue el workflow
Boca protegido, SHA definitivo, postflight y limpieza selectiva. No se opera
ahora el host ni proveedores; Porota/PPI Watch permanecen fuera de alcance.

## Correcciones surgidas en revisión independiente

El observador conserva la tarea de creación de contexto y su handle tardío
cuando STOP interrumpe la espera. El pool hace lo mismo con la adquisición del
manager Playwright. Sin prueba de cierre, la capacidad sigue reservada; cerrar
un préstamo nunca apaga el proceso compartido usado por el otro motor.

El servidor cancela y drena el registro antes de esperar las conexiones activas
de `asyncio.Server`. El controller conserva las tareas hijas y una única fase
de cierre: otro STOP no interrumpe el cleanup ni convierte su cancelación en
una prueba de cierre. Liberar la activación requiere además su ACK de alcance
completo; los cierres individuales no sustituyen ese ACK.

STOP repetido puede reintentar el cierre de su activación con la misma identidad.
El cliente permanece cerrado para nuevas observaciones y logins. Si todos los
holds están cercados, STOP explícito puede pedir recuperación física por el
ejecutor existente; con un motor sano activo, no solicita apagar el worker.
Los holds inciertos permanecen hasta el ACK de alcance o STOP/APPLIED físico.
El callback de cierre certifica el drenaje local, no inventa cierre remoto.

En el runner, sólo STOP explícito puede certificar el testigo estable de una
ejecución que ya terminó. La compensación de START no adquiere ese permiso.
Reconfirmar un certificado conserva su evidencia original y su consumo. El
FULL ZIP cambia por los dos módulos de lifecycle; su allowlist y caps permanecen.

La disponibilidad de START se proyecta sin escribir: exige epoch físico utilizable
y presupuesto disponible, o cierre físico verificado. El total activo usa la
última inspección positiva de contexto abierto, no su creación histórica.

La revisión reprodujo además una incompatibilidad de actualización: un START
físico histórico APPLIED, FAILED o UNCERTAIN sin filas DUAL dejaba ambos motores
sin activación y sin control de cierre. El upgrade existente acredita apagado
físico y esquema, pero no garantiza un recibo STOP/APPLIED en ese ledger.
La recuperación reutiliza el formulario y wake de bot STOP del titular; admite
la solicitud sólo cuando no queda ningún hold lógico, bajo el mismo bloqueo de
escritura que START. Conserva la historia, reutiliza STOP pendiente y no inventa
una activación. START permanece bloqueado hasta el recibo físico APPLIED real.
El panel muestra confirmar, reenviar o esperar según la evidencia disponible.
Un formulario antiguo se rechaza si entretanto comenzó un motor nuevo.

La revisión QA comprobó también el caso DUAL con holds retenidos y START físico
UNCERTAIN. Su STOP explícito puede pedir cierre cuando todos los alcances están
cercados y pertenecen al mismo START físico, incluso tras un reinicio del
controller. Un motor vivo del boot actual sigue impidiendo ese cierre. El STOP
automático conserva su rechazo a UNCERTAIN; los holds y la incertidumbre sólo
se resuelven con evidencia de cierre del runner.

Si ese STOP físico queda CLAIMED o termina REFUSED, FAILED o UNCERTAIN, una
operación nueva del titular puede solicitar otra comprobación del mismo
alcance. Repetir el UUID anterior no crea un nuevo efecto físico; REQUESTED se
reutiliza. La lease protegida serializa ejecutores y sus fences conservan la
historia del pedido reemplazado. Un nuevo UUID permite recuperar también un
CLAIMED ligado a la instalación anterior, sin relajar ese binding. Los recibos
previos y holds no se borran ni se toman como confirmación de cierre.

La confirmación de una ejecución ya detenida añade una prueba por operación
STOP, instalación y token exactos. Conserva el certificado original y exige
APPLIED/FAILED para usar esa confirmación; UNCERTAIN sigue sin autorizar START.
Todas las confirmaciones comparten la marca original de consumo, de modo que
reconfirmar no renueva una ejecución ya gastada. La compensación de START no
recibe esta autoridad adicional.

## QA visual solicitada por Actions

El [pedido del titular y la evaluación inicial](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6886936337)
se registraron durante la revisión. Chromium local abortó antes de abrir una
página por denegación de sockets; no produjo aceptación visual.

El CI existente permite probar el renderer, CSP, formularios nativos y polling
con Chromium real dentro de la imagen del candidato, `--network none`, sandbox
y límites actuales. Las capturas de tamaños de tablet y teléfono usan exclusivamente
miembros y estados ficticios y quedan identificadas por SHA. No se instala otro
navegador en el droplet ni se altera el preview histórico sin formularios.

El selector protegido de origen exacto instalado sólo hace GET de salud y
comprueba identidades. No existe hoy un selector que entregue una captura del
dashboard privado autenticado. La futura captura instalada debe conservar
origen, identidad del par, acceso legítimo, privacidad y cleanup; no puede
fabricar una sesión del dueño ni exportar cookies, pases o credenciales.

## Cierre de fuentes revisado

FULL conserva 47 miembros y ocupa 274702 bytes de ZIP / 1155392 bytes de fuente,
con SHA256 `708dfc01b81dc2f967588088c590ba317c58af2026f338291531de8ea5ad2342`.
El límite de fuente sigue en 1158144 bytes: quedan 2752 bytes.

PAIR se reconstruyó con ocho pruebas canónicas derivadas de los artefactos reales
de release R294 y de los observers que usó APPLY1117. Mantiene 83 miembros,
362048 bytes de ZIP y 1448950 bytes de fuente,
SHA256 `7c8347ac40e8ac65c3d60807d864766200988188f0361f5cc0c2ebd618b809d7`.
El cap 1500000 y la reserva 50000 permanecen; el margen adicional es 1050 bytes.
Los validadores originales aceptaron los ocho archivos sin modificar el reloj.
Son pruebas para dimensionamiento histórico local, no autoridad para un APPLY
nuevo ni copias byte a byte del directorio efímero desaparecido. Con estas mismas
entradas, b23dc20 ocupa 1446843 bytes: 120 más que el corte registrado en R296.

La primera medición real del delta llegó a 1450199 bytes y fue rechazada por
199 bytes antes de host. Se conservaron como comentarios cuatro docstrings
explicativos de lifecycle_intents, reduciendo el paquete 1249 bytes. Tras
normalizar sólo esos cuatro metadatos, el AST con todas sus posiciones y los
objetos de código compilado son idénticos; digest normalizado
`1af2fb68fca2aa34152bf2c2f15057885001e54705fb5edec169d6239f09d767`.
No cambian lógica, allowlists, caps ni reserva. El futuro APPLY debe medir sus
propias evidencias frescas antes de SSH.
Los pins anteriores se preservan como historia; estos ZIP offline no autorizan
ejecutar modos históricos ni certifican una instalación.

## Revisión final de código

El [dictamen y la verificación final](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6887430224)
registran los votos GO de arquitectura/autoridad, QA/producto, integración/operación
y root. Cada revisor excluye sus propios archivos de su dictamen independiente.
La matriz QA final cubre 66 combinaciones de evidencia física, holds y boots;
la ejecución focal final aprueba 208 pruebas. Ruff, formato, mypy de 233 fuentes,
política de aislamiento y pin FULL pasan. La unanimidad es sobre este código;
los artefactos de CI y las pruebas físicas conservan sus gates y límites propios.

## Primer gate publicado: RCA de CI1251

El head `8505db4f4193bec0475e03a18583c93e9772a92e` se publicó en PR517 con
árbol `6fa010788df3e14978070058ab92f7a91f938f58`, idéntico al merge sintético
`df076d91a5edf5fcbbe5afce621fe36b3a617bc9`. [CI1251](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43664696086)
terminó NO_GO: 9143 tests y 34 subtests pasaron, dos tests fallaron y el nuevo
paso visual no produjo artefactos. [Checkpoint completo](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6887623140).

El harness AF_UNIX preparaba una lista cerrada de 14 archivos que no contenía
el nuevo `engine_protocol.py`, importado por el servidor. Se añade ese único
módulo stdlib a la fixture y se verifica su importación en el mismo hijo
`-I -S -B`, con denegación de sockets/procesos durante el import. Los módulos
de navegación permanecen excluidos. La imagen de producción ya copiaba ese
archivo; el fallo era del staging del laboratorio. Su suite focal de 17 casos
pasa después de reproducir el mismo ModuleNotFoundError de CI.

La aserción de limpieza esperaba tres nombres aunque el workflow ahora limpia
los cinco contenedores efímeros exactos. Sólo se actualiza la expectativa; no
se amplía ningún borrado. La comprobación focal pasa.

El renderer usa ZoneInfo de Buenos Aires. El controller Alpine mínimo no
incluía la base IANA y el entorno local sí: al retirar su TZPATH se reproduce
ZoneInfoNotFoundError en la creación de la fixture, antes del navegador.
También existe un uso previo de ZoneInfo en el monitor privado. Se incorpora
`tzdata=2026f-r0` del [repositorio oficial Alpine v3.24/main](https://pkgs.alpinelinux.org/package/v3.24/main/x86_64/tzdata),
manteniendo el pin krb5 y la imagen base. Una comprobación como UID10001 exige
la conversión real a ART durante el build. No se reemplaza la zona IANA por
una hora fija ni se oculta la excepción. [Contrato de datos de Python](https://docs.python.org/3.12/library/zoneinfo.html#data-sources).

El runner visual ahora publica sólo fase, razón y tipo de error de listas
cerradas. Nunca registra contenido de excepción, fixture o browser. Sus cuatro
regresiones diagnósticas pasan y el CLI reproduce `fixture_render` /
`timezone_unavailable` sin stdout cuando falta la zona. La corrección de la
imagen aún requiere el build y el recorrido Chromium del nuevo SHA.

El [primer diagnóstico full3](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43665183283)
observó los tres bundles presentes y Chromium PASS, pero Firefox terminó en
goto y WebKit falló por una biblioteca en launch. La incidencia histórica #402
había quedado diferida; presencia de ejecutable no es prueba de arranque.
El diagnóstico manual existente se amplía sólo para identificar categorías
técnicas y bibliotecas de una lista cerrada, sin publicar stderr ni alterar
caps, sandbox, red o dependencias. No se restauran paquetes GStreamer
vulnerables. Los resultados nuevos deben registrarse antes de afirmar
disponibilidad de los tres motores de navegador.

## Corrección de imagen full3 aprobada antes de implementar

[CI1252](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43666031375)
aprueba 9162 tests, 34 subtests y los laboratorios reales de IPC/UID/systemd.
El recorrido visual falla al registrar un método builtin como callback: el
mapper del wheel Playwright 1.64.1 verificado necesita guardar un atributo en
el callable. Una función Python normal conserva la colección de errores;
la regresión reproduce RED→GREEN sin navegador y tiene revisión independiente.

[Full3 #2](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43666093130)
confirma Chromium PASS, Firefox SIGSEGV durante goto y WebKit sin
libgstcodecparsers-1.0.so.0. Es un bloqueo funcional de los defaults; se conserva
CHECK_FAILED y la retención de custodia, sin declarar disponibles los tres tipos.

El [diseño previo](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6887845873)
y la [unanimidad real de los cuatro revisores](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6887901648)
aprueban una corrección acotada en PR517: base oficial Playwright
v1.64.1-resolute por digest e0006b47eb8c8eb548acebc35ece5968a331051c8f33ae5cd45e9cafd65fdc83,
con CPython 3.12.16/build20261110 explícito y verificado bajo /opt/boca-python.
El contrato Python3.12/uv0.13.4/uv.lock no cambia. Metadatos cerrados por dos
arquitecturas fijan URL y SHA256 de la release Astral inmutable; la venv usa
el intérprete absoluto y prohíbe descargas posteriores. La base trae Python3.14,
que no puede seleccionarse implícitamente para la aplicación.

APT y libapt-pkg7.0 quedan en 3.2.1ubuntu0.1, Brotli en 1.2.0-3ubuntu0.1
y ambos paquetes GStreamer Bad en 1.28.2-1ubuntu1.2. Las fichas oficiales de
[APT](https://packages.ubuntu.com/resolute/apt),
[Brotli](https://packages.ubuntu.com/resolute/libbrotli1) y
[GStreamer](https://packages.ubuntu.com/resolute/libgstreamer-plugins-bad1.0-0)
publican esas versiones de seguridad para amd64/arm64; el build debe comprobar
su disponibilidad firmada efectiva. El helper de mirror
admite sólo Noble o Resolute explícito, preservando firmas y pockets coherentes.
Playwright instala las dependencias de los tres tipos y se reafirman los pins.
Se retiran herramientas de build completas, vendorizadas y ensurepip de ambos
intérpretes, conservando runtime y licencias. No se repite el experimento Debian
de PR332, ya rechazado por sus hallazgos OS.

Se mantienen UID10002, sandbox, seccomp, sólo lectura, caps y controles de
custodia. Los dos escaneos HIGH/CRITICAL, full3 real, CI/IPC y capturas del SHA
resultante son gates; el GO de diseño no acredita que el cambio resuelva Firefox,
capacidad física de 50 contextos, funcionamiento instalado ni aceptación humana.

La [revisión posterior unánime del código](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6888068255)
aprueba la corrección de imagen/helper/callback en sus alcances independientes.
El autor verifica 26 contratos afectados, el helper 41 y el runner visual 21;
arquitectura y QA comprueban nueve casos de imagen cada uno. QA verifica además
los cuatro caminos reales del comando shell de APT con fronteras inertes, sin
añadir errexit: los fallos de helper o segundo update impiden instalaciones.
Los recuentos se solapan. Los diez archivos quedan fuera del cierre FULL/PAIR.
El metadata JSON conserva 1104 bytes y SHA256
01ae08bf7eb4ccb517766aa73526ec0e9a660581eff6fb34f44939528c5185b6.
Build, scans, full3 y capturas del nuevo SHA siguen siendo evidencia pendiente.

## Diagnóstico posterior al build Resolute

CI1253 construye ambas imágenes y aprueba quality-and-tests; el recorrido visual
termina con TimeoutError y no llega a los scans. Full3#3 observa Chromium y WebKit
PASS; Firefox falla en new_page sin una causa clasificada. No se repite el mismo
SHA ni se considera resuelto el bloqueo.

La [corrección diagnóstica previa al código](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6888166845)
separa new_context de new_page con las opciones del runtime. El parser anterior
podía leer un código XPCOM hexadecimal como exit0 y mezclar stderr del fallo con
el cierre deliberado; además, ignoraba errores de cierre. Se conservan fases,
códigos y métodos en listas cerradas, se observa antes de cleanup y el cierre
correcto pasa a ser obligatorio para PASS. Esto no identifica la causa real del
error previo ni cambia la aplicación o sus guardas.

El runner visual conserva todas sus verificaciones y timeouts; añade sólo la
etapa, viewport y contadores acotados para localizar el fallo. Una ejecución Node
inerte del script exacto del renderer con el HTML y cinco snapshots verificó sus
referencias y proyecciones, sin reproducir un navegador ni atribuirle una causa.
Los cuatro roles aprobaron este alcance diagnóstico antes de implementarlo;
la revisión cruzada y la evidencia alojada siguen siendo obligatorias.

La [revisión cruzada final](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6888353010)
obtuvo cuatro votos GO reales para integrar el instrumento: arquitectura revisó
el delta visual (13 casos nuevos PASS), operación/visual revisó full3 (4 focales
PASS), QA revisó ambos (18 y 13 focales PASS) y root revisó la integración.
Cada autor excluyó su propia implementación de su voto independiente. Los
recuentos se solapan. La autoría full3 verificó 39 casos y cinco contratos;
la visual, 34 casos tras 13 RED. Ruff/formato y diff-check PASS. Las seis rutas
modificadas no pertenecen al cierre FULL/PAIR y sus paquetes permanecen intactos.
El análisis de seguridad independiente #1082 sobre ab3f189 permite observar los
scans que CI1253 omitió; su resultado y los nuevos probes siguen pendientes.
Este acuerdo no acredita la causa de Firefox, captura aceptada o promoción.

## Cierre propuesto de los bloqueos de 14cd9a0

Los [resultados alojados](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6888453403)
conservan NO_GO: CI1254 aprueba 9230 pruebas y 34 subtests, pero la UI vence en
queues_start después de aceptar el primer POST. Full3#4 crea contexto y página
Firefox, pierde conexión en goto y no identifica la causa; Chromium/WebKit PASS.
Image security1082 sobre ab3f189 encuentra cuatro HIGH únicamente en el Go1.27.1
embebido de /usr/bin/pebble. OS, Node y paquetes Python analizados no tienen
hallazgos. No se interpreta ese scan como certificado del siguiente SHA.

La [propuesta previa](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6888524385)
separa tres alcances con escritores distintos. Arquitectura retira el binario
Pebble entero innecesario, sólo tras identidad exacta por arquitectura, tipo,
propietario y ausencia de dueño dpkg; no borra metadata ni relaja el scanner.
Las capas/config OCI verificadas no tienen Entrypoint Pebble; Boca usa Python.
El paquete apt homónimo es un servidor ACME distinto y no autoriza un purge.

Visual reproduce el POST303 y GET/control reales mediante un fixture HTTP
efímero en loopback dentro del contenedor CI network-none, sin publicación de
puerto ni listener de aplicación/host. El fixture204 anterior no refleja el
contrato de producción; Playwright1.64.1 conserva una navegación pendiente
en esa ruta y sus redirects no pasan otra vez por el handler route del usuario.
Las cinco navegaciones explícitas se verifican separadamente de la preservación
de filas e inputs durante el polling real. Datos ficticios, CSP, formularios
nativos, SHA, presupuestos, tiempos y límites de captura siguen obligatorios.

QA añade exclusivamente evidencia pasiva a full3: recursos del mismo cgroup y
tres tmpfs antes de launch y al primer fallo, más salida tardía cerrada separada
después del cleanup. UNKNOWN no significa cero. No se atribuye OOM, PIDs o
seccomp sin evidencia; no se cambia ningún predicado PASS ni configuración.
Cada delta requiere votos previos y revisión cruzada de su código antes de
publicarlo. Los paquetes operativos se revisan por intersección, sin rebuild
redundante. La promoción y aceptación física permanecen pendientes.

Los [votos por alcance](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6888549299)
y el [GO QA definitivo del fixture](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6888565397)
completaron cuatro opiniones previas reales para los tres cambios. El fixture
debe aislar servidor/estado por viewport, cerrar listener/socket activo y exigir
hilo muerto tras join acotado. Request-line 2048, headers 8192/64 líneas y cuerpo
2048 bytes; rechazos terminan admisión e impiden PASS. Cinco documentos y seis
snapshots miden 140828 bytes en el diseño, dentro del límite existente 160000.
Esos acuerdos autorizan implementar, no sustituyen revisión de código ni CI.

La [revisión final de los tres deltas](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6888843482)
cerró cuatro votos técnicos reales. Arquitectura y QA revisaron el fixture;
operación revisó imagen y full3; root revisó la integración. Cada autor quedó
excluido de la aprobación independiente de sus propios archivos.

Antes de publicar se corrigieron tres hallazgos: la identidad interna del
cgroup condiciona los deltas; un shutdown concurrente sólo admite EBADF o
ENOTCONN si se comprueba el cierre; y la certificación de descriptores ocurre
después del join acotado, porque socket.makefile retiene referencias hasta que
termina el handler. El P2 de arquitectura retiró temporalmente el GO visual;
su contraejemplo pasa en el sucesor y los recursos que permanecen abiertos
siguen produciendo NO_GO. No se alteró el primer error ni los límites.

La imagen tuvo 42 casos focales PASS; full3, 63 incluyendo dos contratos.
El visual tuvo 79 PASS antes del P2 y 15 afectados PASS después de corregirlo.
Las revisiones independientes fueron focales y se solapan con esos recuentos.
Ruff, formato y diff-check PASS. Las nueve rutas no pertenecen a FULL/PAIR;
sus 47/83 miembros permanecen intactos. La publicación requiere evidencia
alojada nueva: estos votos no certifican el scan, Firefox, capturas ni droplet.


## Polling visual y diagnóstico de tareas tras 18724f8

La [reconciliación del SHA](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6889022274)
registra CI1255: 9331 pruebas y 34 subtests PASS, ambas imágenes construidas y
fallo visual en live_rows_poll tras dos POST303 y tres documentos; no hay
capturas. La causa primaria sigue UNKNOWN. Image Security1083 del mismo SHA
aprobó ambos scans estrictos sin HIGH/CRITICAL; cierra el hallazgo Pebble de
ese candidato. Full3#5 mantiene Chromium/WebKit PASS y Firefox NO_GO en
new_page: pids.peak128 y delta pids.events.max1 con identidad conservada;
memoria336003072B del límite805306368B y deltas OOM0. Acredita aplicación del
límite de tareas; no demuestra OOM, causalidad exacta, capacidad para 50
contextos ni disponibilidad del dashboard instalado.

La [propuesta](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6889045401)
y los [cuatro votos previos reales](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6889058150)
autorizan dos alcances disjuntos. El visual expresa condiciones DOM como
funciones conservando RAF y plazos, y espera response.body para evitar la tarea
huérfana de Response.finished verificada en Python Playwright1.64.1. Añade sólo
clasificación cerrada del primer error y página/conexión bool/UNKNOWN,
congelados antes de cleanup; nunca mensaje, URL, stack o datos. No cambia CSP
ni aplicación y no declara demostrada la hipótesis CSP del fallo anterior.

El workflow diagnóstico añade choice full3/default o firefox-pids. Default
conserva los tres motores y 128 tareas. El modo experimental ejecuta sólo
Firefox192 y Firefox256 una vez cada uno, secuenciales y sobre la misma imagen;
ningún PASS posterior borra un fallo. Antes del driver exige pids.max entero
exacto del presupuesto solicitado; UNKNOWN o discrepancia produce NO_GO.
Mide también preclose tras goto/conexión y antes de cerrar; PASS exige los
tres cierres. Se conservan el primer fallo, deltas con continuidad y stderr
tardío separado. Identidad o límite no verificable no acredita atribución.
No se cambian memoria, CPU, tmpfs, permisos, sandbox, plazos ni recursos de
la instalación.

Autores: operación/visual, dos archivos runner/tests; QA, workflow y dos
contratos afectados; root, ADR y plan. La intersección de las siete rutas con
FULL47/PAIR83 es vacía, sin rebuild ni modificación de pins/caps. La revisión
cruzada final del código y la evidencia alojada nueva siguen pendientes;
los votos de diseño no autorizan por sí mismos merge, release, host ni
aceptación física.

La [revisión final](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6889186686)
cerró cuatro votos técnicos reales sobre los hashes definitivos. Arquitectura
revisó ambos deltas; QA y operación realizaron el cruce, excluyendo sus propios
archivos de aprobación independiente; root verificó la integración. Sin
hallazgos bloqueantes. Autor visual: 18 RED y 45 afectados PASS. Autor del
diagnóstico: 37 RED y 58 afectados PASS en el cierre focal. Arquitectura
verificó cuatro casos por alcance y contraejemplos adicionales en memoria;
QA verificó cuatro visuales. Los recuentos se solapan. Ruff, formato, YAML,
Bash, AST y diff-check PASS; no se repitió la suite base.

La metadata pids_budget_verified separa atribución de suficiencia: true exige
identidad/límite/contador coherentes; un delta positivo sigue visible y no
acredita holgura. UNKNOWN no certifica el experimento aunque el recorrido
funcional termine en PASS. Se publican los siete archivos juntos; los gates
alojados del sucesor, capturas y promoción física siguen pendientes.
