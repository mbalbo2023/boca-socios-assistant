# ADR 0104: medir recursos durante el smoke BETA existente

**Estado:** candidato de código para issue #259, basado en
`5ddfba568d0b53168f51c0e5b33c363ba24c505e`. No se ejecutó este medidor en el
droplet ni se modifican límites, preflight, Dockerfiles o contenedores para
obtener números. La integración y sus recibos reales deben quedar en #45.

## Alcance y antecedente

El [CI 41495122362](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41495122362)
de esa base, job `125447926866`, observó un inicio offline de Chromium:
182,1 MiB, 77 tasks/PIDs, 1072 ms CPU y 1079 ms transcurridos. El medidor de
[ADR0021](0021-single-browser-budget.md) es una observación real del runner,
pero no mide el controller bajo HTTP/SQLite ni el sender; no demuestra
capacidad disponible del host.

Se amplía `scripts/measure_browser_budget.py` como lector reutilizable y se
envuelven únicamente las operaciones ya presentes en
`scripts/check_browser_lifecycle_runtime.py` y el smoke PR existente:

| Fase | Trabajo observado, sin duplicarlo |
| --- | --- |
| `http_acceptance` | El único `acceptance.host_probe` del controller singleton: HTTP y SQLite temporales, simulación local. |
| `startup` / `restart` | Controller y worker sanos antes del recorrido, tras sus inicios ya existentes. |
| `startup_ipc` / `restart_ipc` | Un recorrido IPC sintético por fase; un contexto Chromium a la vez. |
| `sender_startup` | Inicio y READY del sender con outbox vacío y aceptación inventada, siempre `network=none`. |

Los dos comandos IPC y el host probe se trasladan del YAML al wrapper, sin
ejecuciones adicionales. La validación de recibo HTTP conserva el límite de
385 bytes, una sola línea y `_validate_beta_acceptance_receipt` de producción.
El sender sigue ejecutándose después de parar el par: **no se mide consumo
simultáneo de los tres servicios**. No se suma ningún pico individual ni se
extrapolan sesiones, percentiles o recursos disponibles del droplet.

## Lecturas y semántica

El lector usa sólo biblioteca estándar y archivos fijos de cgroup v2:
`memory.current`, `memory.peak`, `pids.current`, `pids.peak` y los campos
`usage_usec`, `user_usec`, `system_usec`, `nr_periods`, `nr_throttled` y
`throttled_usec` de `cpu.stat`. Lee por clave, no por posición, con un máximo
de 4096 bytes por archivo. Valores negativos, inválidos, duplicados o
ausentes se representan individualmente como `UNKNOWN`, nunca cero.

Memoria/PIDs actuales son muestras puntuales; PIDs cuenta tareas/hilos.
Los máximos corresponden a la vida del cgroup de la ejecución actual y no
se restan para fabricar un pico de fase. CPU se informa acumulada y, alrededor
del trabajo, como diferencia entre muestras de la misma identidad/cgroup.
Un cambio de identidad o de cgroup, o un contador decreciente, no produce una
diferencia válida. El throttling es el contador de ese cgroup, no una medida
del headroom del host ni de toda presión de sus ancestros. Referencia:
[interfaz oficial cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html).

Las lecturas son secuenciales mediante `docker exec` y el UID existente.
Incluyen el costo del pequeño proceso Python de observación y de otros
checks ya existentes en ese cgroup. No hay muestreo periódico, segundo
motor de benchmark, stress test, acceso a Boca/Telegram ni cambio de red.
La fuente revisada del lector se transporta directamente; el controller no
instala Playwright ni necesita una nueva imagen que copie `scripts/`.

Se conservan los límites exactos del servicio: controller 0,5 CPU/256 MiB/64
tasks, worker 1 CPU/768 MiB/128 tasks y sender 0,25 CPU/128 MiB/32 tasks.
Un límite ausente, ilimitado o diferente sigue siendo NO_GO. El modo original
de Chromium conserva su contrato estricto: un contador requerido ausente
sigue siendo error. No se convierten sus rechazos en resultados parciales.

La medición exige identidad en ejecución antes y después de cada lectura.
`CgroupnsMode=private` permite el probe. El valor vacío que admite la
inspección legacy no prueba el namespace: los contadores quedan `UNKNOWN`
sin ejecutar el lector ni modificar el contenedor. Un namespace host o una
identidad cambiada siguen fallando. No se leen métricas de otros servicios.

## Tiempo y recibo

El tiempo de IPC y de aceptación HTTP se mide con reloj monotónico alrededor
del comando ya existente; sus deltas CPU abarcan las muestras secuenciales,
incluido overhead, y no exactamente ese mismo intervalo de reloj.
El sender mide desde su `run` hasta observar READY, antes de checks posteriores.
Como Compose ya esperó salud antes del wrapper, `startup`/`restart` informan
solamente edad al observar salud (`StartedAt` frente al reloj UTC del runner),
**no latencia exacta de arranque**. Fecha inválida/futura produce `UNKNOWN`.

Cada línea `BOCA_CI_RESOURCE` contiene JSON de esquema fijo, SHA exacto,
servicio/fase de una lista cerrada, unidades explícitas y sólo cifras o
marcadores controlados. El JSON queda limitado a 4096 bytes. No incluye
identificadores de miembros, credenciales, environment, rutas privadas,
argumentos, contenido de archivos ni stdout/stderr arbitrario de Docker.
El recibo usa `measurement=OBSERVED` sólo con todos sus campos disponibles;
cualquier valor desconocido produce `measurement=UNKNOWN`.

El resultado funcional del smoke y la completitud de medición son datos
separados: un fallo IPC/HTTP/READY conserva el fallo y no emite una medición
satisfactoria de esa fase. Un smoke funcional no convierte una medición
`UNKNOWN` en aceptación completa de recursos. La ausencia de valores debe
quedar explícita en la revisión del SHA final.

## Pruebas y aceptación pendiente

Las regresiones cubren límites por servicio, campos ausentes/ilegibles,
lecturas acotadas, duplicados, tipos y rangos del recibo, cero auténtico frente
a `UNKNOWN`, reinicio/reset de CPU, identidad antes/después, namespace no
comprobable, portabilidad sin Playwright, redacción de errores, una única
invocación por fase y la validación original de aceptación HTTP.
Se conservan las pruebas anteriores del lector y del lifecycle. La ejecución
real del SHA integrado, los datos observados y los checks completos deben
registrarse antes de evaluar esta evidencia. No autoriza bajar reservas,
umbral de preflight o caps, ni ejecutar mediciones sobre el droplet.
