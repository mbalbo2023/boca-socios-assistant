# ADR 0103: preflight de infraestructura antes de publicar imágenes

**Estado:** candidato de #259 y corrección #260 sobre
`5ddfba568d0b53168f51c0e5b33c363ba24c505e`, 2026-11-02.
Implementación y pruebas locales; ninguna ejecución nueva del host.

## Problema y decisión

El preflight de instalación browser depende de imágenes publicadas y owner
preparado. El preflight antiguo sin imagen requiere el daemon activo y
comprueba sólo el contrato de controller. No permite verificar por separado
la infraestructura de la BETA antes de publicar, cuando el daemon preparado
está detenido. Un rechazo por un margen configurado tampoco demuestra
rendimiento insuficiente ni justifica ampliar el servidor.

Se agrega `infrastructure-preflight` al único workflow manual protegido
`boca-first-deploy.yml`. Requiere SHA exacto de main, primer intento, actor y
repositorio establecidos, mutex existente y ambos marcadores
`BOCA_HOST_READONLY_ENV_READY=ready` y `BOCA_DEPLOY_ENV_READY=ready`. Este último
es obligatorio porque puede arrancar temporalmente **sólo** el daemon Boca.

Inputs: `service=controller`; `resource_budget=1.5cpu-1024m-192pids` para el par
o `1.75cpu-1152m-224pids` para el conjunto con Telegram. Imágenes, release,
envelopes, pins, origen y owner no se requieren ni se pasan al host. Imágenes,
release o contexto privado suministrados por error se rechazan. La operación
no publica ni descarga imágenes y no crea/inicia contenedores, volúmenes,
aplicaciones, claves, datos o owner; tampoco ejecuta `prepare-rootless`.

## Ciclo y autenticidad

1. `infrastructure-check` exige unidad preparada inicialmente inactive/dead,
   MainPID cero, runtime sin sockets/estado residual, identidad UID10001,
   directorios privados, configuración y enablement exactos, y ausencia de
   acceso al socket rootful. No adopta un daemon activo o fallido.
2. Además de los bytes del archivo, valida la unidad efectiva cargada:
   `NeedDaemonReload=no`, LoadState, Type, Restart, Delegate, KillMode,
   ejecutable/argv de ExecStart y su política de errores exactos, y hooks
   ExecCondition/Pre/Post/Stop vacíos. Nunca hace daemon-reload. Los metadatos
   de una ejecución previa no se confunden con comandos nuevos.
3. Lee por descriptores, sin seguir symlinks ni modificar entradas, el
   directorio fijo `containers` del data root dedicado: debe existir y estar
   vacío. Esto evita que arrancar Docker reanude una aplicación persistida.
   Un registro desconocido se conserva y bloquea antes del arranque.
4. Revalida main inmediatamente antes del marcador de intento y
   `infrastructure-start`, que repite los controles y reutiliza la mecánica
   existente de arranque. Después exige inventario global vacío.
5. El helper de host verifica Engine >=28, Compose y opciones necesarias,
   rootless/cgroup v2/systemd y delegación, staging vacío, almacenamiento Boca,
   inventario sin contenedores/volúmenes/redes de aplicación y bind/close de
   `127.0.0.1:8443`. Revalida inventario y continuidad de almacenamiento.
6. Desde el marcador, `always()` ejecuta `infrastructure-stop`, también ante
   fallo o cancelación. Revalida identidad y configuración; sólo detiene la
   unidad dedicada si el inventario de contenedores sigue vacío. No ejecuta
   docker stop/rm ni elimina archivos o recursos. Un arranque fallido sin
   socket sólo puede detenerse con unidad auténtica y metadata vacía.
7. Sólo un recibo exacto, exitoso, con unidad inactive/dead, MainPID cero,
   runtime ausente y metadata vacía prueba la restauración al estado detenido.
   El resultado global PASS se emite después de esa prueba. Un fallo anterior
   conserva NO_GO aun si se restauró el daemon correctamente.

Docker puede actualizar su bookkeeping privado al arrancar. No se promete
identidad byte a byte de su data root ni se borran esos archivos. Configuración,
unidad y todos los datos/recursos preexistentes se preservan. Si aparece un
contenedor, una identidad cambia o SSH/runner impide probar la parada, el
estado es **NO_GO INDETERMINADO**: detener activación, conservar recursos y
realizar recuperación Boca-only explícita al recuperar conectividad; nunca
un reintento automático. La cancelación o pérdida del runner puede impedir
incluso ejecutar `always()`; no se declara éxito por haberlo programado.

## Observación y política son distintas

El recibo `BOCA_INFRA_OBSERVATION` contiene sólo SHA y métricas agregadas:
versión Engine, MemAvailable, cantidad de CPU de afinidad, loadavg de un
minuto, la estimación heredada `max(0, afinidad-loadavg1)`, PIDs delegados
libres y bytes/inodos de ambos filesystems. No enumera nombres ajenos,
procesos, argumentos, configuración privada ni valores de secretos.

`BOCA_INFRA_POLICY` evalúa por separado los márgenes vigentes: par
1536 MiB/1.75 CPU/256 PIDs; tres servicios 1792 MiB/2 CPU/288 PIDs; almacenamiento
4 GiB/50 000 inodos en ambos paths. Los límites de contenedores permanecen
1024 MiB/1.5 CPU/192 PIDs y 1152 MiB/1.75 CPU/224 PIDs respectivamente.
Este cambio no rebaja ningún número. Se conserva la observación aun si la
política falla, con `meaning=configured_reserve_not_benchmark` y exit no cero.

Afinidad menos loadavg no es CPU libre medida. En dos CPU, exigir 2.0 hace
fallar cualquier carga media positiva. Separar el colector de la política
permite revisar ese criterio con la evidencia de #259 antes de release;
el veto heredado no se presenta como una calibración definitiva. El perfilado
de los recorridos existentes ocurre en runner aislado, sin estrés ni tráfico
externo; no equivale a capacidad del droplet ni a carga sostenida real.

Un PASS aquí sólo acredita el chequeo previo y el estado final detenido.
No demuestra sandbox Chromium, UID/cgroups efectivos de contenedores todavía
inexistentes, rendimiento de la BETA, preservación de passkey o entrega
Telegram. Esas pruebas permanecen en instalación y aceptación posteriores.

## Regresión #260 y evidencia

El lector privado heredado abría antes de comprobar el tipo: una FIFO local
lo bloqueaba. La regresión con `mkfifo`, subprocess aislado y timeout de dos
segundos reprodujo el fallo antes de corregirlo. Ahora abre con O_NONBLOCK,
rechaza no regulares y hardlinks, y revalida inode/link/mtime/ctime al terminar.
No sigue ni elimina la entrada inesperada. Test canónico:
`tests/test_infrastructure_preflight.py::test_private_fifo_is_rejected_without_blocking`.

Las pruebas ejecutan el stdout real del helper a través del Bash actual del
workflow: policy PASS/NO_GO, SHA/budget exactos, timeout, SSH255 y recibos
faltantes, duplicados o truncados. También cubren unidades efectivas
divergentes, hooks inesperados, inventario no vacío, estado activo inicial,
fallo de arranque, parada no verificada y finalización tras cancelación.
Todo usa fixtures temporales/mocks; no certifica ejecución en el host.

La forma de ExecStart se contrasta con el renderer oficial
[systemd v255, systemctl-show.c](https://github.com/systemd/systemd/blob/v255/src/systemctl/systemctl-show.c#L1407)
y la semántica de propiedades con
[org.freedesktop.systemd1](https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.systemd1.html).
No se añaden dependencias, permisos, servicios o workflows alternativos.
