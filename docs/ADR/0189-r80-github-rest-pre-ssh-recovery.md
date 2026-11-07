# ADR 0189 — R80: recuperar continuidad sólo tras probar aborto pre-SSH

**Fecha:** 2026-11-07 ART. **Estado:** R80 CODE_ONLY, pendiente de PR/CI
y recibo físico independiente. **Alcance:** issue #417 / checkpoint #45.

## Hechos observados (no inferencias de runtime)

- `main=d9100c6c4666c61ba66fbbefa48e61102a20ce5d` contiene R79,
  PR #421 fusionado, postmerge CI #997 y Security #878 GREEN.
- `boca-first-deploy` #804 / run `42339451485`, autor `mbalbo2023`,
  SHA exacto citado, fue `completed/failure`. Job físico
  `128303677116`: gate #37 `failure`, **único paso SSH de recuperación
  #38 `skipped`**, terminal #39 `failure`. Los dos jobs restantes `skipped`.
  Antes del gate, otras rutas SSH del YAML están condicionadas a operaciones
  diferentes y no son elegibles en `cutover-a-worker-recover`.
- Hubo `BOCA_MAIN_REF_PASS` antes de
  `BOCA_WORKER_RECOVERY_GATE state=NO_GO reason=UNVERIFIED`.
  No hay ACK de limpieza; el fallback terminal `INDETERMINATE` no es una
  afirmación de que un comando Docker haya comenzado.
- REST `GET /actions/runs/42329201039` y `GET /actions/runs/42329475083`
  realmente devuelven la propiedad `path` como
  `.github/workflows/<workflow>.yml` **sin sufijo**. R79 exigía sólo
  `<workflow>.yml@main` o `@refs/heads/main`. Sus fixtures usaban una forma
  admitida por el código pero distinta a las respuestas reales.

## Decisión de arquitectura y QA

1. **No reintentar** #804 ni repetir el marcador R79. Construir un cambio
   fix-forward mínimo con `run-name=BOCA-R80-WORKER-RECOVER-ONCE`.
2. Extraer la validación de procedencia a
   `scripts/check_worker_recovery_dispatch.py` (sólo lectura de JSON
   acotados, sin red ni SSH), probada en runners offline y desde el Bash
   real del workflow con respuestas sintéticas GitHub REST.
3. Aceptar `path` sólo si coincide con la ruta histórica exacta desnuda,
   con `@main` o con `@refs/heads/main`. Mantener verificaciones de ID,
   estado, conclusión, run_attempt=1, rama main, SHA, actor y repositorio.
4. Exigir historial íntegro de como máximo 100 dispatches: **un solo** R79
   previo con ID `42339451485`, **un solo** R80 actual con ID+SHA del job.
   El historial incompleto o duplicado bloquea.
5. Validar por REST el run #804 y sus jobs del **attempt 1**. Exigir job
   `128303677116`, dos jobs de validación skipped, 154 pasos con números
   `1..152,304,305` y el conjunto exacto de pasos ejecutados de #804.
   Paso #37 debe ser failure, paso #38 `skipped`, #39 failure; **ningún
   otro paso de host o SSH se permite ejecutado**. Cualquier ambigüedad,
   drift o JSON con claves duplicadas da `NO_GO` antes de SSH.
6. No modificar `host_cutover_worker_recovery.py`, el CID, el lease,
   las dos inspecciones, el `docker container rm` sin `-f/-v`, el transporte
   memfd ni el verificador de ACK. Continúan intocables otros contenedores,
   imágenes, volúmenes, aplicaciones y los módulos BLACKBOX de navegador.

## Riesgos que el gate no elimina

- Un PASS de evidencia pre-SSH no demuestra estado físico actual. El
  ejecutor debe volver a probar identidad, ausencia de montajes, estado
  detenido y legacy sano **antes y después de la única mutación**.
- `NO_GO` o `INDETERMINATE` de R80 no autorizan ningún nuevo dispatch;
  sólo cabe inventario Boca-only READ_ONLY, RCA y nuevo diseño consciente.
- Un futuro `CLEANED cleanup=VERIFIED` resuelve únicamente el contenedor
  temporal de #795; no es un GO_B, no instala BETA, no habilita Telegram.
  Se requieren release dual fresco, preflight worker, PREPARE, GO_B
  independiente y APPLY con recibos físicos propios.

## Regla 84 / trazabilidad

Fuente de verdad: [#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417),
[#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45),
[run #804](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42339451485)
y PR R80 a publicar tras revisión. No se interpreta CI GREEN como deploy.
