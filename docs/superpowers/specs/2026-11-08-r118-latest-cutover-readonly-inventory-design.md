# R118 — Inventario estrictamente READ_ONLY del último Cutover V3

Fecha: 2026-11-08 ART. Owners: continuidad #45, incidentes #417 y limpieza #386.
Estado: **diseño CODE_ONLY**. No se ha despachado ninguna Action física.

## Evidencia y defecto

El incidente Cutover V3 `42426260583` fue ejecutado desde
`f57173862df3143062a136452f2ffc7e3cc51d35` y terminó `NO_GO` en
`PREPARE_WORKER/HEALTH_EXITED`, `ExitCode=1`, `OOMKilled=NO`. El observador
posterior `42426527816` sólo probó el legacy sano y ningún worker en ese
instante; no acreditó residuos de imágenes/volúmenes ni cleanup terminal.
El selector `cutover-a-reconcile` existente autentica un único incidente V3
anterior, `42405706503`, mientras que su parser local de recibos persistentes
acepta terminales v1/v2 pero **no v3**, introducido en R114.

## Alternativas y decisión

- **Extender el selector y observador existentes (seleccionada):** dos
  coordenadas V3 exactas preaprobadas en código (incidente y SHA); identidad
  GitHub autenticada, lectura de recibo v3, doble snapshot y plan Boca-only.
- Crear otro workflow de inventario: rechazado por duplicar admisión, permisos
  y fronteras SSH.
- Saltar el recibo o correr Docker manualmente: rechazado por perder procedencia,
  operación auditada y autorización de alcance.

## Contrato

1. Los únicos incidentes V3 aceptados son #853 `42405706503` y #878
   `42426260583`, ligados respectivamente a sus SHAs inmutables
   `1273338005abf7203d26e618648fe55216030cf3` y
   `f57173862df3143062a136452f2ffc7e3cc51d35`. El runner consulta el
   registro real de GitHub e impide SHA, actor, attempt, título, ruta o evento
   falsificados. V1 con PREPARE mantiene contrato histórico.
2. La lectura del resultado terminal v3 exige las mismas claves exactas de v2
   más `worker_exit_code` (entero exacto 0..255 o `UNKNOWN`) y
   `worker_oom_killed` (booleano exacto o `UNKNOWN`), sólo si
   `worker_primary_phase=HEALTH_EXITED` y nunca con `state=ACCEPTED`.
   Rechaza bool como entero, campos sobrantes, duplicados y formatos cruzados.
   No permite reinterpretar un terminal v3 bajo el protocolo histórico PREPARE.
   El gate de GitHub conserva identidad incluso si `python -O` anula asserts.
3. El verificador de cleanup deriva el CID original únicamente del par
   intent/result y del snapshot verificado, preservando sus barreras de
   `NO_GO`, original sano, etapa y loopback. Si las condiciones físicas reales
   no se cumplen, el inventario fracasa de manera conservadora.
4. No se amplían permisos, operaciones, targets SSH, información privada ni
   superficie de Docker. `host_boca_cleanup.py` sólo observa recursos Boca en
   dos snapshots; no ejecuta deletes, pulls, prune, activación ni navegación.
   Resultado incluso ante éxito del observador: `READ_ONLY_NO_GO`,
   `go_for_retry=false` y **no habilita Cutover**.

## Exclusiones y aceptación

BLACKBOX `synthetic.py` e `ipc_worker.py` completamente intocados, sin importar
ni ejecutar. No tocar Porota ni Docker ajeno, Telegram sender OFF, no reserva
real, no host físico ni dispatcher durante este PR. TDD: fixtures V3 reales
del contrato, rechazo de versiones/identidades adversarias, lectura del script
exacto embebido en workflow, regresión V1/V2, pin del ZIP y gates de calidad.
Tras PR, review y CI exact-SHA, cualquier observación física es una decisión
separada; jamás se repite el Cutover fallido ni se deduce por software que el
worker ya puede arrancar.
