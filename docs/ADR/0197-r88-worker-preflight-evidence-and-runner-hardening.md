# ADR 0197 — R88: evidencia tipada de STOP y captura acotada del worker preflight

**Fecha:** 2026-11-07 ART. **Ownership:** [#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417) para RCA/probe; coordinación de único workflow bajo [#352](https://github.com/mbalbo2023/boca-socios-assistant/issues/352); [#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45) para checkpoints.

## Observado y no demostrado

R87 [PR #429](https://github.com/mbalbo2023/boca-socios-assistant/pull/429) está fusionado en `main=b4b72526d144f58d7577e49a32591ed304c1414d` (CI/Security postmerge SUCCESS, PR0). Su **única** Action protegida [#823](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42357920597) devolvió `CLEANED/VERIFIED` para worker detenido #819, legacy healthy en 8443 y sistemas externos intactos, con artifact verificado `13568895158`. Esa evidencia no demuestra por qué el anterior [preflight #819](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42353468231) devolvió `CLEANUP/STOP/INDETERMINATE`.

El adaptador Docker preserva la causa original como `__cause__`, pero el recibo reducía timeout del CLI, salida no cero, error OS y ACK distinto a un único `STOP`. La posterior observación del probe detenido puede representar parada aplicada con ACK perdido, error de daemon seguido de salida natural o carrera `inspect Running=true`/STOP. Son **hipótesis**, no RCA probado. Los incidentes #795/#807 no tenían subfase STOP registrada y no deben presentarse como idénticos.

QA identificó dos fallos de contrato prospectivos independientes del incidente histórico: comandos de validación dentro del worker basados en `assert` son inefectivos bajo Python `-O`, y el runner del preflight escribía stdout SSH a ruta predecible sin cuota durante el stream. R87 recuperación no ejecutó ese camino.

## Alternativas y decisión

1. Repetir STOP/preflight o aumentar timeouts sin evidencia: **rechazado**, potenciales efectos ambiguos y antirreplay.
2. Eliminar gates de preflight para llegar antes a Cutover: **rechazado**, no prueba aislamiento rootless/worker.
3. **Elegido:** subtipos STOP cerrados, comprobaciones de boundary explícitas y capture temporal privada con límite de escritura, copiando patrones Boca existentes R85/R87. Mantener el mismo único workflow y las mismas primitivas Docker; ninguna imagen/host cambia por el PR.

## Contrato R88

- Mantener **un** intento de `docker stop --time 5` para el CID exacto cuando `State.Running=true`, **cero `rm` si STOP/ACK no queda probado**, y como máximo un `docker rm` exacto cuando corresponda. Sin reintentos ni recuperación heurística.
- En el recibo NO_GO adicionar **únicamente** `stop_failure_cause=NONE|TIMEOUT|NONZERO|OSERROR|ACK_MISMATCH|UNVERIFIED`, determinado por tipo de la excepción causal inmediata. No incluir stderr, stdout, nombres o paths arbitrarios. El recibo PASS y sus SHA/digest/flags permanecen exactos. El parser de Actions acepta sólo la nueva gramática canonical y combinaciones válidas; todo desvío es `UNVERIFIED` y NO_GO.
- Sustituir `assert` por guardas explícitas en `BOUNDARY_COMMAND`; con `python -O` un falso UID, seccomp, cgroup o red debe fallar y **no imprimir PASS**.
- Para SSH del preflight: `umask 077`, directorio temporal aleatorio exclusivo y archivo privado sin enlaces, `ulimit -f` efectivo antes de enviar el ZIP/ejecutar SSH; el verificador `always()` sólo acepta el tamaño y contenido canónicos y elimina el material del runner. No emitir bytes crudos ni logs del host.
- Tests RED/GREEN con `docker` falsificado, STOP timeout, error, ACK perdido y carrera ya detenido; Bash runner con SSH falso y bytes excesivos/symlink/ulimit; pruebas de política, Ruff, Mypy, pytest completo y PR Actions exact-SHA. El equipo independiente de Arquitectura/Infra/QA registra su dictamen antes del merge.

**Límite:** R88 sirve para detectar y prevenir los defectos comprobables de validación y captura, y aportar subtipo causal en un *nuevo* intento; **no corrige retrospectivamente** el `STOP` de #819 ni habilita un nuevo intento físico por sí solo. Un eventual preflight requiere release dual exacto y un GO autónomo condicionado a nueva evidencia; no hay Cutover/GO_B/APPLY hasta PASS físico y revisión independiente. Aplicaciones ajenas, Porota, BLACKBOX, credenciales y volúmenes persisten intocados.

La lección `RCA-417` existente contiene 8 selectores y `fix_pr=426`, ambos inmutables por el validador de retención. R88 conserva ese registro sin duplicarlo ni inventar número futuro de PR; las regresiones y el RCA nuevo se vincularán mediante el PR real y el issue #417.
