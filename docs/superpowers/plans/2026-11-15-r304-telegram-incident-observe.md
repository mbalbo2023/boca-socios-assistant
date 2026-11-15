# R304 — observación acotada del incidente Telegram1156

## Requisito y evidencia previos al código

Requisito registrado en [issue525](https://github.com/mbalbo2023/boca-socios-assistant/issues/525).
Este documento es el diseño sometido a cuatro votos reales previos al código:
Arquitectura, QA, Operaciones y raíz Producto/Seguridad. Autor separado.
Los votos de factibilidad anteriores no sustituyen la aprobación de este plan
ni las cuatro revisiones finales del árbol implementado.

Base exacta del worktree y remoto: R845f31abfb1762dff27e6fc3274fcc40507f3f18,
árbol f360328ed36e4d738a957ae56f40791728ef5cd9. Se importó el objeto Git firmado
de GitHub sólo después de reproducir su SHA exacto; no hay checkpoint como padre.
R sigue instalado por APPLY1153/run43704768556, release867/run43704139794.
CI1270 y Security1089, APPLY/cleanup, ADMIN1154 y STATUS1155 ya están consumidos.

PREPARE1156/run43705714873 devolvió FAILED_STATE_PRESERVED,
restorationINDETERMINATE, senderOFF. PAIR1157/run43705926587 devolvió
HOST_UNVERIFIED sin inventario ni artefacto. Exact-origin1158/run43706245769
confirmó HEALTH_HTTP_200 mediante dos GET de salud, sin identidad del proceso.
Sus metadatos UID_DIFFERS_FROM_HOST no prueban un defecto de permisos; no
autorizan chmod/chown. Ninguna de estas lecturas prueba un helper residual,
la fase histórica fallida, ni presencia/ausencia de clave o recibo público.

El censo del par exige compose.service a todos los contenedores; los helpers
de mantenimiento no tienen esa etiqueta. Restore exige topología exacta y
su fallo sobrescribe el estado anterior. Es una brecha demostrada de diagnóstico,
no una explicación acreditada de1156. No repetir prepare para obtener un log.

## Resultado y no efectos

Añadir un único selector boca-telegram-incident-observe y un observador propio
READ_ONLY. Debe describir el par exacto y, si existe uno solo, un helper del
incidente sin exigir que la topología ya sea aceptable para operar.
Un perfil incorrecto completamente observado es un resultado diagnóstico
válido; no debe volver a ocultarse tras un HOST_UNVERIFIED genérico.

No modificar censo, healthy, backend, atestadores existentes, límites de
Telegram, runtime de los motores ni imágenes. No lease, journal, SQL, contenido
de archivos de datos/custodia, HTTP, exec, start, stop, create, rm, provision,
restore, limpieza, envío ni navegación. SIMULATION_ONLY; BLACKBOX unread y
unmodified; Porota/PPI fuera de alcance. El diagnóstico no requiere release
de imágenes ni un segundo APPLY. W es el nuevo main del observador; R es la
fuente instalada y pueden diferir.

## Coordenadas fijas y admisión

Las coordenadas salen del código revisado, nunca de campos libres del caller:

- Incidente43705714873; APPLY43704768556; instaladoR845f31abfb1762dff27e6fc3274fcc40507f3f18.
- Controller b0dd0fed57c55dbdeb9a6e833d913cb86c0868ae1587394a934450342114bfa1.
- Worker c9c882ff12666fb6cac130879925879cfc0c5c23173a843434adee96b4339dce.
- Controller digest9fc622a3a7165ce03d1113b5f7f334d402a0dad0c6cbfe2da28075843d11bea0.
- Worker digest1a59e0b0cb5eb3621820aed635364076542b691fa6e9c73c0e344f09dacc3abe.
- Repositorios GHCR canónicos de Boca/controlador y Boca/browser ya usados.

Reusar _read_host_binding de host_boca_binding_observe, sin llamar observe ni
pair.observe. Comprobar su concordancia exacta con todas las coordenadas fijas.
Reusar cleanup._rootless_docker_disk_inodes antes de cada pasada y cleanup._docker
como transporte. No modificar esas fuentes compartidas. Comparar dispositivo
e inodo de la raíz del daemon, no capacidad libre variable. UID10001, socket
fijo, rootless/cgroup/systemd y nofollow conservan sus guardas existentes.

## Comandos, ámbito y doble lectura

Recorrido: daemon → binding → listado de IDs/nombres → pertenencia → dos CIDs
fijos → candidato único → binding, repetido una vez y comparado. Dos lecturas
reales; sin reintentos para conseguir estabilidad. La lista inicial se limita
a IDs completos y nombres, máximo tres contenedores y8192 bytes. Rechazar IDs
duplicados, exceso, truncado, desaparición o un objeto adicional no permitido.

Sólo se admite el par fijo y, como máximo, un nombre exacto del patrón
/boca-socios-telegram-maint-43705714873-[a-f0-9]{16}. Antes de perfiles, comprobar
project Boca con plantilla fija. No inspeccionar otros CIDs para averiguar qué
son. Ningún campo, plantilla, ruta o comando proviene del caller. La lectura
de bindings y systemd reutilizada es sólo consulta; no normaliza permisos.

La allowlist de inspección por CID se limita a Id/Name, Image, Config.Image,
Config.User, Config.Cmd, labels individuales de project/service/revision/config
hash/attempt, State.Status/Running/Restarting/Pid/ExitCode/OOMKilled y
State.Health.Status, más campos de HostConfig estrictamente necesarios:
NetworkMode, ReadonlyRootfs, Privileged, LogConfig.Type, CapDrop/CapAdd,
PidsLimit/Memory/NanoCpus, PublishAllPorts/PortBindings, RestartPolicy.Name,
SecurityOpt, Mounts y NetworkSettings.Networks. Cada plantilla es literal,
con respuesta máxima8192 bytes, rechazo sin truncar y sin parsear excedentes;
no inspect completo, Env, State.Error, Health.Log,
stdout/stderr de helpers, labels completas ni cuerpos de secretos.

Para origen de mounts se consulta sólo el Mountpoint de volúmenes canónicos
necesarios y previamente pertenecientes a Boca. Sus rutas nunca se publican.
Reusar MOUNTS de telegram_maintenance_contract, sin importar _attest ni backend.
Las operaciones reconocidas se limitan a verify-schema, owner-identity,
initialize-volume, prepare y publish-recipient, que pertenecen a prepare.
Una operación conocida fuera de esa ruta recibe OPERATION_OUTSIDE_PREPARE;
un comando desconocido no se imprime y recibe UNKNOWN_OPERATION/ARGV_MISMATCH.

## Proyección y razones finitas

Documento canónico de una línea, prefijo propio versionado y máximo4096 bytes.
Identifica run de observación/W e incidente/R/APPLY por separado. Incluye
observer_writes0, engineUNVERIFIED y restore_authorized/cleanup_authorized/
deploy_authorized false. No hay un resultado que otorgue autoridad operativa.
Claves exactas, claves duplicadas rechazadas, tipos estrictos sin bool como int.

Para cada CID fijo: presencia, identidad coincidente, status de Docker cerrado,
running/restarting, PID0..2147483647, exit-1..255, OOM booleano y health cerrado.
No convertir workerPID0 en certificación del motor del controlador.

Helper ABSENT sólo significa ausencia actual. Un candidato único permite
CID, operación enum, estado y fronteras de perfil. Dos candidatos o identidad
no correlacionable implican observación incompleta, sin elegir por orden/edad.
Razones por frontera, en listas ordenadas y acotadas; no texto libre:

| Frontera | Razones permitidas además de MATCH/UNVERIFIED |
| --- | --- |
| Identidad | NAME_MISMATCH, IMAGE_MISMATCH, PROJECT_MISMATCH |
| Comando | MODULE_MISMATCH, ARGV_MISMATCH, UNKNOWN_OPERATION, OPERATION_OUTSIDE_PREPARE |
| UID | UID_MISMATCH |
| Capacidades | CAPDROP_MISMATCH, CAPADD_MISMATCH |
| Mounts | COUNT_MISMATCH, SOURCE_MISMATCH, TARGET_MISMATCH, MODE_MISMATCH, DRIVER_MISMATCH |
| Red | MODE_MISMATCH, ATTACHMENT_MISMATCH, PORTS_PRESENT |
| Recursos | CPU_MISMATCH, MEMORY_MISMATCH, PIDS_MISMATCH |
| Seguridad | ROOTFS_WRITABLE, PRIVILEGED, NO_NEW_PRIVILEGES_MISSING, RESTART_POLICY_MISMATCH, LOG_DRIVER_MISMATCH |

initialize-volume conserva el perfil esperado UID0:0/CHOWN; los demás10001:10001
sin capacidades añadidas. Observar CHOWN, CAP_CHOWN, ausencia u OTHER como enums
distintos sirve para diagnosticar; no cambia qué acepta el atestador existente.
Los valores inesperados nunca se reflejan literalmente. Perfil discrepante
observable → OBSERVED_NO_GO; adquisición incompleta o ambigua → INCOMPLETE_NO_GO
con fase/razón de vocabulario cerrado (binding, daemon, inventario, campo o drift).
Conservar sólo datos ya verificados en un recibo incompleto, sin rellenar estados
desconocidos con éxito. Parser y CLI distinguen ambas clases explícitamente.

## Paquete y Actions

Nuevo modo --telegram-incident-observe de build_protected_boca_bundle y modo
boca-telegram-incident-observe del memfd. Reusar BINDING_SOURCES y añadir sólo
observer y telegram_maintenance_contract:29 entradas esperadas. Cota propia,
tomada del binding:900000 fuente/320000 ZIP, sin ampliar ningún modo existente.
Base estática24 archivos/766450 bytes; contrato1488; observer máximo24000 y
entradas generadas máximo1024 dejan margen. Medir el ZIP final una vez;
contradicción de inventario/cota detiene, no se resuelve elevando caps.
Telegram permanece47/449961 fuente/126448 ZIP y pin4a235926762120596e9a9ccf5cc5f57b464aeba14b65a866f5a2f236c8e792c9.
Full-cutover pin066214cb4ae6a84f9e88973e38e58f7780dccf9556d1beb75cfb7c3b3a500c0e intacto.

Único workflow con host: boca-first-deploy, mutex manual constante existente,
environment protegido, permisos existentes, workflow_dispatch/main/repositorio
exactos, actor y triggering_actor mbalbo2023, attempt1. BOCA_HOST_READONLY_ENV_READY
y BOCA_DEPLOY_ENV_READY permanecen requeridos. Formulario: operación, controller,
1.5cpu-1024m-192pids; los22 textos vacíos. Derivar W de github.sha; no activar
startsWith(telegram-) ni ninguna rama legacy. Checkout sin credenciales; comprobar
main inmediatamente antes de SSH, hash de paquete antes de ejecutar, una SSH
memfd con timeout180s/kill5s y stdout acotado. Verificar recibo desde el mismo
ZIP aislado. Ramas mutantes siempre SKIPPED. No lease del host.

Raíz reconciliará historial de runs antes de enviar y tras cualquier timeout
de UI. Attempt1 no garantiza unicidad entre runs distintos: no afirmar eso.
Un único despacho nuevo después de cuatro revisiones finales/gates de W;
ninguna release/APPLY para este diagnóstico. SUCCESS significa observación
completa verificada, no salud/restauración, y no permite recuperación automática.

## Propiedad de archivos y pruebas focales

Autor sólo modifica siete archivos: nuevo host_telegram_incident_readonly.py,
build_protected_boca_bundle.py, boca_protected_memfd_bootstrap.py,
boca-first-deploy.yml y los tres nuevos tests test_r304_telegram_incident_readonly,
test_r304_telegram_incident_bundle y test_r304_telegram_incident_workflow.
Raíz posee este plan, AGENTS, RCA y documentos de continuidad. No editar fuentes
compartidas, BLACKBOX, paquetes Telegram, check_repo_policy ni CI para eludir gates.

Seis grupos focales, con frontera externa sintética y validación/selección/
comparación/serialización reales: binding y W/R; censo independiente/ausencia/
helper único/ambiguo; perfiles y razones; drift en ambas lecturas; comandos
exclusivamente permitidos y no exposición de secretos; CLI/ZIP real aislado.
Una prueba completa debe observar un helper de perfil incorrecto sin convertirlo
en fallo genérico, y otra confirmar que una entrada incompleta no se presenta
como lectura completa. Ninguna prueba afirma causa histórica o autoriza efectos.
Ruff/formato/tipos del delta y regresiones estrictamente necesarias. No suites,
Docker o certificaciones previas repetidas. Intérprete congelado ya disponible.

Tras diseño4GO: autor implementa y entrega RED/GREEN, paquete medido/hash, logs
y diff; raíz registra RCA525 sobre la brecha demostrada, conservando54 lecciones,
congela árbol y obtiene4GO finales. Publicar PR525 con padreR real, gates del
candidato, merge esperado y gates del nuevo main. Sólo entonces observar una vez.
La evidencia obtenida decide si cabe recuperación existente o una corrección
específica posterior; este plan no aprueba limpieza, restauración ni nuevo prepare.
