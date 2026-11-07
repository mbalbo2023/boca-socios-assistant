# ADR 0199 — R90: observación READ_ONLY exacta después del preflight #827

**Fecha:** 2026-11-07 ART. **Ownership:** RCA #417 y continuidad #45.
**Estado:** CODE_ONLY hasta PR, CI, review independiente, merge y Acción de lectura.

## Hechos físicos, no inferencias

El único `cutover-a-worker-preflight` R89 [#827 / 42368541950](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42368541950)
partió de `main=8a69d155354362e0712dab1229f7d7e4b3e24dd6`, release dual
[#737 / 42361009081](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42361009081),
PR0 y revisión técnica 3/3. Terminó **FAILURE**, sin artefacto de aceptación:

```
BOCA_CUTOVER_WORKER_PREFLIGHT state=NO_GO host=UNVERIFIED phase_claim=CLEANUP cleanup_claim=INDETERMINATE primary_failed_phase_claim=NONE cleanup_failed_stage_claim=STOP stop_failure_cause_claim=ACK_MISMATCH next=read_only_boca_inventory no_retry=1
```

`docker stop --time 5 <CID>` devolvió un ACK distinto del CID esperado. El
helper abortó antes de `docker rm`; no sabemos si el contenedor está detenido,
activo o ausente, ni si el controlador original sigue sano. No repetir #827,
no reciclar el CID de #819, no ejecutar `PREPARE`, `GO_B` ni `APPLY`.

## Alternativas y decisión acotada

- El `cutover-a-observe` genérico no identifica el probe; no sustituye evidencia.
- El inspector existente conoce únicamente #795/#807/#819: un despacho para
  #827 con el código R89 sería rechazado antes de SSH. Mentir con el run #819
  observaría un objeto distinto.
- **R90 reutiliza el inspector existente, sin nuevo workflow ni Docker write.**
  Añade sólo un par run→(SHA, digest) a su mapa cerrado y un case exacto de
  `cutover-a-worker-inspect`, con título único, manteniendo los cuatro
  metadatos rootless `ps`/`inspect`, límites de tiempo/tamaño, captura privada,
  comparación de legacy y recibo v3 (`READ_ONLY_NO_GO`, `observer_writes=0`).

| Identidad inmutable | Valor |
| --- | --- |
| Run fallido | `42368541950` (#827) |
| Probe exacto | `boca-socios-cutover-preflight-42368541950` |
| SHA del probe | `8a69d155354362e0712dab1229f7d7e4b3e24dd6` |
| Browser OCI | `ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:902276a94bbec0ed0be30432baf97b5bd1298fc15e21eda750ccb785fa76bde0` |
| CID controller legacy | `27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793` |
| SHA legacy | `cabce9f1e452e63ded115f447559a358dc0f4d1b` |
| OCI legacy | `ghcr.io/mbalbo2023/boca-socios-assistant@sha256:cf6e4266cfcfea0c07fa31301d59c7aaa3b9c2fefb9f6843baddd208cacd3b59` |

## Plan y criterio de prueba

1. Reproducir en TDD que R89 rechaza #827 y la compuerta de workflow no
   admite ese run; registrar las fallas del test nuevo antes del cambio.
2. Ampliar únicamente la tabla inmutable y el gate de lectura; preservar el
   mismo backend, el objetivo de recuperación separado y sus CID antiguos.
3. Revisar cuatro queries, seccomp/UID, modo failure, ZIP recuperador, CI,
   lint, typing, pruebas adversariales y docs Rule84. PR único sobre `main`,
   revisión Arquitectura/Infra/QA, checks del SHA exacto y PR0 al fusionar.
4. Despachar **una observación física de solo lectura** mediante Actions, sin
   release ni Docker writes; publicar el recibo en #417/#45. No limpiar sin
   nuevo diseño específico si el probe resulta realmente detenido.

**Formulario protegido después del merge:** operación
`cutover-a-worker-inspect`; contexto `42368541950`;
`service=controller`, `resource_budget=1.5cpu-1024m-192pids` y los tres
pins legacy de arriba. **Todos** los otros inputs opcionales vacíos,
especialmente `source_sha`, `image_ref`, `browser_image_ref`, ambos IDs de
release y los envelopes. La Action deriva su propio SHA de `main`.

Lecturas posibles: `ABSENT` no confirma el preflight anterior;
`PRESENT_PIN_MATCH` con `probe_running=false` permite **estudiar** una
recuperación posterior stopped-only de CID exacto, no ejecutarla;
`probe_running=true` o identidad/estado no verificado permanece NO_GO sin
stop/removal. Nunca ejecutar preflight nuevamente sobre ese SHA.

**Restricciones:** sólo Boca rootless y puerto existente 8443; controller,
datos, claves, otros Docker y Porota intocables. BLACKBOX y sitio real Boca
fuera de alcance. La BETA integral sigue **NO instalada ni aceptada**.
