# ADR 0103: preflight de infraestructura antes de publicar imágenes

**Estado:** integrado por PR #261; presente junto con #266 en main
`7300c1021522a28091387a1b53c4f21dd8ad5e12`, 2026-11-02.
[CI 41522036069](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41522036069)
y [seguridad 41522035980](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41522035980)
PASS. El preflight autorizado
[41537794166/job125593988779](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41537794166/job/125593988779)
falló en el control inicial de sólo lectura: marcador, arranque, observación
y restauración quedaron SKIPPED, sin efectos del intento. Su motivo se perdió
por el defecto de observabilidad RCA #268 y no puede reconstruirse desde ese
recibo. La inspección posterior 41538696464 observó el daemon detenido, pero
no identifica la condición original ni evalúa capacidad. El candidato de
[ADR0109](0109-readonly-infrastructure-diagnostics.md) añade una inspección
diagnóstica sin efectos; requiere revisión, checks y merge antes de ejecutarse.
No sustituye este preflight ni relaja sus controles. Evidencia posterior: #45.

La preparación histórica partió de `5ddfba568d0b53168f51c0e5b33c363ba24c505e`;
la corrección CPU siguió al smoke del candidato
`42eb497e8b597cd86035d08370dc935cba9b0f17`. El contrato siguiente se conserva.

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
versión Engine, MemAvailable, CPU reconocidas por Docker al arrancar,
cantidad de CPU permitidas por la jerarquía, techo estructural CPU, estado de
la rama (`materialized` o `configured`), loadavg de un minuto, PIDs delegados
libres y bytes/inodos de ambos filesystems. No enumera nombres ajenos,
procesos, argumentos, configuración privada ni valores de secretos.

`BOCA_INFRA_POLICY` evalúa por separado los márgenes vigentes: par
1536 MiB/1.75 CPU/256 PIDs; tres servicios 1792 MiB/2 CPU/288 PIDs; almacenamiento
4 GiB/50 000 inodos en ambos paths. Los límites de contenedores permanecen
1024 MiB/1.5 CPU/192 PIDs y 1152 MiB/1.75 CPU/224 PIDs respectivamente.
Ningún número se rebaja. Se conserva la observación aun si la política falla,
con `meaning=configured_reserve_not_benchmark` y exit no cero.

### Corrección CPU de #259

Históricamente se evaluaba `max(0, afinidad_del_SSH-loadavg1)`. No es CPU libre
medida: loadavg incluye tareas en espera ininterrumpible, no sólo tareas que
consumen CPU. En dos CPU, el requisito 2.0 rechazaba cualquier carga positiva.
La regresión reprodujo NO_GO con dos CPU, RAM/PIDs suficientes y load1=64.
El smoke de PR #261 aportó diez observaciones de recorridos sintéticos, sin
UNKNOWN: prueba consumo de esas fases en un runner, no capacidad del droplet
ni una calibración empírica de los márgenes. No justifica reducir caps o
reservas de RAM/PIDs. El informe de recursos conserva esas limitaciones.

El nuevo criterio conserva 1.75/2.0 y compara un **techo estructural**, sin
restar loadavg. `load1` se informa con `load_policy=advisory`; si no puede
observarse figura UNKNOWN y no cambia un techo comprobado. Un techo CPU
ilegible o de identidad incierta sigue siendo UNKNOWN/NO_GO, nunca cero o
ilimitado por defecto. El cambio se aplica al preflight nuevo y a los callers
browser existentes del mismo colector, incluido el sender. El contrato legacy
singleton de `observe` y su diagnóstico histórico permanecen separados. Los
recibos browser de preflight/staging también nombran `cpu_ceiling`; nunca
rotulan ese techo como headroom disponible.

El colector sólo lee lo siguiente, sin crear ni iniciar recursos:

1. Docker rootless/systemd y la configuración privada dedicada, previamente
   autenticada por la operación protegida de arranque. Confirma ausencia de
   `cgroup-parent` alternativo y `native.cgroupdriver=systemd`. Moby usa entonces
   `user.slice`; runc resuelve esa slice bajo el `ControlGroup` del manager de
   usuario. **No se usa `docker.service` como padre de contenedores.**
2. El manager privado y la unidad efectiva `user.slice` mediante `systemctl
   --user show --all`, con comandos/entorno fijos y timeout. El ControlGroup
   debe coincidir con la raíz delegada UID10001; exige slice loaded, sin
   NeedDaemonReload, y manager running/degraded. Revalida las propiedades al
   terminar. No hace daemon-reload, start de slice ni cambio de delegación.
3. CPU online, las máscaras `cpuset.cpus.effective` de los niveles donde el
   controlador está habilitado y `cpu.max` de cada ancestro que lo aplica,
   hasta la raíz. Se intersectan las máscaras y se toma el mínimo de las
   cuotas/períodos. La raíz cgroup no tiene `cpu.max`. Un cpuset no delegado
   hereda la última máscara comprobada; no se exige delegarlo para esta BETA.
   Si un archivo requerido falta o no se puede leer, no se infiere ilimitado.
4. Una `user.slice` inactiva puede estar todavía sin cgroup. systemd carga sus
   propiedades efectivas y drop-ins sin iniciarla. Se usan su cuota y
   AllowedCPUs, junto con los ancestros materializados. Una slice existente
   pero sin controlador CPU habilitado todavía también conserva esa política
   efectiva. `configured` declara esa diferencia; no afirma que ya exista un
   contenedor. StartupAllowedCPUs no aplica a running/degraded y el manager se
   revalida para no mezclar una transición global de arranque/parada.
5. Docker `NCPU` es `runtime.NumCPU()` al inicio del daemon: sólo añade un
   límite conservador, identificado como `daemon_startup_cpu_count`. No prueba
   afinidad actual, CPU ociosa ni disponibilidad garantizada. Las cuotas y
   cpusets actuales siguen siendo la base del techo.

Las cuotas se comparan como fracciones exactas, antes de redondear el recibo.
El renderer systemd puede devolver `1.750000s` o `250ms`; AllowedCPUs usa
rangos separados por espacios, mientras sysfs usa comas. Se rechazan formatos
ambiguos, propiedades duplicadas y valores no positivos. Archivos privados
se leen con O_NOFOLLOW/O_NONBLOCK, límites de tamaño e identidad revalidada;
la jerarquía se recorre mediante descriptores, sin seguir symlinks.

El techo no reserva CPU ni predice latencia, competencia con otros servicios,
throttling o sostenibilidad. Tampoco acredita la afinidad efectiva de cada
proceso futuro: esa observación requiere instalación/aceptación posterior.
No se propone ampliar el droplet por incumplir un margen no calibrado.

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


## Fuentes del contrato CPU

- [Moby Docker 29.7.2, withCgroups](https://github.com/moby/moby/blob/docker-v29.7.2/daemon/oci_linux.go#L777):
  padre rootless por defecto y precedencia de configuración. El mismo contrato
  se comprobó en 28.5.2 y 29.0.0.
- [runc 1.3.3, getSliceFull](https://github.com/opencontainers/runc/blob/v1.3.3/vendor/github.com/opencontainers/cgroups/systemd/v2.go):
  resolución bajo el ControlGroup del manager de usuario.
- [Moby 29.7.2, Info](https://github.com/moby/moby/blob/docker-v29.7.2/daemon/info.go#L67)
  y [Go runtime.NumCPU](https://pkg.go.dev/runtime#NumCPU): conteo detectado al
  arranque, no cuota ni afinidad actual.
- [Kernel cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html) y
  [cuotas jerárquicas](https://docs.kernel.org/scheduler/sched-bwc.html#hierarchical-considerations):
  cpu.max, cpuset efectivo, habilitación y restricciones heredadas.
- [systemd 255, slice_load](https://github.com/systemd/systemd/blob/v255/src/core/slice.c#L167)
  y [carga implícita de unidad](https://github.com/systemd/systemd/blob/v255/src/core/unit.c#L1453):
  una slice sin fragmento puede cargar propiedades sin empezar un cgroup.
- [systemd 255, selección de AllowedCPUs](https://github.com/systemd/systemd/blob/v255/src/core/cgroup.c#L1145),
  [renderer de masks](https://github.com/systemd/systemd/blob/v255/src/shared/cpu-set-util.c#L42)
  y [renderer temporal](https://github.com/systemd/systemd/blob/v255/src/basic/time-util.c#L527).

Regresiones canónicas adicionales:
`tests/test_host_cpu_capacity.py::test_io_load_does_not_reject_two_cpu_browser_and_telegram`,
`test_every_container_ancestor_quota_limits_ceiling`,
`test_missing_cpuset_in_manager_inherits_nearest_enabled_ancestor`,
`test_unmaterialized_slice_uses_loaded_quota_and_space_separated_mask`,
`test_expected_kernel_control_missing_is_unknown_not_unlimited` y
`test_advisory_load_survives_exact_real_receipt_workflow_parser`.
Los resultados locales no sustituyen los checks del candidato final ni una
observación autorizada de infraestructura y su parada comprobada en el host.
