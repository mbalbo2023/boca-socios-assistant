# ADR 0109: diagnóstico acotado de la frontera de infraestructura

**Estado:** candidato para [RCA #268](https://github.com/mbalbo2023/boca-socios-assistant/issues/268),
2026-11-02, basado en main `7300c1021522a28091387a1b53c4f21dd8ad5e12`.
La revisión y los checks del candidato exacto preceden el merge; no se ha
ejecutado esta nueva operación en el host.

## Incidente y evidencia

El [run 41537794166](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41537794166),
job `125593988779`, falló en el chequeo inicial de `infrastructure-preflight`.
Los pasos de marcador, arranque, observación y restauración fueron omitidos.
No intentó arrancar Docker ni creó imágenes, contenedores o volúmenes. No
evaluó la capacidad ni la versión real del daemon.

El helper devuelve las razones fijas de `SetupError` por stderr. El workflow
descartaba ese stream y no conservaba el código de salida en el resumen.
Por eso la causa concreta de aquel rechazo **no es recuperable** de sus
logs: no se atribuye a SSH, configuración, RAM o CPU. La prueba determinística
pasa el error real emitido por `main()` a través del Bash anterior y demuestra
que se pierde la razón aunque el resultado siga siendo FAILURE.

La posterior inspección existente
[41538696464](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41538696464)
sí conectó y observó UID10001, daemon inactive/dead y socket ausente, sin
operaciones Docker. Es una observación nueva; no reconstruye la razón perdida
ni prueba las comparaciones de configuración del chequeo más estricto.

## Decisión y alcance

Se agrega `infrastructure-inspect` al mismo workflow manual protegido. Exige
main exacto, actor/repositorio establecidos, primer intento, el mutex existente
y `BOCA_HOST_READONLY_ENV_READY=ready`. Usa `service=controller` y una de las
selecciones existentes `1.5cpu-1024m-192pids` o `1.75cpu-1152m-224pids`.
Esa selección se valida, pero **no se evalúa capacidad**. Imágenes, release,
envelopes, capability y run de recuperación deben estar vacíos. No exige
readiness de despliegue porque no arranca ni detiene servicios.

La única llamada remota ejecuta el `infrastructure-check` existente: identidad,
configuración, enablement, unidad efectiva, estado inicialmente detenido,
runtime ausente y metadata de contenedores vacía. No se modifica ninguna de
esas condiciones. No llama `prepare-rootless`, Docker, arranque, parada,
pull, migración, cleanup o instalación. Tampoco activa el marcador que habilita
la restauración del preflight. Un daemon activo o recursos desconocidos se
conservan y bloquean, sin intentar corregirlos durante la inspección.

El chequeo inicial de `infrastructure-preflight` reutiliza esta misma captura.
Sus pasos posteriores, sus condiciones de parada, los límites, presupuestos,
cuotas y márgenes permanecen intactos.

## Captura y resultado

El SSH mantiene timeout de 60 segundos, TERM y límite adicional de cinco
segundos antes de KILL. Un subshell con `umask 077` y límite de archivo de
4 KiB acota cada stream en el runner. No hay reintento ni upload del contenido.
El parser local abre sin seguir symlinks y sin bloquear en FIFO; exige un
archivo regular propio, sin hardlinks, hasta 1024 bytes por stream, con
identidad y tamaño revalidados. No imprime stdout/stderr crudos, paths,
variables, comandos, configuración privada ni valores de credenciales.

Sólo admite estas combinaciones canónicas, incluida la nueva línea final:

- rc0, stdout `PREPARED` exacto para el SHA y stderr vacío: publica
  `BOCA_INFRA_CHECK state=PREPARED`, transporte confirmado.
- rc1, stdout vacío y el error exacto del helper con una razón permitida:
  publica `state=NO_GO` y esa razón fija; el resultado permanece FAILURE.
  La lista se limita a errores alcanzables por este chequeo. La única familia
  dinámica permitida es la de consulta de metadata del servicio, nunca start
  o stop. Un motivo futuro desconocido necesita revisión antes de publicarse.
- SSH255, timeout124, terminación137 y cualquier otra salida o combinación
  dudosa: `state=INDETERMINATE`, código/categoría acotados y motivo genérico.
  Un recibo aparentemente válido no compensa un transporte fallido.

Recibos ausentes, truncados, duplicados, mezclados, sobredimensionados, con
otro SHA, controles o razones desconocidas fallan cerrados. La salida del
parser también queda en el resumen ante fallo. No interpreta un error como
prueba de que el daemon esté detenido.

Sólo después del chequeo positivo, `infrastructure-inspect` registra
`BOCA_INFRA_INSPECT state=PASS`, `daemon=stopped`, `start_attempted=no` y
`capacity=not_evaluated`. `application=not_started` describe sólo los efectos
de esta operación; no afirma ausencia global de instalaciones o datos previos.
No es un PASS de preflight de capacidad, de despliegue
ni de aceptación. Para iniciar otro preflight se requiere la decisión explícita
correspondiente; no se transforma una inspección en arranque automático.

## Regresiones y límites

La reproducción inicial produjo dos fallos: pérdida de la razón y ausencia
del modo de inspección. Los tests pasan stdout/stderr reales del helper por
el Bash actual, verifican rc/framing/SHA, transporte incierto, límites reales
de archivos del subshell, FIFO/symlink/hardlink, valores privados centinela,
readiness y ambos presupuestos. También comprueban que la inspección no puede
entrar en los pasos con efectos ni emitir el PASS del preflight completo.

Selectores canónicos de `tests/test_infrastructure_diagnostics.py`:

- `test_real_setup_error_survives_initial_workflow_without_raw_stderr`
- `test_readonly_inspection_cannot_reach_effect_steps`
- `test_transport_unknown_never_becomes_prepared`
- `test_ssh_capture_is_bounded_before_parser_reads_it`
- `test_capture_files_are_untrusted_and_never_echoed`

Estos tests son locales con SSH sustituido; no certifican un nuevo resultado
del droplet. La activación sigue detenida hasta recuperar una causa verificable
y completar los controles posteriores con evidencia real.
