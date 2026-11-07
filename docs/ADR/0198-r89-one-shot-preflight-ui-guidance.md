# ADR 0198 — R89: guía exacta de inputs para preflight con antirreplay por SHA

**Fecha:** 2026-11-07 ART. **Alcance:** documentación y descripciones del
formulario GitHub Actions `Boca first deploy`, propietario #417; workflow
único coordinado por #352 y decisiones físicas registradas en #45.
**Estado:** CODE_ONLY; ningún GO de host, preflight, GO_B o Cutover.

## Hallazgo y riesgo

R88 [PR #430](https://github.com/mbalbo2023/boca-socios-assistant/pull/430)
fusionó el diagnóstico STOP tipado y la captura privada; el tree revisado
es `840b6ea15c13cc33286af59c4f3e46a0e689ee24`. El preflight #819
había fallado en `CLEANUP/STOP/INDETERMINATE`; la recuperación R87 #823
verificó la limpieza del CID detenido y el legacy sano, **no** la causa
de STOP. R88 tampoco autoriza otro intento ni Cutover.

El formulario heredado decía que `image_ref` y `release_run_id` podían
quedar vacíos para «preflight» y no explicaba que `legacy_release_run_id`
y `legacy_controller_id` eran obligatorios para **worker preflight**.
La validación real de `.github/workflows/boca-first-deploy.yml` requiere
la imagen controller, imagen browser y release dual del SHA nuevo, más
release, fuente, digest y CID históricos del legacy. El malentendido
causaría un rechazo previo a SSH, pero el `workflow_dispatch` ya existiría.
`scripts/check_worker_preflight_dispatch.py` exige una sola ejecución
con nombre `BOCA-R84-WORKER-PREFLIGHT-ONCE` por SHA, sin importar si pasó
los gates iniciales: **un input erróneo consume ese SHA** para el propósito
del preflight. Una segunda ejecución no es una recuperación permitida.

## Decisión y límites

Corregir las descripciones del formulario sin cambiar valores, opciones,
default, guards, SSH, Docker ni host. Complementar con una guía explícita
para las **ocho coordenadas** del preflight:

| Grupo | Inputs exactos y evidencia |
| --- | --- |
| Identidad del candidato (4) | `source_sha` = `main` y SHA del release nuevo; `image_ref` = digest controller; `browser_image_ref` = digest browser del **mismo release**; `release_run_id` = run SUCCESS que publicó ambos manifests inmutables. |
| Identidad histórica (4) | `legacy_source_sha`, `legacy_image_ref`, `legacy_release_run_id`, `legacy_controller_id` (CID 64 hex) = controlador original realmente observado y release histórico verificado. |

Ningún SHA, CID, digest o run se selecciona por suposición, título de
workflow o copia de un PR; deben verificarse en los recibos y manifests
del día del despacho. `operation=cutover-a-worker-preflight`, rama `main`,
actor autorizado, `service=controller`, presupuesto
`1.5cpu-1024m-192pids`, contexto protegido vacío, demás inputs vacíos.
Antes del botón se requiere revisión independiente de **todos** los campos,
PR0, ausencia de operaciones físicas concurrentes, releases y checks
postmerge exactos, evidencia vigente de legacy sano/namespace limpio y
GO físico separado. La Action de preflight es **effectful** (pull/create/
start/stop/rm de un contenedor efímero Boca-only), aunque NO consume GO_B
ni toca IPC real, 8443, servicios externos o los módulos BLACKBOX.

**Separación obligatoria:** para PREPARE de Cutover A se usa la operación
`cutover-a-apply` con `protected_action_context` **vacío** y las ocho
coordenadas vacías, pues las obtiene un observador independiente de
solo lectura. APPLY es un **segundo run** que recibe sólo el ID corto
del PREPARE en `protected_action_context`, exige artifact vigente y
`BOCA_CUTOVER_A_GO_BINDING_SHA256` aprobado por canal separado. Un
preflight PASS no demuestra IPC real (`ipc_worker=NOT_TESTED`) ni concede
PREPARE, GO_B o APPLY; esas decisiones siguen en NO_GO hasta evidencia
física y autorización específica.

## Alternativas descartadas

- Mantener texto engañoso y confiar en instrucciones verbales: puede
  quemar el único run del SHA por un error de formulario accesible.
- Debilitar antirreplay o permitir repetir el mismo SHA tras fallo
  PRE-SSH: abre un camino de segundo intento que no fue revisado.
- Cambiar semántica del preflight, Docker o Cutover: fuera de alcance;
  R89 corrige sólo la explicación operativa del contrato vigente.

Un eventual rechazo, timeout o limpieza indeterminada continúa
`NO_GO/no_retry=1`: obtener evidencia de solo lectura, preservar legacy
y recursos ajenos y preparar un **nuevo fix-forward revisado** si es
imprescindible. No ejecutar host ni Actions por este ADR.
