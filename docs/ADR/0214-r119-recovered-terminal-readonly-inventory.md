# ADR0214 — R119: compensación RECOVERED para inventario READ_ONLY #878

Fecha: 2026-11-08 ART. Ownership: Infraestructura/DevOps, IPC externo,
QA/Arquitectura y PM Boca. Issues #45, #417, #386. Decisión conjunta:
**GO CODE_ONLY**, **NO_GO físico**.

## Nueva evidencia verificable y RCA

R118 fue fusionado como [PR #450](https://github.com/mbalbo2023/boca-socios-assistant/pull/450),
`main=6a0aa2ea72f61e4bb6178e3cd12e9194f760d0d8`, CI y seguridad
postmerge SUCCESS, PR0. Una única observación `cutover-a-reconcile` sobre
Cutover V3 #878 se realizó en
[Actions #883](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42531818647).
El observer READ_ONLY produjo `terminal=RECOVERED`, `cleanup=ACCEPT`,
`original_restored=true`, `commit_started=false`, original healthy en
`127.0.0.1:8443`, un solo contenedor Boca, sin worker ni candidato,
Stage/archivos de promoción ausentes, `go_for_retry=false`. No modificó Docker.
El siguiente paso falló en `CLEANUP_V3_ORIGINAL_UNVERIFIED`: la puerta R118
para el planner aceptaba únicamente terminal `NO_GO/INDETERMINATE`.

El productor `run_cutover_a` define precisamente `RECOVERED` cuando el
finalizador informó `ACCEPT`, recuperó al original y no inició el commit;
el terminal persistido valida esas condiciones. **RECOVERED acredita la
compensación aceptada, no un Cutover exitoso**. La causa interna del worker
`PREPARE_WORKER/HEALTH_EXITED`, ExitCode entero 1, OOMKilled false, continúa
**UNKNOWN** y no se ejecuta ni inspecciona el BLACKBOX.

## Solución deliberadamente estrecha

No se agrega workflow, permiso ni comando Docker. `cutover-a-reconcile`
mantiene la admisión histórica `NO_GO/INDETERMINATE`. Solamente para
`42426260583` + SHA fuente histórico
`f57173862df3143062a136452f2ffc7e3cc51d35`, sin PREPARE, el
**derivador de CID del planner READ_ONLY** admite la segunda pareja exacta
`RECOVERED/ACCEPT` si también se comprueba:

1. Intent y result presentes, SHA enlazado, restauración verdadera, commit
   irreversible falso; identidad CID completa en recibo y snapshot.
2. Terminal v3 real y evidencia externa tipada `HEALTH_EXITED`, compensación
   `VERIFIED`, ExitCode exactamente `1` (entero, no bool), OOMKilled exactamente
   `false` (bool), sin extraer secretos, logs, entorno, stack ni BLACKBOX.
3. Un solo contenedor Boca: legacy `/boca-socios-controller-1`, running,
   healthy, servicio controller, único binding `127.0.0.1:8443`;
   `boca_inventory=[original]`, candidatos/workers y sus IDs grabados ausentes.
4. Stage y marcadores de promoción `ABSENT`, preflight real
   `STAGE_PREFLIGHT_MATCH`, Compose inode comprobado con modo 0600 o legacy
   0644 y digest/roles concordantes. Cualquier desvío detiene el planner.
5. Recibo observado canónico, acotado y validado por el runner; dos snapshots
   Docker rootless Boca idénticos. `runtime_attested=false`,
   `go_for_retry=false`, `foreign_resources_touched=false`.

El recibo nuevo `boca-postapply-reconcile-v3` del observer proyecta sólo
cinco campos acotados del terminal v3 en `terminal_worker_evidence`; los
recibos históricos v1/v2 se siguen verificando sin reinterpretarlos.
El runner rechaza cualquier clave extra del recibo superior para impedir
publicar datos privados inesperados en Actions. El nuevo
gate se ubica exclusivamente en `verified_cleanup_legacy_id()`, consumido
por el **planificador de solo lectura**. El resultado sigue
`READ_ONLY_NO_GO`; nunca habilita eliminación, worker, Telegram, retry ni
Cutover. No se exige ausencia de **imágenes, volúmenes o redes**: su posible
residuo es precisamente el objeto del inventario posterior, que debe
clasificarlos por propiedad y preservar otras aplicaciones y la imagen
histórica protegida por [ADR0209](0209-r108-attested-historical-quarantine.md).

El ZIP memfd de Cutover incluye ese helper ya allowlisted. El primer FULL
local detectó que los 877124 bytes sin comprimir superaban el límite R114
872000; R119 alinea builder/validador a un techo explícito 880000, con 2876
bytes de margen, **sin ampliar allowlist ni el máximo comprimido 512000**.
Nuevo digest determinista R119
`aa43ffb3ec71104707b6df7eb14a5d66fb10df25aeb3297305854fbf27db75b7`;
pin histórico R118 preservado en las pruebas. La caída inicial de la suite
por límite de ZIP fue un fallo controlado del paquete, no error del BLACKBOX.

## Validación y siguientes decisiones

TDD: prueba positiva RED primero con `CLEANUP_V3_ORIGINAL_UNVERIFIED`, luego
GREEN; matriz negativa por fuente, terminal, compensación, ExitCode/OOM,
recibos, CID, health, puerto, Stage, workers y candidatos, y E2E sintético
terminal-v3 → `host-v3` → `verify-v3` → planner sin SSH ni Docker.
Registrar test suite completa, Ruff, MyPy, policy, ZIP pin y CI/Security
exact-SHA del PR en #45 antes del merge; postmerge PR0 y checks nuevos.

**NO despachar automáticamente otra Action** a partir de la revisión de
código. Infra/IPC/QA/PM deben hacer nueva decisión separada para *una*
observación protegida READ_ONLY si CI postmerge es GREEN, PR0, sin operaciones
host concurrentes y source autenticado. El resultado de tal observación
todavía no certificará cleanup final ni el arranque IPC; esas evidencias,
Telegram rootless, QA funcional y un único Cutover V3 quedan pendientes.
BLACKBOX, Porota, otros Dockers y reservas reales permanecen intocables.

Actas: [A45-R118.3](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6728256895)
y [consenso A45-R119](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6728301895).
