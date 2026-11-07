# ADR 0205 — R97: preservar la fase tipada de fallas Cutover sin dar GO

**Fecha:** 2026-11-07 ART. **Estado:** CODE_ONLY, no constituye BETA desplegada.
**Ámbitos:** issue #417 (RCA), issue #45 (continuidad), QA/Arquitectura/Infraestructura.

## Evidencia y problema específico

El APPLY #844 (`42388694186`) consumió el GO de PREPARE #843 y terminó
`ssh_rc=3`. El diagnóstico de Actions mostró `host_claim=NONE` y
`phase_claim=UNVERIFIED`: el stdout remoto permanece privado en el runner y
no se conserva íntegro. La recuperación #848 (`42397473346`) acreditó
`STAGE_CLEARED`, y el READ_ONLY #849 (`42397628309`) acreditó un único
controlador legacy RUNNING/healthy en `127.0.0.1:8443`, stage ausente,
ningún worker/candidato y terminal del intento #844 en `NO_GO`. Esto **no**
acredita promoción de la BETA ni identifica la fase fallida original.

En código, `_cutover_observe` imprime siempre una línea de observación
`BOCA_CUTOVER_A_OBSERVE state=READY ... effects=none` antes de entrar a la
transacción. Si ésta registra una falla, `host_boca_cutover_cli` puede emitir
un postflight acotado, una línea `BOCA_CUTOVER_A_FAILURE_PHASE` y el terminal
`BOCA_CUTOVER_A_HOST state=NO_GO receipt=RECORDED runtime=UNVERIFIED`.
`classify_cutover_ssh_failure` sólo admitía el postflight y la fase después
de un prefijo **vacío**; rechazaba el prefijo de observación genuino. Es una
causa determinística de **pérdida de diagnóstico**, pero no hay prueba de que
sea la causa física del rc3 de #844.

## Decisión mínima de corrección

Permitir **como máximo una** línea inicial de observación con sintaxis ASCII
exacta, hashes/ID/digests de longitudes canónicas, imágenes GHCR de los dos
roles conocidos y sufijo inmutable (`original=RUNNING`, puerto loopback,
volúmenes preservados, `effects=none`). A continuación se admite el postflight
ya acotado y finalmente **una sola** fase en la allowlist vigente, más terminal
`NO_GO/RECORDED` exacto. No admitir ningún texto extra, duplicado, NUL,
caracter no ASCII, línea truncada o indicador `READY` de forma aislada.

El resultado positivo de esta corrección es exclusivamente
`host_claim=NO_GO_RECORDED_UNVERIFIED` y `phase_claim=<fase tipada>`;
`phase=UNVERIFIED host=UNVERIFIED terminal=UNVERIFIED no_retry=true` no
cambian. No guardar ni publicar stdout/stderr crudos; no cambiar host ZIP,
Docker, GO, identidad, autorización, número de workflows ni blackbox.

## Prueba, alcance y restricción de despliegue

- Reproducir RED/GREEN con recibo compuesto legítimo OBSERVE + fase + NO_GO;
  el caso vacío sin OBSERVE debe continuar compatible.
- Fuzz cerrado: observación falsificada, duplicada, fase desconocida,
  bytes extra/privados y terminal ACCEPT no producen una afirmación positiva.
- Checks CI y revisión independiente exact SHA antes de integrar. La nueva
  evidencia sirve **sólo para un intento nuevo**: el RCA físico del intento
  #844 sigue INDETERMINATE.
- Sólo GitHub Actions puede leer o modificar el droplet. No tocar ningún
  contenedor ajeno, Porota, los datos del propietario ni los módulos
  `synthetic.py` / `ipc_worker.py` protegidos.
