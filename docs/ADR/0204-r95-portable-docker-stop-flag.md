# ADR 0204 — R95: STOP Docker portable sin relajar ACK

**Fecha:** 2026-11-07 ART. **Owners:** QA, Arquitectura, Infraestructura.
**Estado:** CODE_ONLY; R94 #839 recuperó físicamente #834 (CLEANED/VERIFIED), pero no autoriza un nuevo preflight ni Cutover.

## Hechos y causalidad

El preflight R92 [#834](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42375050546)
falló en `CLEANUP/STOP/ACK_MULTILINE`. El Docker STOP devolvió exit 0, pero la
salida disponible al helper no fue exactamente el CID de 64 caracteres. No hubo
`docker rm`; el recibo marcó `INDETERMINATE` y `NO_GO`. No se conoce la versión
del Docker CLI del host ni los bytes completos de la advertencia: la hipótesis
de deprecación es plausible, **no un RCA demostrado**. El inspector #836
acreditó posteriormente un contenedor detenido; no atribuye su parada al
comando STOP y no autoriza repetir #834.

El Docker CLI documenta la opción corta `-t` para establecer el tiempo de
parada, de forma compatible con clientes anteriores y actuales. El nombre
largo `--time` conserva compatibilidad histórica, pero puede emitir un aviso
de deprecación con algunos clientes. El parser histórico exigía correctamente
un ACK igual al CID completo; nunca debe filtrar líneas o aceptar IDs parciales.

## Cambio limitado

En `scripts/host_cutover_worker_preflight.py`, sustituir sólo el argumento
`docker stop --time 5 <CID>` por `docker stop -t 5 <CID>`. Conservar exactamente:

- gracia Docker de 5 segundos y timeout de subprocess de 20 segundos;
- una única ejecución STOP contra CID completo y prohibición de segundo STOP;
- igualdad estricta de ACK con el CID de 64 caracteres, sin recorte selectivo;
- cero RM ante ACK vacío, corto, distinto, multilineal, timeout o excepción;
- único RM permitido sólo tras ACK íntegro y postflight Boca exacto;
- clasificación y recibo fail-closed sin divulgar stdout/stderr privados;
- host rootless Boca UID10001, lease y ninguna operación ajena, Porota o BLACKBOX.

## Evidencia exigida y secuencia

TDD RED primero en cinco asserts históricos y pruebas sintéticas de CLI: un
cliente ficticio emite `warning\nCID` con `--time`, CID único con `-t`, y
`warning\nCID` incluso con `-t` sigue rechazado. GREEN con suite íntegra,
45 RCA/165 selectores, Ruff, MyPy, política, ZIP de preflight y QA 3/3.

No combinar con R94 stopped-only (que nunca usa STOP): el recibo
`CLEANED/VERIFIED` exacto #834 existe en [#839](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42379062317).
Rebasar este candidato sobre ese `main`, PR único/4 checks, merge,
2 postmerge, PR0, publicación
dual exacta del nuevo SHA y evidencia fresca. Un único preflight futuro por
SHA sólo si revisado separadamente; fallo o ACK ambiguo significa NO_GO sin
reintento del mismo SHA. Esta ADR no equivale a autorización GO_B/APPLY,
instalación BETA, Telegram ni navegación/reservas reales.
