# ADR0301 — R296: un candidato para autenticación automática y Telegram

Fecha: 2026-11-14 ART. Estado: CANDIDATO EN RAMA; no instalado.

## Objetivo y decisión del titular
El titular aún no realizó su control de calidad y pide dejar todo listo para
desplegar, incorporando después sus correcciones en un único candidato.
[Decisión canónica](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6881603931).
Se conserva PR517 y su rama desde e8f8395820a720fef3f7d275a490400582adacec;
main/instalada sigue c5a143541ccfcaf26f29cf252a4cb33fd7c540f7.

No hay autorización nueva que pedir para el desarrollo ya encargado. La
promoción queda pendiente de las correcciones del titular; no se ejecutan merge,
release, host, START/STOP del agente, navegación a proveedores ni mensajes.

## Alternativas y elección técnica
1. Volver a construir módulos independientes prolongaría la separación entre
componentes y flujo de usuario y duplicaría código ya revisado.
2. Conectar las piezas existentes mediante sus límites de sesión, custodia y
ciclo de vida completa la función y conserva la evidencia anterior. Es la
elección técnica de integración dentro del alcance autorizado.
3. Quitar gates o marcar estados verificados sin evidencia no implementa las
capacidades faltantes y se descarta.

## Boca
El selector START vincula un socio activo a su UUID en la transacción existente;
una solicitud histórica sin selección sigue siendo observación solamente.
La selección es visible y no cambia por replay ni por elegir otro socio durante
una activación. Los datos secretos permanecen en el vault existente del controller.

El worker conserva la misma sesión Chromium. La preparación devuelve una
observación, y sólo emite una capacidad efímera cuando una página de login
inequívoca de origen permitido está disponible sin cola/challenge. Un destino
o token de Queue-it no equivale a permiso para enviar credenciales. La navegación
de continuación utiliza una única vez el destino legítimamente recibido.

El IPC privado existente añade requests/responses tipados acotados, con peer e
inode comprobados antes de leer secretos. Un nonce pertenece a una operación y
contexto y se consume antes del intercambio. Un proceso efímero supervisado
ejecuta el transporte R295 con las cookies del contexto existente; el límite
total incluye DNS/TLS/lectura/cierre y STOP debe terminar/recolectar el proceso.
No se añade otra sesión de cola, bypass, refresh inventado ni petición de tickets.

El servicio/parser/monitor de autenticación existente se reutiliza. El servicio
no publica por su cuenta: el coordinador comprueba de forma serializada el START
APPLIED, socio activo y STOP antes de publicar. Las etapas visibles son categorías
sin credenciales, tokens ni URLs sensibles.

## Telegram
El caller staged-custody, stage cifrado/passkey, helper de cuatro GET, outbox y
sender existentes se conectan a un backend de instalación vigente. Sus
coordenadas se derivan del binding y evidencias reales bajo la misma lease, no
de flags o CIDs aportados por la UI.

El mecanismo existente de mantenimiento usa la imagen instalada exacta, UID
interno y mounts Boca identificados, red none y recursos acotados. Se reutiliza
para operaciones fijas de almacenamiento/crypto en el namespace que tiene acceso
a los volúmenes. Adaptadores estrechos inyectados en los coordinadores existentes
mantienen sus algoritmos; no se crea un motor criptográfico ni helper persistente.
El coordinador conserva la lease en host y verifica identidad antes/después.

Prepare verifica esquema y custodia antes de escribir y publica sólo un recibo
de clave pública unido a fuente/instalación; no migra SQLite implícitamente.
La UI utiliza ese recibo automáticamente en el stage existente. Activate vuelve
a comprobar owner, stage, nonce, custodia y topología; las fases detenidas no
utilizan un attestor que exige controller healthy. Fallos conservan historial
y estado parcial y restauran solamente el controller exacto cuando es seguro.

El sender existente admite la custodia V2 verificada. La aceptación reclama
sólo su UUID mediante el mismo outbox y no exige borrar historial ni consume
avisos previos. Aceptación API y recepción humana siguen siendo evidencias
diferentes. La capacidad física rootless y respuestas de proveedor sólo se
certifican en operaciones posteriores; las pruebas offline no las inventan.

### Fases y recuperación explícita

| Selector protegido | Resultado verificable | Límite |
| --- | --- | --- |
| `telegram-prepare` | Destinatario público de la instalación vigente | Sin migrar SQLite ni enviar; worker detenido antes de parar controller. |
| `telegram-activate` | Custodia V2, aceptación API y sender incorporado al binding | Stage/passkey, cuatro GET acotados, identidad original y controles por fase. |
| `telegram-renew-stage` | Stage anterior archivado; controller restaurado | Sin custodia completa/parcial. Conserva sobre y nonces; exige código/firma nuevos. Máximo ocho archivos de historial. |
| `telegram-complete-sender` | Finalización de custodia ya comprometida | No repite pairing. Conserva intento/UUID original; API_ACCEPTED evita otro envío, NOT_ATTEMPTED permite sólo el primero, ambigüedad bloquea. |
| `telegram-sender-recover` | Binding/par restaurado o estado republicado | Sin envíos ni nueva identidad de aceptación. Un journal incompleto exige el perfil detenido; estado ya saludable no requiere otro STOP. |

La identidad original se demuestra con el stage, su nonce consumido y la
custodia V2 existente, incluida su firma/HMAC canónico. El nuevo run autoriza
la operación protegida, pero no crea un UUID de aceptación distinto. El outbox
continúa como único ledger de entrega; no se añade una base paralela.

La adopción del sender conserva los campos no relacionados de la instalación
y el archivo ejecutable. Un journal de nombres fijos bloquea el handler durante
la transición de binding/unidades, verifica bytes/hardlinks y conserva estado
ante compensación incierta. No se describe esa secuencia como atómica entre
archivos. Un contenedor sin binding cuya creación quedó incierta requiere RCA;
no se borra por nombre ni se crea otro sender para superar la incertidumbre.

Los helpers de almacenamiento mantienen `log-driver none`, identidad exacta y
montajes fijos. Un volumen existente pasa el verificador canónico de Driver,
Scope, Options y ruta; el nombre o las etiquetas no reemplazan esos controles.
Sólo un volumen recién creado y comprobado vacío admite inicialización UID0/
CHOWN; los existentes nunca se reinicializan ni se eliminan.

### Proyección pública y experiencia de emparejamiento

La página servida genera el código en memoria, sella el token y exige guardar
el stage con passkey antes de mostrar o permitir copiar `/start`. El titular
envía ese comando después del HTTP 202. Se conserva la condición temporal
`discovery_not_before=staged_at`. Si se pierde el 202, la renovación explícita
puede archivar ese stage válido no consumido; nunca se renueva automáticamente.

Tras restaurar/verificar el controller, el publicador estricto existente escribe
la última observación del par y la custodia real que consume `/telegram`. No
abre ni migra SQLite. Un resultado de custodia UNVERIFIED se registra como tal
y bloquea PREPARED/READY cuando la fase exige evidencia positiva. La observación
se vuelve histórica después de su ventana; no se presenta como heartbeat.
Recepción humana permanece UNVERIFIED incluso si la API aceptó el mensaje.

## RCA de las revisiones del candidato

Las [correcciones focales](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6882117122)
y el [cierre de fases](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6882197549)
registran evidencias y responsables antes de modificar cada alcance.

| Defecto reproducido offline | Causa y corrección |
| --- | --- |
| Monitor decía «ciclo finalizado» antes del login | Ready podía conservar cola UNKNOWN. Overlay de autenticación correlacionado, con publicación exitosa dentro de la barrera SQLite. |
| Mensaje de emparejamiento rechazado por fecha | La UI pedía enviar antes de guardar el stage. Se corrigió el orden; fixtures usan tiempos distintos y preservan la frescura. |
| Falla de GET impedía todo emparejamiento nuevo | Stage inmutable más nonce consumido. Renovación explícita archiva ambos hechos sin repetir solicitudes. |
| Volumen bind aceptado sólo por etiqueta/nombre | Faltaba reutilizar Driver/Scope/Options del verificador canónico. Se aplica antes de acceder a la custodia y en rechecks. |
| Custodia lista, sender incompleto y sin continuación | Se conservaba el nonce pero no se retomaba la fase posterior. Continuación explícita con identidad ORIGINAL y lectura del outbox. |
| Actions READY no aparecía en `/telegram` | Faltaba publicar la proyección que lee el panel. Publicación después de restauración con guard de downgrade. |
| Completion saludable carecía de mountpoints | El fixture sustituía el constructor de contexto. Se reutiliza el resolver instalado y se prueba contexto/attestor reales con I/O sintético. |
| Importación diferida ausente en ZIP | Selftest de imports no ejecutaba el perfil del controller. Proyección canónica completa y prueba aislada del perfil real. |
| Red V2 se verificaba con nombre legado | Constructor y attestor legado no recibían la selección V2. Opción acotada conserva defaults y usa la red del contexto/provisión/helper actuales. |

La lección es verificar conexiones entre módulos y fases con los parsers,
almacenamiento y attestors reales; un mock de I/O no debe sustituir el contrato
que se intenta certificar. Los fallos se corrigen antes de publicar un nuevo
SHA, con regresiones pertinentes y revisión independiente, no con reruns ciegos.

## Empaquetado, pruebas y responsabilidades
Los cambios del ledger conservan su cierre stdlib para todos los ZIP de host.
La imagen browser sólo recibe hojas revisadas; nunca DB/vault/cryptography.
El paquete Telegram mantiene su tope y su separación de Cutover. Preparación
y activación pueden tener cierres exclusivos exactos usando implementaciones
canónicas; no se elevan caps o reservas para ocultar exceso.

El ZIP instalado Telegram selecciona declaraciones y dependencias estáticas
canónicas de cleanup, perfil Docker, instalación, servicio, stage y owner. Cada
nodo conserva su AST; no se mantiene una copia del algoritmo. El cierre servido
excluye dispatcher/handler ajenos a esta operación y crypto de imagen innecesaria
en host. Se verifican allowlist/digest, ejecución aislada `-I -S -B`, decoder real,
perfil del controller y recibos. Caps siguen en 450000 bytes de fuente y 300000
comprimidos; full Cutover y sus reservas conservan sus límites independientes.

El [plan R296](../superpowers/plans/2026-11-14-r296-consolidated-beta.md)
asigna worker, controller y Telegram a escritores disjuntos; root posee
integración compartida, documentación y publicación. Pruebas focales, revisión
independiente y checks del SHA consolidado preceden su estado de candidato.
No se repite la suite local completa de R295 ni se confunde CI con despliegue.

### Corte de verificación offline antes de publicar

- Selección consolidada de 27 archivos de pruebas afectados: **417 passed en
  31.63 s**. En R82 se ejecuta sólo el caso del pin ACTUAL requerido; no se
  repite la suite local completa del árbol base.
- Ruff y formato: 76 archivos Python afectados; mypy estricto: 49 fuentes sin
  errores. `git diff --check` y política del repositorio aprobados. YAML válido
  y 17 bloques Bash pertinentes verificados sintácticamente.
- Se construyeron 19 variantes de paquete y se verificaron sus límites y
  transportes existentes. Es empaquetado offline, no construcción de nuevas
  imágenes publicadas ni operación del droplet.

| Paquete | Fuente (bytes) | ZIP (bytes) | Restricción conservada |
| --- | ---: | ---: | --- |
| Full Cutover | 1153285 | 274578 | 1158144 de fuente; margen 4859. |
| Worker preflight | 514909 | 107927 | 520000 de fuente; margen 5091. |
| Administración instalada | 847715 | 206551 | 900000 de fuente. |
| Pair upgrade | 1448257 | 362370 | 1500000 de fuente, con 50000 reservados; margen adicional 1743. |
| Rootless observer | 1392297 | 344778 | 1400000 de fuente. |
| Telegram instalado | 440382 | 125394 | 450000 / 300000; margen de fuente 9618. |

Pin revisado del full ZIP:
`ef06f5a8c8e941b1a1a61defc4f4bbe4aa52a252d85e8533871d6ea2e3d98267`.
El test conserva todos los pins históricos. ZIP Telegram instalado:
`dd6f1cdb58752b145abce94c1f618bf7a5368f0d7993bfb0bad9b4b745425312`.
Estos digests son del transporte derivado de las fuentes, no imágenes ni
certificados de instalación. Cambios posteriores deben volver a medir su
cierre pertinente; la reserva no se puede consumir ni elevar para pasar CI.

El recibo PREFLIGHT_FAILED expresa sender UNVERIFIED cuando todavía no se
observó el binding. La prueba aislada de lease denegada demuestra cero lecturas
del binding; otra prueba SIGTERM ejercita la restauración por la fase conocida.
Una pérdida abrupta no sustituye el procedimiento explícito de recuperación.

## Estado y aceptación
R294 sigue siendo la última instalación certificada. R295 y R296 comparten
PR517; el código nuevo no está instalado. Las pruebas focales y revisiones por
alcance se registran en #417, y el resultado requerido de CI pertenece al SHA
exacto publicado. No se repite localmente la suite completa certificada de base.
Las correcciones Samsung, la promoción final y las comprobaciones físicas de
Docker/systemd, proveedor, START/STOP y recepción humana permanecen pendientes.
Una observación CI GREEN no reemplaza ninguna de esas evidencias.

