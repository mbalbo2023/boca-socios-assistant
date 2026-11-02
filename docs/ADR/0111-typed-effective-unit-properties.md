# ADR 0111: presencia y forma tipada de los comandos de la unidad efectiva

**Estado:** candidato para [RCA #271](https://github.com/mbalbo2023/boca-socios-assistant/issues/271),
2026-11-02. Requiere revisión independiente y checks del SHA exacto antes del
merge; la inspección protegida posterior confirma el resultado real del host.

## Evidencia y límite de la causa

El [run 41542349197](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41542349197)
rechazó la inspección con `effective_preflight_unit_unverified`, rc1 y transporte
confirmado. No intentó arrancar el daemon. Ese recibo acotado no conserva la
salida privada de systemctl: no permite afirmar qué cantidad de líneas ni qué
propiedad concreta devolvió aquel host.

Sí se reprodujo un defecto del código de main
`4b0c65becea753151d39acaf12f9bbacc6199407`. El helper exigía doce líneas al
consultar seis escalares, cinco hooks vacíos y ExecStart. Los tests construían
cinco líneas `Hook=` vacías. El renderer oficial de systemd v255 imprime una
línea por elemento de cada array Exec* y devuelve que lo procesó incluso cuando
el array está vacío; `--all` no añade una línea a ese renderer específico.
La representación documentada de una unidad válida contiene siete líneas y
produce el rechazo anterior. Esto prueba un defecto compatible con el recibo,
no reconstruye la salida real del droplet.

Fuentes primarias consultadas:

- [systemctl-show.c, renderer Exec*](https://github.com/systemd/systemd/blob/v255/src/systemctl/systemctl-show.c#L1374).
- [bus-print-properties.c, selección del renderer](https://github.com/systemd/systemd/blob/v255/src/shared/bus-print-properties.c#L374).
- [busctl.c, JSON y Properties.Get](https://github.com/systemd/systemd/blob/v255/src/busctl/busctl.c).
- [dbus-execute.h, firma de comandos](https://github.com/systemd/systemd/blob/v255/src/core/dbus-execute.h#L19).

## Decisión

La frontera mantiene seis propiedades escalares por `systemctl --user show
--all`: LoadState=loaded, NeedDaemonReload=no, Type=exec, Restart=no,
Delegate=yes y KillMode=mixed. Exige la cantidad y el conjunto exactos de
claves, además de sus valores; faltantes, duplicados y extras siguen bloqueando.

Los seis comandos se leen con una única invocación de `/usr/bin/busctl --user
--no-pager --json=short get-property`, servicio `org.freedesktop.systemd1`, objeto
fijo `/org/freedesktop/systemd1/unit/docker_2eservice` e interfaz
`org.freedesktop.systemd1.Service`. Se solicitan, en orden, ExecCondition,
ExecStartPre, ExecStartPost, ExecStop, ExecStopPost y ExecStart.

El getter oficial realiza un Properties.Get por nombre, termina con error si
una propiedad falta y emite un objeto JSON por resultado. El orden de la
petición fija vincula cada respuesta a su propiedad. No se usa GetAll ni se
infiere que una propiedad ausente sea un array vacío. Un busctl ausente o no
compatible bloquea; este cambio no instala ni reconfigura herramientas.

Se requieren exactamente seis objetos JSON con sólo las claves `type` y
`data`, sin duplicados, firma `a(sasbttttuii)` y un array como valor. Los primeros
cinco arrays deben estar vacíos. ExecStart debe contener exactamente una fila
de diez campos: executable `/usr/bin/env`, argv vectorial idéntico a la unidad
canónica y `ignore_errors=false`. La comparación vectorial distingue límites
de argumentos que el display de systemctl une con espacios.

Los restantes campos describen una ejecución anterior: cuatro timestamps
uint64, PID uint32 y code/status int32. Pueden ser cero o contener metadata de
una ejecución legítima anterior dentro de esos límites. No se interpretan como
acciones y no se imprimen. Booleanos, floats, NaN/Infinity, valores fuera de
rango, estructuras adicionales y errores de decodificación, incluida recursión
excesiva, se rechazan con razones fijas.

Cada salida se limita a 16384 caracteres antes de interpretar propiedades.
El wrapper existente conserva el timeout de 15 segundos, entorno dedicado,
stderr descartado y límite global de salida de 65536 caracteres. Los fallos de
busctl usan la familia ya admitida `user_service_metadata_failed_*`; no se
amplía la lista de diagnósticos ni se publica configuración cruda.

## Alcance y verificación

La lectura sustituye solamente la validación de comandos efectivos. Conserva
identidad, configuración privada, enablement, rechazo de overrides, estado
inicial inactivo, ausencia de runtime y de contenedores, y las fronteras de
arranque/parada. No habilita deploy, no cambia permisos ni la unidad, no inicia
Docker, no instala aplicaciones y no hace peticiones Boca. El fallo de lectura
no habilita un arranque ni una reparación automática.

La regresión nueva ejecuta el helper real con transporte sustituido y el
renderer oficial que omite hooks vacíos. Antes del cambio falla con
`effective_preflight_unit_unverified`; después exige también las dos consultas
fijas y la presencia tipada. Los tests anteriores basados en filas `Hook=`
inventadas se reemplazan por `tests/test_effective_unit_shape.py`, que cubre
drift de escalares y todos los hooks, claves/filas faltantes o duplicadas,
JSON ambiguo y profundo, cardinalidad, identidad, límites de argv, tipos y
rangos numéricos, bloqueo antes del arranque y razones sanitizadas de busctl
pasadas por `main()` y el clasificador del workflow.

Comando local sin dependencias adicionales:

```sh
PYTHONPATH=src python tests/test_effective_unit_shape.py
```

Ejecuta las mismas trece funciones top-level que pytest recoge en CI; no agrega
wrappers de tests ni duplica ejecuciones. La instalación frozen local no se
completó porque faltaba pycparser3.12 en cache; no se sustituyó el lock ni se
presenta la prueba focal como suite completa. Lint, formato, tipos, suite frozen
y gates del repositorio deben aprobar el SHA exacto en GitHub Actions. Ninguna
prueba local acredita por sí misma un PASS de infraestructura real.
