# ADR 0201 — R92: evidencia tipada del ACK de STOP, sin promover cleanup

**Fecha:** 2026-11-07 ART. **Estado:** candidato CODE_ONLY; ninguna Acción física autorizada.
**Incidente:** [#827](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42368541950), RCA [#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417).

## Hechos y límite de inferencia

`#827` informó `CLEANUP/STOP/ACK_MISMATCH`, con `primary_failed_phase=NONE`.
El adapter invocó `docker stop --time 5 <CID completo>` una vez; no lanzó
`docker rm`. El comando volvió sin excepción, pero `stdout.strip()` no fue el
CID esperado. El observador [#829](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42370005970)
encontró ese CID detenido bastante después; el propio `sleep(90)` pudo haber
finalizado naturalmente. No conocemos los bytes de stdout ni la causa original.

Docker CLI normalmente imprime el **argumento que recibió** al completar
`stop`: un CID completo debería reproducirse completo. `--time` está obsoleto
en favor de `--timeout`; una advertencia de deprecación no prueba que haya
alterado stdout. No atribuir el incidente a nombres, ID corto, Docker nuevo,
PATH, wrapper ni a una carrera sin evidencia específica.

La versión **exacta del cliente Docker** de #827 no está atestiguada en el
recibo público. `_browser_engine_version()` comprueba *Server.Version* >=28,
no la versión del cliente CLI. **R92 conserva `--time 5`**, cuya invocación
histórica #827 llegó a exit0; cambiar ahora a `--timeout` exigiría un gate
adicional del cliente antes de cualquier efecto. El cambio de flag sería
otra variable sin evidencia y se difiere; no se toca el daemon.

## Opciones y decisión limitada

1. **Aceptar un ACK inesperado si luego se observa `Running=false`: rechazado.**
   Cambiaría la prueba de éxito R88 y permitiría `rm` tras una anomalía de
   procedencia del comando aún no explicada.
2. **Esperar `sleep(90)` y eliminar sin STOP: diferido.** `docker wait` sería
   una lectura, pero suma espera potencial de ~90 segundos a un presupuesto
   SSH de 420 s que ya permite dos pulls de hasta 120 s, create60, start30 y
   exec20. Un cuelgue podría dejar un worker RUNNING sin compensación. Requiere
   nueva evaluación de plazos, cierre de lease y política de fallo.
3. **R92: diagnóstico acotado y compatibilidad, fail-closed.**
   Mantener el token público `stop_failure_cause`, distinguir sólo la forma
   de stdout (`ACK_EMPTY`, `ACK_SHORT_ID`, `ACK_NAME`, `ACK_MULTILINE`,
   `ACK_OTHER_ID`) y preservar `ACK_MISMATCH` para evidencia histórica y
   cualquier otra forma. Nunca transmitir el texto recibido. Conservar
   `--time 5` en esta revisión. Cualquier ACK distinto del
   CID completo continúa con exactamente un STOP, cero RM, NO_GO y no retry.

## Controles de salida

PASS permanece byte-idéntico. No se altera la identidad, seccomp, rootless,
red none, límites cgroup, lease, capacidad de storage, releases, GO_B ni
Cutover. El receipt NO_GO se acepta sólo por parser de enum y etapa exactos;
no se imprimen stdout/stderr de Docker. Sintéticos RED/GREEN deben demostrar
varias formas de ACK y una sola llamada STOP, ninguna eliminación en mismatch,
además de un caso de stdout correcto que conserva limpieza original.

La recuperación [#831](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42372284155)
informó `CLEANED/VERIFIED` sobre el residuo exacto #827; no identifica los
bytes de STOP previos. R92 no autoriza por sí solo otro preflight, PREPARE,
GO_B/APPLY ni Telegram. La evidencia de cada nuevo SHA exige release dual,
PR0, controles postmerge, estado host fresco y nuevo consenso físico.
