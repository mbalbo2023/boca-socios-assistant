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
