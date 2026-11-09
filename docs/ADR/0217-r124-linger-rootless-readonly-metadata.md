# ADR0217 — R124: linger y metadatos rootless Boca, sin acciones Docker

Estado: **candidato CODE_ONLY, pendiente de PR, CI y despacho READ_ONLY**.
Continuidad: issues #417 y #45. Propietario del alcance: diagnóstico
DevOps/infraestructura; sin cambio de configuración ni instalación.

## Por qué es necesario

El RCA histórico del worker en Cutover V3 #878 (`HEALTH_EXITED`, ExitCode 1,
OOM false) **no posee stderr/traceback, State.Error ni logs internos
recuperables**. PR #452 / R122, integrado en `main=70e91f0884e054c5494c034dbe6445fc0f931160`,
clasifica la inferencia no causal; `worker_internal_cause` continúa UNKNOWN.
La observación READ_ONLY #886 comprobó la topología Boca posterior, no el
valor actual de systemd `Linger` ni la configuración del home/rootless user.
Es incorrecto atribuir ExitCode1 a linger, UID/GID o OCI sin medirlos.

El inspector `inspect-prerequisites` ya informa sockets, cgroup, el estado
de la **única** unidad `docker.service` y candidatos SQLite por metadatos.
Pero **no** ejecuta `loginctl`, no inspecciona los rangos subordinate ID,
los binarios UID map ni los directorios de configuración. El `prepare-rootless`
histórico sí exige `Linger=yes`, pero esa ruta tiene efectos y una precondición
de primera configuración que ya no corresponde al host preparado.

## Opciones y decisión

1. Repetir `prepare-rootless`, `start-existing` o Cutover: **rechazado**;
   puede modificar el host, no devuelve una RCA retrospectiva y su reintento
   no fue autorizado por un fallo previo.
2. Añadir todo a `host_first_deploy.py`: **rechazado** por presupuesto medido:
   el bundle full consumía 877124/880000 bytes, y worker-preflight
   479638/480000 (solo **362 bytes** de margen). No subir los techos.
3. **Elegido:** script independiente `scripts/boca_linger_readonly.py`,
   solo stdlib, transmitido por stdin en el **mismo workflow y selector
   `inspect-prerequisites`**. No se incorpora a los ZIP protegidos, no se
   instala en el host, no añade puerto, Environment, credencial ni operación.
   Un verificador runner-side `scripts/verify_boca_linger_receipt.py` queda
   fuera del host y de ambos ZIP, con pruebas dentro de PR-validation.

El script requiere UID/EUID/GID/EGID=10001, passwd `boca-deploy` con GID
10001 y home **exactamente `/home/boca-deploy`** **antes** de mirar archivos
o comandos; un home ajeno (ej. `/srv/porota`) causa `NO_GO_IDENTITY` sin
inspeccionar el host. Hace exactamente un `loginctl
--no-ask-password show-user 10001 --property=Linger --value` con entorno
cerrado y timeout 5s; acepta exclusivamente `yes\n` y `no\n`.
El resto de respuestas, fallos, permisos o timeout produce UNKNOWN sin
publicar stderr ni contenido original. No invoca Docker, `systemctl start`,
`sudo`, `enable-linger`, rootlesskit ni BLACKBOX.

Mediante `stat` sin seguir symlinks ni recorrer directorios ajenos, informa
tipo, UID, GID y modo del home y runtime `/run/user/10001`, de sus tres
sockets privados, del marcador de linger y de dos rutas Boca bajo el home:
directorio de datos Docker y archivo de unidad `docker.service`. Sólo informa
el tipo y metadatos del objeto, **no lee su contenido** ni asegura la cadena
completa de permisos de padres en la observación del dato y la unidad.
Las rutas y nombres no salen en el recibo. El GID de `docker.sock` es
**informativo**: una correspondencia diferente a 10001 puede ser válida por
rootless/user namespaces y no genera por sí sola NO_GO.
El socket **Docker** con escritura pública se clasifica `OPEN_MODE`
y nunca `METADATA_CANDIDATE`. Los sockets `bus`/`systemd/private` pueden
tener modo `0666` conforme al valor por defecto oficial de
[`SocketMode=`](https://www.freedesktop.org/software/systemd/man/latest/systemd.socket);
se clasifican `SYSTEMD_DEFAULT` y son admisibles **solo con** el runtime
UID10001/GID10001/0700 comprobado. Otros permisos públicos y los sockets
sin escritura del propietario no son candidatos. No se cambia ningún modo.

En `/etc/subuid` y `/etc/subgid` lee archivos del SO hasta 1 MiB, solo si
son regulares, root-owned y no editables por grupo/otros, sin seguir symlink.
Analiza únicamente la fila `boca-deploy` o `10001`, que debe ser única,
con rango mínimo de 65536 UID/GID y sin desborde de 32 bits. No emite nombres
ni rangos de otras cuentas. Comprueba presencia confiable de
`/usr/bin/newuidmap` y `/usr/bin/newgidmap`, y `max_user_namespaces` sin
crear namespaces, iniciar demonios o tocar configuración.

## Recibo, garantías y límites

`BOCA_LINGER_ROOTLESS` produce `identity=OK`,
`linger=YES|NO|UNKNOWN`, `state=METADATA_CANDIDATE|PREREQUISITES_UNPROVEN`;
líneas complementarias `BOCA_LINGER_DIR`, `BOCA_LINGER_SOCKET`,
`BOCA_LINGER_LAYOUT`, `BOCA_LINGER_IDS` y `BOCA_LINGER_SCOPE` tienen
vocabulario/cantidades cerradas, longitud acotada y nunca rutas, env ni
secretos. El runner captura stdout SSH en un archivo temporal privado con
límite y timeout; el intérprete remoto usa `python3 -I -S -`. El runner
**solo publica las seis líneas tras validar** longitud, ASCII, orden,
campos, rangos, correlación de estado y código de salida exacto. Errores
de SSH/transporte, salida ajena, truncamiento o recibo malformado imprimen
únicamente un `NO_GO` fijo, y no provocan otra conexión SSH.
`METADATA_CANDIDATE` es **solo un diagnóstico**, NO un GO de instalación.
`exitcode1_cause=UNKNOWN deploy=NO_GO` siempre.

El diagnóstico nuevo corre **antes del inspector anterior**. Si entrega
un recibo auténtico y validado, incluyendo `PREREQUISITES_UNPROVEN`, se
ejecuta el inspector anterior como una lectura independiente, nunca como
reintento del mismo comando. Un gate final declara NO_GO cuando los metadatos
linger son insuficientes, incluso si el inspector anterior termina bien.
El SSH está acotado a 30s y usa la misma identidad Boca y host key pinneada.
El script solo inspecciona: la conexión SSH puede dejar trazas normales del
sistema operativo, pero no hay escrituras de aplicación ni consultas Docker.

`subuid/subgid=VALID`, `newuidmap=AVAILABLE`, `linger=YES` y
`METADATA_CANDIDATE` son **observaciones parciales**: no verifican rangos
superpuestos con otras cuentas, ejecución real de mapeos, salud del daemon,
compatibilidad OCI ni arranque IPC, y no explican la causa de ExitCode1.

Si el resultado fuera `linger=NO`, **no ejecutar `loginctl enable-linger`**
ni cambiar ownership/permisos: requeriría una decisión aislada de reparación
de cuenta y nueva evidencia. Si `linger=YES`, se prueba el estado actual, no
que fuera igual durante #878 ni que el worker IPC arrancaría. Si `UNKNOWN`,
no sustituirlo por el estado de `docker.service` o un marcador inferido.
OCI/source de la imagen histórica R108, logs del proceso muerto, la
ubicación global de owner/DB y la RCA ExitCode1 siguen por sus frentes
independientes, sin fingir que esta lectura los resuelve.

## Validación y siguiente control

TDD de identidad previa, respuestas/malos formatos de logind, timeout,
subordinate IDs, archivos inseguros, symlinks, sockets/GID rootless,
home ajeno, permisos públicos, salida SSH maliciosa/truncada, transportes
fallidos, ausencia de comandos mutantes, contrato del selector y no duplicación de
permisos. Exigir suite completa, Ruff, formato, MyPy, policy, revisión
Arquitectura/DevOps/QA, PR y CI exact-SHA antes de incorporar a `main`.

Sólo después, una ejecución manual **única de lectura** de `Boca first
deploy` con `operation=inspect-prerequisites`, `source_sha` igual al SHA
hexadecimal **completo** del HEAD vigente de `main`,
`service=controller`, `resource_budget=0.5cpu-256m-64pids`, resto vacío,
permitirá sustituir `Linger=UNKNOWN` por un dato físico verificado. No
iniciar Cutover ni Telegram por esta ampliación. El recibo deberá quedar
registrado en #45 y #417 con el run/SHA y su alcance.
