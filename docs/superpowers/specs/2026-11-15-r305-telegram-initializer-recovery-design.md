# R305 — recuperación del inicializador exacto de Telegram1156

## Intención y autorización

El encargo vigente de Tincho transfiere a raíz la continuidad hasta Docker.
R ya fue instalado por APPLY1153; el bloqueo actual es el helper residual
de prepare1156. [Issue526](https://github.com/mbalbo2023/boca-socios-assistant/issues/526)
registra esta corrección antes del código. La decisión técnica es de raíz,
sometida a cuatro votos independientes; no se presenta como una elección nueva
del titular ni requiere reiterar su autorización de continuidad.

Base W0: be788a7dc602f4fce63da1d2a4ce859da73c5b08. R instalado:
845f31abfb1762dff27e6fc3274fcc40507f3f18; APPLY43704768556, incidente43705714873.
R304/1161(run43725809501) COMPLETE/OBSERVED_NO_GO identifica el helper
ba6699b977623135224e0ab6de8a26a882cecda8bfa819458deace75cb282367,
initialize-volume, created/PID0 y CAP_CHOWN. Par exacto healthy/created.
Recibo SHA256 d52af220a5027476c34c4273f5a49e0e7eba49c6e9cc20c8e60ef1ded7bbacf5.
Este recibo no autoriza efectos ni prueba contenidos del volumen.

## Alternativas y decisión de raíz

A: retirar sólo el helper. Deja el volumen conservado sin inicialización
acreditada y no resuelve prepare; no basta para este cierre.
B, elegida: ejecutar una vez el inicializador ya creado, con identidad/perfil
y exclusividad del volumen nuevamente acreditados, después retirar sólo su CID.
C: retirar y crear una ruta general para adoptar volúmenes. Introduce otro
helper y mayor superficie de escritura; se descarta.
No reinstalar imágenes: el defecto está en el atestador del ZIP host; el
inicializador seguro ya existe en el digest R.

## Invariantes

SIMULATION_ONLY; BLACKBOX synthetic.py/ipc_worker.py unread/unmodified.
Sólo boca-first-deploy protegido, serializado y main exacto. Nada de Porota/PPI,
proveedores, sender, mensajes, secretos nuevos, listeners o cambios de acceso.
Conservar datos, owner/key/passkey/Telegram volumes e imágenes en servicio.
No chmod/chown host, SQL, creación de helpers/volúmenes, restart/stop del par,
prune, force, rm -v o cambio del guard ordinario _created_volume.
R304 conserva bytes/semántica/paquete y no se repite su diagnóstico.
El recuperador no declara engineOFF; se verifica después por la ruta canónica.

## Corrección de representación

En host_telegram_maintenance._attest, initialize-volume admite únicamente
las dos listas singleton ["CHOWN"] y ["CAP_CHOWN"]. No usar sets ni normalizar
prefijos genéricos. Ambas son la misma capacidad de Docker
(https://docs.docker.com/engine/containers/run/#runtime-privilege-and-linux-capabilities).
Rechazar ausencia, duplicados, lista doble, ALL, capacidad extra, strings,
minúsculas y cualquier capacidad añadida para otras operaciones. Todos los
otros campos y el argv original siguen iguales. El volumen existente sigue
prohibido para call ordinario; esta recuperación no finge _created_volume.

## Transacción específica

Nuevo selector boca-telegram-initializer-recover. Coordenadas fijas importadas
del observador R304, más helperCID y observación1161 fijos. Caller aporta sólo
run nuevo y W; no recibe CID, imagen, ruta, payload ni comandos libres.
UID/GID reales/efectivos10001; socket/daemon/rootless canónicos; lease Boca
existente adquirida y verificada durante toda la transacción.

Antes de start: dos snapshots reales estables del observador R304, aumentados
por campos explícitos. Require exactamente par y helper fijo, binding R/APPLY
exacto sin transiciones ni sender, controller healthy/running y worker
created/PID0/notrunning. Exigir helper operation initialize-volume, perfil
MATCH salvo caps=[CAPADD_MISMATCH] con cap_add_observed CAP_CHOWN. Verificar
además HostConfig.CapAdd exactamente ["CAP_CHOWN"], CapDrop ["ALL"], .Image
igual al Image ID efectivo del controller y Config.Image digest R.

Adquirir con plantillas literales y cota8192 por campo:
Config.Entrypoint (null o []), Config.WorkingDir "/app", Config.OpenStdin true,
Config.Tty false, State.StartedAt/FinishedAt strings exactamente
"0001-01-01T00:00:00Z" antes del efecto. No depender de Config.AttachStdin,
que no determina la capacidad de docker start --attach --interactive;
OpenStdin y la llamada explícita son el contrato necesario.
No Env, State.Error, Health.Log ni stdout libre publicado.

Adquirir Mounts tipados del par y comprobar todos contra el contrato canónico
de servicio, incluidas fuentes/nombres/destinos/RW/Driver y bind readonly del
controlador; no Telegram ni directorios ascendentes a su mountpoint. Reusar
el validador canónico de mounts si su cierre ya existe, complementando Source
de cada volumen (el _mounts canónico no lo valida), sin healthy/censo
precondición que vuelva a rechazar el helper. El helper monta exclusivamente
boca-socios_boca_telegram en /run/telegram RW, volume local sin otros mounts.
Verificar Name/Driver/Scope/Options/labels project+volume y Mountpoint canónico
del volumen Telegram, la ruta no redirigida y su identidad estable. La lista
global exacta de tres CIDs impide otro lector/escritor del volumen.
No inspeccionar ni operar objetos ajenos para explicar un mismatch.

Comparar todas las adquisiciones antes de efectos, binding y dev/inode del
daemon; no comparar capacidad libre variable. Conservar conteos disk/inodes
antes/después en recibo. Verificar lease/binding y estado por última vez.
No hacer bucles hasta lograr un resultado favorable.

Efecto único: /usr/bin/docker --host socket-fijo start --attach --interactive
helperCID, input EXACTO b'{"new_empty_volume":"boca-socios_boca_telegram"}',
timeout30, stdout/stderr privados acotados, entorno fijo del adaptador.
No shell ni caller payload. El inicializador R abre NOFOLLOW, exige directorio
vacío y UID0 antes de fchmod0700/fchown10001:10001/fsync. No editar ese código.
La exclusividad real del mount permite mantener healthy al controller, que
no monta Telegram. No se escribe SQLite ni se salta una barrera de escritor.

Aceptación de init: rc0, stderr vacío, stdout exactamente b'{"initialized":true}'
sin LF, perfil/imagen/configuración íntegros, State.Status exited, PID0,
running/restarting/OOM false y exit0. StartedAt/FinishedAt válidos y no cero.
Los campos dinámicos legítimos del helper (State y datos internos de la red
none) no se comparan con created, pero conservan su contrato estricto.
Par, binding, fuentes de mount y volumen deben permanecer iguales.
Revalidar lease y perfil inmediatamente antes de retiro.

Retiro: sólo docker rm helperCID, sin flags, ACK exactamente CID y LF opcional
habitual. Un rm sin ACK no autoriza repetirlo. Verificar helper ausente,
exactamente los dos CIDs originales, volumen preservado/metadatos estables,
par healthy/created y binding sin cambio, daemon igual y métricas disk/inodes.
La inicialización cambia permisos del directorio, no identidad/metadatos Docker.

## Incertidumbre y recibo

No compensation automática. Antes de start fallido: NO_GO/PREFLIGHT, init
NOT_ATTEMPTED, retirement NOT_ATTEMPTED. Al iniciar, marcar init INDETERMINATE.
Timeout, interrupción, salida no canónica, exit no0 o perfil cambiante preservan
helper/volumen y prohíben start/stop/rm adicional. Puede haber escritura parcial
fchmod antes de fchown: no afirmar rollback ni que nada cambió.
Sólo después del éxito íntegro init ACCEPTED. Antes de rm marcar retirement
INDETERMINATE; ausencia confirmada permite RETIRED. Fallo posterior conserva
esos hechos sin degradar init a no ejecutado ni repetir el inicializador.
Ausencia inicial, started/exited o cambio de CID son NO_GO, nunca adopción.

Prefijo BOCA_TELEGRAM_INITIALIZER_RECOVERY_V1, JSON canónico <=4096 con claves
exactas: version, operation, recovery_run_id, workflow_sha, observation_run_id,
incident_run_id, source_sha, installation_run_id, helper_cid, state, phase,
initialization, retirement, pair_state, engine, sender_state, disk_before,
disk_after. operation fija "initialize-and-retire"; version1; engine UNVERIFIED.
Enums initialization NOT_ATTEMPTED/INDETERMINATE/ACCEPTED; retirement
NOT_ATTEMPTED/INDETERMINATE/RETIRED; pair_state UNVERIFIED o
UNCHANGED_HEALTHY_WORKER_STOPPED; sender_state UNVERIFIED/OFF.
El codec admite exclusivamente estas combinaciones (no inventar estado actual
del sender/par si una observación posterior falla):

| state | phase | initialization | retirement | pair_state | sender_state |
| --- | --- | --- | --- | --- | --- |
| NO_GO | INPUT o PREFLIGHT | NOT_ATTEMPTED | NOT_ATTEMPTED | UNVERIFIED | UNVERIFIED |
| NO_GO | START o VERIFY_INITIALIZATION | INDETERMINATE | NOT_ATTEMPTED | UNVERIFIED | UNVERIFIED |
| NO_GO | RETIRE | ACCEPTED | NOT_ATTEMPTED o INDETERMINATE | UNVERIFIED | UNVERIFIED |
| NO_GO | POSTFLIGHT | ACCEPTED | INDETERMINATE o RETIRED | UNVERIFIED | UNVERIFIED |
| ACCEPTED | COMPLETE | ACCEPTED | RETIRED | UNCHANGED_HEALTHY_WORKER_STOPPED | OFF |

No otro cruce es válido. Nunca ACCEPTED fuera de COMPLETE, ni retirement
intentado sin initialization ACCEPTED. Conservar init ACCEPTED ante falla de
rm/postflight y RETIRED cuando la ausencia ya fue acreditada antes de otra falla.
Fases finitas INPUT/PREFLIGHT/START/VERIFY_INITIALIZATION/RETIRE/POSTFLIGHT/COMPLETE.
Métricas no disponibles son null; disponibles ints estrictos no negativos
<=2**63-1, cuatro claves bytes_free/inodes_free/device/inode. INPUT requiere
ambas null; PREFLIGHT permite disk_before null o válido y disk_after null.
START/VERIFY_INITIALIZATION/RETIRE requieren disk_before válido/disk_after null.
POSTFLIGHT requiere disk_before válido y disk_after null o válido. COMPLETE
requiere ambos válidos y device/inode iguales. Nunca fabricar una medición.
Verificador aislado valida coordenadas/tipos/combos, duplicados y canonicidad,
status CLI0 ACCEPTED o3 NO_GO; argumentos inválidos salida estática y2.
Nunca publicar errores/valores privados. El transporte ausente/ambiguo falla.

## Transporte y continuidad

Nuevo módulo único, reutiliza fuentes R304 sin modificarlas. Modo independiente
--telegram-initializer-recover, 30 entradas esperadas (29+recuperador), máximo
900000 fuente/320000 ZIP; recuperador <=24000B. Mutuamente exclusivo, sin
compacción full-cutover heredada. Medir ZIP/CLI/memfd reales una vez.
Medir paquete Telegram afectado por CapAdd: límite450000 fuente/300000 ZIP;
actual449961B. Si no cabe, detener y revisar, nunca subir límite para pasar.
El paquete Telegram no tiene pin literal en su test actual: registrar el hash
nuevo medido en evidencia/docs, sin añadir ni modificar un pin supuesto.
El pin literal full-cutover sí existe y debe permanecer intacto.

Workflow conserva mutex, entorno, permisos, actor+triggering_actor owner,
main/repo/workflow_dispatch/attempt1 y gates actuales. El caso R305 exige
explícitamente BOCA_DEPLOY_ENV_READY=ready, BOCA_TELEGRAM_ENV_READY=ready y
BOCA_HOST_READONLY_ENV_READY=ready. No añade markers BETA/BROWSER/OWNER,
credenciales Bot API o envelopes: el perfil instalado se acredita bajo lease.
Formulario controller/1.5cpu-1024m-192pids y22 textos vacíos. Caso separado:
no agrupar/cambiar casos previos. Checkout sin credenciales, main recheck
inmediatamente antes de única SSH memfd180s/kill5; verificar desde mismoZIP
con -I -S -B. Comparar rc remoto/verificador0 o3 y estado estricto.
Todas las otras ramas quedan SKIPPED; no activa legacy startsWith telegram-.
No claim exactly-once global: reconciliar historial antes/después del despacho.

Cuatro GO finales + CI candidato/main + main reconciliado preceden un despacho.
Tras ACCEPTED, evaluar un prepare canónico sobre R/release867 y sus digests,
con guardas originales. Ese recibo separado debe acreditar PREPARED,
CONTROLLER_HEALTHY_ENGINE_OFF/senderOFF. No release/APPLY/admin repetidos,
no activate/test/send. La aceptación privada y funcional sigue abierta.
